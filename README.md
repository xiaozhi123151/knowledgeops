# KnowledgeOps

单用户知识研究 MVP：PDF / Markdown / TXT / 网页导入，Dense、BM25、RRF 与 CrossEncoder 重排，LangGraph
工具调用 Agent、可追踪引用、持久预算、故障恢复、Web UI、评测和 Docker Compose。

**已验证离线闭环、真实 DeepSeek、BGE-M3 / CrossEncoder 和 Qdrant/Redis Compose，并完成 120 题真实检索实验。**
默认 auto/offline 保留替身；真实 CPU / CUDA 实验、历史离线成绩和不同部署边界分别报告。
实际测试与指标见 [reports/verification.md](reports/verification.md)，不能作为真实模型准确率或生产性能。

## 无密钥启动

Python 3.11/3.12，安装 uv 后，在 Windows PowerShell 执行：

```powershell
git clone https://github.com/xiaozhi123151/knowledgeops.git
Set-Location knowledgeops
uv sync --locked --extra dev
# 仅当 .env 不存在时复制，保留已有配置
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
uv run python -m knowledgeops
```

打开 <http://127.0.0.1:8000>，访问密钥输入 `offline-local-only`，点击“连接知识库”，上传
`examples/sample.pdf`，等待文档 ready，提问 `How does Redis AOF persistence work?`。
开始研究后可查看步骤、调用次数、预算和最终报告；展开引用可查看页码、文本偏移与原文。
继续提问沿用会话，“新建会话”清除当前会话选择。

offline 使用实际 pypdf、LangGraph、SQLite、Qdrant Local 和 BM25，以及 scripted LLM、哈希 Embedding、
词项重合 Reranker。运行不需要网络、Redis 或模型下载；首次安装依赖需要网络。
本环境 PyPI 连接不稳定，因此 pyproject.toml 声明了清华镜像，uv.lock 锁定版本与哈希；换源需显式重新生成锁文件。
参考 tokenizer 数据已附带并校验上游 SHA-256，来源见 `scripts/vendor_tokenizer.py`。

## 增量接入 DeepSeek：只替换 LLM

现有 `complete(messages, tools, max_tokens) -> (assistant_message, total_tokens)` 接口保持不变。
`KO_LLM_PROVIDER` 与检索部署方式 `KO_MODE` 独立：

| 配置 | 行为 |
|---|---|
| `KO_LLM_PROVIDER=auto` | 保留旧行为：offline 使用 Mock，live 使用通用 OpenAI-compatible Provider |
| `KO_LLM_PROVIDER=mock` | 离线 scripted LLM，不发模型请求 |
| `KO_LLM_PROVIDER=deepseek` | 官方 DeepSeek API，显式关闭思考模式 |
| `KO_LLM_PROVIDER=openai` | 现有通用 API Provider |

在被 Git 忽略的 `.env` 中配置，或通过进程环境变量提供：

```dotenv
KO_MODE=offline
KO_LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=在本地填写你的密钥
KO_DEEPSEEK_BASE_URL=https://api.deepseek.com
KO_DEEPSEEK_MODEL=deepseek-flash
```

这会使用**真实 DeepSeek + 实际 LangGraph/Harness/BM25/Qdrant Local**，Embedding/Reranker 仍是本地替身，
不需要额外的 Embedding 密钥、Redis 或 CrossEncoder 下载。完整 live 部署仍需配置这些真实组件。
切回 Mock 只需更改 Provider。Web UI 的“访问密钥”仍是 `KO_API_KEY`，不是 DeepSeek API Key；后者仅供后端认证。

DeepSeek 适配器使用 `extra_body={"thinking":{"type":"disabled"}}` 和 `tool_choice=required`，
不传未列入官方 schema 的 `parallel_tool_calls`；图按既有工具预算逐个执行同一响应中的调用。
SDK 内置重试关闭，429/5xx/网络超时由 Harness 有限重试；每次请求均计数并预留预算。
成功响应按服务端 usage 结算，记录 prompt/completion/total Token、响应模型/ID、耗时和工具调用数量，不记录密钥或请求头。

验证命令：

