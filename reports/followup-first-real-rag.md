# Real RAG Agent acceptance

Actual DeepSeek Flash + BGE-M3 + BGE reranker + Qdrant Server, no mock replies or injected faults.
Small sample; automatic checks verify tool flow, budgets and exact source citations, not full factual entailment.

| Case | Pass | LLM calls | Tokens | Tool executions | Time ms | Citations |
|---|---|---:|---:|---:|---:|---:|
| three_versions | False | 5 | 24223 | 4 | 11059.9 | 0/0 |
| multi_turn_missing_metric | True | 4 | 30019 | 6 | 12680.2 | 3/3 |
| python_lock_versions | False | 5 | 24134 | 4 | 9918.7 | 5/5 |
| private_metric_unanswerable | True | 6 | 56937 | 5 | 10966.1 | 0/0 |

## Context and loop inspection

- Full accumulated messages are resent within a turn by the current tool-calling protocol. Prompt usage/character counts and request fingerprints in real-rag.json expose this cost.
- Session history stores question/report pairs, not past raw tool messages. A follow-up adds history but retrieves fresh evidence.
- Duplicate argument counts and >4-search diagnostic flags are observations; finite Harness budgets remain the actual loop guard.

```json
{
  "tasks": 4,
  "successful_tasks": 2,
  "task_success_rate": 0.5,
  "citations": 8,
  "valid_citations": 8,
  "provider_tokens": 135313,
  "llm_calls": 20,
  "tool_executions": 19,
  "llm_latency_p50_ms": 1527.3003999900538,
  "llm_latency_p95_ms": 3831.026839996048,
  "duplicate_tool_arguments": 0,
  "overretrieval_flags": 0
}
```
