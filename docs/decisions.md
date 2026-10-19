# Design decisions

## D01 — Explicit offline and live modes

The development machine has no Docker and no configured API credentials. A deterministic offline mode
allows the actual extraction, vector storage, BM25, graph, API and recovery paths to be exercised without
pretending that lexical substitutes measure semantic model quality. Live mode never falls back on errors.
The offline Qdrant client owns its local directory in one process; production API and Worker use a Qdrant
server because sharing embedded Qdrant storage between processes is unsupported.

## D02 — SQLite owns metadata; vectors are rebuildable

This is a single-host, private MVP (approximately 50,000 chunks), not a multi-tenant distributed service.
SQLite WAL avoids adding another database service and supports durable task and budget transactions.
Only ready documents are candidates for either retrieval branch. A failure after Qdrant upsert but before
SQLite publish leaves invisible points; stable IDs make a retry safe. A cross-database transaction would
be much more complex. Scale-out requires a shared transactional database and a different BM25 backend.

## D03 — Preserve evidence rather than just a URL

Normalized text, raw content hashes, page/section, and offsets are retained. Content identity does not depend
on the filename; repeated uploads record aliases without duplicating vectors. Offsets refer to normalized
extracted text, not byte positions in PDF files. Extraction and embedding settings are fingerprinted;
changing them requires an explicit new index rather than silently mixing vector spaces.

## D04 — Fetch single public pages using pinned connections

Checking a hostname and then handing it to a normal client leaves a DNS rebinding window. The fetcher
resolves and validates every address, then connects to the selected IP, retaining the hostname for TLS/SNI.
Every redirect is validated again. Proxies are not inherited, ports are restricted to 80/443, and only HTML
is accepted. Browser rendering, crawling and authenticated page import are outside this MVP.

## D05 — CPU inference isolation

A coroutine timeout does not stop a model thread. Live CrossEncoder runs in a single persistent child
process. Timeout/cancellation terminates and joins that process; a late computation cannot publish scores.
Model loading is a distinct startup operation; benchmarks warm up before timed queries. Model and device
are configurable, remote model code is disabled, and the models extra is separate from offline dependencies.

## D06 — Durable reservations and recoverable graphs

Every model attempt reserves input plus maximum output before contacting a provider. Successful usage
settles that reservation; missing usage or process interruption retains it. Retries are charged separately,
SDK implicit retries are disabled, and restart never resets counters or deadlines. Input estimation uses a
bundled SHA-verified cl100k reference tokenizer plus framing margin; compatible-server tokenization can
differ, so this is not an exact remote billing limit. Tool and model results are cached per task to reduce
replay. A crash after a remote response but before local persistence can still duplicate cost.

Graph checkpoints use a JSON-only serializer because this graph stores JSON primitives. No pickle,
dynamic constructor revival, shell or model-directed filesystem tools are needed. Session history and
successful task status commit atomically; task leases fence stale owners from budget/result writes.

## D07 — Single worker, durable notifications and honest health

Redis Streams is an at-least-once notification channel, not the only record that a task exists. The worker
periodically reconciles queued/expired SQLite tasks, so a failed enqueue or Redis data loss does not strand
work. Lease ownership fences stale results, and task creation order serializes a session. A worker heartbeat
is stored separately from API liveness; readiness checks it in live mode rather than assuming the external
worker is running. Deploy exactly one Worker and one API process on a shared local volume; NFS and
horizontal replicas are not supported. The 50,000-chunk figure is a design target, not a measured capacity.

## D08 — Minimal same-origin UI and metadata-only telemetry

Plain HTML/JS avoids a separate frontend build and supports the required upload, query, multi-turn task
and citation flows. All source/model strings use textContent. API credentials stay in sessionStorage,
not URLs or source files. Body limits run before multipart spooling. Langfuse emits task IDs and operational
metadata only; local persisted events are authoritative and telemetry export failures cannot fail a task.

## D09 — Evaluate with fixed owned relevance judgments

The included twelve documents and thirty questions are intentionally small bilingual fixtures. Labels
are fixed by source identity, never generated from the search ranking. Retrieval evaluates unique document
rankings after fetching fifty chunks; failures count as misses. Each variant warms up, then runs each
query three times. HTTP latency includes embedding, retrieval, reranking and serialization, but not import
or startup. Raw rows preserve errors and timings. A saturated Recall@10 on twelve documents is weak
evidence, and lexical offline substitutes cannot establish a real semantic model or reranker improvement.

