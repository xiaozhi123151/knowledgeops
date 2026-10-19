import json

import pytest

from knowledgeops.agent.graph import DirectExecutor, ResearchAgent
from knowledgeops.providers.llm import FakeLLM, call


async def test_agent_tools_citations_and_multiturn(stack):
    _, db, engine, ingest = stack
    await ingest.ingest(ingest.save_upload(b'Redis AOF logs every write. RDB takes snapshots.', 'redis.md'))
    agent = ResearchAgent(engine, DirectExecutor(FakeLLM()))
    state = await agent.run('Redis persistence AOF', 'task1')
    assert state['report']['citations'] and state['compared']
    citation = state['report']['citations'][0]
    assert citation['quote'] in db.chunk(citation['doc_id'], citation['chunk_id']).text
    names = [c['function']['name'] for m in state['messages'] for c in m.get('tool_calls', [])]
    assert names == ['knowledge_search', 'compare_evidence', 'build_report']
    history = [m for m in state['messages'][1:] if m['role'] == 'user'] + [
        {'role': 'assistant', 'content': json.dumps(state['report'])}]
    next_state = await agent.run('What about Redis RDB?', 'task2', history)
    assert next_state['report']['citations']
    assert len([m for m in next_state['messages'] if m['role'] == 'user']) == 2


async def test_empty_retrieval(stack):
    _, _, engine, _ = stack
    result = await ResearchAgent(engine, DirectExecutor(FakeLLM())).run('Unknown subject', 'empty')
    assert result['report']['insufficient_evidence']
    assert not result['report']['citations']


class BadCitationLLM(FakeLLM):
    async def complete(self, messages, tools=None, max_tokens=2000):
        message, usage = await super().complete(messages, tools, max_tokens)
        for c in message.get('tool_calls', []):
            if c['function']['name'] == 'build_report':
                args = json.loads(c['function']['arguments'])
                args['findings'] = [{'text': 'Invented finding', 'citation_ids': ['E-fabricated']}]
                args['quotes'] = {'E-fabricated': 'fake quote'}
                args['insufficient_evidence'] = False
                c['function']['arguments'] = json.dumps(args)
        return message, usage


async def test_wrong_citation_rejected_after_one_repair(stack):
    _, _, engine, ingest = stack
    await ingest.ingest(ingest.save_upload(b'Redis AOF persistence', 'a.txt'))
    with pytest.raises(ValueError, match='AFTER_REPAIR'):
        await ResearchAgent(engine, DirectExecutor(BadCitationLLM())).run('Redis', 'bad')


async def test_arbitrary_tool_is_rejected(stack):
    class UnsafeLLM(FakeLLM):
        async def complete(self, *args, **kwargs):
            return call('shell', {'command': 'whoami'}), None
    _, _, engine, _ = stack
    with pytest.raises(ValueError, match='TOOL_NOT_ALLOWED'):
        await ResearchAgent(engine, DirectExecutor(UnsafeLLM())).run('Anything', 'unsafe')


async def test_comparison_rejects_nested_chunk_ids_instead_of_server_citation_ids(stack):
    class ChunkIDComparison(FakeLLM):
        async def complete(self, messages, tools=None, max_tokens=2000):
            message, usage = await super().complete(messages, tools, max_tokens)
            if not tools:
                assert 'Preserve the E- prefix' in messages[0]['content']
                payload = json.loads(messages[-1]['content'])
                result = json.loads(message['content'])
                for finding in result['agreements']:
                    finding['citation_ids'] = [payload[cid]['chunk_id'] for cid in finding['citation_ids']]
                message['content'] = json.dumps(result)
            return message, usage
    _, _, engine, ingestion = stack
    await ingestion.ingest(ingestion.save_upload(b'Redis AOF persistence', 'comparison.txt'))
    with pytest.raises(ValueError, match='AFTER_REPAIR'):
        await ResearchAgent(engine, DirectExecutor(ChunkIDComparison())).run('Redis', 'comparison-invalid')


async def test_report_requires_generated_quotes_and_rejects_queries_alias(stack):
    from knowledgeops.agent.tools import tool_definitions

    schema = next(t['function']['parameters'] for t in tool_definitions()
                  if t['function']['name'] == 'build_report')
    assert 'quotes' in schema['required'] and schema['additionalProperties'] is False

    class WrongField(FakeLLM):
        async def complete(self, messages, tools=None, max_tokens=2000):
            message, usage = await super().complete(messages, tools, max_tokens)
            for c in message.get('tool_calls', []):
                if c['function']['name'] == 'build_report':
                    args = json.loads(c['function']['arguments'])
                    args['queries'] = args.pop('quotes')
                    c['function']['arguments'] = json.dumps(args)
            return message, usage

    _, _, engine, ingestion = stack
    await ingestion.ingest(ingestion.save_upload(b'Redis AOF persistence', 'field-name.txt'))
    with pytest.raises(ValueError, match='AFTER_REPAIR'):
        await ResearchAgent(engine, DirectExecutor(WrongField())).run('Redis', 'field-name-invalid')


async def test_quote_key_error_is_actionable_and_repaired_once(stack):
    class LabelInsteadOfID(FakeLLM):
        broken = False
        async def complete(self,messages,tools=None,max_tokens=2000):
            message,usage = await super().complete(messages,tools,max_tokens)
            for c in message.get('tool_calls',[]):
                if c['function']['name']=='build_report' and not self.broken:
                    args = json.loads(c['function']['arguments'])
                    args['quotes'] = {'invented_metric_label':next(iter(args['quotes'].values()))}
                    c['function']['arguments'] = json.dumps(args)
                    self.broken = True
            return message,usage
    _,_,engine,ingest = stack
    await ingest.ingest(ingest.save_upload(b'Redis AOF logs writes.','quote.txt'))
    result = await ResearchAgent(engine,DirectExecutor(LabelInsteadOfID())).run('Redis AOF','repair')
    assert result['repairs']==1 and result['report']['citations']
    errors = [json.loads(m['content']) for m in result['messages'] if m.get('name')=='build_report']
    assert 'missing_quote_ids' in errors[0]['error'] and 'invented_metric_label' in errors[0]['error']


async def test_partial_uncertainty_keeps_supported_citations(stack):
    class PartialUnknown(FakeLLM):
        broken = False
        async def complete(self,messages,tools=None,max_tokens=2000):
            message,usage = await super().complete(messages,tools,max_tokens)
            for c in message.get('tool_calls',[]):
                if c['function']['name']=='build_report' and not self.broken:
                    args = json.loads(c['function']['arguments'])
                    args['insufficient_evidence'] = True
                    c['function']['arguments'] = json.dumps(args)
                    self.broken = True
            return message,usage
    _,_,engine,ingest = stack
    await ingest.ingest(ingest.save_upload(b'Redis AOF writes commands; exact throughput not provided.','known.txt'))
    result = await ResearchAgent(engine,DirectExecutor(PartialUnknown())).run('Redis AOF','partial')
    assert result['repairs']==1 and not result['report']['insufficient_evidence']
    assert result['report']['citations']
    errors = [json.loads(m['content']) for m in result['messages'] if m.get('name')=='build_report']
    assert 'mixed known/unknown' in errors[0]['error']
