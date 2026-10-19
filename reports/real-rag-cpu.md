# Real RAG Agent acceptance

Actual DeepSeek Flash + BGE-M3 + BGE reranker + Qdrant Server, no mock replies or injected faults.
Small sample; automatic checks verify tool flow, budgets and exact source citations, not full factual entailment.

| Case | Pass | LLM calls | Tokens | Tool executions | Time ms | Citations |
|---|---|---:|---:|---:|---:|---:|
| three_versions | True | 4 | 30830 | 6 | 79630.0 | 4/4 |

## Context and loop inspection

- Full accumulated messages are resent within a turn by the current tool-calling protocol. Prompt usage/character counts and request fingerprints in real-rag.json expose this cost.
- Session history stores question/report pairs, not past raw tool messages. A follow-up adds history but retrieves fresh evidence.
- Duplicate argument counts and >4-search diagnostic flags are observations; finite Harness budgets remain the actual loop guard.

```json
{
  "tasks": 1,
  "successful_tasks": 1,
  "task_success_rate": 1.0,
  "citations": 4,
  "valid_citations": 4,
  "provider_tokens": 30830,
  "llm_calls": 4,
  "tool_executions": 6,
  "llm_latency_p50_ms": 3584.6465499980695,
  "llm_latency_p95_ms": 4767.506704997686,
  "duplicate_tool_arguments": 0,
  "overretrieval_flags": 0
}
```
