import asyncio

import pytest

from knowledgeops.harness.checkpoints import JSONOnlySerializer
from knowledgeops.harness.executor import DurableHarness
from knowledgeops.providers.llm import FakeLLM
from knowledgeops.storage.tasks import BudgetExceeded, LeaseLost, TaskStore


def harness(stack, **overrides):
    settings, db, _, _ = stack
    settings = settings.model_copy(update=overrides)
    store = TaskStore(db, settings)
    task = store.create('research', {'question': 'Redis'})
    assert store.claim(task, 'owner')
    return DurableHarness(settings, store, task, 'owner', FakeLLM()), store, task


async def test_tool_cache_and_allowlist(stack):
    executor, store, task = harness(stack)
    calls = 0
    async def fn(parsed):
        nonlocal calls
        calls += 1
        return {'hits': []}
    args = {'query': 'Redis'}
    await executor.tool('knowledge_search', args, fn)
    await executor.tool('knowledge_search', args, fn)
    assert calls == 1 and store.get(task)['budget']['tool_calls'] == 1
    with pytest.raises(ValueError, match='TOOL_NOT_ALLOWED'):
        await executor.tool('shell', {}, fn)


async def test_tool_timeout_and_finite_retries(stack):
    executor, store, task = harness(stack, tool_timeout=.01)
    async def slow(parsed):
        await asyncio.sleep(.5)
        return {}
    with pytest.raises(TimeoutError):
        await executor.tool('knowledge_search', {'query': 'x'}, slow)
    assert store.get(task)['budget']['tool_calls'] == 3
    assert sum(e['type'] == 'tool_error' for e in store.events(task)) == 3


async def test_validation_not_retried(stack):
    executor, store, task = harness(stack)
    async def wrong(parsed):
        raise ValueError('invalid output')
    with pytest.raises(ValueError):
        await executor.tool('knowledge_search', {'query': 'x'}, wrong)
    assert store.get(task)['budget']['tool_calls'] == 1


async def test_budget_and_limit_escalation(stack):
    executor, store, task = harness(stack, max_steps=1)
    await executor.step()
    with pytest.raises(BudgetExceeded, match='steps'):
        await executor.step()
    with pytest.raises(ValueError, match='LOWERED'):
        store.create('research', {}, overrides={'max_steps': 2})
    store.reserve(task, 'owner', tokens=19999)
    with pytest.raises(BudgetExceeded, match='tokens'):
        store.reserve(task, 'owner', tokens=2)


async def test_duplicate_claim_session_order_and_fencing(stack):
    settings, db, _, _ = stack
    store = TaskStore(db, settings)
    a = store.create('research', {}, session_id='s')
    b = store.create('research', {}, session_id='s')
    assert not store.claim(b, 'second')
    assert store.claim(a, 'first')
    assert not store.claim(a, 'second')
    with pytest.raises(LeaseLost):
        store.reserve(a, 'second', 'steps')
    store.finish(a, 'first', result={})
    assert store.claim(b, 'second')


def test_serializer_no_pickle():
    serde = JSONOnlySerializer()
    assert serde.loads_typed(serde.dumps_typed({'text': '证据'})) == {'text': '证据'}
    with pytest.raises(ValueError, match='UNSAFE'):
        serde.loads_typed(('pickle', b'payload'))


async def test_llm_cache_usage_and_call_limit(stack):
    executor, store, task = harness(stack, max_llm_calls=1)
    class CountedLLM(FakeLLM):
        async def complete(self, *args):
            message, _ = await super().complete(*args)
            return message, 123
    executor.provider = CountedLLM()
    messages = [{'role': 'user', 'content': 'Redis'}]
    from knowledgeops.agent.tools import tool_definitions
    await executor.llm(messages, tool_definitions())
    await executor.llm(messages, tool_definitions())
    budget = store.get(task)['budget']
    assert budget['tokens'] == 123 and not budget['estimated'] and budget['llm_calls'] == 1
    with pytest.raises(BudgetExceeded, match='llm_calls'):
        await executor.llm([{'role': 'user', 'content': 'Different question'}], tool_definitions())


async def test_interruption_retains_reservation(stack):
    executor, store, task = harness(stack)
    store.reserve(task, 'owner', 'llm_calls', tokens=123)
    store.finish(task, 'owner', error='interrupted', interrupted=True)
    store.resume(task)
    assert store.claim(task, 'new-owner')
    budget = store.get(task)['budget']
    assert budget['tokens'] == 123 and budget['estimated'] and budget['llm_calls'] == 1


async def test_llm_timeouts_are_bounded_and_charged(stack):
    executor, store, task = harness(stack, tool_timeout=.01)
    class SlowLLM(FakeLLM):
        async def complete(self,*args):
            await asyncio.sleep(.2)
    executor.provider = SlowLLM()
    with pytest.raises(TimeoutError):
        await executor.llm([{'role':'user','content':'question'}])
    budget = store.get(task)['budget']
    assert budget['llm_calls'] == 3 and budget['tokens'] > 0 and budget['estimated']


async def test_tool_failures_exhaust_retry_limit(stack):
    executor, store, task = harness(stack)
    async def failing(parsed):
        raise ConnectionError('injected tool outage')
    with pytest.raises(ConnectionError):
        await executor.tool('knowledge_search',{'query':'x'},failing)
    assert store.get(task)['budget']['tool_calls'] == 3
