# Real RAG Agent acceptance

Actual DeepSeek Flash + BGE-M3 + BGE reranker + Qdrant Server, no mock replies or injected faults.
Small sample; automatic checks verify tool flow, budgets and exact source citations, not full factual entailment.

| Case | Pass | LLM calls | Tokens | Tool executions | Time ms | Citations |
|---|---|---:|---:|---:|---:|---:|
| three_versions | True | 4 | 22963 | 5 | 10690.9 | 3/3 |
| multi_turn_missing_metric | True | 4 | 36016 | 6 | 12844.2 | 3/3 |
| python_lock_versions | True | 4 | 36376 | 6 | 12907.3 | 6/6 |
| private_metric_unanswerable | False | 5 | 68037 | 6 | 8387.0 | 0/0 |

## Context and loop inspection

- Full accumulated messages are resent within a turn by the current tool-calling protocol. Prompt usage/character counts and request fingerprints in real-rag.json expose this cost.
- Session history stores question/report pairs, not past raw tool messages. A follow-up adds history but retrieves fresh evidence.
- Duplicate argument counts and >4-search diagnostic flags are observations; finite Harness budgets remain the actual loop guard.

```json
{
  "tasks": 4,
  "successful_tasks": 3,
  "task_success_rate": 0.75,
  "citations": 12,
  "valid_citations": 12,
  "provider_tokens": 163392,
  "llm_calls": 17,
  "tool_executions": 23,
  "llm_latency_p50_ms": 1640.9499000001233,
  "llm_latency_p95_ms": 4516.364800000155,
  "duplicate_tool_arguments": 0,
  "overretrieval_flags": 1
}
```
