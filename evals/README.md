# Evaluation contract

Fixtures: examples/corpus (12 owned bilingual documents), examples/queries.jsonl (30 fixed document-level
relevance judgments), examples/sample.pdf (two-page end-to-end fixture).

Commands: python -m scripts.evaluate_retrieval; python -m scripts.evaluate_agent; python -m scripts.smoke.
Every command takes --mode offline/live. Offline model substitutes are labeled in every report.

Recall@K = |relevant ∩ unique-document-ranking[:K]| / |relevant|.
MRR@10 = 1 / rank of the first relevant document within ten, or zero.
Retrieval failures count as zero quality; latency percentiles describe successful HTTP requests only.
Raw failed rows still record latency and error type. No model-generated relevance labels are used.

Agent success checks terminal completion, nonempty citations and exact-source quote validity. It is not
a judge of semantic correctness, writing quality or conflict detection. Fault-injection evidence is JUnit.
Live Agent evaluation uses the shared knowledge base; use an isolated evaluation deployment.
