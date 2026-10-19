import asyncio
import multiprocessing as mp
import time

import numpy as np
import pytest

from knowledgeops.config import Settings
from knowledgeops.providers.local_embedding import LocalEmbedding
from knowledgeops.providers.reranker import IsolatedCrossEncoder
from knowledgeops.retrieval.engine import RetrievalEngine
from knowledgeops.schemas import Query
from scripts.evaluate_real_retrieval import aggregate, metrics
from scripts.real_retrieval import evidence_qrels, load_questions


def delayed_embedding(pipe, marker):
    pipe.recv()
    time.sleep(0.3)
    marker.write_text("late vector")
    pipe.send(("ok", [[1.0] + [0.0] * 7]))


async def test_embedding_timeout_terminates_underlying_compute(settings, tmp_path):
    provider = LocalEmbedding(
        settings.model_copy(
            update={"embedding_model": "test", "embedding_dimensions": 8, "tool_timeout": 0.02}
        )
    )
    ctx = mp.get_context("spawn")
    provider.worker.pipe, child = ctx.Pipe()
    marker = tmp_path / "late-embedding"
    provider.worker.process = ctx.Process(target=delayed_embedding, args=(child, marker), daemon=True)
    provider.worker.process.start()
    child.close()
    with pytest.raises(TimeoutError, match="EMBEDDING_TIMEOUT"):
        await provider.embed(["query"])
    assert provider.worker.process is None
    await asyncio.sleep(0.4)
    assert not marker.exists()


def test_default_provider_selection_preserves_offline(settings):
    assert settings.resolved_embedding_provider == "mock"
    assert settings.resolved_reranker_provider == "mock"
    assert settings.resolved_qdrant_backend == "local"


def test_full_live_forbids_mock_retrieval():
    with pytest.raises(ValueError, match="Mock retrieval"):
        Settings(
            _env_file=None,
            mode="live",
            llm_provider="openai",
            llm_model="model",
            llm_api_key="test",
            embedding_provider="mock",
        )


def test_live_local_models_do_not_require_embedding_api_key():
    cfg = Settings(
        _env_file=None,
        mode="live",
        llm_provider="openai",
        llm_model="model",
        llm_api_key="test",
        api_key="private-test",
        embedding_provider="local",
        embedding_model="local-test",
    )
    assert cfg.resolved_qdrant_backend == "server"


def test_model_revision_and_normalization_change_fingerprint(settings):
    from knowledgeops.providers.embedding import HashEmbedding
    from knowledgeops.providers.reranker import FakeReranker
    from knowledgeops.storage.db import Database

    cfg = settings.model_copy(update={"embedding_model": "test", "embedding_dimensions": 8})
    db = Database(cfg.data_dir)
    signatures = []
    for revision, normalize in [("a", True), ("b", True), ("b", False)]:
        provider = HashEmbedding()
        provider.index_config = {"revision": revision, "normalize": normalize}
        engine = RetrievalEngine(cfg, db, provider, FakeReranker())
        signatures.append(engine.fingerprint)
        engine.close()
    assert len(set(signatures)) == 3


async def test_dimension_checked_at_model_readiness(settings, monkeypatch):
    cfg = settings.model_copy(update={"embedding_model": "test", "embedding_dimensions": 8})
    provider = LocalEmbedding(cfg)

    async def wrong_ready(self, timeout):
        return "ready", 16

    monkeypatch.setattr(IsolatedCrossEncoder, "_receive", wrong_ready)
    with pytest.raises(ValueError, match="DIMENSION_MISMATCH"):
        await provider.worker._receive(1)


@pytest.mark.parametrize(
    "result,message",
    [
        ([[0.0] * 8], "NOT_NORMALIZED"),
        ([[1.0] * 7], "DIMENSION_OR_VALUE"),
        ([[float("nan")] * 8], "DIMENSION_OR_VALUE"),
    ],
)
async def test_model_vector_validation(settings, monkeypatch, result, message):
    provider = LocalEmbedding(
        settings.model_copy(update={"embedding_model": "test", "embedding_dimensions": 8})
    )

    class Pipe:
        def send(self, data):
            pass

        def close(self):
            pass

    provider.worker.pipe = Pipe()

    async def start():
        pass

    async def receive(timeout):
        return "ok", result

    monkeypatch.setattr(provider.worker, "_start", start)
    monkeypatch.setattr(provider.worker, "_receive", receive)
    with pytest.raises(ValueError, match=message):
        await provider.embed(["text"])
    assert provider.worker.pipe is None


