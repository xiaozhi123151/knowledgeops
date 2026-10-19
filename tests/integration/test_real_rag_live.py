"""Paid API + real retrieval, opt-in. Does not substitute any provider."""

import json
import os

import pytest
from dotenv import dotenv_values

from scripts.common import ROOT

pytestmark = [pytest.mark.live, pytest.mark.retrieval_live, pytest.mark.deepseek_live]


async def test_real_rag_tools_budgets_multiturn_and_sources():
    if os.getenv("KO_RUN_RAG_TESTS") != "1":
        pytest.skip("UNVERIFIED: set KO_RUN_RAG_TESTS=1 after real indexing; uses paid DeepSeek API")
    env = {**dotenv_values(ROOT / ".env"), **os.environ}
    if not (env.get("DEEPSEEK_API_KEY") or env.get("KO_DEEPSEEK_API_KEY")):
        pytest.skip("UNVERIFIED: no DeepSeek API key")
    manifest = ROOT / "data" / "models" / "manifest.json"
    if not manifest.exists() or len(json.loads(manifest.read_text(encoding="utf-8"))) != 2:
        pytest.skip("UNVERIFIED: complete real model weights not configured")
    from scripts.real_retrieval import real_settings

    if not (real_settings().data_dir / "metadata.sqlite").exists():
        pytest.skip("UNVERIFIED: import the public evidence corpus with scripts.index_real_corpus first")
    from scripts.validate_real_rag import validate

    report = await validate()
    assert report["passed"], [
        {k: r.get(k) for k in ["name", "status", "error", "cited_sources", "budget_consistent"]}
        for r in report["cases"]
    ]
    assert report["summary"]["valid_citations"] == report["summary"]["citations"] > 0
    assert report["cases"][1]["history_messages_before_current_question"] > 0
    assert report["cases"][3]["abstained"]
    assert all(r["budget_consistent"] for r in report["cases"])
