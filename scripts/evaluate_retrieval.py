import argparse
import csv
import hashlib
import json
import time

import numpy as np

from scripts.common import REPORTS, ROOT, api_client, import_file, metadata, request, write_json


def document_ranking(hits):
    return list(dict.fromkeys(h['chunk']['doc_id'] for h in hits))


def metrics(ranking, relevant):
    if not relevant:
        raise ValueError('QRELS_EMPTY: every evaluation query needs relevance labels')
    result = {f'recall@{k}':len(set(ranking[:k]) & relevant)/len(relevant) for k in [1,5,10]}
    result['mrr@10'] = next((1/i for i, doc in enumerate(ranking[:10],1) if doc in relevant), 0.0)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['offline','live'], default='offline')
    parser.add_argument('--base-url', default='http://127.0.0.1:8000')
    args = parser.parse_args()
    queries = [json.loads(line) for line in (ROOT/'examples'/'queries.jsonl').read_text(encoding='utf-8').splitlines()]
    rows, summary = [], {'metadata':metadata(args.mode), 'query_count':len(queries), 'repetitions':3,
                         'latency_definition':'HTTP round trip includes query embedding, retrieval, rerank and serialization; '
                                              'excludes import, startup and warmup; errors reported separately',
                         'ranking_definition':'Fetch 50 chunks, collapse duplicate document IDs, evaluate first 1/5/10 documents.'}
    try:
        with api_client(args.mode, args.base_url, 'retrieval') as (client, info):
            summary['providers'] = info['providers']
            summary['index_fingerprint'] = info['index_fingerprint']
            mapping = {path.name:import_file(client,path) for path in sorted((ROOT/'examples'/'corpus').iterdir())}
            summary['corpus_documents'] = len(mapping)
            summary['corpus_sha256'] = hashlib.sha256(b''.join(
                p.name.encode()+p.read_bytes() for p in sorted((ROOT/'examples'/'corpus').iterdir()))).hexdigest()
            summary['qrels_sha256'] = hashlib.sha256((ROOT/'examples'/'queries.jsonl').read_bytes()).hexdigest()
            # Scope retrieval to the fixture documents even when the live server has user documents.
            for name, mode, rerank in [('dense','dense',False), ('hybrid','hybrid',False), ('hybrid_rerank','hybrid',True)]:
                body = {'query':queries[0]['query'],'mode':mode,'rerank':rerank,'top_k':50,'candidates':50,
                        'doc_ids':list(mapping.values())}
                request(client,'POST','/query',json=body)  # warmup, not a measurement
                for query in queries:
                    relevant = {mapping[source] for source in query['relevant_sources']}
                    for repetition in range(3):
                        row = {'variant':name,'query_id':query['id'],'repetition':repetition+1,'error':None}
                        started = time.perf_counter()
                        try:
                            result = request(client,'POST','/query',json={**body,'query':query['query']})
                            row['latency_ms'] = (time.perf_counter()-started)*1000
                            row['ranking'] = document_ranking(result['hits'])
                            row['relevant'] = sorted(relevant)
                            row['hits'] = result['hits']
                            row.update(metrics(row['ranking'],relevant))
                        except Exception as exc:
                            row['latency_ms'] = (time.perf_counter()-started)*1000
                            row['error'] = type(exc).__name__
                            row.update(metrics([],relevant))  # failures count as misses, not silently dropped
                        rows.append(row)
            summary['variants'] = {}
            for name in ['dense','hybrid','hybrid_rerank']:
                group = [r for r in rows if r['variant']==name]
                successful = [r['latency_ms'] for r in group if r['error'] is None]
                summary['variants'][name] = {
                    **{key:float(np.mean([r[key] for r in group])) for key in ['recall@1','recall@5','recall@10','mrr@10']},
                    'p50_ms':float(np.percentile(successful,50)) if successful else None,
                    'p95_ms':float(np.percentile(successful,95)) if successful else None,
                    'error_rate':sum(r['error'] is not None for r in group)/len(group),
                    'measurements':len(group)}
    finally:
        write_json(REPORTS/f'retrieval-{args.mode}.json',summary)
        with (REPORTS/f'retrieval-{args.mode}.jsonl').open('w',encoding='utf-8') as f:
            for row in rows:
                f.write(json.dumps(row,ensure_ascii=False)+'\n')
        if rows:
            with (REPORTS/f'retrieval-{args.mode}.csv').open('w',encoding='utf-8-sig',newline='') as f:
                keys = ['variant','query_id','repetition','latency_ms','recall@1','recall@5','recall@10','mrr@10','error']
                writer = csv.DictWriter(f,fieldnames=keys,extrasaction='ignore')
                writer.writeheader()
                writer.writerows(rows)
    print(json.dumps(summary.get('variants',{}),ensure_ascii=False,indent=2))
    if any(r['error'] for r in rows):
        raise SystemExit('Evaluation completed with errors; inspect raw rows')


if __name__ == '__main__':
    main()
