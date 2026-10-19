import pytest

from knowledgeops.config import Settings
from knowledgeops.ingestion.service import IngestionService
from knowledgeops.providers.embedding import HashEmbedding
from knowledgeops.providers.reranker import FakeReranker
from knowledgeops.retrieval.engine import RetrievalEngine
from knowledgeops.storage.db import Database


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, data_dir=tmp_path, mode='offline', llm_provider='mock')


@pytest.fixture
async def stack(settings):
    db = Database(settings.data_dir)
    engine = RetrievalEngine(settings, db, HashEmbedding(), FakeReranker())
    await engine.initialize()
    ingestion = IngestionService(settings, db, engine)
    yield settings, db, engine, ingestion
    engine.close()
