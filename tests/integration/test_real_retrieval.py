"""External dependencies are opt-in. No fake-model substitutions in these tests."""

import importlib.util
import json
import os
import uuid

import numpy as np
import pytest

from knowledgeops.schemas import Query
from scripts.common import ROOT

pytestmark = [pytest.mark.live, pytest.mark.retrieval_live]


@pytest.fixture
def real_config(tmp_path):
    if os.getenv("KO_RUN_RETRIEVAL_TESTS") != "1":
        pytest.skip("UNVERIFIED: set KO_RUN_RETRIEVAL_TESTS=1 with downloaded weights and Qdrant Server")
    manifest = ROOT / "data" / "models" / "manifest.json"
    if not manifest.exists() or not importlib.util.find_spec("sentence_transformers"):
        pytest.skip("UNVERIFIED: real model weights or sentence-transformers are missing")
    models = json.loads(manifest.read_text(encoding="utf-8"))
    if len(models) != 2 or any(
        not any(
            (ROOT / m["path"] / filename).exists() for filename in ["pytorch_model.bin", "model.safetensors"]
        )
        for m in models
    ):
        pytest.skip("UNVERIFIED: complete pinned dense and reranker weights required")
    # Once dependencies are explicitly configured, connection/loading failures FAIL instead of skipping.
    from scripts.real_retrieval import real_settings

    return real_settings(tmp_path, qdrant_collection="ko_test_" + uuid.uuid4().hex)


@pytest.fixture
async def real_stack(real_config):
    from scripts.real_retrieval import RealStack

    stack = await RealStack(real_config).start()
    try:
        yield stack
    finally:
        stack.engine.client.delete_collection(stack.engine.collection)
        await stack.close()


async def test_real_dense_embeddings_and_cross_encoder(real_stack):
    vectors = np.asarray(
        await real_stack.embedding.embed(
            ["异步队列按先进先出处理任务。", "A queue processes items first in first out."]
        )
    )
    assert vectors.shape == (2, 1024)
    assert np.isfinite(vectors).all()
    assert np.linalg.norm(vectors, axis=1) == pytest.approx([1, 1], abs=1e-4)
    scores = await real_stack.reranker.score(
        "How does a FIFO queue retrieve items?",
        [
            "A FIFO queue retrieves the earliest added item first.",
            "The moon is a natural satellite of Earth.",
        ],
        timeout=120,
    )
    assert len(scores) == 2 and np.isfinite(scores).all()
    assert scores[0] > scores[1]


async def test_real_server_ingest_search_reopen_deduplicate_delete(real_stack, real_config):
    from knowledgeops.retrieval.engine import RetrievalEngine

    service = real_stack.ingestion
    payload = service.save_upload(
        b"FIFO queues retrieve the earliest added item first. Queue maxsize=0 is unlimited.", "fifo.txt"
    )
    doc = await service.ingest(payload)
    duplicate = await service.ingest(payload)
    assert duplicate["duplicate"] and duplicate["doc_id"] == doc["doc_id"]
    hits = await real_stack.engine.search(Query(query="How are items ordered in FIFO queues?", rerank=True))
    assert hits.hits and not hits.warnings
    hit = hits.hits[0]
    assert hit.chunk.doc_id == doc["doc_id"]
    assert all(v is not None for v in [hit.dense_score, hit.bm25_score, hit.rrf_score, hit.rerank_score])
    assert real_stack.db.chunk(hit.chunk.doc_id, hit.chunk.chunk_id).text == hit.chunk.text
    # Separate client/engine reconnect retains indexed data; container recreation has its own infra script.
    second = RetrievalEngine(real_config, real_stack.db, real_stack.embedding, real_stack.reranker)
    try:
        await second.initialize()
        assert (await second.search(Query(query="FIFO", rerank=False))).hits
    finally:
        second.close()
    assert await service.delete(doc["doc_id"])
    assert real_stack.engine.client.count(real_stack.engine.collection).count == 0
    assert not (await real_stack.engine.search(Query(query="FIFO"))).hits


async def test_real_model_revision_rejects_existing_index(real_stack, real_config):
    from knowledgeops.providers.local_embedding import LocalEmbedding
    from knowledgeops.retrieval.engine import RetrievalEngine

    changed = real_config.model_copy(update={"embedding_normalize": False})
    engine = RetrievalEngine(changed, real_stack.db, LocalEmbedding(changed), real_stack.reranker)
    try:
        with pytest.raises(ValueError, match="INDEX_CONFIG_CHANGED"):
            await engine.initialize()
    finally:
        engine.close()
