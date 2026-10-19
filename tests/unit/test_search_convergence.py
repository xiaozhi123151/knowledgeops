import json

import pytest

from knowledgeops.agent.graph import DirectExecutor, ResearchAgent
from knowledgeops.providers.llm import FakeLLM, call


class RepeatedSearchLLM(FakeLLM):
    count = 0

    async def complete(self, messages, tools=None, max_tokens=2000):
        if not tools:
            return await super().complete(messages, tools, max_tokens)
        allowed = {t["function"]["name"] for t in tools}
        if "knowledge_search" in allowed:
            self.count += 1
            return call("knowledge_search", {"query": f"Redis AOF repeated {self.count}", "top_k": 5}), None
        evidence = {
            cid: chunk
            for m in messages
            if m.get("name") == "knowledge_search"
            for cid, chunk in json.loads(m["content"]).get("evidence", {}).items()
        }
        if "compare_evidence" in allowed:
            return call("compare_evidence", {"citation_ids": list(evidence)}), None
        cid, chunk = next(iter(evidence.items()))
        return call(
            "build_report",
            {
                "title": "Bounded search",
                "conclusion": "Redis AOF evidence.",
                "findings": [{"text": "Redis AOF evidence.", "citation_ids": [cid]}],
                "quotes": {cid: chunk["text"]},
                "limitations": [],
            },
        ), None


async def test_search_limit_converges_and_reuses_original_evidence(stack):
    _, db, engine, ingest = stack
    await ingest.ingest(ingest.save_upload(b"Redis AOF logs every write.", "redis.txt"))
    llm = RepeatedSearchLLM()
    state = await ResearchAgent(engine, DirectExecutor(llm)).run("Redis", "bounded")
    searches = [json.loads(m["content"]) for m in state["messages"] if m.get("name") == "knowledge_search"]
    assert llm.count == 4 and len(searches) == 4
    assert sum(len(s["evidence"]) for s in searches) == 1
    assert all(s["reused_evidence_ids"] for s in searches[1:])
    citation = state["report"]["citations"][0]
    assert citation["quote"] in db.chunk(citation["doc_id"], citation["chunk_id"]).text


async def test_model_cannot_ignore_search_limit(stack):
    _, _, engine, ingest = stack
    await ingest.ingest(ingest.save_upload(b"Redis AOF writes.", "redis.txt"))

    class IgnoresLimit(FakeLLM):
        async def complete(self, *args, **kwargs):
            return call("knowledge_search", {"query": "Redis"}), None

    with pytest.raises(ValueError, match="AFTER_REPAIR"):
        await ResearchAgent(engine, DirectExecutor(IgnoresLimit())).run("Redis", "malicious")
