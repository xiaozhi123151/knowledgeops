import io
from unittest.mock import patch

import pytest
from reportlab.pdfgen import canvas

from knowledgeops.ingestion.extract import extract, make_chunks
from knowledgeops.ingestion.web import PinnedHTTP, fetch_page, resolve_public
from knowledgeops.providers.embedding import tokenize
from knowledgeops.retrieval.engine import rrf
from knowledgeops.schemas import Query


def pdf_bytes():
    out = io.BytesIO()
    doc = canvas.Canvas(out)
    doc.drawString(40, 700, 'Redis persistence uses AOF and RDB snapshots.')
    doc.showPage()
    doc.drawString(40, 700, 'Qdrant stores vector embeddings for dense retrieval.')
    doc.save()
    return out.getvalue()


def test_extract_and_chunk():
    segments = extract(pdf_bytes(), '.pdf')
    doc_id, chunks = make_chunks(segments, 'sample.pdf', 'Sample')
    assert [c.page for c in chunks] == [1, 2]
    assert chunks[1].start == len(segments[0].text) + 2
    assert make_chunks(segments, 'alias.pdf', 'Other')[0] == doc_id
    assert make_chunks(segments, 'sample.pdf', 'Sample')[1] == chunks
    assert extract(b'# Header\n\nSome words', '.md')[0].section == 'Header'
    assert '混合' in tokenize('混合检索提升召回')
    assert extract(b'<main>Evidence<script>bad()</script></main>', '.html')[0].text == 'Evidence'
    with pytest.raises(ValueError, match='EMPTY'):
        extract(b'  ', '.txt')
    with pytest.raises(ValueError, match='PDF_PAGE_LIMIT'):
        extract(pdf_bytes(), '.pdf', max_pages=1)


def test_rrf():
    _, chunks = make_chunks(extract(b'a b c d e', '.txt'), 'a.txt', 'a')
    h = rrf([(chunks[0], .8)], [(chunks[0], 2.5)])[0]
    assert h.rrf_score == pytest.approx(2 / 61)
    assert h.dense_score == .8 and h.bm25_score == 2.5


async def test_ingest_query_dedup_refresh(stack):
    _, db, engine, ingest = stack
    a = await ingest.ingest(ingest.save_upload(pdf_bytes(), 'sample.pdf'))
    duplicate = await ingest.ingest(ingest.save_upload(pdf_bytes(), 'alias.pdf'))
    assert a['doc_id'] == duplicate['doc_id'] and duplicate['duplicate']
    for mode in ('dense', 'bm25', 'hybrid'):
        result = await engine.search(Query(query='Redis AOF', mode=mode, rerank=True))
        assert result.hits and result.hits[0].chunk.page == 1
        assert result.hits[0].rerank_score is not None
    old_version = engine.version
    await ingest.ingest(ingest.save_upload('中文知识库支持混合检索和证据引用'.encode(), 'cn.txt'))
    result = await engine.search(Query(query='知识库 引用'))
    assert result.index_version > old_version
    assert any('中文' in h.chunk.text for h in result.hits)
    assert len(db.documents()[0]['sources']) == 2


async def test_failed_index_is_invisible_and_retryable(stack):
    _, db, engine, ingest = stack
    payload = ingest.save_upload(b'Embeddings semantic vector search', 'test.md')
    original = engine.upsert
    async def fail(chunks):
        await original(chunks)
        raise ConnectionError('injected failure after vector upsert')
    engine.upsert = fail
    with pytest.raises(ConnectionError):
        await ingest.ingest(payload)
    assert db.snapshot()[1] == []
    assert not (await engine.search(Query(query='vector'))).hits
    engine.upsert = original
    await ingest.ingest(payload)
    assert len(db.snapshot()[1]) == 1
    assert (await engine.search(Query(query='vector'))).hits


def test_upload_and_ssrf(stack=None):
    with patch('socket.getaddrinfo', return_value=[(2, 1, 6, '', ('127.0.0.1', 80))]):
        with pytest.raises(ValueError, match='URL_BLOCKED'):
            resolve_public('example.com', 80)
    with pytest.raises(ValueError):
        fetch_page('file:///etc/passwd')
    with patch('socket.create_connection') as connect:
        client = PinnedHTTP('example.com', 80, '93.184.216.34', 2)
        client.connect()
        connect.assert_called_once_with(('93.184.216.34', 80), 2)


async def test_filename_and_chunk_overlap(stack):
    _, _, _, ingest = stack
    with pytest.raises(ValueError, match='INVALID_FILENAME'):
        ingest.save_upload(b'x', '../x.txt')
    text = 'Alpha paragraph.\n\n' * 150
    _, chunks = make_chunks(extract(text.encode(), '.txt'), 'long.txt', 'long', 200, 20)
    assert len(chunks) > 2
    for c in chunks:
        assert c.text == text.strip()[c.start:c.end]
        assert len(c.text) <= 200


async def test_dense_preserves_negative_cosine_scores(stack):
    from qdrant_client import models
    _, _, engine, ingest = stack
    doc = await ingest.ingest(ingest.save_upload(b'Opposite direction fixture', 'opposite.txt'))
    chunk = engine.db.snapshot()[1][0]
    query_vector = (await engine.embedding.embed(['Redis']))[0]
    engine.client.upsert(engine.collection, points=[models.PointStruct(id=chunk.chunk_id,
        vector=[-v for v in query_vector], payload={'doc_id':doc['doc_id']})], wait=True)
    result = await engine.search(Query(query='Redis',mode='dense',rerank=False))
    assert len(result.hits) == 1
    assert result.hits[0].dense_score == pytest.approx(-1.0)
