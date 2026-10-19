# Recorded failure analysis

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
