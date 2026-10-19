import asyncio
import hashlib
import math
import time

from qdrant_client import QdrantClient, models
from rank_bm25 import BM25Okapi

from knowledgeops.providers.embedding import tokenize
from knowledgeops.schemas import Hit, SearchResult
from knowledgeops.storage.db import dumps


def rrf(dense, sparse, k=60):
    hits = {}
    for field, rows in [('dense', dense), ('bm25', sparse)]:
        for rank, (chunk, score) in enumerate(rows, 1):
            hit = hits.setdefault(chunk.chunk_id, Hit(chunk=chunk, rrf_score=0.0))
            setattr(hit, field + '_score', float(score))
            setattr(hit, field + '_rank', rank)
            hit.rrf_score += 1 / (k + rank)
    return sorted(hits.values(), key=lambda x: (-x.rrf_score, x.chunk.chunk_id))


class RetrievalEngine:
    collection = 'knowledgeops_v1'

    def __init__(self, settings, db, embedding, reranker):
        self.settings, self.db = settings, db
        self.embedding, self.reranker = embedding, reranker
        self.client = (QdrantClient(path=str(settings.data_dir / 'qdrant'), force_disable_check_same_thread=True)
                       if settings.resolved_qdrant_backend == 'local' else QdrantClient(
                           url=settings.qdrant_url, api_key=settings.qdrant_api_key.get_secret_value() or None,
                           timeout=30))
        self.lock = asyncio.Lock()
        self.version, self.chunks, self.bm25, self.tokens = -1, [], None, []
        config = {
            'embedding': embedding.name, 'dimensions': embedding.dimensions,
            'chunk_size': settings.chunk_size, 'overlap': settings.chunk_overlap,
            'extractor': 'v1', 'tokenizer': 'jieba-v1',
        }
        if hasattr(embedding, 'index_config'):
            config['embedding_config'] = embedding.index_config
        self.fingerprint = hashlib.sha256(dumps(config).encode()).hexdigest()
        # Independent vector spaces cannot share a server collection, even with separate SQLite ledgers.
        self.collection = settings.qdrant_collection + ('_' + self.fingerprint[:24]
            if settings.resolved_qdrant_backend == 'server' else '')

    async def initialize(self):
        with self.db.connect() as c:
            row = c.execute("SELECT value FROM meta WHERE key='fingerprint'").fetchone()
            if row and row[0] != self.fingerprint:
                raise ValueError('INDEX_CONFIG_CHANGED: use an empty data directory and reimport')
            target = dumps({'backend': self.settings.resolved_qdrant_backend, 'collection': self.collection,
                            'url': self.settings.qdrant_url.rstrip('/')
                                   if self.settings.resolved_qdrant_backend == 'server' else 'local'})
            previous = c.execute("SELECT value FROM meta WHERE key='vector_target'").fetchone()
            has_documents = c.execute('SELECT 1 FROM documents LIMIT 1').fetchone()
            if (previous and previous[0] != target) or (not previous and has_documents and
                    self.settings.resolved_qdrant_backend != 'local'):
                raise ValueError('INDEX_TARGET_CHANGED: reimport into a new data directory')
            c.execute("INSERT OR IGNORE INTO meta VALUES('fingerprint',?)", (self.fingerprint,))
            c.execute("INSERT OR IGNORE INTO meta VALUES('vector_target',?)", (target,))
        if not await asyncio.to_thread(self.client.collection_exists, self.collection):
            try:
                await asyncio.to_thread(self.client.create_collection, self.collection,
                                        vectors_config=models.VectorParams(size=self.embedding.dimensions,
                                                                           distance=models.Distance.COSINE))
            except Exception:
                # API and Worker may initialize concurrently. Only suppress a create conflict if
                # the collection now exists; schema compatibility is checked below in either case.
                if not await asyncio.to_thread(self.client.collection_exists, self.collection):
                    raise
        info = await asyncio.to_thread(self.client.get_collection, self.collection)
        if (info.config.params.vectors.size != self.embedding.dimensions or
                info.config.params.vectors.distance != models.Distance.COSINE):
            raise ValueError('VECTOR_SPACE_MISMATCH')

    async def upsert(self, chunks):
        vectors = await self.embedding.embed([c.text for c in chunks])
        if len(vectors) != len(chunks):
            raise ValueError('EMBEDDING_COUNT_MISMATCH')
        for start in range(0, len(chunks), 64):
            points = [models.PointStruct(id=c.chunk_id, vector=v, payload={'doc_id': c.doc_id,
                                                                          'index_fingerprint': self.fingerprint})
                      for c, v in zip(chunks[start:start+64], vectors[start:start+64], strict=True)]
            await asyncio.to_thread(self.client.upsert, self.collection, points=points, wait=True)

    def _refresh(self):
        if self.version != self.db.version():
            self.version, self.chunks = self.db.snapshot()
            tokens = [tokenize(c.text) or ['__empty__'] for c in self.chunks]
            self.tokens = [set(t) for t in tokens]
            self.bm25 = BM25Okapi(tokens) if tokens else None

    async def search(self, request):
        started = time.perf_counter()
        async with self.lock:
            await asyncio.to_thread(self._refresh)
            chunks = [c for c in self.chunks if not request.doc_ids or c.doc_id in request.doc_ids]
            by_id = {c.chunk_id: c for c in chunks}
            dense, sparse = [], []
            if chunks and request.mode in ('dense', 'hybrid'):
                vector = (await self.embedding.embed([request.query]))[0]
                # SQLite ready documents define visibility, even after a partial vector upsert.
                doc_ids = sorted({c.doc_id for c in chunks})
                result = await asyncio.to_thread(self.client.query_points, self.collection,
                    query=vector, query_filter=models.Filter(must=[models.FieldCondition(
                        key='doc_id', match=models.MatchAny(any=doc_ids))]), limit=request.candidates)
                # Cosine similarity is signed. Without an explicitly configured relevance threshold,
                # top-ranked negative/zero values remain valid candidates and retain their raw scores.
                dense = [(by_id[str(p.id)], p.score) for p in result.points if str(p.id) in by_id]
            if chunks and request.mode in ('bm25', 'hybrid'):
                query_tokens = tokenize(request.query)
                scores = self.bm25.get_scores(query_tokens)
                query_set = set(query_tokens)
                # BM25 IDF can be zero/negative in a tiny corpus. Match presence, not score sign,
                # determines eligibility; keep the library's original score for provenance.
                sparse = sorted([(c, float(s)) for c, s, tokens in zip(self.chunks, scores, self.tokens, strict=True)
                                 if c.chunk_id in by_id and query_set & tokens],
                                key=lambda x: (-x[1], x[0].chunk_id))[:request.candidates]
            if request.mode == 'hybrid':
                hits = rrf(dense, sparse)[:request.candidates]
            else:
                field = 'dense' if request.mode == 'dense' else 'bm25'
                hits = [Hit(chunk=c, **{field + '_score': float(s), field + '_rank': i})
                        for i, (c, s) in enumerate(dense if field == 'dense' else sparse, 1)]
            if request.rerank and hits:
                scores = await self.reranker.score(request.query, [h.chunk.text for h in hits],
                                                   timeout=self.settings.tool_timeout)
                for hit, score in zip(hits, scores, strict=True):
                    if not math.isfinite(float(score)):
                        raise ValueError('NONFINITE_RERANK_SCORE')
                    hit.rerank_score = float(score)
                hits.sort(key=lambda h: (-h.rerank_score, -(h.rrf_score or 0), h.chunk.chunk_id))
            return SearchResult(hits=hits[:request.top_k], mode=self.settings.mode,
                                elapsed_ms=(time.perf_counter()-started)*1000, index_version=self.version,
                                warnings=['LOCAL_RETRIEVAL_TEST_DOUBLES: Embedding/Reranker are lexical substitutes; '
                                          'source texts and IDs are real stored document evidence. '
                                          'Retrieval quality is not a semantic model benchmark.']
                                if self.settings.resolved_embedding_provider == 'mock' or
                                   self.settings.resolved_reranker_provider == 'mock' else [])

    async def delete_document(self, doc_id):
        async with self.lock:
            with self.db.connect() as c:
                row = c.execute('SELECT status FROM documents WHERE doc_id=?', (doc_id,)).fetchone()
                if not row:
                    return False
                # Hide first. A network failure leaves a retryable deleting record, never searchable or cited.
                c.execute("UPDATE documents SET status='deleting' WHERE doc_id=?", (doc_id,))
                c.execute("UPDATE meta SET value=CAST(value AS INTEGER)+1 WHERE key='index_version'")
            await asyncio.to_thread(self.client.delete, self.collection,
                points_selector=models.FilterSelector(filter=models.Filter(must=[models.FieldCondition(
                    key='doc_id', match=models.MatchValue(value=doc_id))])), wait=True)
            with self.db.connect() as c:
                c.execute('DELETE FROM chunks WHERE doc_id=?', (doc_id,))
                c.execute('DELETE FROM sources WHERE doc_id=?', (doc_id,))
                c.execute('DELETE FROM documents WHERE doc_id=?', (doc_id,))
            return True

    def close(self):
        self.client.close()
