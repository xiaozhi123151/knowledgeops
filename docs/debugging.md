# Debugging log

This log records observed failures, root causes and regression evidence. Fault injection is identified
separately from model or infrastructure failures. Historical commit IDs refer to the original local repository.

## B01 — Bootstrap invoked from the parent directory

- Symptom: `uv sync --extra dev` returned “No pyproject.toml found”.
- Cause: Git initialization targeted the new subdirectory, but the next command still ran in its parent.
- Fix: all project commands specify the KnowledgeOps working directory explicitly.
- Validation: dependency resolution and all subsequent commands execute inside the project directory.
- No application code was affected; recorded with the first-stage commit.

## B02 — BM25 silently discarded lexical matches in tiny corpora

- Reproduction: import a two-page PDF, query `Redis AOF` in BM25 mode; stage-one pytest returned
  an empty hit list while dense retrieval worked (14 passed, 1 failed).
- Root cause: BM25Okapi IDF is zero when a term occurs in half the corpus, and may be negative when
  it appears in most documents. Filtering with `score > 0` removed valid lexical matches.
- Fix: qualify candidates by actual token overlap, then rank by the original BM25 score. Preserve
  zero/negative raw scores in the API rather than altering the library formula.
- Regression: the two-page PDF test covers all retrieval modes; empty queries without token overlap
  still produce no sparse candidates.

## B03 — LangGraph sync durability without a checkpointer

- Reproduction: all four initial Agent tests failed with `AsyncPregelLoop` missing `_put_checkpoint_fut`.
- Cause: passing `durability='sync'` to a graph compiled without a checkpointer triggers this behavior
  in the resolved LangGraph version. The runtime also warns that durability has no effect in that case.
- Fix: specify synchronous durability only when a checkpointer is installed. Production execution always
  installs SQLite checkpointing; uncheckpointed graph unit tests use the normal invocation path.
- Regression: complete tool loop, empty retrieval, invalid citations and forbidden tool tests.

## B04 — Default token budget exhausted by a normal short research task

- Reproduction: remove an artificially enlarged test budget; durable Agent integration fails with
  `BUDGET_EXCEEDED: tokens` under the specified 20,000-token default.
- Cause: treating every UTF-8 byte as a token reserves several times the normal input size; absent usage
  correctly keeps that reservation, so the overestimate accumulates on every model call.
- Fix: bundle the official cl100k reference tokenizer data (upstream SHA-256 verified) and count locally
  with a framing margin. No network request is needed in offline mode. Still mark missing provider usage
  as estimated: arbitrary compatible servers may use another tokenizer, so remote exact cost is not guaranteed.
- Regression: the durable Agent test must pass with the default budget, not a raised test-only limit.

## B05 — HTTP test assumed citation ordering meant retrieval ordering

- Symptom: end-to-end report test failed because the first citation had page 2 instead of page 1.
- Investigation: the quote exactly matched page 2; citation IDs are sorted for stable output, while
  retrieval rank is recorded independently. The application was mapping sources correctly.
- Fix: assert the presence and exact text of the page-1 citation rather than assuming citation-array order.
  This was a test assumption correction, not a source-location bug.

## B06 — Readiness initially assumed a separate Worker was alive

- Found during integration review: the live readiness implementation initially set worker status to true
  merely because live mode uses an external worker. It could advertise readiness while no worker existed.
- Fix: persist periodic Worker heartbeats and refresh them during long tasks; readiness requires freshness.
- Regression: health tests distinguish dependency health from liveness; worker heartbeat freshness is tested.

## B07 — Windows smoke server leaked past parent-process termination

- Reproduction: the first real HTTP smoke completed functional checks, then failed temporary-directory
  cleanup with WinError 32 on Qdrant's SQLite file.
- Investigation: SQLite handles were unavailable immediately after server termination. Windows launchers
  can also leave a child interpreter when only the launcher is terminated; a later process inventory did
  not prove a persistent orphan in this run. The initial summary incorrectly retained PASS after cleanup failed.
