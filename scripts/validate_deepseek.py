"""Real DeepSeek + actual LangGraph/Harness/BM25/Qdrant Local; explicit retrieval-model substitutes."""
import argparse
import asyncio
import hashlib
import json
import re
import time
import uuid
from pathlib import Path

import numpy as np

from knowledgeops.agent.tools import TOOL_MODELS
from knowledgeops.config import Settings
from knowledgeops.runtime import Runtime
from scripts.common import REPORTS, ROOT, metadata
from scripts.fetch_deepseek_docs import fetch_documents

QUESTIONS = [
    ('version_comparison',
     '请分别检索 DeepSeek-V2、DeepSeek-V3、DeepSeek-V4.1-Flash 的官方文档，比较三个版本的总参数量、'
     '每 token 激活参数量、上下文长度。必须调用 knowledge_search（可按版本分别检索并把 top_k 设为 4 或更大），'
     '再调用 compare_evidence 对比实际检索证据，最后调用 build_report。findings 应覆盖三个版本，每个版本写一条，'
     '指标必须直接见于对应版本证据，不能用其他版本的值替代。quotes 使用最短指标原文，不要改写，尽量小于100字符。'
     '结论用中文。三个版本在同一台 A100 80GB、batch=1 下的准确吞吐量是多少？如果这些文档缺乏同条件实测依据，'
     '在 limitations 明确写“无法确认”，不要用论文相对提升率代替绝对吞吐量。'),
    ('followup_missing_evidence',
     '继续核查：仅依据知识库中的官方版本文档，能否确认 DeepSeek-V2、V3、V4.1-Flash 在同一台 A100 80GB '
     'batch=1 下的绝对 tokens/s 排名？请实际检索并比较证据，无法确认时明确说无法确认，不能从参数量推算性能。'
     '如果有可确认的上下文长度或参数指标，可以列出并引用，以区分已知和未知。引用用最短原文。'),
    ('tool_failure_recovery',
     '请检索并对比 DeepSeek-V2 与 DeepSeek-V3 的总参数量和每 token 激活参数量。调用 compare_evidence 后，'
     '用 build_report 给出中文结论，引用必须是检索原文。无法得到同一硬件绝对 tokens/s 时说明无法确认。'),
]


def audit_messages(messages):
    calls, invalid = [], []
    for message in messages:
        for call in message.get('tool_calls', []):
            function = call.get('function', {})
            name = function.get('name')
            try:
                args = json.loads(function['arguments'])
                TOOL_MODELS[name].model_validate(args)
                calls.append({'id':call['id'],'name':name,'arguments':args,'valid':True})
            except (KeyError, TypeError, ValueError):
                invalid.append({'id':call.get('id'),'name':name,'valid':False})
    return calls, invalid


CONCISE = ('\n输出约束：最多3条 findings，conclusion不超过200个汉字，limitations最多3条。'
           '每个版本优先只选1条同时包含参数量和上下文的证据；quotes键必须是相同的E-...引用ID，'
           '每个quote尽量短于80字符且是对应那一条证据text的连续子串。不要添加训练量、KV缓存等题外指标。'
           '不要为了缺失的吞吐量制造引用；明确无法确认即可。若有已知指标但吞吐量未知，'
           'insufficient_evidence必须为false，未知部分写入limitations。只有完全没有支持性发现时才设为true并清空findings/quotes。')