```powershell
uv run python -m scripts.probe_deepseek
uv run python -m scripts.validate_deepseek --refresh-docs
uv run pytest -m deepseek_live -q
# 一次执行原有回归、真实 API 测试、离线消融和全部报告；会产生真实 API 费用
uv run python -m scripts.verify --deepseek
uv run python -m scripts.check_secrets
```

真实集成测试没有密钥时自动跳过；设 `KO_RUN_DEEPSEEK_TESTS=0` 可明确禁止真实调用。
`scripts.verify` 默认禁止真实 API，`--deepseek` 才开启。HTTP 故障注入单独测试，不把人工制造的 429/5xx 当作线上事件。
真实运行报告为 [deepseek-integration.md](reports/deepseek-integration.md)，原始事件、usage、引用与失败尝试保存在同名 JSON 和
`deepseek-attempt-*.json` 中。测试运行数很小，成功率与分位数只描述这次运行。

验收下载 DeepSeek-V2、DeepSeek-V3、DeepSeek-V4.1-Flash 的官方原始 Markdown，记录 URL、下载时间和 SHA-256，
完整快照保存在 `data/deepseek_validation/documents`，CLI 的索引/检查点/任务账本保存在 `data/deepseek_validation/index`。
场景覆盖三版本参数/上下文比较、多轮追问缺失的同硬件吞吐量，以及一次可控本地检索失败后的恢复。
文档目录只给模型版本和文档 ID，不注入指标答案；所有引用仍须来自实际检索到的原文。

生产默认 Token 预算仍为 20,000、最大输出 2,000。长文档验收使用显式配置：80,000 Token、最大输出 6,000、
模型与工具超时 60 秒；步数/调用次数上限保持既有默认值。缺少 usage 时仍保留估算预留，不允许通过恢复重置预算。
如需在 UI 中执行相同的大文档研究，可将对应 `KO_TOKEN_BUDGET`、`KO_OUTPUT_TOKENS`、`KO_LLM_TIMEOUT`、
`KO_TOOL_TIMEOUT` 设置为该验证配置后重启；这不改变代码默认值。

## 真实模式 / Docker Compose

编辑 `.env`，配置相互独立的 LLM 与 Embedding：

```dotenv
KO_MODE=live
KO_API_KEY=替换为私有随机访问密钥
KO_LLM_BASE_URL=https://你的兼容服务/v1
KO_LLM_API_KEY=你的密钥
KO_LLM_MODEL=支持函数工具调用的模型名称
KO_EMBEDDING_BASE_URL=https://你的向量服务/v1
KO_EMBEDDING_API_KEY=你的向量密钥
KO_EMBEDDING_MODEL=向量模型名称
KO_EMBEDDING_DIMENSIONS=1536
```

维度必须与模型实际输出一致。LLM 适配器使用 Chat Completions，要求支持 `tools`、`tool_choice=required`、
`parallel_tool_calls=false`、`max_tokens`；其他兼容协议需专用适配，不宣称所有兼容服务均已验证。

CrossEncoder 默认 `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`；`KO_RERANKER_MODEL` 可替换为模型名或容器内路径，
`KO_RERANKER_DEVICE=cpu/cuda`，默认批量 8、最大输入长度 512 tokens。长候选可能截断。
首次启动下载权重，离线部署需提前预置。Compose 默认 CPU；GPU 需额外配置设备与运行时。

```powershell
docker compose up --build -d
docker compose logs -f api worker
docker compose ps
```

四个服务为 API、单个 Worker、Qdrant、Redis。API 仅发布 `127.0.0.1:8000`，Qdrant/Redis 不发布宿主端口。
应用数据、Qdrant、Redis AOF、模型缓存使用持久卷。镜像包含 models/trace extras；首次构建和下载可能较慢。
本机没有 Docker，尚未实际构建或启动这些容器；标签锁定不等于逐位可复现镜像。

不用 Docker 时：`uv sync --locked --extra dev --extra models --extra trace`，设置可访问的 Qdrant/Redis 地址，
分别执行 `uv run python -m knowledgeops` 与 `uv run python -m knowledgeops.worker`。
API/Worker 的 `KO_DATA_DIR` 必须为同机共享持久目录，配置一致；不要对离线 Qdrant 目录启动第二个进程。
所有真实模式依赖故障明确报错，不会静默降级成 Mock。

