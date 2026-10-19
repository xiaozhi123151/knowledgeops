# Real retrieval experiment

Real BGE dense/CrossEncoder + Qdrant Server. No offline test-double results in this table.
Frozen questions SHA-256: `1f92b0dd071168e63fd39a01991f356cfe6234d889f4ea51ceb08a4c7e8c9c32`; source/config details: real-retrieval-fiveway.json.
Questions: 120 (answerable 100); chunks: 1201; repetitions: 3.

| Variant | Recall@5 | MRR@10 | nDCG@10 | P50 ms | P95 ms | Failures |
|---|---:|---:|---:|---:|---:|---:|
| Dense | 0.5325 | 0.4717 | 0.4874 | 42.2 | 51.3 | 0/360 |
| Dense+Rerank | 0.7083 | 0.5916 | 0.6167 | 420.2 | 488.4 | 0/360 |
| BM25 | 0.2950 | 0.2665 | 0.2791 | 5.4 | 7.1 | 0/360 |
| Hybrid | 0.4633 | 0.4008 | 0.4316 | 45.2 | 53.6 | 0/360 |
| Hybrid+Rerank | 0.7308 | 0.5877 | 0.6146 | 436.6 | 525.3 | 0/360 |

## Boundaries and methodology

- Chunk-level judgments. Every overlapping chunk containing an annotated anchor is grade 2; other chunks are unjudged, treated as zero. Short anchors and incomplete judgments can penalize valid alternate evidence.
- 20 unanswerable questions are excluded from Recall/MRR/nDCG denominators. Their nonempty retrieval rate is reported separately; nearest-neighbor search has no calibrated abstention threshold.
- Assistant-authored questions; manual inspection is possible via questions.json evidence context, line and source URL. Initial judgments are not independent human gold labels; subsequent actual human spot checks are tracked separately in relevance-review-status.json. Keyword/semantic pairs share facts, so 120 is not 120 independent facts.
- Fixed 50 candidates, top 10 chunks, RRF k=60, no per-variant tuning, fixed shuffled order; 3 repetitions. Latency includes query embedding, BM25/Qdrant and reranking, excludes load/import/warmup.
- Timing includes engine.search (real Qdrant HTTP requests) and returned-hit snapshot serialization; FastAPI/browser HTTP serialization is excluded.
- No answer generation occurs in retrieval metrics. These are limited public-document results, not production accuracy.

## Load, import and warmup (excluded from query latency)

```json
{
  "embedding_load_ms": 36036.31939998013,
  "reranker_load_ms": 12869.884399988223,
  "import_ms": 235.85659998934716,
  "warmup_ms": 2335.205799987307
}
```

## Bad cases

- Q066 / BM25: 一个关联子协程出错时，结构化任务组会如何处置兄弟任务？ Recall@5=0.000, first judged rank=None; top source=None. Inspect raw hits and qrels: competing release notes and overlapping/unjudged passages can outrank the exact annotated evidence. This is a candidate explanation, not a causal proof.
- Q088 / Dense+Rerank: Python 3.11 的异常组与 TaskGroup 失败处理怎样联系起来？ Recall@5=0.000, first judged rank=7; top source=asyncio-task. Inspect raw hits and qrels: competing release notes and overlapping/unjudged passages can outrank the exact annotated evidence. This is a candidate explanation, not a causal proof.
- Q073 / Hybrid: asyncio 流读取器默认缓冲限制是多少？ Recall@5=0.000, first judged rank=None; top source=asyncio-queue. Inspect raw hits and qrels: competing release notes and overlapping/unjudged passages can outrank the exact annotated evidence. This is a candidate explanation, not a causal proof.
- Q064 / Hybrid: 能否让不同操作系统线程安全地共享这些协程锁？ Recall@5=0.000, first judged rank=None; top source=python-3.12. Inspect raw hits and qrels: competing release notes and overlapping/unjudged passages can outrank the exact annotated evidence. This is a candidate explanation, not a causal proof.
- Q093 / Dense: 从 3.10 到 3.12，OpenSSL 最低要求与 distutils 的移除分别是什么变化？ Recall@5=0.000, first judged rank=8; top source=python-3.10. Inspect raw hits and qrels: competing release notes and overlapping/unjudged passages can outrank the exact annotated evidence. This is a candidate explanation, not a causal proof.
- Q031 / Hybrid: Python 3.11 asyncio 新增哪个任务组 API？ Recall@5=0.000, first judged rank=None; top source=python-3.10. Inspect raw hits and qrels: competing release notes and overlapping/unjudged passages can outrank the exact annotated evidence. This is a candidate explanation, not a causal proof.
- Q018 / Hybrid+Rerank: 升级 3.10 后，加密库的最低兼容基线是什么？ Recall@5=0.000, first judged rank=None; top source=python-3.12. Inspect raw hits and qrels: competing release notes and overlapping/unjudged passages can outrank the exact annotated evidence. This is a candidate explanation, not a causal proof.
- Q012 / BM25: 怎样在 3.9 中用运算符组合两个映射？ Recall@5=0.000, first judged rank=None; top source=DeepSeek-V3. Inspect raw hits and qrels: competing release notes and overlapping/unjudged passages can outrank the exact annotated evidence. This is a candidate explanation, not a causal proof.
- Q078 / BM25: 为什么子进程写满输出管道后，单纯等待进程退出可能永远卡住？ Recall@5=0.000, first judged rank=None; top source=None. Inspect raw hits and qrels: competing release notes and overlapping/unjudged passages can outrank the exact annotated evidence. This is a candidate explanation, not a causal proof.
- Q043 / Dense+Rerank: Python 3.13 无 GIL 支持属于什么成熟度？ Recall@5=0.000, first judged rank=None; top source=python-3.12. Inspect raw hits and qrels: competing release notes and overlapping/unjudged passages can outrank the exact annotated evidence. This is a candidate explanation, not a causal proof.
- Q096 / BM25: 比较 Python 3.11 标准库新增的 TOML 解析能力与 3.12 移除的构建包。 Recall@5=0.667, first judged rank=1; top source=python-3.11. Inspect raw hits and qrels: competing release notes and overlapping/unjudged passages can outrank the exact annotated evidence. This is a candidate explanation, not a causal proof.
- Q022 / BM25: 3.10 如何用竖线声明值可属于两种类型之一？ Recall@5=0.000, first judged rank=None; top source=python-3.12. Inspect raw hits and qrels: competing release notes and overlapping/unjudged passages can outrank the exact annotated evidence. This is a candidate explanation, not a causal proof.
- Q091 / BM25: 比较 Python 3.12 每子解释器 GIL 与 3.13 实验性 free-threading，两者是否同一能力？ Recall@5=0.000, first judged rank=None; top source=python-3.13. Inspect raw hits and qrels: competing release notes and overlapping/unjudged passages can outrank the exact annotated evidence. This is a candidate explanation, not a causal proof.
- Q099 / Dense: 比较 Python 3.8 vectorcall 与 3.13 JIT 的作用和默认启用情况。 Recall@5=0.500, first judged rank=3; top source=python-3.12. Inspect raw hits and qrels: competing release notes and overlapping/unjudged passages can outrank the exact annotated evidence. This is a candidate explanation, not a causal proof.
- Q089 / Hybrid: 结合 3.11 发布说明与任务文档解释新增任务组及其失败语义。 Recall@5=0.000, first judged rank=None; top source=python-3.11. Inspect raw hits and qrels: competing release notes and overlapping/unjudged passages can outrank the exact annotated evidence. This is a candidate explanation, not a causal proof.
