# Public technical evidence benchmark

120 assistant-authored questions: 40 keyword, 40 semantic paraphrases, 10 cross-document,
10 version-conflict, 20 explicitly unanswerable within the provided snapshots. The single-fact
question styles share 40 anchors; this is not 120 independent facts or independently human-labeled data.
The version category includes migration comparisons and mistaken-equivalence questions (such as
per-interpreter GIL versus free-threaded execution); these are not all directly contradictory numerical claims.

`manifest.json` contains first-party URLs, original-byte SHA-256 and timestamps. CPython sources are pinned
to release tags, imported as TXT with original RST syntax. DeepSeek snapshots retain Markdown sections.
`questions.json` contains exact quotes, original character spans, line numbers and surrounding context.
Inspect these against `documents/` to review labels. Metrics have not been used to select or revise questions.
`questions.sha256` freezes the file. A deliberate revision requires a new benchmark version and rerunning all variants.

The evaluator normalizes anchors with the ingestion normalizer and labels every matching source chunk
as grade 2, including overlapping chunks. Other passages are unjudged and treated as zero, not exhaustively
verified negatives. Chunk-level Recall@5 / MRR@10 / standard nDCG@10 use the 100 answerable questions.
Overlapping chunks count as separate relevance units, which can lower recall despite finding the fact once;
inspect raw qrels to audit that effect. This benchmark cannot establish general production quality.

Unanswerable questions lack qrels and never receive artificially perfect scores. Retrieval nonempty rate is
reported separately. Top-k nearest-neighbor retrieval does not itself detect insufficient answer evidence.
Agent abstention is evaluated separately with exact-source citation verification.

`fetch_benchmark_docs.py` reproduces CPython snapshots and copies previously fetched official DeepSeek docs.
On a clean checkout first run `python -m scripts.fetch_deepseek_docs`.
Sources are upstream documentation, not private user data. CPython files are under the PSF license (LICENSE.python).
DeepSeek documents remain subject to upstream repository/model licensing; manifest URLs identify their sources.
