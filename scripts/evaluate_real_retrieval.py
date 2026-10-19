"""Real models + Qdrant Server only. Frozen chunk qrels, separate from legacy offline evaluations."""

import argparse
import asyncio
import csv
import json
import math
import os
import platform
import random
import subprocess
import time
from collections import Counter
from importlib.metadata import version
from pathlib import Path

import numpy as np

from knowledgeops.schemas import Query
from scripts.common import REPORTS, metadata, write_json
from scripts.real_retrieval import RealStack, evidence_qrels, load_questions, real_settings

VARIANTS = [
    ("Dense", "dense", False),
    ("Dense+Rerank", "dense", True),
    ("BM25", "bm25", False),
    ("Hybrid", "hybrid", False),
    ("Hybrid+Rerank", "hybrid", True),
]


def metrics(ranked, qrels):
    qrels = {cid: grade for cid, grade in qrels.items() if grade > 0}
    if not qrels:
        return {"recall_at_5": None, "mrr_at_10": None, "ndcg_at_10": None}
    ranked = list(dict.fromkeys(ranked))
    recall = len(set(ranked[:5]) & qrels.keys()) / len(qrels)
    reciprocal = next((1 / r for r, c in enumerate(ranked[:10], 1) if c in qrels), 0)
    dcg = sum((2 ** qrels.get(c, 0) - 1) / math.log2(i + 2) for i, c in enumerate(ranked[:10]))
    ideal = sum(
        (2**grade - 1) / math.log2(i + 2) for i, grade in enumerate(sorted(qrels.values(), reverse=True)[:10])
    )
    return {"recall_at_5": recall, "mrr_at_10": reciprocal, "ndcg_at_10": dcg / ideal}


def aggregate(rows):
    answerable = [r for r in rows if r["answerable"]]
    successful = [r for r in rows if not r["error"]]
    # Errors count as zero relevance; latency is reported for completed and failed attempts separately.
    return {
        key: float(np.mean([r[key] for r in answerable])) if answerable else None
        for key in ["recall_at_5", "mrr_at_10", "ndcg_at_10"]
    } | {
        "queries": len({r["query_id"] for r in rows}),
        "attempts": len(rows),
        "failures": sum(bool(r["error"]) for r in rows),
        "failure_rate": sum(bool(r["error"]) for r in rows) / len(rows),
        "p50_ms": float(np.percentile([r["elapsed_ms"] for r in successful], 50)) if successful else None,
        "p95_ms": float(np.percentile([r["elapsed_ms"] for r in successful], 95)) if successful else None,
        "failed_latency_ms": [r["elapsed_ms"] for r in rows if r["error"]],
        "unanswerable_nonempty_rate": (
            float(np.mean([bool(r["ranked"]) for r in rows if not r["answerable"]]))
            if any(not r["answerable"] for r in rows)
            else None
        ),
    }


