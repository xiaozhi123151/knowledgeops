"""Shared strict profile for REAL experiments; never falls back to test doubles."""

import hashlib
import json
import os
import time

from knowledgeops.config import Settings
from knowledgeops.ingestion.extract import normalize
from knowledgeops.ingestion.service import IngestionService
from knowledgeops.providers.local_embedding import LocalEmbedding
from knowledgeops.providers.reranker import IsolatedCrossEncoder
from knowledgeops.retrieval.engine import RetrievalEngine
from knowledgeops.storage.db import Database
from scripts.common import ROOT
from scripts.fetch_benchmark_docs import CORPUS


def real_settings(root=None, **overrides):
    manifest = json.loads((ROOT / "data" / "models" / "manifest.json").read_text(encoding="utf-8"))
    emb, rer = manifest
    device = os.environ.get("KO_EXPERIMENT_DEVICE", "cpu")
    if device not in ("cpu", "cuda"):
        raise ValueError("KO_EXPERIMENT_DEVICE must be cpu or cuda")
    precision = "float16" if device == "cuda" else "float32"
    values = dict(
        mode="offline",
        llm_provider="mock",
        data_dir=root or ROOT / "data" / ("real_retrieval_cuda" if device == "cuda" else "real_retrieval"),
        embedding_provider="local",
        embedding_model=emb["model"],
        embedding_revision=emb["revision"],
        embedding_model_path=ROOT / emb["path"].replace("\\", "/"),
        embedding_dimensions=1024,
        embedding_device=device,
        embedding_precision=precision,
        embedding_batch_size=8,
        embedding_max_length=512,
        embedding_normalize=True,
        reranker_provider="cross_encoder",
        reranker_model=rer["model"],
        reranker_revision=rer["revision"],
        reranker_model_path=ROOT / rer["path"].replace("\\", "/"),
        reranker_batch_size=8,
        reranker_device=device,
        reranker_precision=precision,
        reranker_max_length=512,
        model_threads=8,
        models_local_only=True,
        qdrant_backend="server",
        qdrant_url="http://127.0.0.1:6333",
        tool_timeout=120,
        task_timeout=600,
        token_budget=100000,
        output_tokens=6000,
        llm_timeout=90,
    )
    values.update(overrides)
    return Settings(**values)


def load_questions():
    raw = (CORPUS / "questions.json").read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != (CORPUS / "questions.sha256").read_text().strip():
        raise ValueError("BENCHMARK_NOT_FROZEN")
    data = json.loads(raw)
    sources = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))["sources"]
    for s in sources:
        raw_doc = (CORPUS / "documents" / s["filename"]).read_bytes()
        if hashlib.sha256(raw_doc).hexdigest() != data["source_hashes"][s["id"]]:
            raise ValueError("BENCHMARK_SOURCE_CHANGED")
    return data, sources, digest


class RealStack:
    def __init__(self, settings):
        self.settings = settings
        self.db = Database(settings.data_dir)
        self.embedding = LocalEmbedding(settings)
        self.reranker = IsolatedCrossEncoder(settings)
        self.engine = RetrievalEngine(settings, self.db, self.embedding, self.reranker)
        self.ingestion = IngestionService(settings, self.db, self.engine)
        self.timings = {}

    async def start(self):
        try:
            start = time.perf_counter()
            await self.embedding.warmup()
            self.timings["embedding_load_ms"] = (time.perf_counter() - start) * 1000
            start = time.perf_counter()
            await self.reranker.warmup()
            self.timings["reranker_load_ms"] = (time.perf_counter() - start) * 1000
            await self.engine.initialize()
            return self
        except BaseException:
            await self.close()
            raise

    async def import_corpus(self, sources):
        source_ids = {}
        for s in sources:
            payload = self.ingestion.save_upload(
                (CORPUS / "documents" / s["filename"]).read_bytes(), s["filename"]
            )
            payload.update(source=s["url"], title=s["id"])
            t = time.perf_counter()
            result = await self.ingestion.ingest(payload)
            source_ids[s["id"]] = result["doc_id"]
            print(
                "import",
                s["id"],
                result["chunk_count"],
                "chunks",
                round(time.perf_counter() - t, 2),
                "s",
                flush=True,
            )
        return source_ids

    async def close(self):
        self.reranker.close()
        await self.embedding.close()
        self.engine.close()


def evidence_qrels(data, chunks, source_ids):
    # Positive judgments include every overlapping chunk containing an exact normalized anchor.
    # All other chunks are UNJUDGED (treated as zero for this limited benchmark).
    anchors = {}
    for e in data["evidence"]:
        ids = {
            c.chunk_id
            for c in chunks
            if c.doc_id == source_ids[e["source_id"]] and normalize(e["quote"]) in c.text
        }
        if not ids:
            raise ValueError("EVIDENCE_NOT_IN_CHUNKS: " + e["id"])
        anchors[e["id"]] = ids
    return {q["id"]: {cid: 2 for e in q["evidence_ids"] for cid in anchors[e]} for q in data["questions"]}
