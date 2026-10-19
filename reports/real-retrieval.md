# Real retrieval experiment

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
