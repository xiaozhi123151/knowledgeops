# KnowledgeOps verification report

Generated: 2026-10-18T15:54:20.749727+00:00
Source commit: `336de424169e424fae024f8fdf0aa79fff1e6d10`; dirty tree: True

**Separate evidence tracks:** offline fixture tables use model substitutes; the real retrieval table uses pinned BGE models and Qdrant Server. Real RAG adds official DeepSeek API calls. The earlier DeepSeek-only track retains its separate retrieval-substitute boundary. Synthetic faults are labeled; offline results do not establish model quality or production latency.

## Test execution

- pytest: 107 passed, 0 skipped, 0 failed, 0 errors; 294.23 seconds.
- Statement coverage: 88.28% (includes optional live paths in denominator).
- Real HTTP offline PDF smoke: PASS.
- Process recovery test forcibly kills and restarts an interpreter; it does not simulate a restart with an in-memory flag.

## Offline fixture retrieval ablation

30 labeled queries, 12 documents, 3 measured repetitions per query and variant after warmup. Errors count as misses. Document-level ranking.

| Variant | Recall@1 | Recall@5 | Recall@10 | MRR@10 | P50 ms | P95 ms | Error rate |
|---|---:|---:|---:|---:|---:|---:|---:|
| dense | 0.9667 | 1.0000 | 1.0000 | 0.9833 | 24.00 | 43.55 | 0.0000 |
| hybrid | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 23.89 | 41.94 | 0.0000 |
| hybrid_rerank | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 23.21 | 44.56 | 0.0000 |

HTTP round trip includes query embedding, retrieval, rerank and serialization; excludes import, startup and warmup; errors reported separately

## Offline Agent checks

- 30 tasks; completion with valid citations: 100.00%.
- Exact-source citation validity: 100.00% across 90 citations.
- Task latency: P50 609.94 ms; P95 753.51 ms.
- This does not measure semantic answer correctness or conflict-detection accuracy.

## Real API evidence

## Real DeepSeek API integration

Recorded API run: 2026-10-18T15:44:08.805091+00:00; source commit `95dc8e976db89bc06dfb35bfa84c7a8082e2cc4f`.

Status: **PASS**. Model `deepseek-flash`, endpoint `https://api.deepseek.com`, thinking `disabled`.

**Real model calls; actual LangGraph, Harness, BM25 and Qdrant Local. Embedding and reranker remain explicitly labeled local test doubles. This is not full live retrieval-stack validation.**

| Case | Pass | LLM calls | Reported tokens | Time ms | Valid citations |
|---|---|---:|---:|---:|---:|
| version_comparison | True | 4 | 21745 | 7676.03 | 4/4 |
| followup_missing_evidence | True | 4 | 30758 | 8429.78 | 4/4 |
| tool_failure_recovery | True | 4 | 17130 | 8066.45 | 2/2 |

- Actual model requests/responses: 12/12.
- Service-reported tokens: prompt 64553, completion 5080, total 69633.
- Tool attempts completed: 15/16 (93.75%). Denominator includes deliberate local failure injection.
- Invalid model function arguments: 0 / 15 model function calls.
- API call P50/P95: 1556.17/3681.31 ms; task P50/P95: 8066.45/8393.44 ms.
- Percentiles describe this small run only. Tokens use provider usage, not character estimates.
- Budget checks compare persisted attempts and tokens with actual response usage; reservations remain estimated only when a response is unavailable. No API key is part of this report.

Separate real protocol probe: pass=True, 1 request, 1204 reported tokens, 2247.44 ms. It is not included in the three research tasks above.

### Public source provenance