- Fix: terminate the owned process tree on Windows before cleanup; wait for exit and retry short-lived
  file-handle release. Cleanup exceptions now mark the smoke run failed instead of printing PASS.
- Regression: rerun the subprocess-based smoke and check that no server process remains.

## B08 — Evaluation tests could not import repository scripts

- Symptom: final pytest collection failed with `No module named scripts.common` and `scripts.evaluate_retrieval`,
  while `python -m scripts.smoke` worked.
- Cause: the pytest console entrypoint and module execution have different initial import paths. Repository
  scripts are operational companions, intentionally outside the installed library package.
- Fix: declare project and test helper paths in pytest configuration; use an explicit shared polling helper
  instead of importing one test file from another.
- Regression: console pytest and operational module commands both run from the documented project directory.

## B09 — Mock transport tests still need explicit SDK credentials

- Symptom: two new provider protocol tests failed before sending a request with OpenAIError “Missing credentials”.
- Cause: they constructed the live adapters using offline settings with empty keys, planning to replace the
  transport afterwards. The installed SDK validates credentials in its constructor.
- Fix: set explicit test-only dummy credentials in those tests before constructing adapters. Requests use
  httpx MockTransport against fixture.invalid, never the network. Production validation remains strict.
- Regression: verify function-call request parameters, returned usage, embedding response reordering and
  dimension mismatch, without requiring any real key or claiming real API integration.

## B10 — Dense retrieval imposed an undocumented zero threshold

- Reproduction: store the exact opposite of a query vector in actual Qdrant Local. The raw cosine score
  is -1, but the application returned zero hits; the new regression test failed before the fix.
- Cause: an initial `score > 0` condition silently removed zero/negative cosine candidates. Unlike a
  configured relevance threshold, cosine sign alone does not determine whether a ranked result is useful.
- Fix: preserve all top-ranked ready-document candidates and their signed raw scores. The Agent must judge
  whether evidence supports a conclusion; a score must not be represented as a calibrated probability.
- Regression: opposite-vector score is returned unchanged; rerun the complete suite and ablations because
  candidate membership has changed. This can alter measured offline rankings, so earlier metrics are superseded.

## Fixing commit index

| Entry | Fixing commit | Evidence |
|---|---|---|
| B01 bootstrap working directory | `3be4e4b` | dependency install and stage-one tests |
| B02 zero/negative BM25 IDF | `2a5609d` | two-page PDF across all search modes |
| B03 uncheckpointed sync durability | `5262e8a` | four Agent graph scenarios |
| B04 default token reservation | `b70466f` | durable Agent under default 20,000-token budget |
| B05 citation-order test assumption | `6c5ac1c` | HTTP PDF source lookup |
| B06 separate Worker readiness | `6c5ac1c` | heartbeat freshness and dependency health tests |
| B07 Windows smoke cleanup | `4afc47d` | repeated subprocess HTTP smoke completed and cleaned up |
| B08 pytest operational imports | `4afc47d` | final console pytest collection succeeds |
| B09 SDK mock credentials | `b490083` | no-network provider protocol tests |
| B10 signed dense scores | `97b649b` | actual Qdrant opposite-vector regression |

The final verification report supersedes intermediate metric runs. Intermediate phase JUnit files preserve
the stage gates; current accumulated results, skips, coverage and raw measurements are in reports/verification.md.

## B11 — A new LLM timeout changed a previously passing Harness contract

- Reproduction: initial integration regression produced 49 passes and one failure in the existing
  bounded-timeout test. The short tool timeout no longer canceled a slow LLM test double.
- Cause: a new fixed 30-second llm_timeout overrode the earlier tool_timeout behavior.
- Fix: the new field is optional; absence falls back to the existing tool timeout in SDK and Harness.
- Evidence: deepseek-regression-initial.xml preserves the failure; later regression runs include the old test.

## B12 — Real three-document research exceeded the default token reservation

