import hashlib
from argparse import Namespace

import pytest

from knowledgeops.config import Settings
from knowledgeops.runtime import Runtime
from knowledgeops.schemas import Query
from scripts.rebuild import rebuild


async def test_explicit_rebuild_retains_originals(tmp_path, monkeypatch):
    source, target = tmp_path/'original', tmp_path/'rebuilt'
    original = await Runtime(Settings(_env_file=None,data_dir=source)).start()
    try:
        result = await original.ingestion.ingest(original.ingestion.save_upload(
            ('Redis persistent evidence. '*100).encode(),'original.txt'))
        original_id = result['doc_id']
        original_count = len(original.db.snapshot()[1])
    finally:
        await original.close()
    before = hashlib.sha256((source/'metadata.sqlite').read_bytes()).hexdigest()
    monkeypatch.setenv('KO_CHUNK_SIZE','200')
    monkeypatch.setenv('KO_CHUNK_OVERLAP','20')
    await rebuild(Namespace(source=source,target=target,mode='offline'))
    newer = await Runtime(Settings(data_dir=target)).start()
    try:
        assert len(newer.db.snapshot()[1]) > original_count
        assert newer.db.documents()[0]['doc_id'] == original_id
        assert (await newer.engine.search(Query(query='Redis persistence'))).hits
        assert (target/'rebuild-manifest.json').exists()
        assert hashlib.sha256((source/'metadata.sqlite').read_bytes()).hexdigest() == before
        assert list((source/'raw').iterdir())
    finally:
        await newer.close()
    with pytest.raises(ValueError,match='empty'):
        await rebuild(Namespace(source=source,target=target,mode='offline'))
