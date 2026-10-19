import pytest

from knowledgeops.schemas import Query
from scripts.evaluate_real_retrieval import VARIANTS, metrics
from scripts.review_relevance import validate_review


def test_fiveway_dense_rerank_is_distinct_and_zero_grades_are_not_relevant():
    assert ("Dense+Rerank", "dense", True) in VARIANTS
    assert len(VARIANTS) == 5
    result = metrics(["negative", "partial", "direct"], {"negative": 0, "partial": 1, "direct": 2})
    assert result["recall_at_5"] == 1
    assert result["mrr_at_10"] == 0.5
    assert all(x is None for x in metrics(["negative"], {"negative": 0}).values())


async def test_dense_rerank_preserves_score_provenance_without_bm25(stack, monkeypatch):
    _, _, engine, ingestion = stack
    await ingestion.ingest(ingestion.save_upload(b"Alpha cache TTL 60 seconds.", "a.txt"))
    await ingestion.ingest(ingestion.save_upload(b"Beta cache TTL 120 seconds.", "b.txt"))
    dense = await engine.search(Query(query="Alpha cache", mode="dense", rerank=False, top_k=2))
    expected = list(reversed([h.chunk.chunk_id for h in dense.hits]))

    async def score(query, texts, timeout):
        assert len(texts) == 2
        return [1, 10]

    monkeypatch.setattr(engine.reranker, "score", score)
    result = await engine.search(Query(query="Alpha cache", mode="dense", rerank=True, top_k=2))
    assert [h.chunk.chunk_id for h in result.hits] == expected
    original = {h.chunk.chunk_id: h for h in dense.hits}
    for hit in result.hits:
        assert hit.dense_score == original[hit.chunk.chunk_id].dense_score
        assert hit.dense_rank == original[hit.chunk.chunk_id].dense_rank
        assert hit.bm25_score is None and hit.rrf_score is None
        assert hit.rerank_score in (1, 10)


def submission(**overrides):
    return {"pool_sha256": "frozen", "reviewer": "unit-test fixture, not a real reviewer",
            "human_attestation": True,
            "judgments": [{"item_id": "a", "grade": 2, "quote": "TaskGroup", "reason": "fixture"}],
            **overrides}


POOL = {"pool_sha256": "frozen", "items": [{"item_id": "a", "text": "TaskGroup waits for tasks."}]}


def test_accept_exact_source_review():
    assert validate_review(POOL, submission())["judgments"][0]["grade"] == 2


@pytest.mark.parametrize("change,error", [
    ({"reviewer": ""}, "HUMAN_REVIEWER_REQUIRED"),
    ({"human_attestation": False}, "HUMAN_REVIEWER_REQUIRED"),
    ({"pool_sha256": "other"}, "REVIEW_POOL_MISMATCH"),
    ({"judgments": []}, "EMPTY_REVIEW"),
    ({"judgments": [{"item_id": "x", "grade": 2, "quote": "TaskGroup", "reason": "x"}]}, "UNKNOWN_OR_DUPLICATE"),
    ({"judgments": [{"item_id": "a", "grade": 3, "quote": "TaskGroup", "reason": "x"}]}, "INVALID_RELEVANCE"),
    ({"judgments": [{"item_id": "a", "grade": 2, "quote": "fabricated", "reason": "x"}]}, "EXACT_QUOTE"),
    ({"judgments": [{"item_id": "a", "grade": 0, "reason": ""}]}, "REASON_REQUIRED"),
])
def test_reject_unverifiable_human_review(change, error):
    with pytest.raises(ValueError, match=error):
        validate_review(POOL, submission(**change))