- Real evidence: deepseek-attempt-01-budget.json records two successful API requests, 8,165 reported
  tokens, five completed searches, then BUDGET_EXCEEDED before another remote request.
- Cause: retrieval context grew across several searches; input plus maximum-output reservation no longer
  fit the remaining 20,000-token allowance. This was a functioning guard, not fabricated API failure.
- Resolution: use an explicit larger research validation profile and concise report instructions; retain
  defaults and all budget accounting. Successful runs must reconcile usage exactly with the task ledger.

## B13 — A valid four-tool response was rejected by a hard-coded graph cap

- Real evidence: deepseek-attempt-02-tool-batch.json records one non-thinking API response containing four
  function calls (1,538 reported tokens). The old graph rejected it before executing tools.
- Cause: the graph assumed providers return at most three calls; DeepSeek returned an additional search.
- Fix: use the existing task tool limit as the batch bound and keep serial execution/accounting. The
  request/step/tool budgets still cap execution. A unit test checks both four calls and a smaller configured bound.

## B14 — Citation quote-map semantics were underspecified for a real model

- Real evidence: deepseek-attempt-03-quotes.json failed with OUTPUT_VALIDATION_FAILED_AFTER_REPAIR.
  Checkpoint inspection showed correct retrieved E-... references in findings but quotes keyed by labels
  such as v2_total_activated. The repair changed wording rather than those dictionary keys.
- Fix: describe quote-key semantics in JSON Schema and system instructions, and return missing/extraneous
  IDs in validation feedback. Do not remap labels heuristically or accept unknown sources.
- Regression: a scripted wrong-key case repairs once; permanent invalid citations still fail closed.

## B15 — Long real tool arguments were cut off at the output limit

- Real evidence: deepseek-attempt-04-truncation.json records finish_reason=length at exactly 3,000 output
  tokens. JSON parsing failed; the next attempt corrected JSON but quoted text from a different chunk,
  exhausting the single repair. No report with those citations was published.
- Fix: a concise three-finding acceptance prompt, a 6,000-output evaluation allowance, exact per-chunk
  quote instructions and actionable incomplete-JSON feedback. Source validation and repair count remain strict.
- First successful complete run: deepseek-acceptance-first.json, five real requests, 39,683 service-reported
  tokens, three verified citations covering the three versions, with missing throughput explicitly unconfirmed.

DeepSeek fixing commits are recorded after the final regression/integration run. Historical failed runs
remain separate from the final acceptance-run denominator and retain their own real usage.

## B16 — Partial uncertainty was confused with a wholly unsupported report

- Real full-run evidence: the missing-throughput follow-up set insufficient_evidence=true while including
  supported parameter findings. Existing validation correctly rejected that inconsistent combination; the
  larger repair request then exceeded the remaining reservation. The first version-comparison turn had passed.
- Fix: clarify flag semantics in schema, system instruction and repair feedback. Supported specs plus
  missing measurements use false with explicit limitations; true requires no supported findings/quotes.
  Validation itself is unchanged. A regression verifies one repair while retaining valid source citations.

## B17 — Final verifier had two assumptions unrelated to model correctness

- The injected-failure case succeeded and its conclusion explicitly said absolute throughput could not
  be confirmed, but the checker searched limitations only. Check both conclusion and limitations, requiring
  the uncertainty phrase and throughput term in the same sentence; do not require empty citations for mixed reports.
- The verification wrapper forced KO_LLM_PROVIDER=mock globally. An existing test intentionally constructing
  live defaults then saw a different validation error. Set auto with offline mode in the wrapper; explicit
  test/runtime fixtures and offline HTTP scripts still force mock where needed, while live-default tests retain
  their original behavior. Real DeepSeek tests explicitly select their provider.
- The failed full-run JUnit and three-case API JSON are retained separately before rerunning.

## DeepSeek fix and verification index

| Entries | Commit | Evidence |
|---|---|---|
| B11–B15: provider timeout compatibility, real batch behavior, quote schema and truncation | `1de9ad6` | archived actual failures, non-network regression tests, first complete real API pass |
| B16–B17: partial uncertainty semantics and verifier assumptions | `40817c6` | final all-tests run and real three-case acceptance |