## API 与业务行为

业务接口带 `X-API-Key`；`/docs` 提供交互文档。

| 方法 / 路径 | 用途 |
|---|---|
| POST `/api/v1/documents` | multipart 上传，202 返回 task_id |
| POST `/api/v1/documents/url` | JSON url，单页网页导入 |
| GET `/api/v1/documents` | 文档、来源别名和索引状态 |
| GET `/api/v1/documents/{doc_id}/chunks/{chunk_id}` | 来源文本、页码/章节和偏移 |
| POST `/api/v1/query` | query、mode、rerank、top_k、candidates、doc_ids |
| POST `/api/v1/research` | question、可选 session_id、降低后的 limits |
| GET `/api/v1/tasks/{task_id}` | 状态、结果、错误与预算 |
| GET `/api/v1/tasks/{task_id}/events?after=0` | 增量事件；用 next_after 继续读取 |
| POST `/api/v1/tasks/{task_id}/resume` | 恢复可恢复任务 |
| GET `/health/live`、`/health/ready` | 存活与依赖就绪 |

query 的 mode 为 dense/bm25/hybrid，rerank 独立开关；默认各路 50 候选，RRF k=60，融合前 50 项重排，返回 5 项。
保留 Dense、BM25、RRF、Rerank 得分与排名。BM25 按索引版本刷新；只有完整索引成功的文档可见。

原文件 SHA-256 用于完整性检查，规范化文本哈希定义文档身份。重复内容记录来源别名，不重复索引。
默认 800 字符分块、120 重叠，PDF 不跨页，Markdown 保留标题；偏移对应规范化提取文本，不是 PDF 字节位置。
文本 PDF 页数上限 300、文件上限 20 MB；扫描页需 OCR，加密 PDF 须先解密。网页只导入公开 HTML 单页。

Agent 注册 knowledge_search、compare_evidence、build_report；同会话串行执行，成功历史保留最近四轮。
比较仅接受已检索证据，报告引用 ID 由服务器生成，引用摘录必须与存储原文一致；错误引用最多修正一次。
引用校验不等同于语义蕴含或事实准确性判断。

## Harness、恢复与观测

默认限制：12 个模型/工具节点步骤、8 次 LLM 请求、12 次工具尝试、20,000 Token、180 秒任务运行期限；
每次输出最多 2,000 Token、工具超时 30 秒、暂时性错误最多额外重试 2 次。客户端只能降低限制。

每次 LLM 尝试先预留参考 tokenizer 输入计数、格式余量与最大输出额度；有 usage 时结算，缺少 usage 或进程中断时
保留预留额并标识估算。兼容服务器 tokenizer 可能不同，不保证远端计费的精确上限。SDK 隐式重试关闭，重试单独计费。

同步 LangGraph 检查点、每任务调用缓存、SQLite 预算账本和任务租约协同恢复。Redis Streams 至少一次投递，Worker
定期扫描遗漏通知和过期任务。恢复不会重置预算或延长截止时间。终止错误、预算耗尽或无效引用进入 failed，不能 resume
绕过限制；interrupted 或租约过期且未到截止时间可恢复。远端返回后、本地保存前崩溃仍可能重复调用/计费，不承诺 exactly-once。

CrossEncoder 在独立子进程中串行运行，超时或取消终止进程，禁止迟到结果写回。工具白名单不含任意 Shell、文件路径或代码执行。
网页导入校验每次 DNS 与重定向，拒绝私网/元数据地址并绑定已验证 IP。上传限制在 multipart 解析前生效；UI 将来源文本安全转义。

可选 Langfuse 使用 `KO_LANGFUSE_PUBLIC_KEY`、`KO_LANGFUSE_SECRET_KEY`、`KO_LANGFUSE_BASE_URL`。
只导出任务 ID 和操作元数据，默认不发送问题、提示词、原文或密钥；未配置和导出失败不阻断研究。
本地持久事件为主要追踪记录。readiness 检查 SQLite/Qdrant/Redis/Worker 心跳，不代表付费模型调用已经成功。

## 测试与评测

完整离线验收与报告生成可只运行 `uv run python -m scripts.verify`。该命令顺序执行测试与评测，避免并行负载干扰延迟。

