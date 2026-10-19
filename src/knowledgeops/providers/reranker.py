import asyncio
import multiprocessing as mp

from knowledgeops.providers.embedding import tokenize


class FakeReranker:
    """Lexical-overlap test double, not a CrossEncoder."""
    name = 'offline-overlap-v1'

    async def score(self, query, texts, timeout=30):
        words = set(tokenize(query))
        return [len(words & set(tokenize(t))) / max(1, len(words)) for t in texts]

    def close(self):
        pass


def _model_process(pipe, model, device, batch_size, options):
    try:
        import torch
        from sentence_transformers import CrossEncoder
        torch.set_num_threads(options['threads'])
        encoder = CrossEncoder(model, device=device, max_length=options['max_length'], trust_remote_code=False,
                               revision=options['revision'], local_files_only=options['local_only'],
                               model_kwargs={'torch_dtype':torch.float16 if options['precision']=='float16'
                                             else torch.float32})
        pipe.send(('ready', None))
        while True:
            value = pipe.recv()
            if value is None:
                break
            query, texts = value
            scores = encoder.predict([(query, t) for t in texts], batch_size=batch_size,
                                     activation_fn=torch.nn.Identity(),
                                     show_progress_bar=False).tolist()
            pipe.send(('ok', scores))
    except BaseException as exc:
        try:
            pipe.send(('error', type(exc).__name__ + ': ' + str(exc)[:500]))
        except (BrokenPipeError, EOFError, OSError):
            pass
    finally:
        pipe.close()


class IsolatedCrossEncoder:
    """One persistent child; kill and join on timeout. A timed-out compute cannot publish later."""
    def __init__(self, settings):
        self.name = settings.reranker_model
        self.load_name = str(settings.reranker_model_path) if settings.reranker_model_path else self.name
        self.device = settings.reranker_device
        self.batch = settings.reranker_batch_size
        self.options = {'max_length': settings.reranker_max_length, 'revision': settings.reranker_revision,
                        'local_only': settings.models_local_only, 'threads': settings.model_threads,
                        'precision':settings.reranker_precision}
        self.load_timeout = settings.model_load_timeout
        self.score_scale = 'raw_cross_encoder_logit; uncalibrated, not a probability'
        self.process = self.pipe = None
        self.lock = asyncio.Lock()

    async def _receive(self, timeout):
        if not await asyncio.to_thread(self.pipe.poll, timeout):
            self.close()
            raise TimeoutError('RERANKER_TIMEOUT')
        status, result = self.pipe.recv()
        if status == 'error':
            self.close()
            raise RuntimeError('RERANKER_FAILED: ' + result)
        return status, result

    async def warmup(self):
        async with self.lock:
            await self._start()

    async def _start(self):
        if self.process and self.process.is_alive():
            return
        self.close()
        ctx = mp.get_context('spawn')
        self.pipe, child = ctx.Pipe()
        target, args = self._process_spec(child)
        self.process = ctx.Process(target=target, args=args, daemon=True)
        self.process.start()
        child.close()
        status, _ = await self._receive(self.load_timeout)
        if status != 'ready':
            raise RuntimeError('RERANKER_NOT_READY')

    def _process_spec(self, child):
        return _model_process, (child, self.load_name, self.device, self.batch, self.options)

    async def score(self, query, texts, timeout=30):
        async with self.lock:
            try:
                await self._start()
                self.pipe.send((query, texts))
                _, scores = await self._receive(timeout)
                if len(scores) != len(texts):
                    raise ValueError('RERANKER_COUNT_MISMATCH')
                return scores
            except BaseException:
                self.close()
                raise

    def close(self):
        if self.process:
            if self.process.is_alive():
                self.process.terminate()
            self.process.join(timeout=5)
            self.process.close()
        if self.pipe:
            self.pipe.close()
        self.process = self.pipe = None
