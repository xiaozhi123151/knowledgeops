import argparse
import time

from scripts.common import REPORTS, ROOT, api_client, import_file, metadata, request, wait_task, write_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['offline','live'], default='offline')
    parser.add_argument('--base-url', default='http://127.0.0.1:8000')
    args = parser.parse_args()
    report = {'metadata':metadata(args.mode), 'passed':False, 'checks':[]}
    started = time.perf_counter()
    try:
        with api_client(args.mode, args.base_url, 'smoke') as (client, info):
            report['providers'] = info['providers']
            import_file(client, ROOT / 'examples' / 'sample.pdf')
            report['checks'].append('PDF upload and completed indexing')
            retrieved = request(client, 'POST', '/query', json={'query':'Redis AOF persistence','rerank':True})
            assert retrieved['hits'] and retrieved['hits'][0]['rerank_score'] is not None
            report['checks'].append('Hybrid retrieval and rerank with retained scores')
            submitted = request(client, 'POST', '/research', json={'question':'How does Redis AOF persistence work?'})
            task = wait_task(client, submitted['task_id'])
            assert task['status'] == 'succeeded', task['error']
            assert task['result']['citations'], 'No citations in report'
            for citation in task['result']['citations']:
                chunk = request(client, 'GET', f"/documents/{citation['doc_id']}/chunks/{citation['chunk_id']}")
                assert citation['quote'] in chunk['text']
                assert chunk['page'] is not None
            report['checks'].append('Report citations map to stored PDF pages and verbatim text')
            events = request(client,'GET', f"/tasks/{submitted['task_id']}/events")['events']
            assert any(e['type'] == 'tool_completed' for e in events)
            report['checks'].append('Persistent task events available')
            report['task'], report['event_count'] = task, len(events)
            report['passed'] = True
    except Exception as exc:
        report['passed'] = False
        report['error'] = type(exc).__name__ + ': ' + str(exc)
        raise
    finally:
        report['elapsed_ms'] = (time.perf_counter()-started)*1000
        write_json(REPORTS / f'smoke-{args.mode}.json', report)
        print(f"Smoke {args.mode}: {'PASS' if report['passed'] else 'FAIL'}; reports/smoke-{args.mode}.json")


if __name__ == '__main__':
    main()