```powershell
uv run pytest -m "not live" -q
uv run pytest -q --junitxml=reports/pytest.xml --cov=knowledgeops --cov-report=json:reports/coverage.json --cov-report=xml:reports/coverage.xml
uv run ruff check src tests scripts
uv run python -m scripts.smoke --mode offline
uv run python -m scripts.evaluate_retrieval --mode offline
uv run python -m scripts.evaluate_agent --mode offline
uv run python -m scripts.build_report
```

offline 脚本启动独立临时 Uvicorn HTTP 服务和数据目录，结束后清理，不访问用户知识库。
12 份自有中英文档、30 条固定标注查询位于 examples，另含中英文 PDF 示例；`scripts.prepare_examples` 可重建示例，生成 PDF 需要 dev extra。
网页测试使用可控响应，未把真实外网页面抓取计为验证通过。

消融比较 Dense / Hybrid / Hybrid+Rerank，各查询预热后测 3 次。返回 50 分块后按文档去重，计算 Recall@1/5/10、
MRR@10、P50/P95 和错误率。延迟为 HTTP 往返，包含问题 Embedding、检索、重排、序列化，排除导入/启动/预热。
失败算未命中，耗时另存原始记录；分位数只统计成功请求。小语料 Recall@10 容易饱和，不据此宣称真实重排提升。

Agent 评测检查任务完成和引用原文一致性，不测语义正确率。pytest 覆盖空检索、超时、工具失败、重复调用、非法工具、
错误引用、预算耗尽、租约冲突、依赖故障，以及**实际终止并重启解释器**的恢复测试。

真实服务和凭据就绪后：

```powershell
uv run python -m scripts.smoke --mode live
$env:KO_RUN_LIVE_TESTS='1'
uv run pytest -m live -q
uv run python -m scripts.evaluate_retrieval --mode live
uv run python -m scripts.evaluate_agent --mode live
```

live 脚本连接默认 8000，可传 --base-url；pytest 可配置 KO_TEST_BASE_URL，读取 .env 中 KO_API_KEY。
live 评测会导入示例数据，建议使用专用评测实例；检索消融限定示例文档，Agent 使用共享知识库。
未显式开启 KO_RUN_LIVE_TESTS 时真实集成测试跳过并单独统计；开启后服务故障必须失败。
报告保留时间、提交、工作区状态、源码哈希、模型/索引指纹与原始 JSONL/CSV；测试报告从实际 JUnit/coverage 生成。

## 备份、重建、限制与后续优化

停止 API 与 Worker 后，完整备份应用目录和 Qdrant 卷；SQLite 数据库与 WAL/SHM 应同步保留。
不要在写入过程中分别复制数据库和 WAL。Compose 可先 `docker compose stop api worker` 再做卷快照。

变更 Embedding 模型、维度、分块参数触发指纹不匹配。`scripts.rebuild` 从旧原文件重建到新空目录，保留旧数据，
不自动覆盖或删除。live 可复用同一个 Qdrant Server，新向量空间使用独立 collection；仍需新应用数据目录与显式导入。
重建命令说明见该脚本 --help。

首版不含 OCR、多用户隔离、全站爬取、JS 页面、多机/多 Worker、语义引用判定。约 5 万分块为设计目标，未做容量测试。
SQLite 共享卷要求同机本地磁盘，不能用 NFS；BM25 在内存重建。仅支持一个 API 进程和一个 Worker。

当前未验证：API/Worker 镜像构建与完整四容器部署、其他 LLM/外部 Embedding API、Langfuse 投递、
Python 应用在 3.11/Linux 的运行与容量目标。Qdrant/Redis 的 WSL2 Linux 容器、真实 BGE CPU/CUDA 推理已经实测。
应用实测为 Windows/Python 3.12。CI 配置覆盖 Python 3.11/3.12，配置存在不表示已经运行。

建议先完成 live 验证和领域标注评测，再调分块/候选数/重排；增加无答案与冲突样本、人工语义评审、生产监控和备份演练。
需要扩展时迁移共享数据库与全文索引、加入知识库权限，再考虑 OCR 与并行研究。

