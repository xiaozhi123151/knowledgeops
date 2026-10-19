# Real RAG Agent acceptance

Actual DeepSeek Flash + BGE-M3 + BGE reranker + Qdrant Server, no mock replies or injected faults.
Small sample; automatic checks verify tool flow, budgets and exact source citations, not full factual entailment.

| Case | Pass | LLM calls | Tokens | Tool executions | Time ms | Citations |
|---|---|---:|---:|---:|---:|---:|
| three_versions | True | 4 | 23333 | 5 | 10397.7 | 3/3 |
| multi_turn_missing_metric | True | 4 | 36048 | 6 | 10096.0 | 3/3 |
| python_lock_versions | True | 4 | 24768 | 4 | 8826.5 | 5/5 |
| private_metric_unanswerable | True | 5 | 46046 | 6 | 10375.9 | 0/0 |

## Context and loop inspection

- Full accumulated messages are resent within a turn by the current tool-calling protocol. Prompt usage/character counts and request fingerprints in real-rag.json expose this cost.
- Session history stores question/report pairs, not past raw tool messages. A follow-up adds history but retrieves fresh evidence.
- Duplicate argument counts and >4-search diagnostic flags are observations; finite Harness budgets remain the actual loop guard.

```json
{
  "tasks": 4,
  "successful_tasks": 4,
  "task_success_rate": 1.0,
  "citations": 11,
  "valid_citations": 11,
  "provider_tokens": 130195,
  "llm_calls": 17,
  "tool_executions": 21,
  "llm_latency_p50_ms": 1631.8994000030216,
  "llm_latency_p95_ms": 3490.8053800114426,
  "duplicate_tool_arguments": 0,
  "overretrieval_flags": 0
}
```
