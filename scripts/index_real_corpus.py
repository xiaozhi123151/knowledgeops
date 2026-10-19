"""Stage the real corpus independently of reranker readiness (indexing never invokes a reranker)."""

import asyncio
import json
import time

from knowledgeops.config import Settings
from knowledgeops.ingestion.service import IngestionService
from knowledgeops.providers.local_embedding import LocalEmbedding
from knowledgeops.retrieval.engine import RetrievalEngine
from knowledgeops.storage.db import Database
from scripts.common import REPORTS, ROOT, metadata, write_json
from scripts.fetch_benchmark_docs import CORPUS
from scripts.real_retrieval import load_questions


async def main():
    _, sources, digest = load_questions()
    model = json.loads((ROOT / "data" / "models" / "manifest.json").read_text(encoding="utf-8"))[0]
    settings = Settings(
        mode="offline",
        llm_provider="mock",
        data_dir=ROOT / "data" / "real_retrieval",
        embedding_provider="local",
        embedding_model=model["model"],
        embedding_revision=model["revision"],
        embedding_model_path=ROOT / model["path"],
        embedding_dimensions=1024,
        models_local_only=True,
        qdrant_backend="server",
        qdrant_url="http://127.0.0.1:6333",
        tool_timeout=120,
    )
    db = Database(settings.data_dir)
    embedding = LocalEmbedding(settings)
    engine = RetrievalEngine(settings, db, embedding, None)
    service = IngestionService(settings, db, engine)
    report = {"metadata": metadata("real_indexing"), "question_sha256": digest, "documents": []}
    try:
        t = time.perf_counter()
        await embedding.warmup()
        report["embedding_load_ms"] = (time.perf_counter() - t) * 1000
        await engine.initialize()
        t = time.perf_counter()
        for source in sources:
            payload = service.save_upload(
                (CORPUS / "documents" / source["filename"]).read_bytes(), source["filename"]
            )
            payload.update(source=source["url"], title=source["id"])
            start = time.perf_counter()
            result = await service.ingest(payload)
            report["documents"].append(
                {"source_id": source["id"], **result, "elapsed_ms": (time.perf_counter() - start) * 1000}
            )
            print(
                source["id"],
                result["chunk_count"],
                "chunks",
                round(time.perf_counter() - start, 2),
                "s",
                flush=True,
            )
        report["import_ms"] = (time.perf_counter() - t) * 1000
        report["qdrant_points"] = engine.client.count(engine.collection).count
        write_json(REPORTS / "real-indexing.json", report)
    finally:
        engine.close()
        await embedding.close()


if __name__ == "__main__":
    asyncio.run(main())
