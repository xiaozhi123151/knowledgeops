"""Render measured DeepSeek evidence, kept separate from synthetic fault-injection results."""
import json
import xml.etree.ElementTree as ET

from scripts.common import REPORTS


def number(value,percent=False):
    if value is None:
        return 'n/a'
    return f'{value:.2%}' if percent else f'{value:.2f}'


def section(data):
    summary = data.get('summary',{})
    lines = ['## Real DeepSeek API integration','',
        f"Recorded API run: {data['metadata']['at_utc']}; source commit `{data['metadata']['git_commit']}`.",'',
        f"Status: **{'PASS' if data.get('passed') else 'FAIL'}**. Model `{data['model']}`, "
        f"endpoint `{data['endpoint']}`, thinking `{data['thinking']}`.",'',
        '**Real model calls; actual LangGraph, Harness, BM25 and Qdrant Local. Embedding and reranker '
        'remain explicitly labeled local test doubles. This is not full live retrieval-stack validation.**','',
        '| Case | Pass | LLM calls | Reported tokens | Time ms | Valid citations |',
        '|---|---|---:|---:|---:|---:|']
    for case in data['cases']:
        lines.append(f"| {case['name']} | {case['success']} | {case.get('budget',{}).get('llm_calls',0)} | "
            f"{case.get('provider_usage_total',0)} | {case['elapsed_ms']:.2f} | "
            f"{case.get('valid_citations',0)}/{case.get('citations',0)} |")
    if summary:
        lines += ['',f"- Actual model requests/responses: {summary['llm_requests']}/{summary['llm_successful_responses']}.",
            f"- Service-reported tokens: prompt {summary['prompt_tokens']}, completion {summary['completion_tokens']}, "
            f"total {summary['total_tokens']}.",
            f"- Tool attempts completed: {summary['tools_completed']}/{summary['tool_attempts']} "
            f"({number(summary['tool_attempt_success_rate'],True)}). Denominator includes deliberate local failure injection.",
            f"- Invalid model function arguments: {summary['invalid_model_function_calls']} / "
            f"{summary['model_function_calls']} model function calls.",
            f"- API call P50/P95: {number(summary['api_p50_ms'])}/{number(summary['api_p95_ms'])} ms; "
            f"task P50/P95: {number(summary['task_p50_ms'])}/{number(summary['task_p95_ms'])} ms.",
            '- Percentiles describe this small run only. Tokens use provider usage, not character estimates.',
            '- Budget checks compare persisted attempts and tokens with actual response usage; reservations remain '
            'estimated only when a response is unavailable. No API key is part of this report.']
    probe = REPORTS/'deepseek-probe.json'
    if probe.exists():
        measured = json.loads(probe.read_text(encoding='utf-8'))
        lines += ['', f"Separate real protocol probe: pass={measured.get('passed')}, "
            f"{measured['budget']['llm_calls']} request, {measured['budget']['tokens']} reported tokens, "
            f"{measured['elapsed_ms']:.2f} ms. It is not included in the three research tasks above."]
    lines += ['', '### Public source provenance','']
    for source in data['sources']:
        lines.append(f"- [{source['version']}]({source['url']}): raw SHA-256 `{source['sha256']}`, "
            f"{source['bytes']} bytes, {source.get('chunk_count','?')} chunks, fetched {source['fetched_at_utc']}.")
    lines += ['', '### Fault-test boundary','',data['fault_boundary'],
        'Actual service 429/5xx incidents are not claimed. Network errors are injected in HTTP transport tests '
        'and identified as synthetic; the recovery scenario injects only one local search failure and uses real API replies.']
    return lines


def render(data):
    lines = ['# DeepSeek real API integration report','',
        f"Generated from run: {data['metadata']['at_utc']}; source commit `{data['metadata']['git_commit']}`.",
        f"Source SHA-256: `{data['metadata']['source_sha256']}`.",''] + section(data)
    for case in data['cases']:
        report = case.get('report')
        lines += ['', f"## Actual answer: {case['name']}",'']
        if not report:
            lines.append(f"Task failed: `{case.get('error')}`. No answer was published.")
            continue
        lines += [report['conclusion'],'']
        for finding in report['findings']:
            lines.append('- '+finding['text']+' ['+', '.join(finding['citation_ids'])+']')
        lines += ['', 'Limitations:',''] + ['- '+v for v in report['limitations']]
        lines += ['', 'Verified quotes:','']
        for citation in report['citations']:
            lines += [f"- `{citation['citation_id']}` — [source]({citation['source']}): "
                      + citation['quote'].replace('\n',' / ')]
    attempts = sorted(REPORTS.glob('deepseek-attempt-*.json'))
    if attempts:
        lines += ['', '## Exploratory failures retained','',
            'These are real earlier attempts, not synthetic model replies. They are excluded from the final '
            'acceptance-run success rate; their usage is retained here rather than hidden.','',
            '| Artifact | Requests | Reported tokens | Outcome |','|---|---:|---:|---|']
        for path in attempts:
            old = json.loads(path.read_text(encoding='utf-8'))
            summary = old.get('summary',{})
            errors = '; '.join(str(c.get('error')) for c in old.get('cases',[]))
            lines.append(f"| {path.name} | {summary.get('llm_requests',0)} | {summary.get('total_tokens',0)} | {errors} |")
    fault_xml = REPORTS/'deepseek-fault-injection.xml'
    if fault_xml.exists():
        suites = list(ET.parse(fault_xml).getroot().iter('testsuite'))
        count = sum(int(s.attrib.get('tests',0)) for s in suites)
        failures = sum(int(s.attrib.get('failures',0))+int(s.attrib.get('errors',0)) for s in suites)
        lines += ['', '## Synthetic transport/Harness regression','',
            f'{count} selected tests, {failures} failures/errors in deepseek-fault-injection.xml. '
            'These validate code behavior under injected faults; they are not real server fault observations.']
    (REPORTS/'deepseek-integration.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
