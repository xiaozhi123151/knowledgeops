import asyncio
import contextlib
import uuid

from knowledgeops.agent.graph import ResearchAgent
from knowledgeops.harness.executor import DurableHarness
from knowledgeops.storage.tasks import BudgetExceeded, LeaseLost


def safe_error(exc):
    if isinstance(exc, (ValueError, BudgetExceeded, LeaseLost)):
        return str(exc)[:500]
    return type(exc).__name__ + ': task failed; inspect structured task events'


class TaskRunner:
    def __init__(self, settings, store, engine, ingestion, llm, checkpointer):
        self.settings, self.store, self.engine = settings, store, engine
        self.ingestion, self.llm, self.checkpointer = ingestion, llm, checkpointer
        self.owner = uuid.uuid4().hex
        self.trace = None

    async def _heartbeat(self, task_id):
        while True:
            await asyncio.sleep(self.settings.lease_seconds / 3)
            self.store.heartbeat(task_id, self.owner)
            self.store.worker_heartbeat()

    async def execute(self, task_id):
        if not self.store.claim(task_id, self.owner):
            return False
        task = self.store.get(task_id)
        heartbeat = asyncio.create_task(self._heartbeat(task_id))
        work = asyncio.create_task(self._work(task))
        try:
            done, _ = await asyncio.wait([heartbeat, work], return_when=asyncio.FIRST_COMPLETED)
            if heartbeat in done:
                heartbeat.result()
            result = await work
            if task['kind'] == 'research':
                self.store.complete_research(task_id, self.owner, task['session_id'],
                                             task['payload']['question'], result)
            else:
                self.store.finish(task_id, self.owner, result=result)
        except asyncio.CancelledError:
            with contextlib.suppress(LeaseLost):
                self.store.finish(task_id, self.owner, error='WORKER_INTERRUPTED', interrupted=True)
            raise
        except LeaseLost:
            return False
        except Exception as exc:
            with contextlib.suppress(LeaseLost):
                self.store.finish(task_id, self.owner, error=safe_error(exc))
        finally:
            for future in (work, heartbeat):
                if not future.done():
                    future.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await future
        return True

    async def _work(self, task):
        import time
        remaining = task['deadline'] - time.time()
        if remaining <= 0:
            raise BudgetExceeded('TASK_DEADLINE_EXCEEDED')
        async with asyncio.timeout(remaining):
            if task['kind'] == 'ingest':
                return await self.ingestion.ingest(task['payload'])
            if task['kind'] != 'research':
                raise ValueError('UNKNOWN_TASK_KIND')
            executor = DurableHarness(self.settings, self.store, task['task_id'], self.owner, self.llm)
            executor.trace = self.trace
            agent = ResearchAgent(self.engine, executor, self.checkpointer)
            result = await agent.run(task['payload']['question'], task['task_id'],
                                     history=self.store.history(task['session_id']), resume=True)
            if not result.get('report'):
                raise ValueError('REPORT_MISSING')
            return result['report']
