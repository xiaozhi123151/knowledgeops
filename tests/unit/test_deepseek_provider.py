"""SYNTHETIC HTTP fault injection, never reported as real DeepSeek server behavior."""
import asyncio
import json

import httpx
import pytest
from openai import APIStatusError, AsyncOpenAI
from pydantic import SecretStr

from knowledgeops.agent.graph import ResearchAgent
from knowledgeops.agent.tools import tool_definitions
from knowledgeops.config import Settings
from knowledgeops.harness.executor import DurableHarness
from knowledgeops.providers.llm import DeepSeekLLM, FakeLLM, make_llm
from knowledgeops.storage.tasks import BudgetExceeded, TaskStore

DUMMY = 'transport-test-secret-not-a-real-key'


def response_body(tool=True):
    message = {'role':'assistant','content':'{"agreements":[],"conflicts":[],"limitations":[]}'}
    if tool:
        message = {'role':'assistant','content':None,'tool_calls':[{'id':'call_fixture','type':'function',
            'function':{'name':'knowledge_search','arguments':'{"query":"DeepSeek-V2"}'}}]}
    return {'id':'synthetic-response','object':'chat.completion','created':0,'model':'deepseek-flash',
        'choices':[{'index':0,'finish_reason':'tool_calls' if tool else 'stop','message':message}],
        'usage':{'prompt_tokens':100,'completion_tokens':20,'total_tokens':120,'prompt_cache_hit_tokens':30}}


