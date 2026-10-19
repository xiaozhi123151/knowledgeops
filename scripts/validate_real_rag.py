"""Actual DeepSeek + BGE + Qdrant Server + Redis. No synthetic faults or model outputs."""

import argparse
import asyncio
import json
import re
import secrets
import time
import uuid

import numpy as np

from knowledgeops.runtime import Runtime
from scripts.common import REPORTS, metadata, write_json
from scripts.real_retrieval import load_questions, real_settings
from scripts.validate_deepseek import CONCISE, QUESTIONS, audit_messages

CASES = [
    ("three_versions", QUESTIONS[0][1], ["DeepSeek-V2", "DeepSeek-V3", "DeepSeek-V4.1-Flash"], False),
    ("multi_turn_missing_metric", QUESTIONS[1][1], [], False),
    (
        "python_lock_versions",
        "请实际检索 Python 3.12 与 Python 3.13 官方发布说明，比较每子解释器 GIL 和实验性 free-threading。"
        "这是否意味着所有 C 扩展导入后都能保持无 GIL？按版本分别检索，调用 compare_evidence，最后 build_report。"
        "每个版本给一条发现并引用它的原文，不能把两个版本当成同一特性。",
        ["python-3.12", "python-3.13"],
        False,
    ),
    (
        "private_metric_unanswerable",
        "仅依据这些公开技术文档，能否确认我公司从未公开的私有 Web 服务在 RTX 5060 上的实测 QPS？"
        "请实际调用 knowledge_search 并核查，不能用 Python 加速比例、参数量或其他基准推算这个未知实测数值。"
        "若没有这个服务的实验依据，必须明确无法确认，报告 insufficient_evidence=true，findings、quotes 清空。"
        "请完成所需工具流程并调用 build_report。",
        [],
        True,
    ),
]