Agent evaluation measures completion and exact-source citation validity, not semantic entailment. A
configured live test must fail on service errors; absent configuration produces an explicit skip. Metadata
records source hashes as well as Git revision because report generation itself can dirty the repository.

## D10 — Explicit, non-destructive index rebuild

An index fingerprint mismatch cannot be solved safely by reusing old vectors. The rebuild command reads
retained raw content into a separate empty directory, verifies hashes, and writes a manifest. Existing
data, sessions and tasks are retained in the original directory; sessions/tasks do not migrate into a new
index. At this stage live rebuild required a separate empty Qdrant instance with a fixed collection.
**Superseded by D16:** server collections now include the embedding fingerprint, so new model spaces can
share a server while still requiring an empty application directory and explicit reimport.

## D11 — Preserve signed similarity scores

Dense retrieval returns top-ranked candidates without an implicit zero threshold. Cosine similarities
can be negative; the sign is not a calibrated relevance decision. Source existence and exact quotes are
validated separately, while answer sufficiency remains a model/human judgment. Future domain-specific
thresholds require calibration and explicit configuration, not assumptions from the offline hash model.

## D12 — Independent DeepSeek LLM selection, unchanged retrieval architecture

The machine still lacks full live retrieval infrastructure. Requiring an unrelated Embedding key, Redis
and downloaded CrossEncoder weights just to validate tool-calling would couple independent concerns.
An additive KO_LLM_PROVIDER switch reuses the same complete() interface and keeps auto's existing behavior.
DeepSeek can run with local retrieval, and the UI/report explicitly labels that mixed boundary. Full live
mode still requires its real retrieval services. Credentials are backend environment secrets; endpoint
validation restricts the DeepSeek adapter to the official HTTPS base, and the key is never model context.

## D13 — Explicit non-thinking protocol and measured usage

Official DeepSeek documentation says thinking is on by default and required/named tool choices need it
disabled. The adapter always sends thinking.type=disabled, including the comparison call. It omits the
undocumented parallel_tool_calls parameter; multiple returned tools execute serially under the existing
Harness. SDK retries remain zero. Detailed safe response metadata supplements the existing integer usage
return, so no Provider interface or budget-storage rewrite is needed. API error bodies and headers are
never persisted; failed requests retain conservative reservations when exact usage is unavailable.

References: https://api-docs.deepseek.com/guides/thinking_mode/ and
https://api-docs.deepseek.com/api/create-chat-completion/ (checked during this integration).

## D14 — Real version-document acceptance, separate from injected faults

Three first-party Markdown snapshots supply the evidence. URLs, download times and hashes make the
input inspectable; metrics are not inserted into prompts. A real-model turn must retrieve, compare and
publish exact-source citations; a follow-up must acknowledge missing same-hardware throughput evidence.
A third turn injects one local search failure but uses real model replies throughout. HTTP 429/5xx/timeouts
are deterministic transport tests, clearly separated from real service observations. Missing credentials
skip real tests; offline verification explicitly disables them even when .env contains a key.

Long documents require a declared 80,000-token/6,000-output evaluation profile. Defaults remain 20,000/2,000.
The earlier genuine budget exhaustion is retained; no counters, limits or source checks are bypassed.

## D15 — Clarify tool schemas instead of weakening citation validation

A real model interpreted quotes dictionary keys as human-readable metric labels, unlike the scripted
provider. Field descriptions now require the same E-... IDs as findings; repair feedback enumerates
missing/extraneous IDs. Invalid/truncated JSON feedback asks for shorter complete output. Exact-substring
validation and the single-repair cap remain intact. Concise case prompts reduce accidental long JSON
truncation; a larger explicit output allowance is used only in the evaluation profile.

## D16 — Independent real retrieval providers, explicit index compatibility