async def run_validation(root: Path, *, refresh_docs=False, cases=3):
    documents = ROOT/'data'/'deepseek_validation'/'documents'
    manifest = documents/'manifest.json'
    sources = fetch_documents(documents) if refresh_docs or not manifest.exists() else json.loads(
        manifest.read_text(encoding='utf-8'))['documents']
    # A three-document research turn can need several searches and a long comparison context.
    # This explicit evaluation profile does not change production defaults or bypass accounting.
    settings = Settings(mode='offline', llm_provider='deepseek', data_dir=root,
                        token_budget=80000, output_tokens=6000, tool_timeout=60, llm_timeout=60)
    runtime = await Runtime(settings).start()
    report = {'metadata':metadata('real_deepseek_local_retrieval'), 'model':runtime.llm.name,
        'endpoint':settings.deepseek_base_url,'thinking':'disabled','sources':sources,'cases':[],
        'integration_boundary':{'llm':'real official DeepSeek HTTP API', 'agent':'real LangGraph',
            'harness':'real durable budgets/checkpoints/retries', 'search':'actual BM25 + Qdrant Local',
            'embedding':'offline hash test double','reranker':'offline lexical-overlap test double',
            'redis':'not used in single-process local validation'},
        'fault_boundary':'tool_failure_recovery injects one local ConnectionError; API replies remain real. '
                         'HTTP 429/5xx/timeouts are tested separately with labeled synthetic transports.'}
    secret = settings.deepseek_api_key.get_secret_value()
    run_id = uuid.uuid4().hex
    try:
        source_by_doc = {}
        for source in sources:
            path = documents/source['filename']
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != source['sha256']:
                raise ValueError('PUBLIC_SNAPSHOT_HASH_MISMATCH')
            payload = runtime.ingestion.save_upload(data,path.name)
            payload.update(source=source['url'],title=source['version'])
            imported = await runtime.ingestion.ingest(payload)
            source['doc_id'] = imported['doc_id']
            source['chunk_count'] = imported['chunk_count']
            source_by_doc[imported['doc_id']] = source['version']
        for index, (name, question) in enumerate(QUESTIONS[:cases]):
            question += CONCISE + '\n可检索文档目录（只有来源元数据，没有指标答案）：' + json.dumps(
                [{'version':s['version'],'doc_id':s['doc_id']} for s in sources],ensure_ascii=False)
            session_id = ('version-conversation-' if index < 2 else 'failure-conversation-') + run_id
            row = {'name':name,'question':question,'success':False}
            original_search = runtime.engine.search
            injected = 0
            if name == 'tool_failure_recovery':
                async def fail_once(request, original_search=original_search):
                    nonlocal injected
                    if not injected:
                        injected += 1
                        raise ConnectionError('DELIBERATE_LOCAL_TOOL_FAULT')
                    return await original_search(request)
                runtime.engine.search = fail_once
            task_id = runtime.store.create('research',{'question':question},session_id=session_id)
            started = time.perf_counter()
            try:
                await runtime.runner.execute(task_id)
                task = runtime.store.get(task_id)
                events = runtime.store.events(task_id)
                checkpoint = await runtime.runner.checkpointer.aget_tuple({'configurable':{'thread_id':task_id}})
                state = checkpoint.checkpoint.get('channel_values', {}) if checkpoint else {}
                messages = state.get('messages', [])
                # Only audit the current turn; the previous turn is persisted in session history.
                last_user = max((i for i,m in enumerate(messages) if m['role']=='user'),default=0)
                calls, invalid = audit_messages(messages[last_user:])
                citations = (task['result'] or {}).get('citations', [])
                valid_citations = []
                for citation in citations:
                    chunk = runtime.db.chunk(citation['doc_id'],citation['chunk_id'])
                    valid_citations.append(bool(chunk and citation['quote'] in chunk.text and
                        citation['citation_id'] in state.get('evidence', {}) and
                        citation['source'] == chunk.source))
                llm_events = [e['data'] for e in events if e['type']=='llm_completed']
                tool_attempts = [e['data'] for e in events if e['type']=='tool_started']
                tool_completed = [e['data'] for e in events if e['type']=='tool_completed']
                known_versions = sorted({source_by_doc[c['doc_id']] for c in citations if c['doc_id'] in source_by_doc})
                limitations = (task['result'] or {}).get('limitations', [])
                uncertainty_text = ' '.join([(task['result'] or {}).get('conclusion',''),*limitations])
                unknown_acknowledged = any(
                    any(term in sentence for term in ['吞吐','tokens/s','tokens per second']) and
                    any(word in sentence for word in ['无法确认','无法确定','未提供','未给出','缺乏','不能确认'])
                    for sentence in re.split(r'[。；\n]',uncertainty_text))
                usage_total = sum(e['usage'] for e in llm_events if isinstance(e.get('usage'),int))
                budget_consistent = (task['budget']['llm_calls'] == sum(e['type']=='llm_started' for e in events)
                    and task['budget']['tool_calls'] == len(tool_attempts)
                    and task['budget']['tokens'] == usage_total
                    and not task['budget']['estimated'])
                workflow_ok = {'knowledge_search','compare_evidence','build_report'} <= {c['name'] for c in calls}
                coverage_ok = len(known_versions) == 3 if index == 0 else (
                    bool(citations) or index == 1 and bool((task['result'] or {}).get('insufficient_evidence')))
                row.update(task_id=task_id,status=task['status'],error=task['error'],budget=task['budget'],
                    limits=task['limits_json'],report=task['result'],events=events,tool_calls=calls,
                    invalid_tool_calls=invalid,valid_citations=sum(valid_citations),citations=len(citations),
                    cited_versions=known_versions,unknown_acknowledged=unknown_acknowledged,
                    budget_consistent=budget_consistent,provider_usage_total=usage_total,
                    llm_responses=llm_events,tool_attempts=len(tool_attempts),tool_completed=len(tool_completed),
                    injected_local_failures=injected,
                    success=task['status']=='succeeded' and all(valid_citations)
                        and not invalid and workflow_ok and coverage_ok and unknown_acknowledged and budget_consistent)
            finally:
                runtime.engine.search = original_search
                row['elapsed_ms'] = (time.perf_counter()-started)*1000
                report['cases'].append(row)
        rows = report['cases']
        responses = [e for r in rows for e in r.get('llm_responses', [])]
        attempts = sum(r.get('tool_attempts',0) for r in rows)
        count = sum(r.get('tool_completed',0) for r in rows)
        report['summary'] = {'tasks':len(rows),'tasks_passed':sum(r['success'] for r in rows),
            'task_success_rate':sum(r['success'] for r in rows)/len(rows) if rows else None,
            'llm_requests':sum(r.get('budget',{}).get('llm_calls',0) for r in rows),
            'llm_successful_responses':len(responses),
            'prompt_tokens':sum(e.get('prompt_tokens') or 0 for e in responses),
            'completion_tokens':sum(e.get('completion_tokens') or 0 for e in responses),
            'total_tokens':sum(e.get('total_tokens') or 0 for e in responses),
            'tool_attempts':attempts,'tools_completed':count,
            'tool_attempt_success_rate':count/attempts if attempts else None,
            'model_function_calls':sum(len(r.get('tool_calls',[]))+len(r.get('invalid_tool_calls',[])) for r in rows),
            'invalid_model_function_calls':sum(len(r.get('invalid_tool_calls',[])) for r in rows),
            'citations':sum(r.get('citations',0) for r in rows),
            'valid_citations':sum(r.get('valid_citations',0) for r in rows),
            'api_p50_ms':float(np.percentile([e['elapsed_ms'] for e in responses],50)) if responses else None,
            'api_p95_ms':float(np.percentile([e['elapsed_ms'] for e in responses],95)) if responses else None,
            'task_p50_ms':float(np.percentile([r['elapsed_ms'] for r in rows],50)) if rows else None,
            'task_p95_ms':float(np.percentile([r['elapsed_ms'] for r in rows],95)) if rows else None}
        report['passed'] = bool(rows) and all(r['success'] for r in rows)
    finally:
        await runtime.close()
        # Defense in depth; the secret is never part of prompts, source docs or report schema.
        serialized = json.dumps(report,ensure_ascii=False,indent=2).replace(secret,'[REDACTED]')
        (REPORTS/'deepseek-integration.json').write_text(serialized,encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--refresh-docs',action='store_true')
    parser.add_argument('--cases',type=int,choices=[1,2,3],default=3)
    parser.add_argument('--data-dir',type=Path,default=ROOT/'data'/'deepseek_validation'/'index',
                        help='Persistent validation index, checkpoints and task evidence; existing data retained')
    args = parser.parse_args()
    result = asyncio.run(run_validation(args.data_dir,refresh_docs=args.refresh_docs,cases=args.cases))
    print(json.dumps({'passed':result.get('passed'),'summary':result.get('summary'),
        'cases':[{'name':r['name'],'success':r['success'],'error':r.get('error')} for r in result['cases']]},
        ensure_ascii=False,indent=2))
    if not result.get('passed'):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
