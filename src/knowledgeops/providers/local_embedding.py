"""Real dense SentenceTransformer in a bounded, terminable worker. No fallback to hashing."""

import numpy as np

from knowledgeops.providers.reranker import IsolatedCrossEncoder


def _embedding_process(pipe, model, device, batch, options):
    try:
        import torch
        from sentence_transformers import SentenceTransformer

        torch.set_num_threads(options["threads"])
        encoder = SentenceTransformer(
            model,
            device=device,
            revision=options["revision"],
            local_files_only=options["local_only"],
            trust_remote_code=False,
            model_kwargs={
                "torch_dtype": torch.float16 if options["precision"] == "float16" else torch.float32
            },
        )
        encoder.max_seq_length = options["max_length"]
        dimension = (
            encoder.get_embedding_dimension()
            if hasattr(encoder, "get_embedding_dimension")
            else encoder.get_sentence_embedding_dimension()
        )
        pipe.send(("ready", dimension))
        while True:
            texts = pipe.recv()
            if texts is None:
                break
            vectors = encoder.encode(
                texts,
                batch_size=batch,
                normalize_embeddings=options["normalize"],
                show_progress_bar=False,
                convert_to_numpy=True,
            )
            # Normalize exported vectors in float32 even when inference runs in FP16.
            vectors = np.asarray(vectors, dtype=np.float32)
            if options["normalize"]:
                vectors = vectors / np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12)
            pipe.send(("ok", vectors.tolist()))
    except BaseException as exc:
        try:
            pipe.send(("error", type(exc).__name__ + ": " + str(exc)[:500]))
        except (OSError, EOFError):
            pass
    finally:
        pipe.close()


class _EmbeddingWorker(IsolatedCrossEncoder):
    def __init__(self, settings):
        super().__init__(settings)
        self.name, self.device, self.batch = (
            settings.embedding_model,
            settings.embedding_device,
            settings.embedding_batch_size,
        )
        self.options.update(
            revision=settings.embedding_revision,
            max_length=settings.embedding_max_length,
            normalize=settings.embedding_normalize,
            precision=settings.embedding_precision,
        )
        self.dimensions = settings.embedding_dimensions
        self.load_name = str(settings.embedding_model_path) if settings.embedding_model_path else self.name

    def _process_spec(self, child):
        return _embedding_process, (child, self.load_name, self.device, self.batch, self.options)

    async def _receive(self, timeout):
        try:
            status, result = await super()._receive(timeout)
        except TimeoutError as exc:
            raise TimeoutError("EMBEDDING_TIMEOUT") from exc
        except RuntimeError as exc:
            raise RuntimeError(str(exc).replace("RERANKER_FAILED", "EMBEDDING_FAILED")) from exc
        if status == "ready" and result != self.dimensions:
            self.close()
            raise ValueError("EMBEDDING_DIMENSION_MISMATCH: configure dimensions before indexing")
        return status, result


class LocalEmbedding:
    def __init__(self, settings):
        self.worker = _EmbeddingWorker(settings)
        self.name = settings.embedding_model
        self.dimensions = settings.embedding_dimensions
        self.timeout = settings.tool_timeout
        self.index_config = {
            "provider": "sentence_transformers",
            "revision": settings.embedding_revision,
            "normalize": settings.embedding_normalize,
            "max_length": settings.embedding_max_length,
            "pooling": "repository SentenceTransformer modules",
            "dtype": settings.embedding_precision,
        }

    async def warmup(self):
        await self.worker.warmup()

    async def embed(self, texts):
        if not texts:
            return []
        async with self.worker.lock:
            try:
                await self.worker._start()
                # Bound IPC and inference size independently of the total import size.
                vectors = []
                for start in range(0, len(texts), self.worker.batch):
                    batch = texts[start : start + self.worker.batch]
                    self.worker.pipe.send(batch)
                    _, result = await self.worker._receive(self.timeout)
                    array = np.asarray(result)
                    if array.shape != (len(batch), self.dimensions) or not np.isfinite(array).all():
                        raise ValueError("EMBEDDING_DIMENSION_OR_VALUE_MISMATCH")
                    if self.index_config["normalize"] and not np.allclose(
                        np.linalg.norm(array, axis=1), 1, atol=1e-4
                    ):
                        raise ValueError("EMBEDDING_NOT_NORMALIZED")
                    vectors.extend(result)
                return vectors
            except BaseException:
                self.worker.close()
                raise

    async def close(self):
        self.worker.close()
