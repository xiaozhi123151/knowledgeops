import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from knowledgeops.harness.checkpoints import JSONOnlySerializer
from knowledgeops.providers.llm import FakeLLM
from knowledgeops.storage.tasks import TaskStore
from knowledgeops.worker.runner import TaskRunner


async def test_durable_agent_and_session(stack):
    settings, db, engine, ingest = stack
    await ingest.ingest(ingest.save_upload(b'Redis AOF records writes. RDB snapshots persist data.', 'redis.txt'))
    store = TaskStore(db, settings)
    task_id = store.create('research', {'question': 'Redis AOF'}, session_id='conversation')
    async with aiosqlite.connect(settings.data_dir / 'checkpoints.sqlite') as conn:
        saver = AsyncSqliteSaver(conn, serde=JSONOnlySerializer())
        runner = TaskRunner(settings, store, engine, ingest, FakeLLM(), saver)
        await runner.execute(task_id)
        result = store.get(task_id)
        assert result['status'] == 'succeeded', result['error']
        assert result['result']['citations']
        assert result['budget']['llm_calls'] == 4
        assert result['budget']['estimated']
        assert len(store.history('conversation')) == 2
        assert not await runner.execute(task_id)
        assert len(store.history('conversation')) == 2


async def test_repeated_agent_calls_hit_step_cap(stack):
    from knowledgeops.providers.llm import call
    class LoopLLM(FakeLLM):
        async def complete(self,*args):
            return call('knowledge_search',{'query':'Redis'}), None
    settings, db, engine, ingest = stack
    settings = settings.model_copy(update={'max_steps':4})
    store = TaskStore(db,settings)
    task_id = store.create('research',{'question':'Loop forever'})
    async with aiosqlite.connect(settings.data_dir/'checkpoints.sqlite') as conn:
        runner = TaskRunner(settings,store,engine,ingest,LoopLLM(),
                            AsyncSqliteSaver(conn,serde=JSONOnlySerializer()))
        await runner.execute(task_id)
    result = store.get(task_id)
    assert result['status'] == 'failed' and 'steps' in result['error']
    assert result['budget']['tool_calls'] == 1  # Duplicate reads reuse the cached result.
    assert any(e['type']=='tool_cache_hit' for e in store.events(task_id))