- [DeepSeek-V2](https://raw.githubusercontent.com/deepseek-ai/DeepSeek-V2/main/README.md): raw SHA-256 `03d59c7d02d2d19af8a83f588c2eebaed20b7014179cc0e9370d078f2d702ad4`, 20391 bytes, 48 chunks, fetched 2026-10-15T08:20:50.771959+00:00.
- [DeepSeek-V3](https://raw.githubusercontent.com/deepseek-ai/DeepSeek-V3/main/README.md): raw SHA-256 `1f766f151bb4d501b18c9d1e229ac25682c68c75893d6d3bc9734e2a60125c0e`, 20851 bytes, 44 chunks, fetched 2026-10-15T08:20:51.169432+00:00.
- [DeepSeek-V4.1-Flash](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash/raw/main/README.md): raw SHA-256 `347c9db4e5506acb531cbc3b724407ab88e9af8781679152f0823d7bac16d251`, 13110 bytes, 27 chunks, fetched 2026-10-15T08:20:52.982195+00:00.

### Fault-test boundary

tool_failure_recovery injects one local ConnectionError; API replies remain real. HTTP 429/5xx/timeouts are tested separately with labeled synthetic transports.
Actual service 429/5xx incidents are not claimed. Network errors are injected in HTTP transport tests and identified as synthetic; the recovery scenario injects only one local search failure and uses real API replies.

Actual answers and exploratory failures: [deepseek-integration.md](deepseek-integration.md).

## Follow-up failures retained before repairs

2026-10-18 first full regression: 102 passed / 2 failed / 0 skipped. One incompatible legacy local index and one real-model protocol acceptance failure. The original tests and budgets were retained. Repair `a013932` adds exact comparison IDs, explicit temperature 0 and comparison JSON-object output; a fresh fixture index preserves the original incompatible directory. See [first JUnit](followup-first-junit.xml), [first log](followup-first.log) and [initial real RAG](followup-first-real-rag.json).

Second full run: 105 passed / 1 failed. All four real RAG tasks completed, but the first version-report call used `queries` instead of `quotes`, so the unchanged zero-invalid-call assertion failed. Repair `95dc8e9` explicitly requires the exact quote-map field in generated output; invalid aliases are still rejected. See [second JUnit](followup-second-junit.xml), [second log](followup-second.log) and [second real RAG](followup-second-real-rag.json). Passing reruns do not erase these failures or guarantee future provider conformance.

# 五路真实检索与人工抽查

本表只含 BGE + Qdrant Server 的真实运行。原四路报告保留在 real-retrieval.*。
本轮 120 题 × 5 路 × 3 次 = 1800 次；100 题计入相关性指标，20 道无答案题单独统计。
全部方法共享冻结语料、原始 qrels、50 候选与 top-10；GPU FP16。加载、预热与导入不计入查询延迟。
计时包含 engine.search 和返回命中快照的 Python 序列化；不包含 FastAPI HTTP，非生产负载压测。

| 方法 | Recall@5 | MRR@10 | nDCG@10 | P50 ms | P95 ms | 失败/次数 |
|---|---:|---:|---:|---:|---:|---:|
| Dense | 0.5325 | 0.4717 | 0.4874 | 42.21 | 51.30 | 0/360 |
| Dense+Rerank | 0.7083 | 0.5916 | 0.6167 | 420.20 | 488.39 | 0/360 |
| BM25 | 0.2950 | 0.2665 | 0.2791 | 5.40 | 7.13 | 0/360 |
| Hybrid | 0.4633 | 0.4008 | 0.4316 | 45.23 | 53.65 | 0/360 |
| Hybrid+Rerank | 0.7308 | 0.5877 | 0.6146 | 436.63 | 525.31 | 0/360 |

Dense + Rerank 的 MRR/nDCG 略高，而 Hybrid + Rerank 的 Recall@5 更高。单次固定语料结果不足以证明通用优劣；没有基于结果调整融合权重或测试标准。

## 同题比较（每题一次，不把重复测量当独立问题）

| 左方案 vs 右方案 | 指标 | 胜 | 平 | 负 |
|---|---|---:|---:|---:|
| Dense+Rerank vs Dense | recall_at_5 | 29 | 61 | 10 |
| Dense+Rerank vs Dense | mrr_at_10 | 40 | 44 | 16 |
| Dense+Rerank vs Dense | ndcg_at_10 | 45 | 39 | 16 |
| Hybrid+Rerank vs Hybrid | recall_at_5 | 34 | 62 | 4 |
| Hybrid+Rerank vs Hybrid | mrr_at_10 | 43 | 48 | 9 |
| Hybrid+Rerank vs Hybrid | ndcg_at_10 | 50 | 40 | 10 |
| Dense+Rerank vs Hybrid+Rerank | recall_at_5 | 3 | 90 | 7 |
| Dense+Rerank vs Hybrid+Rerank | mrr_at_10 | 5 | 88 | 7 |
| Dense+Rerank vs Hybrid+Rerank | ndcg_at_10 | 7 | 84 | 9 |

## 实际人工抽查

用户实际评了 2 / 2738 个问题—分块对；完整复核的问题池数为 0。这是定点抽查，不是全量人工金标准。
原始 qrels 不变；没有用两条抽查重算或宣称人工复核后的整体分数。

| 问题 | 来源 | 冻结标签 | 用户评分 | 意义 |
|---|---|---|---:|---|
| Q032 哪个 3.11 并发结构帮助等待一组关联协程完成？ | [asyncio-task](https://raw.githubusercontent.com/python/cpython/v3.12.0/Doc/library/asyncio-task.rst) | unjudged | 2 | 确认存在有效替代证据漏标 |
| Q052 如何配置异步队列使其容量不受正数上限限制？ | [asyncio-subprocess](https://raw.githubusercontent.com/python/cpython/v3.12.0/Doc/library/asyncio-subprocess.rst) | unjudged | 0 | 确认错误对象的召回 |

人工原始回答、来源摘录、chunk ID、接收时间、问题池/提交哈希见 relevance-user-submission.json、relevance-human-ledger.jsonl、retrieval-followup.json。未替用户编写判断理由。
盲审页面：relevance-review.html；导出后执行 `python -m scripts.review_relevance accept 文件.json`。仅全部候选完成判断的问题才会进入单独的 pooled 指标；pool Recall 不等于完整语料 Recall。

## 保留的 Bad Case

Q032：TaskGroup 原文明确给出 3.11 与退出时等待全部任务；用户评为 2，原始 nDCG 仍因漏标而惩罚这段证据。
Q052：重排将子进程 StreamReader buffer 排在队列 maxsize 证据前；用户评为 0，说明存在对象范围混淆。
Q056：队列超时问题中的 Barrier/wait 段落不能替代 Queue + wait_for 的完整依据。此项仍为开发者分析，未获人工评分。
Q081：重排集中返回锁/同步段落，可能遗漏问题中队列 FIFO 的另一半；此项未获人工评分。

## 加载与预热

```json
{
  "embedding_load_ms": 36036.31939998013,
  "reranker_load_ms": 12869.884399988223,
  "import_ms": 235.85659998934716,
  "warmup_ms": 2335.205799987307
}
```


## Four-container real API/Worker acceptance

Result: **PASS**; profile: compose.yaml + compose.acceptance.yaml; CPU float32 BGE pair, real DeepSeek. See [four-container.json](four-container.json).

Detailed environment and per-call latency: [four-container.md](four-container.md).

- both_container_sources_match_checkout: PASS
- four_live_services: PASS
- api_queues_while_worker_stopped: PASS
- restarted_worker_consumes_durable_task: PASS
- real_dense_hybrid_cross_encoder: PASS
- pdf_http_ingestion: PASS
- inflight_worker_sigkill_checkpoint_and_budget_recovery: PASS
- deepseek_tool_call_and_exact_citations: PASS

Actual DeepSeek task budget: `{"estimated": false, "llm_calls": 5, "pending_estimates": 0, "steps": 9, "tokens": 13029, "tool_calls": 7}`.
Validated citations: 4; whole task including worker restart: 39737.28 ms. CPU container acceptance timings are separate from GPU retrieval experiments.

## New real retrieval stack evidence

Real-model experiments below are separate from the historical offline fixture table above. CPU indexing and GPU/CPU query runs identify their device and precision in each artifact.

Qdrant/Redis Docker Compose persistence probe: **PASS**; server 1.17.0. Containers were stopped and recreated with named volumes. Sentinel vectors validate infrastructure only, not semantic retrieval quality.

### Real retrieval experiment

Real BGE dense/CrossEncoder + Qdrant Server. No offline test-double results in this table.
Frozen questions SHA-256: `1f92b0dd071168e63fd39a01991f356cfe6234d889f4ea51ceb08a4c7e8c9c32`; source/config details: real-retrieval.json.
Questions: 120 (answerable 100); chunks: 1201; repetitions: 3.

| Variant | Recall@5 | MRR@10 | nDCG@10 | P50 ms | P95 ms | Failures |
|---|---:|---:|---:|---:|---:|---:|
| Dense | 0.5325 | 0.4717 | 0.4874 | 42.2 | 49.8 | 0/360 |
| BM25 | 0.2950 | 0.2665 | 0.2791 | 5.2 | 7.0 | 0/360 |
| Hybrid | 0.4633 | 0.4008 | 0.4316 | 45.8 | 53.3 | 0/360 |
| Hybrid+Rerank | 0.7308 | 0.5877 | 0.6146 | 443.9 | 542.9 | 0/360 |

## Boundaries and methodology

- Chunk-level judgments. Every overlapping chunk containing an annotated anchor is grade 2; other chunks are unjudged, treated as zero. Short anchors and incomplete judgments can penalize valid alternate evidence.
- 20 unanswerable questions are excluded from Recall/MRR/nDCG denominators. Their nonempty retrieval rate is reported separately; nearest-neighbor search has no calibrated abstention threshold.
- Assistant-authored questions; manual inspection is possible via questions.json evidence context, line and source URL. Independent human relevance review has not been completed. Keyword/semantic pairs share facts, so 120 is not 120 independent facts.
- Fixed 50 candidates, top 10 chunks, RRF k=60, no per-variant tuning, fixed shuffled order; 3 repetitions. Latency includes query embedding, BM25/Qdrant and reranking, excludes load/import/warmup.
- Timing surrounds engine.search (including real Qdrant HTTP requests); FastAPI/browser HTTP serialization is excluded.
- No answer generation occurs in retrieval metrics. These are limited public-document results, not production accuracy.

## Load, import and warmup (excluded from query latency)

```json
{
  "embedding_load_ms": 30005.23239999893,
  "reranker_load_ms": 11945.379499997216,
  "import_ms": 11622.56780000098,
  "warmup_ms": 1283.1225000009
}
```

## Bad cases

- Q014 / BM25: 不想把前缀当作字符集合删掉，3.9 有什么精确删除办法？ Recall@5=0.000, first judged rank=None; top source=DeepSeek-V3. Inspect raw hits and qrels: competing release notes and overlapping/unjudged passages can outrank the exact annotated evidence. This is a candidate explanation, not a causal proof.
- Q056 / Dense: 异步队列不接收等待时长参数时，怎样限制阻塞时间？ Recall@5=0.000, first judged rank=7; top source=asyncio-sync. Inspect raw hits and qrels: competing release notes and overlapping/unjudged passages can outrank the exact annotated evidence. This is a candidate explanation, not a causal proof.
- Q044 / Dense: 3.13 是否已把无解释器锁执行作为全面稳定的默认模式？ Recall@5=0.000, first judged rank=None; top source=python-3.12. Inspect raw hits and qrels: competing release notes and overlapping/unjudged passages can outrank the exact annotated evidence. This is a candidate explanation, not a causal proof.
- Q089 / Hybrid: 结合 3.11 发布说明与任务文档解释新增任务组及其失败语义。 Recall@5=0.000, first judged rank=None; top source=python-3.11. Inspect raw hits and qrels: competing release notes and overlapping/unjudged passages can outrank the exact annotated evidence. This is a candidate explanation, not a causal proof.
- Q057 / BM25: asyncio.Lock 获取顺序是否公平？ Recall@5=0.000, first judged rank=6; top source=asyncio-sync. Inspect raw hits and qrels: competing release notes and overlapping/unjudged passages can outrank the exact annotated evidence. This is a candidate explanation, not a causal proof.
- Q065 / Hybrid: TaskGroup 子任务失败后其余任务怎样处理？ Recall@5=0.000, first judged rank=None; top source=asyncio-task. Inspect raw hits and qrels: competing release notes and overlapping/unjudged passages can outrank the exact annotated evidence. This is a candidate explanation, not a causal proof.
- Q050 / BM25: 异步队列默认先处理最早还是最近加入的项目？ Recall@5=0.000, first judged rank=None; top source=None. Inspect raw hits and qrels: competing release notes and overlapping/unjudged passages can outrank the exact annotated evidence. This is a candidate explanation, not a causal proof.
- Q098 / BM25: 比较 Python 3.9 内置集合泛型注解与 3.12 类型参数语法。 Recall@5=0.000, first judged rank=None; top source=DeepSeek-V4.1-Flash. Inspect raw hits and qrels: competing release notes and overlapping/unjudged passages can outrank the exact annotated evidence. This is a candidate explanation, not a causal proof.
- Q095 / Dense: 能否把 Python 3.11 性能摘要与 3.13 默认关闭的 JIT 当成同一项保证？ Recall@5=0.500, first judged rank=3; top source=python-3.13. Inspect raw hits and qrels: competing release notes and overlapping/unjudged passages can outrank the exact annotated evidence. This is a candidate explanation, not a causal proof.
- Q081 / Hybrid+Rerank: 异步队列与异步锁分别提供怎样的取出顺序与等待公平性？ Recall@5=0.333, first judged rank=2; top source=asyncio-sync. Inspect raw hits and qrels: competing release notes and overlapping/unjudged passages can outrank the exact annotated evidence. This is a candidate explanation, not a causal proof.
- Q052 / BM25: 如何配置异步队列使其容量不受正数上限限制？ Recall@5=0.000, first judged rank=None; top source=None. Inspect raw hits and qrels: competing release notes and overlapping/unjudged passages can outrank the exact annotated evidence. This is a candidate explanation, not a causal proof.
- Q038 / Hybrid+Rerank: 3.12 为泛型声明和类型别名提供了什么新的表达方式？ Recall@5=0.500, first judged rank=1; top source=python-3.12. Inspect raw hits and qrels: competing release notes and overlapping/unjudged passages can outrank the exact annotated evidence. This is a candidate explanation, not a causal proof.
- Q089 / BM25: 结合 3.11 发布说明与任务文档解释新增任务组及其失败语义。 Recall@5=0.000, first judged rank=None; top source=python-3.11. Inspect raw hits and qrels: competing release notes and overlapping/unjudged passages can outrank the exact annotated evidence. This is a candidate explanation, not a causal proof.
- Q012 / Dense: 怎样在 3.9 中用运算符组合两个映射？ Recall@5=0.000, first judged rank=None; top source=python-3.9. Inspect raw hits and qrels: competing release notes and overlapping/unjudged passages can outrank the exact annotated evidence. This is a candidate explanation, not a causal proof.
- Q099 / Hybrid+Rerank: 比较 Python 3.8 vectorcall 与 3.13 JIT 的作用和默认启用情况。 Recall@5=0.000, first judged rank=None; top source=python-3.13. Inspect raw hits and qrels: competing release notes and overlapping/unjudged passages can outrank the exact annotated evidence. This is a candidate explanation, not a causal proof.


### Real RAG Agent acceptance

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


### Observed bad cases and judgment limits

These observations use the frozen 120-question experiment, repetition 0. Full original top-three excerpts,
chunk IDs, URLs and metric values are in `real-bad-case-audit.json`, reproduced with
`python -m scripts.audit_real_bad_cases`. No labels or retrieval parameters were changed after these observations.

| Question | Observation | Metric / limitation |
|---|---|---|
| Q032: 3.11 task-group structure | Dense puts the annotated 3.11 release-note chunk at rank 2; Hybrid moves it to rank 9. BM25 ranks unrelated release/platform text using version-number overlap. | Dense nDCG 0.6309; Hybrid 0.3010. Equal-rank fusion of weak lexical candidates is a plausible degradation mechanism; not a proof across every query. |
| Q032 after rerank | Reranker puts the actual `asyncio-task` TaskGroup documentation first. It states that all tasks are awaited on exit and has `versionadded:: 3.11`. That valid alternate source is unjudged in the frozen qrels. | Recorded nDCG 0.0000 undercounts this alternate evidence. Do not interpret every graded regression as a worse factual answer. |
| Q052: unlimited async queue capacity | Hybrid ranks the annotated Queue maxsize passage first. Reranker promotes two subprocess buffering passages, moving the queue passage to rank 3. | nDCG 1.0000 → 0.5000, Recall@5 remains 1.0000. This is a scope-confusion error in the observed ranking. |
| Q056: queue-operation timeout | Hybrid puts the annotated queue passage at rank 7; reranker omits it from top 10 and ranks synchronization Barrier / wait_for passages. | nDCG 0.3333 → 0.0000. Related generic timeout advice may help partially, but specific queue context is lost. |
| Q081: queue FIFO and lock fairness | Hybrid's top three cover lock fairness and FIFO queue evidence. Reranker's top three concentrate on synchronization primitives. | Recall@5 0.6667 → 0.3333; nDCG 0.8711 → 0.4525. Pair relevance does not explicitly optimize multi-source evidence coverage. Overlap-positive qrels also affect the denominator. |

Across all 100 answerable questions, 10 have lower nDCG after reranking than Hybrid in repetition 0.
The aggregate reranked result improves while individual regressions remain. Hybrid itself is below Dense;
there is no universal benefit from adding BM25 or RRF. Most questions are Chinese and source passages are
English: a lexical-only branch often has no semantic bridge, as Q052/Q056/Q081's empty BM25 result shows.

For the 20 unanswerable questions, Dense/Hybrid/reranked retrieval is nonempty in every attempt, BM25 in 85%.
This is expected from unthresholded nearest-neighbor retrieval and is not answer correctness. Agent refusal
must examine evidence, rather than treating a nonempty hit list as proof.

Next experiments should obtain independent relevance review with pooled alternate passages, add more
independent facts, test title/version-aware inputs and evaluate evidence-diversity selection. Each needs a
new declared dataset/profile and a complete rerun. The current scores remain unchanged; no significance
claim is made from correlated keyword/semantic pairs over 40 facts.


### Real failures and repair evidence

- First full run: 87 passed / 1 failed / 2 skipped. The private-QPS task made 5 searches and hit the next Token reservation after 68,037 reported tokens. Original budgets and success assertions were retained for the passing rerun.
- `69a2190`: additive providers, vector-space namespaces, deletion and frozen public benchmark.
- `db8c263`: Qdrant client/server alignment, pinned weights and explicit inference precision.
- `bb7239b`: server search cap and evidence-body reuse; same unanswerable test now passes.
- Raw failed evidence: real-rag-first-attempt.json / retrieval-first-full-junit.xml. The retrieval quality run was measured at db8c263; the later repair changes Agent control, not retrieval ranking or frozen labels.

## Unverified integrations

- External Embedding API and non-DeepSeek LLMs
- Langfuse server delivery
- 50,000-chunk capacity
- Python application on 3.11 (3.12 Windows and Linux validated)
- Full human relevance judgment coverage; only the recorded spot checks completed

## Skips


## Reproduction and evidence

- README contains the exact commands; raw per-query rankings/times are in retrieval-offline.jsonl and CSV.
- Agent task outcomes, reports and budgets are in agent-offline.jsonl.
- JUnit and coverage are pytest.xml, coverage.xml and coverage.json.
- docs/debugging.md records observed failures, investigation and fixing commits.
- docs/decisions.md records tradeoffs and deployment boundaries.