设计理由见 [docs/decisions.md](docs/decisions.md)，真实异常和修复提交见 [docs/debugging.md](docs/debugging.md)。

## 真实 Embedding / CrossEncoder / Qdrant Server（独立实验入口）

保留默认离线链路，增量开关为 `KO_EMBEDDING_PROVIDER=local|api|mock|auto`、
`KO_RERANKER_PROVIDER=cross_encoder|mock|auto`、`KO_QDRANT_BACKEND=server|local|auto`。
`auto` 沿用旧行为，完整 live 模式拒绝替身。BGE-M3 的 dense 向量维度是 1024；本轮只使用 dense
能力，BM25 仍为独立词法检索，不使用 BGE learned sparse/ColBERT。余弦、BM25、RRF 和重排原始 logits
分别保留；不同量纲不直接相加。配置/归一化/模型版本改变时须新建数据目录并重新导入。

```powershell
# 安装真实模型依赖，锁文件已包含这些可选依赖
uv sync --locked --extra dev --extra models
uv run --extra models python -m scripts.fetch_retrieval_models
# 常规 Docker 主机：只启动本轮真实依赖；不会替换原有 API 服务
# 命名卷位于 Linux 文件系统，避免 Windows 绑定挂载的存储问题
 docker compose -f compose.retrieval.yaml up -d
# 本机已实际使用 WSL2 Ubuntu：
wsl -d Ubuntu -u root -- docker compose --project-directory (wsl wslpath -a (Get-Location).Path) -f compose.retrieval.yaml up -d
uv run --extra models python -m scripts.verify_retrieval_infra --wsl
uv run --extra models python -m scripts.evaluate_real_retrieval
uv run --extra models python -m scripts.validate_real_rag
```

下载脚本从官方 Hugging Face 读取 immutable revision，保存到忽略的 `data/models/`，并生成模型 manifest
和权重 SHA-256。评测脚本只读取这个 manifest，并强制 `local_files_only`；没有权重或 Qdrant 时直接报错，
不会降级到 Mock。私有网络代理应通过进程环境配置；没有把本机网络绕行方案写进产品或 Docker 镜像。
本机 WSL 没有 systemd 启动 Docker，需在另一个终端保持 `wsl -d Ubuntu -u root -- dockerd` 运行。

默认实际实验为 CPU FP32、8 线程、batch=8、最大序列 512（可配置至模型支持范围），不把首次加载或预热
算入查询 P50/P95。硬件有 GPU 并不等于当前 torch 已具备可用 CUDA 构建；切换 GPU 需单独安装兼容构建并重测。
脚本固定 50 候选、RRF k=60，120 题中 100 道可回答题计入分块级 Recall@5 / MRR@10 / nDCG@10，
20 道不可回答题单独记录非空检索率。详细标注边界见 `evals/public_technical/README.md`。
原来的 `scripts.evaluate_retrieval --mode offline` 仍保留；其替身成绩不与真实模型混表。

真实 Agent 入口需要现有 `.env` 中的 `DEEPSEEK_API_KEY`，不需要 Embedding API Key。使用独立
`data/real_retrieval`，复用评测时导入的 15 份公开文档；不会自动读取当前目录的个人资料。
该入口使用真实 Redis 通知与实际 TaskRunner 执行，记录每次 LLM 的上下文规模、usage、工具耗时、引用与重复调用。
模型加载耗时单列。通用服务部署可在 `.env` 中填写对应 selectors、模型/revision/path、1024 维及新数据目录。
完整四服务生产部署仍用 `compose.yaml`；本轮宿主机模型实验通过 `compose.retrieval.yaml` 提供真实 Qdrant/Redis。

```powershell
# 原有离线回归与真实测试严格分开
$env:KO_RUN_DEEPSEEK_TESTS='0'
uv run --extra models pytest -m 'not live'
# 权重齐备、Qdrant 已启动才显式执行；缺权重会 skip，配置后运行错误会 FAIL
$env:KO_RUN_RETRIEVAL_TESTS='1'
uv run --extra models pytest -m retrieval_live
# 全回归包含已有真实 DeepSeek 测试，可能产生 API 费用
$env:KO_RUN_DEEPSEEK_TESTS='1'
uv run --extra models pytest --junitxml=reports/retrieval-final-junit.xml --cov=knowledgeops --cov-report=json:reports/retrieval-coverage.json
```

