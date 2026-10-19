# 运行与评测

所有命令均从仓库根目录执行。配置项见 `.env.example`；密钥放在本地 `.env` 或环境变量中。

## 离线模式

```bash
uv sync --locked --extra dev
uv run python -m knowledgeops
```

访问 `http://127.0.0.1:8000`，页面访问密钥为 `offline-local-only`。无需创建 `.env`。
离线模式运行实际 PDF 提取、LangGraph、SQLite、BM25 与 Qdrant Local；LLM、Embedding 和 Reranker 使用确定性替身。
需要调整配置时，首次复制 `.env.example` 为 `.env`；已有 `.env` 时保留原配置。

## 单独接入 DeepSeek

在 `.env` 中设置：

```dotenv
KO_MODE=offline
KO_LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=在本地填写
KO_DEEPSEEK_BASE_URL=https://api.deepseek.com
KO_DEEPSEEK_MODEL=deepseek-flash
```

这组配置使用真实 LLM，检索模型仍为替身。若要复现真实 BGE 检索，请继续配置下节。
DeepSeek 使用非思考模式、温度 0；SDK 隐式重试关闭，重试与 Token 消耗统一计入 Harness。
Web 页面的访问密钥对应 `KO_API_KEY`，与后端的 DeepSeek 密钥是两个配置。

## BGE 模型与检索实验

```bash
uv sync --locked --extra dev --extra models
uv run --extra models python -m scripts.fetch_retrieval_models
docker compose -f compose.retrieval.yaml up -d
uv run --extra models python -m scripts.evaluate_real_retrieval --repetitions 3 --prefix my-fiveway
```

模型下载约 4.6 GB，保存在 `data/models/`；脚本固定模型 revision 并记录 SHA-256。
评测使用仓库中的冻结公开语料，自动建立独立索引，需要可访问的 Qdrant Server。
默认 CPU FP32；设置 `KO_EXPERIMENT_DEVICE=cuda` 使用 GPU FP16，需要安装匹配的 CUDA PyTorch。
切换设备与精度会使用不同的索引指纹，不能混用已有向量空间。

已测 CUDA 环境为 Windows / Python 3.12，可用独立环境复现：

```powershell
uv venv data/venv-cuda --python 3.12
uv pip install --python data/venv-cuda/Scripts/python.exe --no-deps -r requirements-cuda-windows.lock
uv pip install --python data/venv-cuda/Scripts/python.exe --no-deps -e .
$env:KO_EXPERIMENT_DEVICE='cuda'
& data/venv-cuda/Scripts/python.exe -m scripts.evaluate_real_retrieval --repetitions 3 --prefix my-fiveway
& data/venv-cuda/Scripts/python.exe -m scripts.validate_real_rag
```

该锁文件不适用于其他平台。CPU 与 GPU 的延迟分开比较，模型加载和预热时间单独记录。
不同输出前缀便于保留已有报告。指标定义和标签限制见 [语料说明](../evals/public_technical/README.md)。

## 四容器部署

已验收组合为 API、Worker、Qdrant 和 Redis，使用本地 BGE-M3、CrossEncoder 与 DeepSeek Flash。
需要 Docker Compose 2.24.4+、下载完成的模型和足够的系统内存；CPU 配置建议预留约 16 GB。
先在 `.env` 或环境变量设置 `DEEPSEEK_API_KEY`，生成独立的应用访问凭证：

```bash
uv run python -m scripts.prepare_acceptance
```

Linux 主机：

```bash
docker compose --env-file data/acceptance/compose.env -p knowledgeops-acceptance -f compose.yaml -f compose.acceptance.yaml up --build -d
uv run python -m scripts.verify_four_container
```

Windows PowerShell + WSL2 Ubuntu：

```powershell
$projectPath = (wsl -d Ubuntu wslpath -a (Get-Location).Path).Trim()
wsl -d Ubuntu -u root -- docker compose --project-directory $projectPath --env-file data/acceptance/compose.env -p knowledgeops-acceptance -f compose.yaml -f compose.acceptance.yaml up --build -d
uv run python -m scripts.verify_four_container --wsl
```

