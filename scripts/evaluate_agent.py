import argparse
import json
import time

import numpy as np

from scripts.common import REPORTS, ROOT, api_client, import_file, metadata, request, wait_task, write_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['offline','live'], default='offline')
    parser.add_argument('--base-url', default='http://127.0.0.1:8000')
    parser.add_argument('--limit', type=int, default=30)
    args = parser.parse_args()
    if args.limit <= 0:
        parser.error('--limit must be positive')
    queries = [json.loads(line) for line in (ROOT/'examples'/'queries.jsonl').read_text(encoding='utf-8').splitlines()][:args.limit]
    rows, summary = [], {'metadata':metadata(args.mode), 'scoring':'Task completion and exact-source citation validity; '
                                                                  'not semantic correctness or answer quality.'}
    try:
        with api_client(args.mode, args.base_url, 'agent') as (client, info):
            summary['providers'] = info['providers']
            summary['index_fingerprint'] = info['index_fingerprint']
            mapping = {p.name:import_file(client,p) for p in sorted((ROOT/'examples'/'corpus').iterdir())}
            for query in queries:
                started = time.perf_counter()
                row = {'query_id':query['id'],'success':False,'valid_citations':0,'citations':0,'error':None}
                try:
                    run = request(client,'POST','/research',json={'question':query['query']})
                    task = wait_task(client,run['task_id'])
                    row.update(task_id=run['task_id'], budget=task['budget'],status=task['status'])
                    if task['status'] != 'succeeded':
                        raise RuntimeError(task['error'])
                    citations = task['result']['citations']
                    row['citations'] = len(citations)
                    for citation in citations:
                        chunk = request(client,'GET',f"/documents/{citation['doc_id']}/chunks/{citation['chunk_id']}")
                        if citation['quote'] in chunk['text'] and citation['chunk_id'] == chunk['chunk_id']:
                            row['valid_citations'] += 1
                    row['success'] = row['valid_citations'] == len(citations) and bool(citations)
                    row['retrieved_relevant_source'] = bool({c['doc_id'] for c in citations} &
                                                           {mapping[s] for s in query['relevant_sources']})
                    row['report'] = task['result']
                except Exception as exc:
                    row['error'] = type(exc).__name__ + ': ' + str(exc)[:300]
                row['elapsed_ms'] = (time.perf_counter()-started)*1000
                rows.append(row)
            total_citations = sum(r['citations'] for r in rows)
            summary.update(tasks=len(rows), success_rate=sum(r['success'] for r in rows)/len(rows),
                citation_validity=sum(r['valid_citations'] for r in rows)/total_citations if total_citations else None,
                total_citations=total_citations,
                p50_ms=float(np.percentile([r['elapsed_ms'] for r in rows],50)),
                p95_ms=float(np.percentile([r['elapsed_ms'] for r in rows],95)),
                fault_injection='See JUnit: test_harness, test_agent, test_model_isolation, test_process_recovery.')
    finally:
        write_json(REPORTS/f'agent-{args.mode}.json',summary)
        with (REPORTS/f'agent-{args.mode}.jsonl').open('w',encoding='utf-8') as f:
            for row in rows:
                f.write(json.dumps(row,ensure_ascii=False)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k != 'metadata'},ensure_ascii=False,indent=2))
    if any(not r['success'] for r in rows):
        raise SystemExit('Agent evaluation contains failures; inspect raw rows')


if __name__ == '__main__':
    main()