Final measured run: 68 passed, 2 skipped (unconfigured full retrieval-stack integration), zero failures/errors.
Three real research tasks passed with 12 successful API responses, 74,229 service-reported tokens, 10/10
exact-source citations. Tools completed 15/16 attempts: the deliberately injected local failure was retried
successfully. Provider failure bodies/headers and API credentials were not persisted. Source hashes in
reports/verification.json identify the measured library/configuration, and raw per-response counts/times
are in reports/deepseek-integration.json. See that report for the actual answers and sample-size limits.

## 2026-10-15 — Real infrastructure setup and retrieval boundary bugs

- Observation: Docker CLI was absent on Windows; WSL2 Ubuntu 24.04 existed. Installed Ubuntu's docker.io
  and docker-compose-v2, and ran dockerd in WSL. A detached daemon died when the WSL command exited;
  keeping a foreground host session provided a live daemon without modifying WSL boot settings.
- Actual first Compose pull failed with registry-1.docker.io network timeout. The configured Windows
  loopback proxy was unreachable from WSL NAT. A temporary, ignored reverse bridge relayed only to that
  proxy; no credentials were copied into images or reports. A firewall-rule attempt returned access denied,
  so no firewall rule was installed. This is an environment workaround, not an application fallback.
- Evidence: reports/real-infrastructure.json records real container IDs before/after recreation, Qdrant
  1.17.0, Redis persistence and write/search/delete results. Sentinel vectors are explicitly synthetic
  infrastructure probes; they are never retrieval-quality results.
- Code inspection found that mode alone selected all retrieval substitutes, preventing real local models
  with a separately selected LLM; added additive provider selectors. Inspection also found only vector
  dimension was checked and server collection was fixed across model spaces. Added full embedding
  fingerprint, server namespaces and vector-target metadata; regression tests exercise incompatible
  normalization/revision/target without changing existing test expectations.
- Direct Hugging Face large-weight downloads timed out after partial progress; public ranged downloads
  through the existing proxy use pinned revisions and verify official weight SHA-256 before loading.
  Failed/partial files stay under ignored data/, never count as downloaded or integrated weights.
- Regression so far: original offline suite 66 passed / 4 explicitly disabled external tests; after new
  validation/deletion/benchmark tests, 79 passed / 4 skipped. Additional real model evidence is recorded
  only after actual loading and measurements finish. Fix commit: see the retrieval-provider commit.

### Pytest collection collision (actual failure)

After adding a real integration module, the full run aborted before executing tests:
`import file mismatch: test_real_retrieval` referred to both tests/unit and tests/integration.
These test folders are intentionally not Python packages. Renamed the unit module to
`test_retrieval_contracts.py`; assertions and skip conditions were unchanged. The collection failure
is preserved in the command history and subsequent complete suite provides regression evidence.

### Client/server version mismatch observed during the first real index build

`qdrant-client 1.19.1` warned that server 1.17.0 exceeded its supported minor-version difference.
The previous wide `<2` dependency range had resolved beyond the pinned Compose image. Rather than suppress
compatibility checks or migrate persisted server data during an experiment, pinned the client to
`>=1.17,<1.18` and regenerated uv.lock (1.17.1). Re-run real server tests and container-persistence probe
with the matched pair; the initial indexing log truthfully retains the old warning. SentenceTransformers
also warned about a renamed dimension accessor; select the new accessor when available, retain old-version
compatibility for the supported optional dependency range. Fix commit is recorded in the final verification.

The full-suite collection collision was fixed in 69a2190. That commit also records the additive provider,
index namespace and fail-closed deletion changes. No pre-existing test assertions were relaxed.

### Spawn-time source change and a preserved failed real test attempt

