"""Summarize recorded five-way measurements and actual human spot checks, without model calls."""

import json
from collections import Counter

from scripts.common import REPORTS, write_json


def main():
    prefix = "real-retrieval-fiveway"
    report = json.loads((REPORTS / f"{prefix}.json").read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in (REPORTS / f"{prefix}-raw.jsonl").read_text(encoding="utf-8").splitlines()]
    first = {(r["query_id"], r["variant"]): r for r in rows if r["repetition"] == 0}
    qids = sorted({r["query_id"] for r in rows if r["answerable"]})
    comparisons = []
    for left, right in [("Dense+Rerank", "Dense"), ("Hybrid+Rerank", "Hybrid"),
                        ("Dense+Rerank", "Hybrid+Rerank")]:
        for metric in ("recall_at_5", "mrr_at_10", "ndcg_at_10"):
            signs = Counter("win" if first[qid, left][metric] > first[qid, right][metric] + 1e-12
                            else "loss" if first[qid, left][metric] < first[qid, right][metric] - 1e-12
                            else "tie" for qid in qids)
            comparisons.append({"left": left, "right": right, "metric": metric,
                                **{k: signs[k] for k in ("win", "tie", "loss")}})
    status = json.loads((REPORTS / "relevance-review-status.json").read_text(encoding="utf-8"))
    pool = json.loads((REPORTS / "relevance-review-pool.json").read_text(encoding="utf-8"))
    original = json.loads((REPORTS / f"{prefix}-qrels.json").read_text(encoding="utf-8"))
    by_item = {i["item_id"]: i for i in pool["items"]}
    judgments = []
    ledger = REPORTS / "relevance-human-ledger.jsonl"
    if ledger.exists():
        for record in map(json.loads, ledger.read_text(encoding="utf-8").splitlines()):
            if record["pool_sha256"] != pool["pool_sha256"]:
                continue
            for j in record["judgments"]:
                item = by_item[j["item_id"]]
                judgments.append({**item, **j, "reviewer": record["reviewer"],
                                  "provenance": record.get("provenance"),
                                  "frozen_grade": original[item["query_id"]].get(item["chunk_id"], "unjudged")})
    output = {"experiment_metadata": report["metadata"], "summary": report["summary"],
              "paired_question_counts": comparisons, "human_review": status, "judgments": judgments}
    write_json(REPORTS / "retrieval-followup.json", output)
    lines = ["# 五路真实检索与人工抽查", "", "本表只含 BGE + Qdrant Server 的真实运行。原四路报告保留在 real-retrieval.*。",
             "本轮 120 题 × 5 路 × 3 次 = 1800 次；100 题计入相关性指标，20 道无答案题单独统计。",
             "全部方法共享冻结语料、原始 qrels、50 候选与 top-10；GPU FP16。加载、预热与导入不计入查询延迟。",
             "计时包含 engine.search 和返回命中快照的 Python 序列化；不包含 FastAPI HTTP，非生产负载压测。", "",
             "| 方法 | Recall@5 | MRR@10 | nDCG@10 | P50 ms | P95 ms | 失败/次数 |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for name, s in report["summary"].items():
        lines.append(f"| {name} | {s['recall_at_5']:.4f} | {s['mrr_at_10']:.4f} | {s['ndcg_at_10']:.4f} | "
                     f"{s['p50_ms']:.2f} | {s['p95_ms']:.2f} | {s['failures']}/{s['attempts']} |")
    lines += ["", "Dense + Rerank 的 MRR/nDCG 略高，而 Hybrid + Rerank 的 Recall@5 更高。"
              "单次固定语料结果不足以证明通用优劣；没有基于结果调整融合权重或测试标准。", "",
              "## 同题比较（每题一次，不把重复测量当独立问题）", "",
              "| 左方案 vs 右方案 | 指标 | 胜 | 平 | 负 |", "|---|---|---:|---:|---:|"]
    for c in comparisons:
        lines.append(f"| {c['left']} vs {c['right']} | {c['metric']} | {c['win']} | {c['tie']} | {c['loss']} |")
    lines += ["", "## 实际人工抽查", "",
              f"用户实际评了 {status['human_reviewed_items']} / {status['pooled_items']} 个问题—分块对；"
              f"完整复核的问题池数为 {len(status['fully_reviewed_questions'])}。这是定点抽查，不是全量人工金标准。",
              "原始 qrels 不变；没有用两条抽查重算或宣称人工复核后的整体分数。", "",
              "| 问题 | 来源 | 冻结标签 | 用户评分 | 意义 |", "|---|---|---|---:|---|"]
    for j in judgments:
        meaning = "确认存在有效替代证据漏标" if j["grade"] > 0 and j["frozen_grade"] == "unjudged" else "确认错误对象的召回"
        lines.append(f"| {j['query_id']} {j['question']} | [{j['title']}]({j['source']}) | {j['frozen_grade']} | {j['grade']} | {meaning} |")
    lines += ["", "人工原始回答、来源摘录、chunk ID、接收时间、问题池/提交哈希见 relevance-user-submission.json、"
              "relevance-human-ledger.jsonl、retrieval-followup.json。未替用户编写判断理由。",
              "盲审页面：relevance-review.html；导出后执行 `python -m scripts.review_relevance accept 文件.json`。"
              "仅全部候选完成判断的问题才会进入单独的 pooled 指标；pool Recall 不等于完整语料 Recall。", "",
              "## 保留的 Bad Case", "",
              "Q032：TaskGroup 原文明确给出 3.11 与退出时等待全部任务；用户评为 2，原始 nDCG 仍因漏标而惩罚这段证据。",
              "Q052：重排将子进程 StreamReader buffer 排在队列 maxsize 证据前；用户评为 0，说明存在对象范围混淆。",
              "Q056：队列超时问题中的 Barrier/wait 段落不能替代 Queue + wait_for 的完整依据。此项仍为开发者分析，未获人工评分。",
              "Q081：重排集中返回锁/同步段落，可能遗漏问题中队列 FIFO 的另一半；此项未获人工评分。", "",
              "## 加载与预热", "", "```json", json.dumps(report["timings"], indent=2), "```", ""]
    (REPORTS / "retrieval-followup.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
