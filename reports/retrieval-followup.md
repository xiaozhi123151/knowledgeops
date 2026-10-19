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
