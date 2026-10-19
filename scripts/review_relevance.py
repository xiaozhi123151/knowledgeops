"""Blind, source-backed HUMAN judgment collection; never invents reviewer decisions.

prepare: pool all five variants' top-10 chunks plus frozen positives, no ranking/model labels in UI.
accept: validate a human-exported file and append immutable judgments. Original qrels stay frozen.
score: only fully judged pools receive separate pooled (not exhaustive-corpus) metrics.
"""

import argparse
import hashlib
import json
import random
from datetime import datetime, timezone
from pathlib import Path

from knowledgeops.storage.db import Database
from scripts.common import REPORTS, ROOT, write_json
from scripts.evaluate_real_retrieval import aggregate, metrics
from scripts.real_retrieval import load_questions


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def validate_review(pool, submission):
    if submission.get("pool_sha256") != pool["pool_sha256"]:
        raise ValueError("REVIEW_POOL_MISMATCH")
    if not submission.get("reviewer", "").strip() or submission.get("human_attestation") is not True:
        raise ValueError("HUMAN_REVIEWER_REQUIRED")
    allowed = {r["item_id"]: r for r in pool["items"]}
    seen = set()
    for row in submission.get("judgments", []):
        item_id = row.get("item_id")
        if item_id not in allowed or item_id in seen:
            raise ValueError("UNKNOWN_OR_DUPLICATE_REVIEW_ITEM")
        seen.add(item_id)
        if type(row.get("grade")) is not int or row["grade"] not in (0, 1, 2):
            raise ValueError("INVALID_RELEVANCE_GRADE")
        if not row.get("reason", "").strip():
            raise ValueError("REVIEW_REASON_REQUIRED")
        quote = row.get("quote", "")
        if row["grade"] > 0 and (not quote or quote not in allowed[item_id]["text"]):
            raise ValueError("POSITIVE_REVIEW_NEEDS_EXACT_QUOTE")
    if not seen:
        raise ValueError("EMPTY_REVIEW")
    return submission


def prepare(prefix):
    report = json.loads((REPORTS / f"{prefix}.json").read_text(encoding="utf-8"))
    data, _, question_hash = load_questions()
    if report["question_sha256"] != question_hash:
        raise ValueError("QUESTION_VERSION_MISMATCH")
    raw_path = REPORTS / f"{prefix}-raw.jsonl"
    rows = [json.loads(line) for line in raw_path.read_text(encoding="utf-8").splitlines()]
    originals = json.loads((REPORTS / f"{prefix}-qrels.json").read_text(encoding="utf-8"))
    root = ROOT / "data" / ("real_retrieval_cuda" if report["configuration"]["device"] == "cuda"
                            else "real_retrieval")
    _, chunks = Database(root).snapshot()
    by_id = {c.chunk_id: c for c in chunks}
    questions = {q["id"]: q for q in data["questions"]}
    pairs = {(r["query_id"], cid) for r in rows if r["repetition"] == 0 for cid in r["ranked"][:10]}
    pairs |= {(qid, cid) for qid, qrels in originals.items() for cid in qrels}
    pairs = sorted(pairs)
    random.Random(20261018).shuffle(pairs)
    items = []
    for qid, cid in pairs:
        chunk = by_id[cid]
        items.append({"item_id": digest([qid, cid])[:20], "query_id": qid,
                      "question": questions[qid]["question"], "category": questions[qid]["category"],
                      "chunk_id": cid, "doc_id": chunk.doc_id, "source": chunk.source,
                      "title": chunk.title, "locator": chunk.model_dump(exclude={"text"}),
                      "text": chunk.text, "text_sha256": hashlib.sha256(chunk.text.encode()).hexdigest()})
    payload = {"schema": 1, "question_sha256": question_hash,
               "raw_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
               "prefix": prefix, "items": items}
    pool = payload | {"pool_sha256": digest(payload)}
    write_json(REPORTS / "relevance-review-pool.json", pool)
    # JSON embedded in script must not allow a source text to terminate the script element.
    embedded = json.dumps(pool, ensure_ascii=False).replace("<", "\\u003c")
    page = HTML.replace("__POOL__", embedded)
    (REPORTS / "relevance-review.html").write_text(page, encoding="utf-8")
    print(f"Prepared {len(items)} blind items / {len(questions)} questions; HUMAN judgments pending")
    write_json(REPORTS / "relevance-review-status.json", {
        "pool_sha256": pool["pool_sha256"], "pooled_items": len(items),
        "pooled_questions": len(questions), "human_reviewed_items": 0,
        "status": "pending_human_review", "limitations": "No human judgments have been fabricated. "
        "Pool recall is not exhaustive corpus recall; unjudged items are not human negatives."})
    # Re-preparing the identical pool must not hide already accepted human judgments.
    score()


