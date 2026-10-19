"""Reconstruct selected bad cases from recorded ranks and persisted original chunks; no model calls."""

import argparse
import json

from knowledgeops.storage.db import Database
from scripts.common import REPORTS, ROOT, write_json
from scripts.real_retrieval import load_questions


def main(case_ids):
    report = json.loads((REPORTS / "real-retrieval.json").read_text(encoding="utf-8"))
    data, _, digest = load_questions()
    if digest != report["question_sha256"]:
        raise ValueError("Recorded results belong to a different question version")
    root = (
        ROOT
        / "data"
        / ("real_retrieval_cuda" if report["configuration"]["device"] == "cuda" else "real_retrieval")
    )
    if not (root / "metadata.sqlite").exists():
        raise FileNotFoundError("The original indexed evidence is required")
    _, chunks = Database(root).snapshot()
    by_id = {c.chunk_id: c for c in chunks}
    questions = {q["id"]: q for q in data["questions"]}
    qrels = json.loads((REPORTS / "real-retrieval-qrels.json").read_text(encoding="utf-8"))
    rows = [
        json.loads(line)
        for line in (REPORTS / "real-retrieval-raw.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    output = []
    for qid in case_ids:
        case = {
            "id": qid,
            "question": questions[qid]["question"],
            "judged_sources": sorted({by_id[c].title for c in qrels[qid]}),
            "variants": {},
        }
        for name in report["summary"]:
            row = next(
                r for r in rows if r["query_id"] == qid and r["variant"] == name and r["repetition"] == 0
            )
            case["variants"][name] = {
                "metrics": {k: row[k] for k in ["recall_at_5", "mrr_at_10", "ndcg_at_10"]},
                "top3": [
                    {
                        "source": by_id[c].title,
                        "id": c,
                        "text": by_id[c].text,
                        "source_url": by_id[c].source,
                        "judged": c in qrels[qid],
                    }
                    for c in row["ranked"][:3]
                ],
            }
        output.append(case)
    write_json(REPORTS / "real-bad-case-audit.json", output)
    print("Wrote exact ranked excerpts for " + ", ".join(case_ids))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("cases", nargs="*", default=["Q032", "Q052", "Q056", "Q081"])
    main(parser.parse_args().cases)