async def test_delete_hides_bm25_dense_and_citation(stack):
    _, db, engine, ingestion = stack
    result = await ingestion.ingest(
        ingestion.save_upload(b"Unique deletion probe: zebra cache TTL 99.", "probe.txt")
    )
    result2 = await ingestion.ingest(
        ingestion.save_upload(b"Unique deletion probe: zebra cache TTL 99.", "alias.txt")
    )
    assert result2["duplicate"]
    hit = (await engine.search(Query(query="zebra", rerank=False))).hits[0]
    assert await ingestion.delete(result["doc_id"])
    assert not db.chunk(hit.chunk.doc_id, hit.chunk.chunk_id)
    assert not (await engine.search(Query(query="zebra", rerank=False))).hits
    assert engine.client.count(engine.collection).count == 0
    assert not await ingestion.delete(result["doc_id"])


async def test_failed_delete_is_hidden_and_retryable(stack, monkeypatch):
    _, db, engine, ingestion = stack
    doc = await ingestion.ingest(ingestion.save_upload(b"Cannot leak a deleted document.", "probe.txt"))
    original = engine.client.delete

    def fail(*args, **kwargs):
        raise ConnectionError("injected delete failure")

    monkeypatch.setattr(engine.client, "delete", fail)
    with pytest.raises(ConnectionError):
        await ingestion.delete(doc["doc_id"])
    assert db.documents()[0]["status"] == "deleting"
    assert not (await engine.search(Query(query="document"))).hits
    monkeypatch.setattr(engine.client, "delete", original)
    assert await ingestion.delete(doc["doc_id"])


async def test_switching_vector_target_requires_reimport(stack):
    settings, _, engine, _ = stack
    engine.settings = settings.model_copy(update={"qdrant_backend": "server"})
    with pytest.raises(ValueError, match="INDEX_TARGET_CHANGED"):
        await engine.initialize()


def test_metric_hand_calculation_and_unanswerable():
    values = metrics(["x", "a", "b"], {"a": 2, "b": 2})
    assert values["recall_at_5"] == 1
    assert values["mrr_at_10"] == 0.5
    assert values["ndcg_at_10"] == pytest.approx((3 / np.log2(3) + 3 / np.log2(4)) / (3 + 3 / np.log2(3)))
    assert all(v is None for v in metrics(["a"], {}).values())
    assert metrics([], {"a": 2})["recall_at_5"] == 0
    assert metrics(["x", "x", "a"], {"a": 2})["mrr_at_10"] == 0.5


def test_failed_queries_not_removed_from_quality_denominator():
    base = {
        "answerable": True,
        "query_id": "q",
        "ranked": [],
        "elapsed_ms": 5,
        "recall_at_5": 0,
        "mrr_at_10": 0,
        "ndcg_at_10": 0,
        "error": "timeout",
    }
    good = base | {"error": None, "recall_at_5": 1, "mrr_at_10": 1, "ndcg_at_10": 1}
    summary = aggregate([base, good])
    assert summary["recall_at_5"] == 0.5 and summary["failure_rate"] == 0.5


def test_public_questions_are_frozen_and_anchors_exist():
    from knowledgeops.ingestion.extract import extract, make_chunks
    from scripts.fetch_benchmark_docs import CORPUS

    data, sources, digest = load_questions()
    assert len(data["questions"]) >= 100 and len(digest) == 64
    assert {q["category"] for q in data["questions"]} == {
        "keyword",
        "semantic",
        "cross_document",
        "version_conflict",
        "unanswerable",
    }
    chunks = []
    source_ids = {}
    for s in sources:
        path = CORPUS / "documents" / s["filename"]
        doc_id, batch = make_chunks(extract(path.read_bytes(), path.suffix), s["url"], s["id"])
        chunks.extend(batch)
        source_ids[s["id"]] = doc_id
    qrels = evidence_qrels(data, chunks, source_ids)
    assert all(bool(qrels[q["id"]]) == q["answerable"] for q in data["questions"])