The first real retrieval pytest run passed the first test but two subsequent child model loads failed
with `EMBEDDING_FAILED: KeyError: precision`. During that running multi-process test, precision options
were added to source: an existing parent held the old provider class while Windows spawn imported the
new child implementation. Re-running with one consistent source version passed all 3 real model tests
in 66.01 seconds. Kept the first attempt XML/log instead of overwriting it; future measurements freeze
source before spawning. This was a test-run/source consistency error, not a failed BGE weight/model check.

### Actual BGE downloads, index and CPU cost

Both selected BAAI weights are 2.27 GB each and their SHA-256 values match the official pinned Hugging Face
revisions (evals/public_technical/models.json). Large direct downloads repeatedly timed out. The reranker
was fetched from the BAAI ModelScope mirror and accepted only after matching the official Hugging Face
SHA-256. No mirror content was accepted on name alone. On Windows, trying to reassemble an already mmap-loaded
weight file returned OSError 22; verify and reuse the immutable existing file instead of opening it for write.

Actual CPU FP32 indexing imported 15 documents / 1,201 chunks in 480.59 seconds. A separate two-query timing
probe measured 22,034 and 21,757 ms, with 50 rerank candidates. These are timing probes, not quality scores.
The planned full evaluation therefore tries an isolated compatible CUDA wheel; default CPU environment
and the validated index remain intact. Wheel downloads use the official package SHA-256 even when a mirror
is needed. GPU results are recorded only after real kernels/models run successfully.

CPU real-RAG acceptance also passed: reports/real-rag-cpu.json records one three-version task,
4 real DeepSeek requests / 30,830 provider tokens / 6 tools / 4 exact-source citations in 79.63 seconds.
It is archived separately from the full experiment; no CPU timings are pooled with GPU timings.

### Genuine real Agent failure: repeated searches exhausted the next reservation

First full run: 87 passed, 1 failed, 2 skipped (215.66 s). Retained reports/retrieval-first-full-junit.xml,
reports/retrieval-first-full.log and reports/real-rag-first-attempt.json. Three tasks passed; private QPS
refusal failed with BUDGET_EXCEEDED: tokens after 5 searches and 6 tools. The ledger held 68,037 actual
provider tokens, but the next context plus output reservation would exceed 100,000. Thus enforcement
worked; silently raising the test budget would obscure the root cause.

Context telemetry showed 50 retrieved occurrences / 26 distinct chunks, 24 repeated bodies and up to
65,612 content characters. Added a default-4 server search limit with a comparison/report-only closing
phase. The execution guard rejects a model that ignores advertised tools. Full results remain cached;
prompt messages send repeated chunks only as references. Added deterministic tests for convergence,
exact original citation reuse and refusal of a malicious looping model. The existing acceptance scenarios,
Token budgets and assertions are unchanged. Fix commit is recorded below after committing the repair.

### Passing rerun and reproducible final evidence

Repair commit: bb7239b (search cap + body deduplication). The original four real RAG scenarios and
100,000-token profile were rerun unchanged. All four passed: 19 real DeepSeek requests, 136,726 actual
provider tokens, 21 tools and 11/11 exact-source citations. The private-QPS task now completes after
4 searches with 38,458 tokens; maximum input content was 30,915 characters and no repeated chunk bodies.
The earlier 68,037-token failed task remains archived. These are stochastic task observations, not a
controlled percentage-improvement claim. Four related searches can still be semantically redundant;
a cap and exact-argument duplicate count do not prove optimal retrieval efficiency.

Full pytest: 90 passed / 2 skipped / 0 failures, 221.39 seconds. Coverage: 88.2668%. The two skipped tests
are the original external HTTP API/Worker deployment tests, disabled via KO_RUN_LIVE_TESTS=0; real BGE,
Redis and DeepSeek tests were explicitly enabled. CPU model integration separately passed 3 tests.

