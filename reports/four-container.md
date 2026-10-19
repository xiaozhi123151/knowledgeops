# 四容器真实 API / Worker 验收

结果：**PASS**；记录时间：2026-10-18T15:44:33.951652+00:00。
配置：compose.yaml + compose.acceptance.yaml；API/Worker 分离，共享 SQLite WAL，Redis Streams 投递，Qdrant Server 持久化；CPU FP32 BGE-M3 + bge-reranker-v2-m3 + 官方 DeepSeek Flash 非思考模式。
使用工程样例 PDF 和自有 TXT 验证部署闭环，不把这组任务当作公开语料回答质量评测。

| 检查 | 结果 |
|---|---|
| both_container_sources_match_checkout | PASS |
| four_live_services | PASS |
| api_queues_while_worker_stopped | PASS |
| restarted_worker_consumes_durable_task | PASS |
| real_dense_hybrid_cross_encoder | PASS |
| pdf_http_ingestion | PASS |
| inflight_worker_sigkill_checkpoint_and_budget_recovery | PASS |
| deepseek_tool_call_and_exact_citations | PASS |

## 实际研究调用与恢复

强制终止发生在真实 LLM 返回后；随后启动同一 Worker 容器，等待 SQLite 租约回收并恢复 LangGraph。
停止 Worker 期间，通过 API 新建的导入任务保持 queued，重启后才完成。

| 观测 | 数值 |
|---|---|
| SIGKILL 前预算 | `{"estimated": false, "llm_calls": 1, "pending_estimates": 0, "steps": 2, "tokens": 1625, "tool_calls": 2}` |
| 最终预算 | `{"estimated": false, "llm_calls": 5, "pending_estimates": 0, "steps": 9, "tokens": 13029, "tool_calls": 7}` |
| 完成的真实 LLM 调用 / usage 合计 | 5 / 13029 Token |
| 工具成功 / 尝试 | 6 / 7 |
| 工具缓存命中 | 1 |
| 通过原文接口核验的引用 | 4 |
| 整体研究耗时（含 Worker 冷启动与租约恢复） | 39737.28 ms |
| 该任务 LLM 网络调用 P50 / P95 | 1388.35 / 3445.44 ms |
| 单次请求重复证据正文次数最大值 | 0 |

该验收只有一个被强制中断的研究任务，不能从 1/1 外推通用恢复率或生产延迟。Token 来自真实 provider usage；远端在网络中断时的潜在重复计费不承诺 exactly-once。

## 实际容器环境与源码

```json
{
  "api": {
    "source_sha256": "774547a6a4dfbd2b8d9936fe77ac05ce3e8d03b873a6e72e22c82ea16c430aa0",
    "files": 38,
    "python": "3.12.15",
    "dependencies": {
      "torch": "2.14.1+cpu",
      "sentence-transformers": "5.7.0",
      "transformers": "5.19.0",
      "qdrant-client": "1.17.1"
    }
  },
  "worker": {
    "source_sha256": "774547a6a4dfbd2b8d9936fe77ac05ce3e8d03b873a6e72e22c82ea16c430aa0",
    "files": 38,
    "python": "3.12.15",
    "dependencies": {
      "torch": "2.14.1+cpu",
      "sentence-transformers": "5.7.0",
      "transformers": "5.19.0",
      "qdrant-client": "1.17.1"
    }
  }
}
```

API 和 Worker 源码 SHA-256 均与当前目录匹配。原始容器清单、就绪信息、预算、事件、查询得分和报告：[four-container.json](four-container.json)。

## 复现

```powershell
uv run python -m scripts.prepare_acceptance
# 按 README 启动 compose.yaml + compose.acceptance.yaml
uv run python -m scripts.verify_four_container --wsl
uv run python -m scripts.render_four_container
```
