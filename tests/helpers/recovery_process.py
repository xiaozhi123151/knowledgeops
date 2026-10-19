"""Subprocess fixture: the parent forcibly terminates this process during a graph node."""
import asyncio
import sys
from pathlib import Path

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from knowledgeops.config import Settings
from knowledgeops.harness.checkpoints import JSONOnlySerializer
from knowledgeops.ingestion.service import IngestionService
from knowledgeops.providers.embedding import HashEmbedding
from knowledgeops.providers.llm import FakeLLM
from knowledgeops.providers.reranker import FakeReranker
from knowledgeops.retrieval.engine import RetrievalEngine
from knowledgeops.storage.db import Database
from knowledgeops.storage.tasks import TaskStore
from knowledgeops.worker.runner import TaskRunner


async def main():
    root, mode = Path(sys.argv[1]), sys.argv[2]
    settings = Settings(_env_file=None, mode='offline', llm_provider='mock', data_dir=root,
                        lease_seconds=1, token_budget=100000)
    db = Database(root)
    store = TaskStore(db, settings)
    engine = RetrievalEngine(settings, db, HashEmbedding(), FakeReranker())
    await engine.initialize()
    ingest = IngestionService(settings, db, engine)
    class PauseAfterSearch(FakeLLM):
        async def complete(self, messages, tools=None, max_tokens=2000):
            if any(m.get('name') == 'knowledge_search' for m in messages):
                (root / 'crash-ready').write_text('ready')
                await asyncio.sleep(120)
            return await super().complete(messages, tools, max_tokens)
    async with aiosqlite.connect(root / 'checkpoints.sqlite') as conn:
        saver = AsyncSqliteSaver(conn, serde=JSONOnlySerializer())
        llm = PauseAfterSearch() if mode == 'crash' else FakeLLM()
        runner = TaskRunner(settings, store, engine, ingest, llm, saver)
        if mode == 'crash':
            await ingest.ingest(ingest.save_upload(b'Redis AOF preserves write operations.', 'recovery.txt'))
            task_id = store.create('research', {'question': 'Redis AOF'}, session_id='resume-test')
            (root / 'task-id').write_text(task_id)
        else:
            task_id = (root / 'task-id').read_text()
        await runner.execute(task_id)
    engine.close()


if __name__ == '__main__':
    asyncio.run(main())