def accept(path):
    pool = json.loads((REPORTS / "relevance-review-pool.json").read_text(encoding="utf-8"))
    submission = validate_review(pool, json.loads(path.read_text(encoding="utf-8-sig")))
    record = {"accepted_at_utc": datetime.now(timezone.utc).isoformat(),
              "submission_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), **submission}
    ledger = REPORTS / "relevance-human-ledger.jsonl"
    if ledger.exists():
        existing = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
        grades = {j["item_id"]: j["grade"] for record in existing
                  if record.get("pool_sha256") == pool["pool_sha256"] for j in record["judgments"]}
        if any(j["item_id"] in grades and grades[j["item_id"]] != j["grade"]
               for j in submission["judgments"]):
            raise ValueError("REVIEWER_DISAGREEMENT_REQUIRES_ADJUDICATION")
    with ledger.open("a", encoding="utf-8") as out:
        out.write(json.dumps(record, ensure_ascii=False) + "\n")
    score()


def score():
    pool = json.loads((REPORTS / "relevance-review-pool.json").read_text(encoding="utf-8"))
    by_item = {r["item_id"]: r for r in pool["items"]}
    ledger = REPORTS / "relevance-human-ledger.jsonl"
    records = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()] if ledger.exists() else []
    judgments, reviewers = {}, set()
    for record in records:
        if record.get("pool_sha256") != pool["pool_sha256"]:
            continue
        validate_review(pool, record)
        reviewers.add(record["reviewer"])
        for row in record["judgments"]:
            # Disagreements are unresolved, never silently use the latest reviewer.
            if row["item_id"] in judgments and judgments[row["item_id"]] != row["grade"]:
                raise ValueError("REVIEWER_DISAGREEMENT_REQUIRES_ADJUDICATION")
            judgments[row["item_id"]] = row["grade"]
    complete = {r["query_id"] for r in pool["items"]}
    complete -= {r["query_id"] for r in pool["items"] if r["item_id"] not in judgments}
    qrels = {qid: {r["chunk_id"]: judgments[r["item_id"]] for r in pool["items"]
                   if r["query_id"] == qid} for qid in complete}
    raw_path = REPORTS / f"{pool['prefix']}-raw.jsonl"
    if hashlib.sha256(raw_path.read_bytes()).hexdigest() != pool["raw_sha256"]:
        raise ValueError("REVIEW_RANKING_CHANGED")
    rows = []
    for line in raw_path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row["query_id"] not in complete:
            continue
        judged = qrels[row["query_id"]]
        row["answerable"] = any(v > 0 for v in judged.values())
        row.update(metrics(row["ranked"], judged))
        rows.append(row)
    status = {"pool_sha256": pool["pool_sha256"], "pooled_items": len(by_item),
              "human_reviewed_items": len(judgments), "reviewers": sorted(reviewers),
              "fully_reviewed_questions": sorted(complete),
              "status": "complete" if len(judgments) == len(by_item) else "partial" if judgments else "pending_human_review",
              "metric_scope": "Only fully human-judged pools; pool Recall is not exhaustive-corpus Recall.",
              "summary": {v: aggregate([r for r in rows if r["variant"] == v])
                          for v in sorted({r["variant"] for r in rows})}}
    write_json(REPORTS / "relevance-review-status.json", status)
    write_json(REPORTS / "relevance-reviewed-qrels.json", qrels)
    print(json.dumps(status, ensure_ascii=False, indent=2))