Windows Docker Desktop 用户需将 `data/acceptance/compose.env` 中的模型和私有配置路径改为 Docker 可访问的 Windows 路径，直接运行 Docker 命令并省略 `--wsl`。
模型只读挂载，API/Worker 共享 SQLite 卷，Qdrant 与 Redis 使用独立持久卷。服务入口是 `http://127.0.0.1:18000`；Qdrant 和 Redis 不向宿主机开放端口。
`data/acceptance/service.env` 包含应用访问凭证和 DeepSeek 密钥，保持在本机。
`verify_four_container` 会停止、重启并强制终止一次 Worker，请仅指向独立验收实例。

通用 OpenAI-compatible LLM / Embedding API 可通过 `.env.example` 中的地址、模型及独立密钥配置，使用基础 `compose.yaml` 启动。
Embedding 的模型、维度、归一化、精度或分块策略改变后，需要重建索引。

## 测试入口

```bash
uv run pytest -q -m "not live"
uv run ruff check src tests scripts
uv run python -m scripts.smoke --mode offline
uv run python -m scripts.check_secrets
```

真实集成的开启条件：

| 测试 | 条件 |
|---|---|
| DeepSeek 工具调用 | `DEEPSEEK_API_KEY` 已配置，`KO_RUN_DEEPSEEK_TESTS` 未设为 `0` |
| BGE / Qdrant | `KO_RUN_RETRIEVAL_TESTS=1`，本地权重和 Qdrant 就绪 |
| 真实 RAG Agent | `KO_RUN_RAG_TESTS=1`，权重、索引、Redis、Qdrant 和 DeepSeek 就绪 |
| HTTP API | `KO_RUN_LIVE_TESTS=1`、`KO_TEST_BASE_URL`、私有 `KO_API_KEY` |
| 四容器恢复 | `KO_RUN_FOUR_CONTAINER_TESTS=1`；WSL 环境另设 `KO_DOCKER_IN_WSL=1` |

以上测试会调用外部模型或操作验收容器。完整验收入口：

```powershell
& data/venv-cuda/Scripts/python.exe -m scripts.run_acceptance_tests --wsl --device cuda
```

这会生成新的测试报告，不应把跳过的集成项计为通过。离线评测单独使用 `scripts.evaluate_retrieval --mode offline`，不与真实模型成绩合表。

## 人工相关性复核

```bash
uv run --extra models python -m scripts.review_relevance prepare --prefix real-retrieval-fiveway
uv run python -m http.server 8766 --bind 127.0.0.1 --directory reports
```

打开 `http://127.0.0.1:8766/relevance-review.html`，按证据给出 0/1/2 级判断并导出 JSON，再执行：

```bash
uv run python -m scripts.review_relevance accept review.json
uv run python -m scripts.summarize_retrieval_followup
```

复核记录追加保存，冻结的原始成绩保持不变。只有候选全部完成判断的问题池才生成独立 pooled 指标。

## 备份与观测

停止 API 与 Worker 后，一起备份应用数据库及 WAL/SHM、Qdrant 持久卷。不要在写入时分别复制 SQLite 文件。
`scripts.rebuild --help` 提供重建入口：使用旧原文件构建新索引，保留旧数据；不要直接覆盖不兼容的向量空间。

Langfuse 可通过 `KO_LANGFUSE_PUBLIC_KEY`、`KO_LANGFUSE_SECRET_KEY`、`KO_LANGFUSE_BASE_URL` 配置；未配置时使用本地事件记录。
默认 Trace 只发操作元数据，不发送问题、原文或密钥；真实 Langfuse 服务投递仍待验证。
业务 API 使用 `X-API-Key`，路径统一以 `/api/v1` 开头；接口详情见运行后的 `/docs`。
健康检查为 `/health/live` 和 `/health/ready`，就绪状态只检查存储及 Worker，不触发付费 LLM 请求。
