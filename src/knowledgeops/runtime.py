import asyncio
from contextlib import AsyncExitStack

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from knowledgeops.harness.checkpoints import JSONOnlySerializer
from knowledgeops.harness.trace import Trace
from knowledgeops.ingestion.service import IngestionService
from knowledgeops.providers.embedding import APIEmbedding, HashEmbedding
from knowledgeops.providers.llm import make_llm
from knowledgeops.providers.local_embedding import LocalEmbedding
from knowledgeops.providers.reranker import FakeReranker, IsolatedCrossEncoder
from knowledgeops.retrieval.engine import RetrievalEngine
from knowledgeops.storage.db import Database
from knowledgeops.storage.tasks import TaskStore
from knowledgeops.worker.queue import RedisQueue, stop_worker, worker_loop
from knowledgeops.worker.runner import TaskRunner


class Runtime:
    def __init__(self, settings):
        self.settings = settings
        self.stack = AsyncExitStack()
        self.worker = None
        self.queue = None
        self.engine = None
        self.embedding = self.llm = self.reranker = self.trace = None

    async def start(self, background_worker=False):
        try:
            self.db = Database(self.settings.data_dir)
            self.store = TaskStore(self.db, self.settings)
            live = self.settings.mode == 'live'
            self.embedding = {'api': APIEmbedding, 'local': LocalEmbedding, 'mock': lambda _: HashEmbedding()}[
                self.settings.resolved_embedding_provider](self.settings)
            self.llm = make_llm(self.settings)
            self.reranker = (IsolatedCrossEncoder(self.settings)
                             if self.settings.resolved_reranker_provider == 'cross_encoder' else FakeReranker())
            if isinstance(self.embedding, LocalEmbedding):
                await self.embedding.warmup()
            self.engine = RetrievalEngine(self.settings, self.db, self.embedding, self.reranker)
            await self.engine.initialize()
            if isinstance(self.reranker, IsolatedCrossEncoder):
                # Startup readiness does not advertise a missing/unloadable CrossEncoder as ready.
                await self.reranker.warmup()
            if live:
                self.queue = RedisQueue(self.settings)
                await self.queue.initialize()
            self.ingestion = IngestionService(self.settings, self.db, self.engine)
            conn = await self.stack.enter_async_context(aiosqlite.connect(self.settings.data_dir / 'checkpoints.sqlite'))
            await conn.execute('PRAGMA journal_mode=WAL')
            await conn.execute('PRAGMA busy_timeout=20000')
            saver = AsyncSqliteSaver(conn, serde=JSONOnlySerializer())
            self.trace = Trace(self.settings)
            self.runner = TaskRunner(self.settings, self.store, self.engine, self.ingestion, self.llm, saver)
            self.runner.trace = self.trace
            if background_worker:
                self.worker = asyncio.create_task(worker_loop(self), name='knowledgeops-worker')
            return self
        except BaseException:
            await self.close()
            raise

    async def notify(self, task_id):
        if self.queue:
            try:
                await self.queue.enqueue(task_id)
            except Exception:
                self.store.event(task_id, 'queue_deferred', {'reason': 'Redis notification failed; ledger reconciliation will retry'})

    async def close(self):
        await stop_worker(self.worker)
        if self.queue:
            await self.queue.close()
        if self.trace:
            await self.trace.close()
        if self.reranker:
            self.reranker.close()
        if self.engine:
            self.engine.close()
        for provider in (self.embedding, self.llm):
            if provider:
                await provider.close()
        await self.stack.aclose()
