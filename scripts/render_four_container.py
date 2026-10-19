"""Render the recorded real-container result. No API requests and no synthetic measurements."""

import json

import numpy as np

from scripts.common import REPORTS


def main():
    report = json.loads((REPORTS / "four-container.json").read_text(encoding="utf-8"))
    lines = ["# 四容器真实 API / Worker 验收", "",
             f"结果：**{'PASS' if report.get('passed') else 'FAIL'}**；记录时间：{report['metadata']['at_utc']}。",
             "配置：compose.yaml + compose.acceptance.yaml；API/Worker 分离，共享 SQLite WAL，Redis Streams 投递，"
             "Qdrant Server 持久化；CPU FP32 BGE-M3 + bge-reranker-v2-m3 + 官方 DeepSeek Flash 非思考模式。",
             "使用工程样例 PDF 和自有 TXT 验证部署闭环，不把这组任务当作公开语料回答质量评测。", "",
             "| 检查 | 结果 |", "|---|---|"]
    for name, passed in report.get("checks", {}).items():
        lines.append(f"| {name} | {'PASS' if passed else 'FAIL'} |")
    events = report.get("events", [])
    llm = [e["data"] for e in events if e["type"] == "llm_completed"]
    tools = [e["data"] for e in events if e["type"] == "tool_completed"]
    attempts = [e for e in events if e["type"] == "tool_started"]
    searches = [e["data"] for e in events if e["type"] == "llm_started"]
    task = report.get("research", {})
    lines += ["", "## 实际研究调用与恢复", "",
              "强制终止发生在真实 LLM 返回后；随后启动同一 Worker 容器，等待 SQLite 租约回收并恢复 LangGraph。",
              "停止 Worker 期间，通过 API 新建的导入任务保持 queued，重启后才完成。", "",
              "| 观测 | 数值 |", "|---|---|",
              f"| SIGKILL 前预算 | `{json.dumps(report.get('budget_at_worker_kill',{}))}` |",
              f"| 最终预算 | `{json.dumps(task.get('budget',{}))}` |",
              f"| 完成的真实 LLM 调用 / usage 合计 | {len(llm)} / {sum(c['usage'] or 0 for c in llm)} Token |",
              f"| 工具成功 / 尝试 | {len(tools)} / {len(attempts)} |",
              f"| 工具缓存命中 | {sum(e['type']=='tool_cache_hit' for e in events)} |",
              f"| 通过原文接口核验的引用 | {report.get('validated_citations',0)} |",
              f"| 整体研究耗时（含 Worker 冷启动与租约恢复） | {report.get('research_elapsed_ms',0):.2f} ms |"]
    if llm:
        latencies = [c["elapsed_ms"] for c in llm]
        lines += [f"| 该任务 LLM 网络调用 P50 / P95 | {np.percentile(latencies,50):.2f} / "
                  f"{np.percentile(latencies,95):.2f} ms |"]
    lines += [f"| 单次请求重复证据正文次数最大值 | "
              f"{max((c.get('repeated_search_evidence_chunks',0) for c in searches),default=0)} |", "",
              "该验收只有一个被强制中断的研究任务，不能从 1/1 外推通用恢复率或生产延迟。"
              "Token 来自真实 provider usage；远端在网络中断时的潜在重复计费不承诺 exactly-once。", "",
              "## 实际容器环境与源码", "", "```json",
              json.dumps(report.get("deployed_environment", {}), ensure_ascii=False, indent=2), "```", "",
              "API 和 Worker 源码 SHA-256 均与当前目录匹配。原始容器清单、就绪信息、预算、事件、查询得分和报告："
              "[four-container.json](four-container.json)。", "",
              "## 复现", "", "```powershell", "uv run python -m scripts.prepare_acceptance",
              "# 按 README 启动 compose.yaml + compose.acceptance.yaml",
              "uv run python -m scripts.verify_four_container --wsl",
              "uv run python -m scripts.render_four_container", "```", ""]
    (REPORTS / "four-container.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