新增 `DELETE /api/v1/documents/{doc_id}` 删除分块与向量；失败时文档先隐藏，可重试删除。
原始内容寻址文件保留，便于审计与共享别名安全。通过删除文档也会使其旧引用变为不可用，客户端会明确收到 404。

### 可选 CUDA 复现（Windows / Python 3.12，独立环境）

CPU 真实集成已经验证；CUDA 不修改默认 `.venv` 或系统驱动。`requirements-cuda-windows.lock` 固定本轮
依赖和官方 PyTorch 2.7.1+cu128 wheel SHA-256，适用于 Windows Python 3.12。更换平台要另行解析环境。

```powershell
uv venv data/venv-cuda --python 3.12
uv pip install --python data/venv-cuda/Scripts/python.exe --no-deps -r requirements-cuda-windows.lock
uv pip install --python data/venv-cuda/Scripts/python.exe --no-deps -e .
$env:KO_EXPERIMENT_DEVICE='cuda'
# 使用独立 data/real_retrieval_cuda 与包含 float16 指纹的 collection，重新导入全部语料
# 不用普通 uv run 覆盖这个独立环境的 CUDA torch
& data/venv-cuda/Scripts/python.exe -m scripts.evaluate_real_retrieval
& data/venv-cuda/Scripts/python.exe -m scripts.validate_real_rag
$env:KO_RUN_RETRIEVAL_TESTS='1'
$env:KO_RUN_RAG_TESTS='1'
$env:KO_RUN_DEEPSEEK_TESTS='1'
& data/venv-cuda/Scripts/python.exe -m pytest --junitxml=reports/pytest.xml --cov=knowledgeops --cov-report=json:reports/coverage.json
```

四组正式成绩以 `reports/real-retrieval.json` 的 device/precision 为准；CPU 初次索引和少量耗时探测保存在
独立文件，不与 CUDA 查询分布合并。服务 `.env` 对应配置为 `KO_EMBEDDING_DEVICE=cuda`、
`KO_RERANKER_DEVICE=cuda`、`KO_EMBEDDING_PRECISION=float16`、`KO_RERANKER_PRECISION=float16`。
浮点精度也参与索引兼容性检查。模型不可用或显存不足时明确失败，不自动换小模型或 CPU。

Agent 每任务另有 `KO_MAX_SEARCH_CALLS=4` 的服务端检索上限。达到上限后只允许比较已有证据并提交报告；
缺乏依据时必须拒答。重复命中的分块保留在状态与缓存，但后续工具消息仅回传已有引用 ID，减少重复上下文。
这没有增加 Token 预算，也不改变引用原文校验。首次真实无答案任务因过度检索耗尽下一次预算预留的失败已存档。

实验结果与 Bad Case：`reports/real-retrieval.md`、`reports/real-bad-cases.md`、`reports/real-rag.md`。
可用 `python -m scripts.audit_real_bad_cases` 从持久化分块与记录的排名重新导出原文审计。
主验收报告由 `python -m scripts.build_report` 从实际 JUnit、覆盖率和各实验文件自动生成。

### 五路对照与人工相关性复核（2026-10-18）

新增 `Dense+Rerank`，与另外四路在同一次运行中测量。冻结的四路旧报告不覆盖。
本轮真实数据、同题胜平负和人工抽查见 [retrieval-followup.md](reports/retrieval-followup.md)。

```powershell
$env:KO_EXPERIMENT_DEVICE='cuda'
& data/venv-cuda/Scripts/python.exe -m scripts.evaluate_real_retrieval --repetitions 3 --prefix real-retrieval-fiveway
uv run --extra models python -m scripts.review_relevance prepare --prefix real-retrieval-fiveway
# 盲审页面无需外部服务；仅绑定本机。填写本人实际判断后导出 JSON。
uv run python -m http.server 8766 --bind 127.0.0.1 --directory reports
# 浏览器打开 http://127.0.0.1:8766/relevance-review.html
uv run python -m scripts.review_relevance accept '导出的文件.json'
uv run python -m scripts.summarize_retrieval_followup
```