Four real retrieval variants: 120 questions, 100 answerable, 15 sources, 1,201 chunks, 3 repeats = 1,440
measured attempts, zero query errors. GPU FP16, RTX 5060 Laptop, torch 2.7.1+cu128. Hybrid Recall@5=0.4633
is below Dense=0.5325; Hybrid+Rerank=0.7308 but nDCG declines on 10 individual questions versus Hybrid.
Q032's valid unjudged TaskGroup alternative demonstrates incomplete labels, whereas Q052's promotion
of subprocess buffers for an async Queue capacity question demonstrates an actual scope mismatch.
Kept all scores and frozen qrels unchanged. Exact excerpts and distinctions are in reports/real-bad-cases.md.

After indexing, the infrastructure probe recreated both containers again: the CPU and GPU collections
both retained exactly 1,201 real vectors, then the real Agent retrieved them successfully. Qdrant/Redis
container persistence is verified; API/Worker image builds/full four-container deployment remain unverified.

## B22 — A transitive uv source declaration did not select Linux CPU torch

Observed during this follow-up: adding `[tool.uv.sources] torch=...` while torch was only a transitive
dependency produced a 13 ms `uv lock` run with no lockfile change. Inspection still showed Linux CUDA
dependency wheels. This would have made an ordinary CPU container unnecessarily large.
Added torch explicitly to the existing `models` extra, retained the Linux-only source marker and ran
`uv lock` again. The lock now selects `torch==2.14.1+cpu` from the official explicit CPU index on Linux,
retains the Windows source, and removes unnecessary CUDA runtime packages. The real CPU Docker image
built successfully (2.45 GB); model startup reached real-provider readiness. This is a packaging fix,
not a change to retrieval math or an observed libgomp crash. libgomp1 was added proactively for the slim
image. Implementation commit: d42c860.

## B23 — Actual human spot checks separate label incompleteness from ranking error

This is an observed evaluation-label defect, not a test injection. The frozen Q032 qrels only include
release-note anchors; a retrieved asyncio-task paragraph states `All tasks are awaited when the context
manager exits` and `versionadded:: 3.11`, but was unjudged. On 2026-10-18 the user explicitly graded
this candidate A=2. The user graded Q052's subprocess StreamReader-limit candidate B=0, confirming that
the reranker's top hit concerns the wrong object for an asyncio.Queue capacity question.

Preserve original qrels/scores and append these two actual human decisions with exact chunk IDs,
question/pool/submission hashes and response provenance. Do not invent a reviewer rationale: the user
provided grades only. No full query pool is completely human-judged, so the human-pooled summary remains
empty rather than claiming an improved accuracy. Reproduction: `scripts.review_relevance score` and
`scripts.summarize_retrieval_followup`; artifacts are `relevance-human-ledger.jsonl` and
`retrieval-followup.md`. Collector and validation tests are in commit d42c860.

## B24 — First follow-up regression: 102 passed / 2 failed, original assertions preserved

Archived `followup-first-junit.xml`, `followup-first.log`, `followup-first-real-rag.json/.md` and first
coverage before rerunning. Four-container acceptance already passed in this run (`four-container-first.json`).

1. Legacy DeepSeek-only test failed before its first API call: Qdrant Local could not load `memory` and
   `payload` fields in an older fixture directory after the deliberate 1.17.1 client pin. The test invocation
   had explicitly reused `data/deepseek_validation/index`, rather than its default isolated tmp_path.
   Use a new per-run directory, reimport the same frozen public files and retain the old index unchanged.
   This is an incompatible test artifact; no live Server index or assertion was modified.
2. The real-retrieval version task failed with `OUTPUT_VALIDATION_FAILED_AFTER_REPAIR`. Cached comparison
   responses used bare chunk UUIDs instead of E-prefixed evidence IDs. Both retries were rejected. The
   comparison prompt lacked an explicit allowed-ID list; added it and forbade nested chunk/doc IDs.
   Also observed a stray `]>` in a search argument. Its one repair completed the task with valid citations,
   but the original strict “no invalid tool calls” acceptance still failed. Do not count it as a pass.
   Use explicit configurable temperature 0 and comparison JSON-object mode, and make JSON repair feedback
   specific to the failed tool. No quote normalization, ID remapping, extra retries or budget increase.

