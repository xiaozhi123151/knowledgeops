# DeepSeek real API integration report

Generated from run: 2026-10-18T15:44:08.805091+00:00; source commit `95dc8e976db89bc06dfb35bfa84c7a8082e2cc4f`.
Source SHA-256: `49692e7c2fdb24a6b60262032d1b21cb8fc46f2d2b5e0120dd75e6331aa3c742`.

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

## Actual answer: version_comparison

官方文档显示：DeepSeek-V2 为 236B 总参数、每 token 激活 21B、上下文 128k；DeepSeek-V3 为 671B 总参数、每 token 激活 37B、上下文 128K；DeepSeek-V4.1-Flash 为 552B 骨干参数，预填充每 token 激活 8B、解码 16B，支持最长 100 万 token 上下文。三份文档均未给出 A100 80GB、batch=1 下的绝对吞吐量，故该指标无法确认。

- DeepSeek-V2：官方 README 模型下载表列出 DeepSeek-V2 为 236B 总参数、21B 激活参数、128k 上下文长度（同表另有 V2-Lite 16B/2.4B/32k，不属本项）。 [E-871d7088-b673-56b3-b55a-11fa06391bf9]
- DeepSeek-V3：官方 README 模型下载表列出 DeepSeek-V3 为 671B 总参数、37B 激活参数、128K 上下文长度。 [E-7f8f8bc4-c83b-538c-96da-ac9868313eb4]
- DeepSeek-V4.1-Flash：官方文档称其为 552B 骨干参数的多模态 MoE 模型，支持最长一百万 token 上下文，预填充阶段每 token 激活 8B、解码阶段激活 16B（基准表中亦记为 552B 骨干、8B/16B 激活）。 [E-a2c871b9-bdcf-5e59-afa1-8660da4c44a7, E-7f06f4c9-c846-5169-a725-054c600921c8]

Limitations:

- 三份官方文档均未提供 A100 80GB、batch=1 条件下的实测吞吐量（tokens/s），因此该绝对吞吐量无法确认；文档中仅有相对提升率（如 V2 相对 DeepSeek 67B 的最大生成吞吐提升倍数），不能替代同条件绝对吞吐量。
- DeepSeek-V4.1-Flash 文档使用“骨干参数 552B”表述，且激活参数按预填充 8B / 解码 16B 分列，与 V2/V3 的单一“每 token 激活参数”口径不完全一致，跨版本直接比较需谨慎。
- V2 与 V3 的上下文长度分别写作 128k 与 128K，属同一量级的不同书写形式；V4.1-Flash 的“一百万 token”为文档表述，未给出与 V2/V3 相同的表格化口径。

Verified quotes:

- `E-7f06f4c9-c846-5169-a725-054c600921c8` — [source](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash/raw/main/README.md): | # Activated Params | — | 13B | 49B | 8B / 16B |
- `E-7f8f8bc4-c83b-538c-96da-ac9868313eb4` — [source](https://raw.githubusercontent.com/deepseek-ai/DeepSeek-V3/main/README.md): | DeepSeek-V3 | 671B | 37B | 128K |
- `E-871d7088-b673-56b3-b55a-11fa06391bf9` — [source](https://raw.githubusercontent.com/deepseek-ai/DeepSeek-V2/main/README.md): | DeepSeek-V2 | 236B | 21B | 128k |
- `E-a2c871b9-bdcf-5e59-afa1-8660da4c44a7` — [source](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash/raw/main/README.md): 552B backbone parameters and support for contexts of up to one million tokens

## Actual answer: followup_missing_evidence

无法确认。三份官方文档均未给出 A100 80GB、batch=1 下的绝对 tokens/s，故无法据此排出吞吐量名次，也不能由参数量推算性能。可确认的已知指标为：V2 为 236B 总参数、21B 激活、128k 上下文；V3 为 671B 总参数、37B 激活、128K 上下文；V4.1-Flash 为 552B 骨干参数、预填充 8B/解码 16B 激活、最长一百万 token 上下文。

- DeepSeek-V2：官方 README 模型下载表列出 236B 总参数、21B 激活参数、128k 上下文长度（同表 V2-Lite 16B/2.4B/32k 不属本项）。 [E-871d7088-b673-56b3-b55a-11fa06391bf9]
- DeepSeek-V3：官方 README 模型下载表列出 671B 总参数、37B 激活参数、128K 上下文长度。 [E-7f8f8bc4-c83b-538c-96da-ac9868313eb4]
- DeepSeek-V4.1-Flash：官方文档称其为 552B 骨干参数的多模态 MoE 模型，支持最长一百万 token 上下文，预填充每 token 激活 8B、解码激活 16B（基准表亦记 552B 骨干、8B/16B 激活）。 [E-a2c871b9-bdcf-5e59-afa1-8660da4c44a7, E-7f06f4c9-c846-5169-a725-054c600921c8]

Limitations:

- 三份官方文档均未提供 A100 80GB、batch=1 条件下的绝对吞吐量（tokens/s），因此该条件下的 tokens/s 排名无法确认；文档中仅有相对提升率（如 V2 相对 DeepSeek 67B 的最大生成吞吐提升倍数），不能替代同条件绝对吞吐量，也不能由参数量推算性能。
- DeepSeek-V4.1-Flash 使用“骨干参数 552B”且激活参数按预填充 8B / 解码 16B 分列，与 V2/V3 单一“每 token 激活参数”口径不一致，跨版本直接比较需谨慎。
- V2 与 V3 上下文写作 128k 与 128K，属同一量级的不同书写形式；V4.1-Flash 的“一百万 token”为叙述性表述，未采用与 V2/V3 相同的表格口径。

Verified quotes:

- `E-7f06f4c9-c846-5169-a725-054c600921c8` — [source](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash/raw/main/README.md): | # Activated Params | — | 13B | 49B | 8B / 16B |
- `E-7f8f8bc4-c83b-538c-96da-ac9868313eb4` — [source](https://raw.githubusercontent.com/deepseek-ai/DeepSeek-V3/main/README.md): | DeepSeek-V3 | 671B | 37B | 128K |
- `E-871d7088-b673-56b3-b55a-11fa06391bf9` — [source](https://raw.githubusercontent.com/deepseek-ai/DeepSeek-V2/main/README.md): | DeepSeek-V2 | 236B | 21B | 128k |
- `E-a2c871b9-bdcf-5e59-afa1-8660da4c44a7` — [source](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash/raw/main/README.md): 552B backbone parameters and support for contexts of up to one million tokens

## Actual answer: tool_failure_recovery

两份官方 README 引言均给出明确数值：DeepSeek-V2 为 236B 总参数、每 token 激活 21B；DeepSeek-V3 为 671B 总参数、每 token 激活 37B。V3 总参数约为 V2 的 2.84 倍，激活参数约为 1.76 倍。两者均为 MoE 架构，证据间无冲突。但检索证据未提供同一硬件下的绝对 tokens/s，故吞吐量对比无法确认。

- DeepSeek-V2 为 MoE 模型，总参数 236B，每个 token 激活 21B。 [E-e3df752b-bc2c-5c51-bbce-93e9ab0fd7fc]
- DeepSeek-V3 为 MoE 模型，总参数 671B，每个 token 激活 37B。 [E-b64fd0a6-f0b7-5313-842d-734527a3832d]
- 对比：V3 总参数 671B 高于 V2 的 236B，每 token 激活参数 37B 高于 V2 的 21B；两条证据在架构与指标口径上一致，无冲突。 [E-e3df752b-bc2c-5c51-bbce-93e9ab0fd7fc, E-b64fd0a6-f0b7-5313-842d-734527a3832d]

Limitations:

- 检索证据未提供同一硬件配置下的绝对 tokens/s 吞吐量数据，因此两版本的吞吐量对比无法确认。
- 仅使用各版本 README 引言段落作为证据，未纳入下载表格等其他章节的重复数值。
- 参数量倍数（约 2.84 倍与 1.76 倍）为基于引用数值的算术推算，非原文直接陈述。

Verified quotes:

- `E-b64fd0a6-f0b7-5313-842d-734527a3832d` — [source](https://raw.githubusercontent.com/deepseek-ai/DeepSeek-V3/main/README.md): 671B total parameters with 37B activated for each token
- `E-e3df752b-bc2c-5c51-bbce-93e9ab0fd7fc` — [source](https://raw.githubusercontent.com/deepseek-ai/DeepSeek-V2/main/README.md): It comprises 236B total parameters, of which 21B are activated for each token.

## Exploratory failures retained

These are real earlier attempts, not synthetic model replies. They are excluded from the final acceptance-run success rate; their usage is retained here rather than hidden.

| Artifact | Requests | Reported tokens | Outcome |
|---|---:|---:|---|
| deepseek-attempt-01-budget.json | 2 | 8165 | BUDGET_EXCEEDED: tokens |
| deepseek-attempt-02-tool-batch.json | 1 | 1538 | LLM_PROTOCOL_ERROR: expected one to three function calls |
| deepseek-attempt-03-quotes.json | 5 | 46289 | OUTPUT_VALIDATION_FAILED_AFTER_REPAIR |
| deepseek-attempt-04-truncation.json | 6 | 60121 | OUTPUT_VALIDATION_FAILED_AFTER_REPAIR |
| deepseek-attempt-05-partial-uncertainty.json | 16 | 132458 | None; BUDGET_EXCEEDED: tokens; None |

## Synthetic transport/Harness regression

19 selected tests, 0 failures/errors in deepseek-fault-injection.xml. These validate code behavior under injected faults; they are not real server fault observations.