Keep auto's existing mode-dependent defaults and the established Agent/Harness graph. Add local
SentenceTransformer, CrossEncoder and Qdrant backend selectors so real retrieval can be tested independently
of queue/LLM deployment. Full live mode still rejects mock retrieval and requires Qdrant Server. Local
inference runs in bounded persistent child processes; timeout/cancellation terminates and joins the child,
so a coroutine timeout cannot silently publish late model output. CPU FP32 is the reproducible initial
profile: installed locked torch is CPU-only; GPU hardware availability alone does not prove compatible
CUDA kernels. BGE-M3 is used for dense vectors only, not its learned sparse/ColBERT modes.

Fingerprint includes model identity, revision, normalization, sequence limit, pooling specification,
dimension and chunk/tokenizer settings. Server collection names include that fingerprint, preventing
separate SQLite ledgers from mixing equal-dimensional but incompatible vector spaces. SQLite also records
the vector target, rejecting an accidental switch from a populated local index to an empty remote server.
Model/normalization/target changes require a new data directory and explicit reimport; original raw data
and sessions remain untouched. Repository revision pins are mandatory in experiment manifests; manually
replacing local weights under the same revision is outside the declared reproducibility contract.

## D17 — Keep score scales separate and make deletion fail closed

Dense cosine, BM25 raw scores, rank-based RRF and uncalibrated CrossEncoder logits are different quantities.
RRF combines only ranks (k=60); reranker logits order the candidate set and are never summed with lexical
or cosine scores. Returning each field separately permits auditing negative scores and rerank regressions.
CrossEncoder uses an explicit identity activation to avoid presenting sigmoid outputs as calibrated probabilities.
Deletion first hides the document in SQLite and bumps BM25 visibility, then waits for Qdrant deletion,
then removes metadata. A dependency failure leaves a hidden, retryable deleting record. Ingestion and deletion
share a service lock. Content-addressed raw files are retained, avoiding accidental removal of shared aliases.

## D18 — Freeze inspectable positive evidence before real measurements

The 120-question benchmark uses release-pinned CPython and first-party DeepSeek snapshots, exact source
anchors, byte hashes and a frozen question hash. Questions are assistant-authored, not independently human
annotated; keyword/semantic pairs share 40 facts. We choose chunk-level graded qrels to avoid a 15-document
benchmark making top-10 document retrieval look trivially perfect. All overlapping chunks containing an
anchor are positives; other passages are unjudged, so valid alternative evidence can be undercounted.
These limitations are exposed rather than optimized away after observing results.

Unanswerable items are excluded from relevance averages and get a separate nonempty-retrieval rate.
No arbitrary similarity threshold is introduced to manufacture abstention. Actual Agent insufficiency
checks are separate. Four variants use the same candidate cap, corpus and fixed shuffled trial order;
three measured repetitions follow explicit model-load, corpus-import and inference-warmup timing.
Real model results live in separate files/tables from earlier offline fixtures. Network/API errors count
as quality misses and have separate failure rates; they are not silently dropped from the denominator.

## D19 — Measure hardware profiles separately; FP16 has its own vector space

The actual CPU probe (reports/cpu-query-probe.json) measured roughly 22 seconds for a 50-candidate
Hybrid+Rerank query, after real weights loaded. A three-repeat 120-question four-variant run would contain
360 such calls, so testing a compatible GPU build is justified by measured cost. Preserve the default
CPU environment and uv.lock; CUDA is installed in an isolated ignored environment with a separate pinned
Windows requirements file and an official wheel SHA-256. No driver or OS upgrade is attempted.

Float16 inference is opt-in; embedding precision participates in the fingerprint, and the CUDA experiment
uses a new data directory and collection. Exported vectors are re-normalized in float32 before validation
and Qdrant writes. CPU and CUDA latency/results must never be averaged together. All four variants within
an experiment use the same device/precision/corpus settings. GPU availability is established by executing
kernels and real model inference, not merely detecting an NVIDIA device.

References checked: BGE dense usage https://huggingface.co/BAAI/bge-m3 ; raw reranker semantics
https://huggingface.co/BAAI/bge-reranker-v2-m3 ; PyTorch Blackwell/CUDA 12.8 support
https://pytorch.org/blog/pytorch-2-7/ ; Qdrant named-volume guidance
https://qdrant.tech/documentation/quickstart/ .

## D20 — Bound search loops and transmit each evidence body once