async def validate(cases=4):
    data, sources, digest = load_questions()
    settings = real_settings(
        mode="live",
        llm_provider="deepseek",
        api_key=secrets.token_urlsafe(32),
        redis_url="redis://127.0.0.1:6379/0",
    )
    started = time.perf_counter()
    runtime = await Runtime(settings).start()
    report = {
        "metadata": metadata("real_rag"),
        "boundary": {
            "llm": runtime.llm.name,
            "embedding": runtime.embedding.name,
            "reranker": runtime.reranker.name,
            "qdrant": "real HTTP server",
            "redis": "real Streams service; direct runner invoked for measured tasks",
            "agent": "actual LangGraph + durable Harness",
            "fault_injection": "none",
            "device": settings.embedding_device,
            "precision": settings.embedding_precision,
            "collection": runtime.engine.collection,
            "index_fingerprint": runtime.engine.fingerprint,
            "max_search_calls": settings.max_search_calls,
        },
        "question_sha256": digest,
        "provider_load_ms": (time.perf_counter() - started) * 1000,
        "cases": [],
        "note": "Small engineering acceptance sample; citation structure validity is not semantic answer accuracy.",
    }
    try:
        # Reuse exactly the indexed benchmark snapshots; fail on missing source instead of switching providers.
        docs = runtime.db.documents()
        source_ids = {
            s["id"]: next(d["doc_id"] for d in docs if d["title"] == s["id"] and d["status"] == "ready")
            for s in sources
        }
        directory = json.dumps(
            [{"source_id": k, "doc_id": v} for k, v in source_ids.items()], ensure_ascii=False
        )
        session = "real-rag-" + uuid.uuid4().hex
        for i, (name, question, required_sources, unanswerable) in enumerate(CASES[:cases]):
            question += CONCISE + "\n可检索来源目录（只含标识，不含答案）：" + directory
            task_id = runtime.store.create(
                "research", {"question": question}, session_id=session if i < 2 else session + "-" + str(i)
            )
            await runtime.notify(task_id)
            t = time.perf_counter()
            await runtime.runner.execute(task_id)
            task = runtime.store.get(task_id)
            events = runtime.store.events(task_id)
            checkpoint = await runtime.runner.checkpointer.aget_tuple(
                {"configurable": {"thread_id": task_id}}
            )
            state = checkpoint.checkpoint.get("channel_values", {}) if checkpoint else {}
            messages = state.get("messages", [])
            last_user = max((n for n, m in enumerate(messages) if m["role"] == "user"), default=0)
            calls, invalid = audit_messages(messages[last_user:])
            result = task["result"] or {}
            citations = result.get("citations", [])
            citation_checks = []
            for c in citations:
                chunk = runtime.db.chunk(c["doc_id"], c["chunk_id"])
                citation_checks.append(
                    bool(
                        chunk
                        and c["quote"] in chunk.text
                        and c["source"] == chunk.source
                        and c["citation_id"] in state.get("evidence", {})
                    )
                )
            llm = [e["data"] for e in events if e["type"] == "llm_completed"]
            contexts = [e["data"] for e in events if e["type"] == "llm_started"]
            tools = [e["data"] for e in events if e["type"] == "tool_completed"]
            names = [c["name"] for c in calls]
            canonical = [
                c["name"] + ":" + json.dumps(c["arguments"], sort_keys=True, ensure_ascii=False)
                for c in calls
            ]
            retrieved = {v["doc_id"] for v in state.get("evidence", {}).values()}
            cited = {c["doc_id"] for c in citations}
            expected = {source_ids[s] for s in required_sources}
            usage = sum(e["usage"] for e in llm if e.get("usage") is not None)
            budget_consistent = (
                task["budget"]["tokens"] == usage
                and task["budget"]["llm_calls"] == len(llm)
                and not task["budget"]["estimated"]
            )
            abstained = (
                result.get("insufficient_evidence") is True and not result.get("findings") and not citations
            )
            uncertainty_text = result.get("conclusion", "") + " " + " ".join(result.get("limitations", []))
            unknown_acknowledged = bool(
                re.search(
                    r"无法确认|不能确认|未提供|缺乏|不足|not (?:available|provided)|cannot",
                    uncertainty_text,
                    re.I,
                )
            )
            success = (
                task["status"] == "succeeded"
                and not invalid
                and all(citation_checks)
                and {"knowledge_search", "compare_evidence", "build_report"} <= set(names)
                and expected <= cited
                and budget_consistent
                and (unknown_acknowledged if i in (0, 1, 3) else True)
                and (abstained if unanswerable else (bool(citations) if required_sources else bool(result)))
            )
            row = {
                "name": name,
                "task_id": task_id,
                "session_id": task["session_id"],
                "question": question,
                "success": success,
                "status": task["status"],
                "error": task["error"],
                "elapsed_ms": (time.perf_counter() - t) * 1000,
                "budget": task["budget"],
                "limits": task["limits_json"],
                "budget_consistent": budget_consistent,
                "reported_tokens": usage,
                "llm_responses": llm,
                "context_metrics": contexts,
                "tool_metrics": tools,
                "calls": calls,
                "invalid_calls": invalid,
                "citations": len(citations),
                "valid_citations": sum(citation_checks),
                "report": result,
                "retrieved_sources": [k for k, v in source_ids.items() if v in retrieved],
                "cited_sources": [k for k, v in source_ids.items() if v in cited],
                "history_messages_before_current_question": max(0, last_user - 1),
                "duplicate_tool_arguments": len(canonical) - len(set(canonical)),
                "tool_cache_hits": sum(e["type"] == "tool_cache_hit" for e in events),
                "search_calls": sum(n == "knowledge_search" for n in names),
                "overretrieval_diagnostic": sum(n == "knowledge_search" for n in names) > 4,
                "abstained": abstained,
                "unknown_acknowledged": unknown_acknowledged,
                "events": events,
            }
            report["cases"].append(row)
            write_json(REPORTS / "real-rag.json", report)
            print(
                name,
                task["status"],
                "success=",
                success,
                "tokens=",
                usage,
                "seconds=",
                round(row["elapsed_ms"] / 1000, 2),
                flush=True,
            )
        rows = report["cases"]
        responses = [e for r in rows for e in r["llm_responses"]]
        report["summary"] = {
            "tasks": len(rows),
            "successful_tasks": sum(r["success"] for r in rows),
            "task_success_rate": sum(r["success"] for r in rows) / len(rows),
            "citations": sum(r["citations"] for r in rows),
            "valid_citations": sum(r["valid_citations"] for r in rows),
            "provider_tokens": sum(r["reported_tokens"] for r in rows),
            "llm_calls": len(responses),
            "tool_executions": sum(len(r["tool_metrics"]) for r in rows),
            "llm_latency_p50_ms": float(np.percentile([r["elapsed_ms"] for r in responses], 50))
            if responses
            else None,
            "llm_latency_p95_ms": float(np.percentile([r["elapsed_ms"] for r in responses], 95))
            if responses
            else None,
            "duplicate_tool_arguments": sum(r["duplicate_tool_arguments"] for r in rows),
            "overretrieval_flags": sum(r["overretrieval_diagnostic"] for r in rows),
        }
        report["passed"] = all(r["success"] for r in rows)
        write_json(REPORTS / "real-rag.json", report)
        lines = [
            "# Real RAG Agent acceptance",
            "",
            "Actual DeepSeek Flash + BGE-M3 + BGE reranker + Qdrant Server, no mock replies or injected faults.",
            "Small sample; automatic checks verify tool flow, budgets and exact source citations, not full factual entailment.",
            "",
            "| Case | Pass | LLM calls | Tokens | Tool executions | Time ms | Citations |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
        for r in rows:
            lines.append(
                f"| {r['name']} | {r['success']} | {len(r['llm_responses'])} | {r['reported_tokens']} | "
                f"{len(r['tool_metrics'])} | {r['elapsed_ms']:.1f} | {r['valid_citations']}/{r['citations']} |"
            )
        lines += [
            "",
            "## Context and loop inspection",
            "",
            "- Full accumulated messages are resent within a turn by the current tool-calling protocol. "
            "Prompt usage/character counts and request fingerprints in real-rag.json expose this cost.",
            "- Session history stores question/report pairs, not past raw tool messages. A follow-up adds history but retrieves fresh evidence.",
            "- Duplicate argument counts and >4-search diagnostic flags are observations; finite Harness budgets remain the actual loop guard.",
            "",
            "```json",
            json.dumps(report["summary"], indent=2),
            "```",
        ]
        (REPORTS / "real-rag.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return report
    finally:
        await runtime.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=int, default=4)
    result = asyncio.run(validate(parser.parse_args().cases))
    if not result["passed"]:
        raise SystemExit(1)