原始标签、人工判断、未判断项目分开保留。当前用户已实际抽查两条候选（Q032 的 TaskGroup 分块=2，
Q052 的子进程缓冲区分块=0）；
不是全量人工复核。仅完整判断的问题池才生成独立 pooled 指标，不更改冻结标注下的成绩。
重复运行 `prepare` 前先备份复核文件；问题池哈希改变时旧判断不会被迁移或冒用。

### 四容器真实 API / Worker 验收

沿用 `compose.yaml`，叠加 `compose.acceptance.yaml`：CPU FP32 BGE-M3、真实 CrossEncoder、DeepSeek Flash、
独立 Worker 与 API、Qdrant、Redis；监听本机 18000，不占用原离线 UI 的 8000。
Linux 锁文件使用官方 CPU PyTorch wheel；Windows CUDA 实验环境不变。
需要 Docker Compose 2.24.4+（使用 `!override`）及约 16 GB 可用系统内存，首次下载模型约 4.6 GB。

```powershell
# .env 或进程环境已有 DEEPSEEK_API_KEY；本命令生成忽略的私有应用访问凭证，不打印值。
uv run python -m scripts.prepare_acceptance
# 本机 WSL2：生成的 compose.env 使用 /mnt/d/... 路径。
wsl -d Ubuntu -u root -- docker compose --project-directory (wsl wslpath -a (Get-Location).Path) --env-file data/acceptance/compose.env -p knowledgeops-acceptance -f compose.yaml -f compose.acceptance.yaml up --build -d
uv run python -m scripts.verify_four_container --wsl
```

普通 Linux Docker 主机可直接执行同一 `docker compose ...` 命令，省略 `wsl ...` 前缀；
`prepare_acceptance` 会使用 Linux 绝对路径。Windows Docker Desktop 用户把 `data/acceptance/compose.env`
中的两个路径改为 Docker Desktop 可访问的 Windows 路径，并省略 `--wsl`。
模型以只读目录挂载；服务数据用独立命名卷。`service.env` 只含私有凭证，不能提交或发给他人。
网络受限时仅在本机构建命令设置代理，不把代理、密钥写进镜像。

`verify_four_container` 会停止并重启验收项目的 Worker，并在实际研究中 SIGKILL 一次 Worker，验证
任务排队、检查点恢复、预算连续性及引用原文。请在独立验收部署运行，不要指向生产项目。
`tests/integration/test_live.py` 的既有两个 HTTP 测试保持不变；设置 `KO_RUN_LIVE_TESTS=1`、
`KO_TEST_BASE_URL=http://127.0.0.1:18000` 和私有 `KO_API_KEY` 后执行。
额外破坏性验收测试由 `KO_RUN_FOUR_CONTAINER_TESTS=1` 显式开启；WSL 设置 `KO_DOCKER_IN_WSL=1`。
所有开关默认关闭，不把依赖缺失的跳过项算通过。

完整验收可使用私有凭证加载入口（会实际调用付费 API、重启验收 Worker）：

```powershell
& data/venv-cuda/Scripts/python.exe -m scripts.run_acceptance_tests --wsl --device cuda
```

该入口为历史 DeepSeek-only 检索替身测试创建独立数据目录，避免复用其他 Qdrant Client 版本的本地存储格式；
真实 BGE / Qdrant Server 测试与其报告边界保持分离。默认 DeepSeek 温度为 0，可用
`KO_DEEPSEEK_TEMPERATURE` 配置；内部比较启用 JSON-object 输出，但仍严格校验服务端引用 ID 和原文。

本轮最后一次完整验收：107 通过、0 失败、0 跳过，覆盖率 88.28%；包括真实模型、两个既有 HTTP 测试及
四容器中断恢复。前两次完整运行的 102/2 和 105/1 失败记录保留在 reports/followup-first-* 与
followup-second-*，修复提交及边界见 docs/debugging.md；一次通过不保证外部模型今后的格式稳定性。

## GitHub 发布与隐私

本仓库为脱敏快照，保留源码、测试及真实实验报告；本机路径已替换为通用占位符。
历史测试数字与评测标签保持原样，原始本地 Git 历史未上传。详情见 [发布说明](docs/publication.md)。