async def setup_harness(settings, db, handler, **overrides):
    settings = settings.model_copy(update={'deepseek_api_key':SecretStr(DUMMY),**overrides})
    provider = DeepSeekLLM(settings)
    await provider.client.close()
    provider.client = AsyncOpenAI(api_key=DUMMY,base_url='https://api.deepseek.com',max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    store = TaskStore(db,settings)
    task_id = store.create('research',{'question':'Synthetic transport test'})
    store.claim(task_id,'test-owner')
    executor = DurableHarness(settings,store,task_id,'test-owner',provider)
    return executor,store,task_id,provider


async def test_non_thinking_tools_usage_and_roundtrip(stack):
    settings,db,_,_ = stack
    requests = []
    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        assert request.url.host=='api.deepseek.com' and request.url.path=='/chat/completions'
        assert body['model']=='deepseek-flash' and body['thinking']=={'type':'disabled'}
        assert body['temperature'] == 0
        if not body.get('tools'):
            assert body['response_format'] == {'type':'json_object'}
        assert 'parallel_tool_calls' not in body
        return httpx.Response(200,json=response_body(tool=bool(body.get('tools'))))
    executor,store,task,provider = await setup_harness(settings,db,handler)
    try:
        messages = [{'role':'user','content':'查找版本'}]
        message = await executor.llm(messages,tool_definitions())
        assert json.loads(message['tool_calls'][0]['function']['arguments'])['query']=='DeepSeek-V2'
        result = {'role':'tool','name':'knowledge_search','tool_call_id':'call_fixture','content':'{"evidence":{}}'}
        await executor.llm([*messages,message,result],tool_definitions())
        assert 'name' not in requests[1]['messages'][-1]
        assert requests[1]['messages'][-1]['tool_call_id']=='call_fixture'
        await executor.llm([{'role':'user','content':'Return JSON comparison'}])
        budget = store.get(task)['budget']
        assert budget['llm_calls']==3 and budget['tokens']==360 and not budget['estimated']
        complete = [e for e in store.events(task) if e['type']=='llm_completed']
        assert complete[0]['data']['prompt_tokens']==100 and complete[0]['data']['cached_tokens']==30
        assert provider.client.max_retries==0
        assert DUMMY not in json.dumps(store.events(task))
    finally:
        await provider.close()


async def test_configurable_deepseek_temperature(settings):
    cfg = settings.model_copy(update={'deepseek_api_key': SecretStr(DUMMY), 'deepseek_temperature': 0.2})
    provider = DeepSeekLLM(cfg)
    try:
        assert provider.request_options(tool_definitions())['temperature'] == 0.2
        assert 'response_format' not in provider.request_options(tool_definitions())
    finally:
        await provider.close()


@pytest.mark.parametrize('status',[429,500,503])
async def test_retryable_http_statuses_charge_every_attempt(stack,status,caplog):
    settings,db,_,_ = stack
    attempts = 0
    def handler(request):
        nonlocal attempts
        attempts += 1
        if attempts==1:
            return httpx.Response(status,json={'error':{'message':DUMMY,'type':'injected'}})
        return httpx.Response(200,json=response_body())
    executor,store,task,provider = await setup_harness(settings,db,handler)
    try:
        await executor.llm([{'role':'user','content':'tool call'}],tool_definitions())
        assert attempts==2 and store.get(task)['budget']['llm_calls']==2
        budget = store.get(task)['budget']
        assert budget['tokens']>120 and budget['estimated'] and budget['pending_estimates']==1
        errors = [e['data'] for e in store.events(task) if e['type']=='llm_error']
        assert errors[0]['status_code']==status
        assert DUMMY not in json.dumps(store.events(task)) and DUMMY not in caplog.text
    finally:
        await provider.close()


@pytest.mark.parametrize('status',[400,401,403,422])
async def test_client_errors_not_retried(stack,status):
    settings,db,_,_ = stack
    def handler(request):
        return httpx.Response(status,json={'error':{'message':'injected client error','type':'invalid'}})
    executor,store,task,provider = await setup_harness(settings,db,handler)
    try:
        with pytest.raises(APIStatusError):
            await executor.llm([{'role':'user','content':'tool call'}],tool_definitions())
        assert store.get(task)['budget']['llm_calls']==1
    finally:
        await provider.close()


async def test_http_timeout_retries_are_bounded(stack):
    settings,db,_,_ = stack
    def handler(request):
        raise httpx.ReadTimeout('deliberate synthetic timeout',request=request)
    executor,store,task,provider = await setup_harness(settings,db,handler)
    try:
        from openai import APITimeoutError
        with pytest.raises(APITimeoutError):
            await executor.llm([{'role':'user','content':'tool call'}],tool_definitions())
        assert store.get(task)['budget']['llm_calls']==3
        assert len([e for e in store.events(task) if e['type']=='llm_error'])==3
    finally:
        await provider.close()


async def test_harness_deadline_cancels_pending_http(stack):
    settings,db,_,_ = stack
    async def handler(request):
        await asyncio.sleep(.2)
        return httpx.Response(200,json=response_body())
    executor,store,task,provider = await setup_harness(settings,db,handler,llm_timeout=.01)
    try:
        with pytest.raises(TimeoutError):
            await executor.llm([{'role':'user','content':'tool call'}],tool_definitions())
        assert store.get(task)['budget']['llm_calls']==3
    finally:
        await provider.close()


async def test_call_budget_prevents_extra_retry(stack):
    settings,db,_,_ = stack
    def handler(request):
        return httpx.Response(429,json={'error':{'message':'injected throttling'}})
    executor,store,task,provider = await setup_harness(settings,db,handler,max_llm_calls=1)
    try:
        with pytest.raises(BudgetExceeded,match='llm_calls'):
            await executor.llm([{'role':'user','content':'tool call'}],tool_definitions())
        assert store.get(task)['budget']['llm_calls']==1
    finally:
        await provider.close()


def test_provider_selection_and_key_validation(monkeypatch,settings):
    monkeypatch.delenv('DEEPSEEK_API_KEY',raising=False)
    monkeypatch.delenv('KO_DEEPSEEK_API_KEY',raising=False)
    assert isinstance(make_llm(settings),FakeLLM)
    with pytest.raises(ValueError,match='DEEPSEEK_API_KEY'):
        Settings(_env_file=None,llm_provider='deepseek')
    with pytest.raises(ValueError,match='official'):
        Settings(_env_file=None,llm_provider='deepseek',DEEPSEEK_API_KEY=DUMMY,
                 deepseek_base_url='https://not-deepseek.invalid')


async def test_valid_multi_search_batch_uses_harness_bound(stack):
    from knowledgeops.providers.llm import call
    settings,db,engine,_ = stack
    def handler(request):
        body = response_body()
        body['choices'][0]['message']['tool_calls'] = [
            call('knowledge_search',{'query':str(i)})['tool_calls'][0] for i in range(4)]
        return httpx.Response(200,json=body)
    executor,store,task,provider = await setup_harness(settings,db,handler)
    try:
        state = {'messages':[{'role':'user','content':'four searches'}]}
        result = await ResearchAgent(engine,executor).model(state)
        assert len(result['messages'][-1]['tool_calls'])==4
        executor.settings = executor.settings.model_copy(update={'max_tool_calls':2})
        with pytest.raises(ValueError,match='one to 2'):
            await ResearchAgent(engine,executor).model(state)
    finally:
        await provider.close()
