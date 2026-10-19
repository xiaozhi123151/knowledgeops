import json
import xml.etree.ElementTree as ET

from scripts.common import REPORTS, metadata, write_json
from scripts.deepseek_report import render as render_deepseek
from scripts.deepseek_report import section as deepseek_section


def main():
    tree = ET.parse(REPORTS/'pytest.xml')
    suites = list(tree.getroot().iter('testsuite'))
    totals = {key:sum(int(s.attrib.get(key,0)) for s in suites) for key in ['tests','failures','errors','skipped']}
    totals['passed'] = totals['tests']-totals['failures']-totals['errors']-totals['skipped']
    totals['seconds'] = sum(float(s.attrib.get('time',0)) for s in suites)
    skip_reasons = [e.attrib.get('message','') for e in tree.getroot().iter('skipped')]
    coverage = json.loads((REPORTS/'coverage.json').read_text(encoding='utf-8'))['totals']
    retrieval = json.loads((REPORTS/'retrieval-offline.json').read_text(encoding='utf-8'))
    agent = json.loads((REPORTS/'agent-offline.json').read_text(encoding='utf-8'))
    smoke = json.loads((REPORTS/'smoke-offline.json').read_text(encoding='utf-8'))
    deepseek_path = REPORTS/'deepseek-integration.json'
    deepseek = json.loads(deepseek_path.read_text(encoding='utf-8')) if deepseek_path.exists() else None
    report = {'metadata':metadata('verification'), 'pytest':totals,'skip_reasons':skip_reasons,
              'coverage_percent':coverage['percent_covered'], 'retrieval':retrieval,'agent':agent,'smoke':smoke,
              'unverified':['Docker image build and Compose runtime','External Embedding API and non-DeepSeek LLMs',
                            'Real CrossEncoder weights/inference','Real Redis Streams and Qdrant Server',
                            'Langfuse server delivery','Python application on 3.11 or Linux (service containers were tested)',
                            '50,000-chunk capacity']}
    real_tracks = {}
    for name in ('real-infrastructure','real-retrieval','real-rag','real-retrieval-fiveway','four-container',
                 'relevance-review-status'):
        path=REPORTS/(name+'.json')
        if path.exists():
            real_tracks[name]=json.loads(path.read_text(encoding='utf-8'))
    report['real_tracks']=real_tracks
    if real_tracks.get('real-infrastructure',{}).get('passed'):
        report['unverified'].remove('Docker image build and Compose runtime')
        report['unverified'].append('API/Worker Docker image build and complete four-service container deployment')
        report['unverified'].remove('Real Redis Streams and Qdrant Server')
    if 'real-retrieval' in real_tracks:
        report['unverified'].remove('Real CrossEncoder weights/inference')
    four = real_tracks.get('four-container',{})
    if four.get('passed'):
        report['unverified'] = [x for x in report['unverified'] if x not in (
            'API/Worker Docker image build and complete four-service container deployment',
            'Docker image build and Compose runtime',
            'Python application on 3.11 or Linux (service containers were tested)')]
        report['unverified'].append('Python application on 3.11 (3.12 Windows and Linux validated)')
    human = real_tracks.get('relevance-review-status',{})
    if human.get('status') != 'complete':
        report['unverified'].append('Full human relevance judgment coverage; only the recorded spot checks completed')
    if deepseek:
        report['deepseek'] = deepseek
        report['deepseek_source_matches_current'] = (
            deepseek['metadata']['source_sha256'] == report['metadata']['source_sha256'])
        render_deepseek(deepseek)
        if not deepseek.get('passed'):
            report['unverified'].append('DeepSeek end-to-end acceptance has not passed')
        if not report['deepseek_source_matches_current']:
            report['unverified'].append('Current source differs from the last measured DeepSeek run; rerun integration')
    else:
        report['unverified'].append('Real DeepSeek API (not run)')
    write_json(REPORTS/'verification.json',report)
    lines = ['# KnowledgeOps verification report','',f"Generated: {report['metadata']['at_utc']}",
             f"Source commit: `{report['metadata']['git_commit']}`; dirty tree: {report['metadata']['working_tree_dirty']}",'',
             '**Separate evidence tracks:** offline fixture tables use model substitutes; the real retrieval '
             'table uses pinned BGE models and Qdrant Server. Real RAG adds official DeepSeek API calls. '
             'The earlier DeepSeek-only track retains its separate retrieval-substitute boundary. '
             'Synthetic faults are labeled; offline results do not establish model quality or production latency.','',
             '## Test execution','',f"- pytest: {totals['passed']} passed, {totals['skipped']} skipped, "
             f"{totals['failures']} failed, {totals['errors']} errors; {totals['seconds']:.2f} seconds.",
             f"- Statement coverage: {coverage['percent_covered']:.2f}% (includes optional live paths in denominator).",
             f"- Real HTTP offline PDF smoke: {'PASS' if smoke['passed'] else 'FAIL'}.",
             '- Process recovery test forcibly kills and restarts an interpreter; it does not simulate a restart with an in-memory flag.','',
             '## Offline fixture retrieval ablation','',f"{retrieval['query_count']} labeled queries, {retrieval['corpus_documents']} documents, "
             '3 measured repetitions per query and variant after warmup. Errors count as misses. Document-level ranking.',
             '', '| Variant | Recall@1 | Recall@5 | Recall@10 | MRR@10 | P50 ms | P95 ms | Error rate |',
             '|---|---:|---:|---:|---:|---:|---:|---:|']
    for name,m in retrieval['variants'].items():
        lines.append(f"| {name} | {m['recall@1']:.4f} | {m['recall@5']:.4f} | {m['recall@10']:.4f} | "
                     f"{m['mrr@10']:.4f} | {m['p50_ms']:.2f} | {m['p95_ms']:.2f} | {m['error_rate']:.4f} |")
    lines += ['',retrieval['latency_definition'], '', '## Offline Agent checks','',
              f"- {agent['tasks']} tasks; completion with valid citations: {agent['success_rate']:.2%}.",
              f"- Exact-source citation validity: {agent['citation_validity']:.2%} across {agent['total_citations']} citations.",
              f"- Task latency: P50 {agent['p50_ms']:.2f} ms; P95 {agent['p95_ms']:.2f} ms.",
              '- This does not measure semantic answer correctness or conflict-detection accuracy.','',
              '## Real API evidence','']
    if deepseek:
        lines += deepseek_section(deepseek)
        lines += ['', 'Actual answers and exploratory failures: [deepseek-integration.md](deepseek-integration.md).','']
    else:
        lines += ['DeepSeek integration not run.','']
    if real_tracks:
        initial = REPORTS/'followup-first-junit.xml'
        if initial.exists():
            suites = list(ET.parse(initial).getroot().iter('testsuite'))
            initial_counts = {k:sum(int(s.attrib.get(k,0)) for s in suites)
                              for k in ('tests','failures','errors','skipped')}
            initial_passed = initial_counts['tests']-sum(initial_counts[k]
                                for k in ('failures','errors','skipped'))
            report['followup_initial_tests'] = initial_counts | {'passed':initial_passed}
            lines += ['## Follow-up failures retained before repairs','',
                      f"2026-10-18 first full regression: {initial_passed} passed / "
                      f"{initial_counts['failures']} failed / {initial_counts['skipped']} skipped. "
                      'One incompatible legacy local index and one real-model protocol acceptance failure. '
                      'The original tests and budgets were retained. Repair `a013932` adds exact comparison IDs, '
                      'explicit temperature 0 and comparison JSON-object output; a fresh fixture index preserves '
                      'the original incompatible directory. See [first JUnit](followup-first-junit.xml), '
                      '[first log](followup-first.log) and [initial real RAG](followup-first-real-rag.json).','']
        second = REPORTS/'followup-second-junit.xml'
        if second.exists():
            suites = list(ET.parse(second).getroot().iter('testsuite'))
            counts = {k:sum(int(s.attrib.get(k,0)) for s in suites)
                      for k in ('tests','failures','errors','skipped')}
            passed = counts['tests']-sum(counts[k] for k in ('failures','errors','skipped'))
            report['followup_second_tests'] = counts | {'passed':passed}
            lines += [f"Second full run: {passed} passed / {counts['failures']} failed. All four real RAG tasks "
                      'completed, but the first version-report call used `queries` instead of `quotes`, so the '
                      'unchanged zero-invalid-call assertion failed. Repair `95dc8e9` explicitly requires the '
                      'exact quote-map field in generated output; invalid aliases are still rejected. '
                      'See [second JUnit](followup-second-junit.xml), [second log](followup-second.log) and '
                      '[second real RAG](followup-second-real-rag.json). Passing reruns do not erase these '
                      'failures or guarantee future provider conformance.','']
        followup = REPORTS/'retrieval-followup.md'
        if followup.exists():
            lines += [followup.read_text(encoding='utf-8'), '']
        if four:
            lines += ['## Four-container real API/Worker acceptance','',
                      f"Result: **{'PASS' if four.get('passed') else 'FAIL'}**; profile: "
                      f"{four.get('configuration')}. See [four-container.json](four-container.json).",'']
            lines += ['Detailed environment and per-call latency: [four-container.md](four-container.md).','']
            for name, passed in four.get('checks',{}).items():
                lines.append(f"- {name}: {'PASS' if passed else 'FAIL'}")
            if four.get('research'):
                lines += ['', 'Actual DeepSeek task budget: `' + json.dumps(four['research']['budget']) + '`.',
                          f"Validated citations: {four.get('validated_citations')}; whole task including worker restart: "
                          f"{four.get('research_elapsed_ms',0):.2f} ms. CPU container acceptance timings are separate "
                          'from GPU retrieval experiments.','']
        lines += ['## New real retrieval stack evidence','',
                  'Real-model experiments below are separate from the historical offline fixture table above. '
                  'CPU indexing and GPU/CPU query runs identify their device and precision in each artifact.','']
        infra=real_tracks.get('real-infrastructure')
        if infra:
            lines += [f"Qdrant/Redis Docker Compose persistence probe: **{'PASS' if infra.get('passed') else 'FAIL'}**; "
                      f"server {infra.get('server_version')}. Containers were stopped and recreated with named volumes. "
                      'Sentinel vectors validate infrastructure only, not semantic retrieval quality.','']
        for name in ('real-retrieval','real-rag'):
            path=REPORTS/(name+'.md')
            if path.exists() and name in real_tracks:
                lines += [path.read_text(encoding='utf-8').replace('# Real ','### Real ',1),'']
        audit=REPORTS/'real-bad-cases.md'
        if audit.exists():
            lines += [audit.read_text(encoding='utf-8').replace('# Recorded failure analysis',
                                                               '### Observed bad cases and judgment limits',1),'']
        lines += ['### Real failures and repair evidence','',
                  '- First full run: 87 passed / 1 failed / 2 skipped. The private-QPS task made 5 searches '
                  'and hit the next Token reservation after 68,037 reported tokens. Original budgets and success '
                  'assertions were retained for the passing rerun.',
                  '- `69a2190`: additive providers, vector-space namespaces, deletion and frozen public benchmark.',
                  '- `db8c263`: Qdrant client/server alignment, pinned weights and explicit inference precision.',
                  '- `bb7239b`: server search cap and evidence-body reuse; same unanswerable test now passes.',
                  '- Raw failed evidence: real-rag-first-attempt.json / retrieval-first-full-junit.xml. '
                  'The retrieval quality run was measured at db8c263; the later repair changes Agent control, '
                  'not retrieval ranking or frozen labels.','']
    lines += [
              '## Unverified integrations',''] + ['- '+x for x in report['unverified']]
    lines += ['', '## Skips',''] + ['- '+x for x in dict.fromkeys(skip_reasons)]
    lines += ['', '## Reproduction and evidence','',
              '- README contains the exact commands; raw per-query rankings/times are in retrieval-offline.jsonl and CSV.',
              '- Agent task outcomes, reports and budgets are in agent-offline.jsonl.',
              '- JUnit and coverage are pytest.xml, coverage.xml and coverage.json.',
              '- docs/debugging.md records observed failures, investigation and fixing commits.',
              '- docs/decisions.md records tradeoffs and deployment boundaries.','']
    write_json(REPORTS/'verification.json',report)
    (REPORTS/'verification.md').write_text('\n'.join(lines),encoding='utf-8')
    print('Wrote reports/verification.md and verification.json')


if __name__ == '__main__':
    main()