New synthetic regression still rejects bare chunk IDs after one repair; synthetic provider tests assert
the actual request options. These tests validate mechanics, not real model quality. Real API rerun results
are recorded separately after execution. The implementation repair commit is listed below after creation.

Repair commit: a013932. Targeted rerun: 3 real integration tests passed in 97.32 seconds, using the
original assertions and budgets. This comprises the single-call probe, the legacy three-task validation
(retrieval substitutes explicitly labeled) and the four-task true-BGE RAG validation. Artifact:
`followup-targeted-live-junit.xml`; intermediate measured JSON files retain their own boundary.
Offline rerun: 96 passed / 10 live tests deselected in 32.04 seconds.

## B25 — A successful repaired task still failed strict protocol acceptance

Second full run: 105 passed / 1 failed. Archived `followup-second-junit.xml`, `followup-second.log`,
`followup-second-real-rag.json`, coverage, and the passing `four-container-second.json`.
The version task's first build_report contained a `queries` field instead of `quotes`. Pydantic rejected
the extra field, the one allowed repair returned a valid report with all three real sources, and the
Harness accounted for both calls. The test still required zero invalid function calls and correctly failed.

Root cause: the model-facing schema inherited the optional quotes default, while source-backed reports
logically require that exact map. Made quotes explicitly required in generation, enumerated the report's
exact property names, and told the model to include {} for no-evidence reports. The business validator
still rejects the wrong alias, and no real acceptance assertion was changed. Synthetic regression injects
the same alias twice and must fail closed after one repair. This cannot guarantee future provider output
conformance; keep first/second failures visible alongside the final run rather than advertising stability
from a single passing run.

Repair commit: 95dc8e9. Final complete run after rebuilding/recreating API and Worker: **107 passed,
0 failed, 0 skipped**, 294.24 seconds; host statement coverage 88.2840%. Existing real acceptance
assertions/budgets remained unchanged. The new alias-injection regression also passes by rejecting it.
Offline real-HTTP smoke passed again. All first/second run files remain available.

The final public-corpus true RAG sample has 4/4 strict successes, 17 real LLM requests, 130,195 provider
tokens, 21 completed tools and 11/11 exact-source citations. The separate CPU four-container interrupted
task used 5 LLM requests, 13,029 actual tokens and 7 tool attempts; the report had 4 valid citations.
Both API/Worker source hashes match the checkout. Captured image IDs are identical; official model
weight hashes were rechecked after the run. See four-container.md/json, container-images.json and
followup-weights-integrity.json. These are small engineering acceptance samples, not general accuracy,
reliability or production-latency guarantees. Full human judgments, Python 3.11, external Langfuse and
50,000-chunk capacity remain unverified.

## B26 — Git newline normalization invalidated byte-hash reproducibility

Observed during final packaging QA: the working five-way raw JSONL had 1,800 CRLFs but its committed blob
had none; working questions.json had 1,444 CRLFs while HEAD used LF. The existing `* text=auto eol=lf`
rule silently converted generated text when staged. Tests had read the original working files, so their
frozen hashes passed locally but a fresh Git checkout would fail them. This was found by reading Git blobs,
not by fabricating a failed test run.

Added `evals/public_technical/** -text` and `reports/** -text` to preserve actual measured/source bytes,
then renormalized the index from unchanged working files. Question SHA remains
`1f92b0dd071168e63fd39a01991f356cfe6234d889f4ea51ceb08a4c7e8c9c32`.
No labels, queries, rankings, scores or test assertions changed. Final QA must verify committed question,
source and raw-result hashes as well as the delivery archive's member hashes.

Fix commit: 336de42. The frozen-question/anchor regression passed again. Readback of committed blobs,
all 15 source hashes, the original question SHA, the human pool hash and the raw-result SHA is captured
in reports/git-byte-integrity.json. This packaging correction leaves the tested working files unchanged;
the final 107-test application result remains the same measured run.