The first full real-stack run had 87 passes / 1 failure / 2 skips. Three Agent cases passed, while the
unanswerable private-QPS case made five nearby searches with top_k=10. It accumulated 50 evidence
occurrences but only 26 unique chunks; one model request carried 65,612 content characters. Actual usage
was 68,037 tokens when the next conservative reservation correctly exceeded the unchanged 100,000-token
profile. This is an observed Agent convergence problem; the Harness prevented an unbounded request.

Raising the budget would hide the failure. Instead add a configurable server search-call cap (default 4),
checked in tool execution as well as advertised model tools. At the cap the graph exposes comparison,
then report submission. Exact evidence remains in graph/checkpoint/cache state; later search messages
reference already-sent IDs instead of retransmitting their bodies. Full immutable results remain cached
for deterministic recovery. No source quotation, repair, Token or evaluation success constraint is relaxed.

The same unanswerable scenario and all four real acceptance cases must be rerun under the same Token,
LLM/tool/step budgets. Retain the first failed JSON, JUnit and log. Retrieval benchmark labels, scores and
parameters remain frozen; this change concerns Agent control/context only. A later benchmark revision
may review alternate positives, but this failure is not a reason to alter current qrels.

### Current verification outcome (after D20)

The unchanged acceptance cases pass within their original evaluation budgets. Bodies are emitted once
per current task; multi-turn session history remains question/report pairs with fresh retrieval. No
exact-argument loops were observed in four tasks, but search counts 3/4/2/4 show room for earlier stopping.
Do not infer general answer quality from 4/4 completion or 11/11 structurally valid citations. Frozen
retrieval judgments are incomplete and the observed 10 reranking regressions include both ranking errors
and valid unjudged alternatives. Keep these limitations with any reported score.

## D21 — Add the missing Dense + Rerank arm without changing the engine

The earlier four-way experiment cannot isolate whether RRF adds value after the same CrossEncoder.
The existing Query already supports dense+rerank, so add an experimental arm rather than restructure
retrieval. Run all five arms again, on the same frozen 120 questions, 1,201 chunks, 50 candidates and
GPU FP16 profile, with three repetitions in fixed shuffled order. Preserve the original four-way files;
new files use `real-retrieval-fiveway`. Do not splice a new arm's latency into an older run's table.
Dense cosine, BM25, RRF ranks and raw CrossEncoder logits remain separate provenance fields. Dense
reranking reorders only dense candidates; it does not invoke BM25 or add unlike raw score scales.

The results show a tradeoff: Dense+Rerank has slightly higher MRR/nDCG and lower latency than
Hybrid+Rerank, while Hybrid+Rerank has higher Recall@5. Pairwise wins/ties/losses count each question
once, not each timing repetition as independent evidence. No general superiority claim follows.

## D22 — Human decisions are an append-only evidence track, not assistant-generated gold labels

Incomplete anchor labels can score valid alternative evidence as irrelevant. Changing them after seeing
scores would make comparisons hard to audit. Keep frozen qrels and rankings, pool top-10 chunks from
all five arms plus original positives, blind method/rank/old labels, and retain exact source text, chunk
IDs, corpus hash and pool hash. Require a named human response and exact quotation for positive labels.
Grades are 0 irrelevant, 1 partial support, 2 direct support. Grade 0 is never counted as relevant.

The user actually replied A=2/B=0 on 2026-10-18: Q032's TaskGroup passage is direct evidence, whereas
Q052's subprocess StreamReader limit concerns a different object. Record the supplied grades and the
fact that no free-text rationale was supplied; do not invent one. These are two targeted spot checks,
not 120 human-reviewed questions. Fully judged pools alone may enter a separate human-pooled table;
pool Recall still cannot establish exhaustive-corpus Recall. Conflicting reviewers require explicit
adjudication and must not silently overwrite earlier labels.

## D23 — A strict CPU four-container profile keeps deployment evidence separate from GPU experiments

The previous real RAG runner invoked TaskRunner directly on the host; it did not prove that the HTTP API
and a separate containerized Worker communicate through Redis and shared SQLite. Add an override for
the existing four-service Compose architecture with isolated named volumes, loopback port 18000,
read-only pinned BGE weights, and an ignored private env file. Live mode continues to reject test doubles.
Use the already declared real-RAG 100k Token/600s task/120s tool profile; keep test assertions unchanged.