HTML = '''<!doctype html><html lang="zh"><meta charset="utf-8"><title>KnowledgeOps 人工相关性盲审</title>
<style>body{font:16px system-ui;max-width:1000px;margin:32px auto;padding:16px}pre{white-space:pre-wrap;background:#eee;padding:16px}button,input,select,textarea{font:inherit;margin:5px;padding:8px}textarea{width:95%}nav{position:sticky;top:0;background:white;padding:8px}small{color:#555}</style>
<h1>人工相关性复核</h1><p>按问题的对象、版本与限制判断原文；不显示检索方法、排名或原始标签。0=无关/错误对象，1=部分支持（跨文档只支持一部分也选1），2=直接完整支持。不能确定请跳过。正例必须粘贴当前原文中的准确摘录，并写理由。所有判断由你实际完成。</p>
<nav>复核人 <input id="reviewer" placeholder="姓名或稳定代号"> <select id="filter"><option value="">全部问题</option></select><button id="save">导出已完成判断</button><span id="progress"></span></nav>
<main id="main"></main><script>
const pool=__POOL__, key='ko-review-'+pool.pool_sha256;
let state=JSON.parse(localStorage.getItem(key)||'{}');
const $=x=>document.getElementById(x), el=(t,s)=>{let n=document.createElement(t);n.textContent=s;return n};
$('reviewer').value=state.reviewer||'';
const ids=[...new Set(pool.items.map(x=>x.query_id))].sort();
for(const id of ids){const o=el('option',id+' '+pool.items.find(x=>x.query_id===id).question);o.value=id;$('filter').append(o)}
function persist(){state.reviewer=$('reviewer').value;localStorage.setItem(key,JSON.stringify(state));$('progress').textContent=Object.keys(state.judgments||{}).length+'/'+pool.items.length+' 项'}
function render(){const root=$('main');root.replaceChildren();
 const items=pool.items.filter(x=>!$('filter').value||x.query_id===$('filter').value);
 // Show one question at a time to keep the full pool responsive.
 const qid=$('filter').value||items[0]?.query_id;
 for(const item of items.filter(x=>x.query_id===qid)){
  const s=el('section','');s.append(el('h2',item.query_id+' '+item.question));
  const a=el('a',item.title+' · 原始来源');a.href=item.source;a.target='_blank';a.rel='noopener noreferrer';s.append(a,el('small','  chunk '+item.chunk_id),el('pre',item.text));
  const prior=state.judgments?.[item.item_id]||{};const grade=document.createElement('select');
  for(const [value,label] of [['','未判断'],['0','0 无关'],['1','1 部分支持'],['2','2 直接支持']]){const o=el('option',label);o.value=value;grade.append(o)}grade.value=prior.grade??'';
  const reason=document.createElement('textarea');reason.placeholder='判断理由（必填）';reason.value=prior.reason||'';
  const quote=document.createElement('textarea');quote.placeholder='从上方原文粘贴准确摘录（正例必填）';quote.value=prior.quote||'';
  function change(){state.judgments??={};if(grade.value==='')delete state.judgments[item.item_id];else state.judgments[item.item_id]={item_id:item.item_id,grade:Number(grade.value),reason:reason.value,quote:quote.value};persist()}
  for(const n of [grade,reason,quote])n.onchange=change;s.append(grade,reason,quote);root.append(s);
 }persist()}
$('filter').onchange=render;$('reviewer').onchange=persist;
$('save').onclick=()=>{persist();const judgments=Object.values(state.judgments||{});
 if(!state.reviewer.trim()||!judgments.length){alert('请填写复核人和实际判断');return}
 for(const j of judgments){const item=pool.items.find(x=>x.item_id===j.item_id);if(!j.reason.trim()||(j.grade>0&&(!j.quote||!item.text.includes(j.quote)))){alert('存在缺少理由或非原文摘录的判断：'+item.query_id);return}}
 const result={pool_sha256:pool.pool_sha256,reviewer:state.reviewer,human_attestation:true,reviewed_at:new Date().toISOString(),judgments};
 const a=el('a','');a.href=URL.createObjectURL(new Blob([JSON.stringify(result,null,2)],{type:'application/json'}));a.download='relevance-human-review.json';a.click();URL.revokeObjectURL(a.href)};render();
</script></html>'''


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--prefix", default="real-retrieval-fiveway")
    p = sub.add_parser("accept")
    p.add_argument("path", type=Path)
    sub.add_parser("score")
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.prefix)
    elif args.command == "accept":
        accept(args.path)
    else:
        score()