def render(report, rows):
    lines = [
        "# Real retrieval experiment",
        "",
        "Real BGE dense/CrossEncoder + Qdrant Server. No offline test-double results in this table.",
        f"Frozen questions SHA-256: `{report['question_sha256']}`; "
        f"source/config details: {report.get('report_prefix','real-retrieval')}.json.",
        f"Questions: {report['question_count']} (answerable {report['answerable_count']}); "
        f"chunks: {report['chunk_count']}; repetitions: {report['repetitions']}.",
        "",
        "| Variant | Recall@5 | MRR@10 | nDCG@10 | P50 ms | P95 ms | Failures |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, s in report["summary"].items():
        lines.append(
            f"| {name} | {s['recall_at_5']:.4f} | {s['mrr_at_10']:.4f} | {s['ndcg_at_10']:.4f} | "
            f"{s['p50_ms']:.1f} | {s['p95_ms']:.1f} | {s['failures']}/{s['attempts']} |"
        )
    lines += [
        "",
        "## Boundaries and methodology",
        "",
        "- Chunk-level judgments. Every overlapping chunk containing an annotated anchor is grade 2; other chunks "
        "are unjudged, treated as zero. Short anchors and incomplete judgments can penalize valid alternate evidence.",
        "- 20 unanswerable questions are excluded from Recall/MRR/nDCG denominators. Their nonempty retrieval rate "
        "is reported separately; nearest-neighbor search has no calibrated abstention threshold.",
        "- Assistant-authored questions; manual inspection is possible via questions.json evidence context, line and source URL. "
        "Initial judgments are not independent human gold labels; subsequent actual human spot checks are tracked "
        "separately in relevance-review-status.json. Keyword/semantic pairs share facts, so 120 is not 120 independent facts.",
        "- Fixed 50 candidates, top 10 chunks, RRF k=60, no per-variant tuning, fixed shuffled order; "
        f"{report['repetitions']} repetitions. Latency includes query embedding, BM25/Qdrant and reranking, excludes load/import/warmup.",
        '- Timing includes engine.search (real Qdrant HTTP requests) and returned-hit snapshot serialization; '
        'FastAPI/browser HTTP serialization is excluded.',
        "- No answer generation occurs in retrieval metrics. These are limited public-document results, not production accuracy.",
        "",
        "## Load, import and warmup (excluded from query latency)",
        "",
        "```json",
        json.dumps(report["timings"], indent=2),
        "```",
        "",
        "## Bad cases",
        "",
    ]
    for bad in report["bad_cases"][:15]:
        lines += [
            f"- {bad['query_id']} / {bad['variant']}: {bad['question']} "
            f"Recall@5={bad['recall_at_5']:.3f}, first judged rank={bad['first_relevant_rank']}; "
            f"top source={bad['top_source']}. {bad['diagnostic']}"
        ]
    return "\n".join(lines) + "\n"


async def evaluate(repetitions=3, root=None, prefix="real-retrieval"):
    if Path(prefix).name != prefix or not prefix or prefix in (".", ".."):
        raise ValueError("Report prefix must be a simple filename")
    data, sources, digest = load_questions()
    settings = real_settings(root)
    stack = await RealStack(settings).start()
    report = {
        "metadata": metadata("real_retrieval"),
        "question_sha256": digest,
        "repetitions": repetitions,
        "question_count": len(data["questions"]),
        "answerable_count": sum(q["answerable"] for q in data["questions"]),
        "categories": dict(Counter(q["category"] for q in data["questions"])),
        "variants": VARIANTS,
        "report_prefix": prefix,
        "models": {
            "embedding": settings.embedding_model,
            "embedding_revision": settings.embedding_revision,
            "reranker": settings.reranker_model,
            "reranker_revision": settings.reranker_revision,
        },
        "configuration": {
            "device": settings.embedding_device,
            "threads": settings.model_threads,
            "dimensions": settings.embedding_dimensions,
            "normalize": settings.embedding_normalize,
            "precision": settings.embedding_precision,
            "max_length": settings.embedding_max_length,
            "batch": settings.embedding_batch_size,
            "reranker_max_length": settings.reranker_max_length,
            "candidates": 50,
            "rrf_k": 60,
            "top_k": 10,
        },
        "dependencies": {n: version(n) for n in ["torch", "sentence-transformers", "transformers", "numpy"]},
        "environment": {
            "processor": platform.processor(),
            "logical_cpus": os.cpu_count(),
            "execution_device": settings.embedding_device + " " + settings.embedding_precision,
        },
    }
    report["metadata"]["quality_warning"] = (
        "Real models; small public corpus, incomplete assistant-authored qrels; no production-quality claim."
    )
    try:
        gpu = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,driver_version,memory.total,memory.free",
                "--format=csv,noheader",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        report["environment"]["gpu_inventory"] = gpu.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        report["environment"]["gpu_inventory"] = "unavailable"
    rows = []
    rawpath = REPORTS / f"{prefix}-raw.jsonl"
    try:
        server = await asyncio.to_thread(stack.engine.client.info)
        report["qdrant"] = {
            "server_version": server.version,
            "collection": stack.engine.collection,
            "fingerprint": stack.engine.fingerprint,
            "backend": "HTTP server",
        }
        t = time.perf_counter()
        source_ids = await stack.import_corpus(sources)
        stack.timings["import_ms"] = (time.perf_counter() - t) * 1000
        _, chunks = stack.db.snapshot()
        report["chunk_count"] = len(chunks)
        qrels = evidence_qrels(data, chunks, source_ids)
        write_json(REPORTS / f"{prefix}-qrels.json", qrels)
        t = time.perf_counter()
        for _, mode, rerank in VARIANTS:
            await stack.engine.search(
                Query(
                    query="Python 3.12 generic type parameters",
                    mode=mode,
                    rerank=rerank,
                    top_k=10,
                    candidates=50,
                )
            )
        stack.timings["warmup_ms"] = (time.perf_counter() - t) * 1000
        report["timings"] = stack.timings
        jobs = [
            (q, variant, rep) for rep in range(repetitions) for q in data["questions"] for variant in VARIANTS
        ]
        random.Random(20261015).shuffle(jobs)
        by_id = {c.chunk_id: c for c in chunks}
        with rawpath.open("w", encoding="utf-8") as raw:
            for i, (q, (name, mode, rerank), rep) in enumerate(jobs):
                row = {
                    "query_id": q["id"],
                    "question": q["question"],
                    "category": q["category"],
                    "answerable": q["answerable"],
                    "variant": name,
                    "repetition": rep,
                    "error": None,
                }
                t = time.perf_counter()
                try:
                    result = await stack.engine.search(
                        Query(query=q["question"], mode=mode, rerank=rerank, top_k=10, candidates=50)
                    )
                    row["ranked"] = [h.chunk.chunk_id for h in result.hits]
                    row["hits"] = [h.model_dump(exclude={"chunk": {"text"}}) for h in result.hits]
                except Exception as exc:
                    row.update(ranked=[], hits=[], error=type(exc).__name__ + ": " + str(exc)[:300])
                row["elapsed_ms"] = (time.perf_counter() - t) * 1000
                row.update(metrics(row["ranked"], qrels[q["id"]]))
                raw.write(json.dumps(row, ensure_ascii=False) + "\n")
                raw.flush()
                rows.append(row)
                if (i + 1) % 20 == 0:
                    print(f"evaluated {i + 1}/{len(jobs)}", flush=True)
        report["summary"] = {
            name: aggregate([r for r in rows if r["variant"] == name]) for name, _, _ in VARIANTS
        }
        report["by_category"] = {
            name: {
                cat: aggregate([r for r in rows if r["variant"] == name and r["category"] == cat])
                for cat in report["categories"]
                if cat != "unanswerable"
            }
            for name, _, _ in VARIANTS
        }
        report["bad_cases"] = []
        for row in rows:
            if row["answerable"] and row["recall_at_5"] < 1 and row["repetition"] == 0:
                first = next((i for i, c in enumerate(row["ranked"], 1) if c in qrels[row["query_id"]]), None)
                report["bad_cases"].append(
                    {k: row[k] for k in ["query_id", "question", "variant", "recall_at_5"]}
                    | {
                        "first_relevant_rank": first,
                        "top_source": by_id[row["ranked"][0]].title if row["ranked"] else None,
                        "diagnostic": "Inspect raw hits and qrels: competing release notes and overlapping/unjudged "
                        "passages can outrank the exact annotated evidence. This is a candidate explanation, not a causal proof.",
                    }
                )
        # Prefer cases where reranking degraded relative to the same query's hybrid result.
        paired = {(r["query_id"], r["variant"]): r for r in rows if r["repetition"] == 0}
        report["rerank_regressions"] = [
            {
                "query_id": q["id"],
                "hybrid": paired[(q["id"], "Hybrid")]["ndcg_at_10"],
                "rerank": paired[(q["id"], "Hybrid+Rerank")]["ndcg_at_10"],
            }
            for q in data["questions"]
            if q["answerable"]
            and paired[(q["id"], "Hybrid+Rerank")]["ndcg_at_10"] < paired[(q["id"], "Hybrid")]["ndcg_at_10"]
        ]
        report["dense_rerank_regressions"] = [
            {"query_id": q["id"], "dense": paired[(q["id"], "Dense")]["ndcg_at_10"],
             "rerank": paired[(q["id"], "Dense+Rerank")]["ndcg_at_10"]}
            for q in data["questions"] if q["answerable"]
            and paired[(q["id"], "Dense+Rerank")]["ndcg_at_10"] < paired[(q["id"], "Dense")]["ndcg_at_10"]
        ]
        write_json(REPORTS / f"{prefix}.json", report)
        (REPORTS / f"{prefix}.md").write_text(render(report, rows), encoding="utf-8")
        with (REPORTS / f"{prefix}.csv").open("w", newline="", encoding="utf-8-sig") as output:
            fields = [
                "query_id",
                "category",
                "answerable",
                "variant",
                "repetition",
                "recall_at_5",
                "mrr_at_10",
                "ndcg_at_10",
                "elapsed_ms",
                "error",
            ]
            writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        print(json.dumps(report["summary"], indent=2), flush=True)
        return report
    finally:
        await stack.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--prefix", default="real-retrieval", help="Separate output name; preserve earlier runs")
    args = parser.parse_args()
    if args.repetitions < 1:
        parser.error("repetitions must be positive")
    asyncio.run(evaluate(args.repetitions, args.data_dir, args.prefix))