CPU is appropriate here because the WSL host has no verified NVIDIA container runtime and two app
processes each load the model pair. Pin Linux torch to the explicit official CPU wheel index in uv.lock;
the default Linux PyPI wheel otherwise pulls CUDA libraries that this deployment cannot use. The
separately pinned Windows CUDA environment remains separate. Add libgomp1 to the slim base image.
See the official configuration guidance: https://docs.astral.sh/uv/guides/integration/pytorch/ .

Acceptance must use real PDF HTTP uploads, a stopped Worker leaving a task queued, a restarted Worker
consuming it, and an in-flight SIGKILL after a paid LLM call. Preserve budgets/checkpoints across restart
and validate report quotes through the public source endpoint. CPU container task latency includes
the restart and is never merged with GPU query percentiles. Private credentials are excluded from
the build context, reports and Git; model files are mounted rather than baked into the image.

## D24 — Strengthen the comparison contract after an observed real-model failure

The first follow-up regression had 102 passes / 2 failures. One reused Qdrant Local directory was written
by a different client schema (`memory`/`payload` fields rejected by locked 1.17.1); use a fresh fixture
directory and rebuild from unchanged public snapshots, preserving the old directory. Do not delete
unknown persisted fields or alter the tests' assertions to make that directory load.

In the other failure the internal comparison generated bare chunk UUIDs instead of the supplied E-prefixed
dictionary keys, twice. The validator correctly refused to publish a report. The previous comparison
prompt did not explicitly distinguish those two IDs even though nested source payloads contain both.
Expose the exact allowed dictionary keys in the comparison prompt and forbid nested chunk/doc IDs;
keep the same strict validation and one-repair allowance. A deterministic regression injects that same
mistake and still must fail closed. JSON syntax errors now receive tool-specific repair guidance.

DeepSeek non-thinking requests now explicitly use configurable temperature 0 by default, and the internal
comparison requests JSON-object output. This reduces avoidable format randomness without guaranteeing
determinism or repairing/accepting fabricated identifiers. Record first failures and rerun the original
cases and thresholds unchanged. Retrieval-only results contain no LLM calls and do not change.
Official references: https://api-docs.deepseek.com/api/create-chat-completion/ and
https://api-docs.deepseek.com/quick_start/parameter_settings/ .

## D25 — Require the quote-map field in generated reports while preserving validation semantics

The second complete rerun had 105 passes / 1 failure: every real RAG task finished with valid quotes,
but the first build_report call in the version task misspelled `quotes` as `queries`. The single repair
worked; the unchanged strict protocol test nevertheless correctly failed because an invalid call occurred.
Preserve this result rather than counting eventual task completion as zero invalid model calls.

BuildInput's empty-dictionary default is useful for compatible empty-report inputs, but made quotes
optional in the model-facing schema. Explicitly require it in the generation schema, list the exact
report fields in the system contract, and require quotes={} for unsupported reports. Do not accept aliases,
rename model fields on receipt, add repair attempts or relax the strict acceptance audit. A new regression
still rejects `queries` after the existing one repair. This narrows generated output without changing the
stored Report format, tool interface, graph architecture or source validation.

Do not assume temperature 0 guarantees valid schema or deterministic answers. DeepSeek Beta strict mode
requires closed objects with fixed required properties; our evidence-keyed quote map has dynamic keys.
A Beta adapter would require a deliberate interface design rather than just setting strict=true.
Keep it out of this incremental fix. Reference: https://api-docs.deepseek.com/guides/tool_calls/ .

## D26 — Keep frozen benchmark and measured-evidence bytes intact in Git

Final archive QA found the Windows working copies of questions.json and raw JSONL had CRLF, while
`git show HEAD:path` had LF under the repository's general text normalization rule. Actual experiments
and their hashes were consistent with the working bytes, but a fresh checkout would not reproduce those
hashes. Do not change the frozen questions or recalculate their declared SHA to fit Git's converted blob.
Mark frozen public snapshots and reports `-text`, then stage their unchanged actual bytes. This preserves
the exact corpus used, original question hash, human-pool provenance and raw timing/ranking hashes across
operating systems. Source code continues to use the existing LF policy. Validate both working files and
committed blobs; ZIP hashes alone would not detect a Git normalization problem.
