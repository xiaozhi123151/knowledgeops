import asyncio
import hashlib
import os
import uuid
from pathlib import Path

from knowledgeops.ingestion.extract import extract, make_chunks
from knowledgeops.ingestion.web import fetch_page


class IngestionService:
    def __init__(self, settings, db, engine):
        self.settings, self.db, self.engine = settings, db, engine
        self.lock = asyncio.Lock()
        self.raw_dir = settings.data_dir / 'raw'
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    def save_upload(self, data, filename):
        if not filename or '/' in filename or '\\' in filename or ':' in filename or filename in ('.', '..'):
            raise ValueError('INVALID_FILENAME')
        if len(data) > self.settings.max_upload_bytes:
            raise ValueError('UPLOAD_TOO_LARGE')
        suffix = Path(filename).suffix.lower()
        if suffix not in ('.pdf', '.md', '.txt'):
            raise ValueError('UNSUPPORTED_FORMAT')
        raw_hash = hashlib.sha256(data).hexdigest()
        path = self.raw_dir / (raw_hash + suffix)
        if not path.exists():
            temp = self.raw_dir / ('.upload-' + uuid.uuid4().hex)
            temp.write_bytes(data)
            os.replace(temp, path)
        return {'raw_hash': raw_hash, 'suffix': suffix, 'source': filename, 'title': filename}

    async def ingest(self, payload):
        async with self.lock:
            if 'url' in payload:
                data, source = await asyncio.to_thread(fetch_page, payload['url'])
                suffix, title = '.html', source
                raw_hash = hashlib.sha256(data).hexdigest()
                (self.raw_dir / (raw_hash + suffix)).write_bytes(data)
            else:
                raw_hash, suffix = payload['raw_hash'], payload['suffix']
                # Payload paths never control file access; only a verified hash and known extension do.
                if len(raw_hash) != 64 or any(c not in '0123456789abcdef' for c in raw_hash):
                    raise ValueError('INVALID_RAW_HASH')
                if suffix not in ('.pdf', '.md', '.txt'):
                    raise ValueError('INVALID_RAW_SUFFIX')
                data = (self.raw_dir / (raw_hash + suffix)).read_bytes()
                if hashlib.sha256(data).hexdigest() != raw_hash:
                    raise ValueError('RAW_CONTENT_HASH_MISMATCH')
                source, title = payload['source'], payload['title']
            segments = await asyncio.to_thread(extract, data, suffix, self.settings.max_pdf_pages)
            doc_id, chunks = make_chunks(segments, source, title,
                                        self.settings.chunk_size, self.settings.chunk_overlap)
            needed = self.db.stage_document(doc_id, title, self.engine.fingerprint, chunks, source, raw_hash)
            if needed:
                await self.engine.upsert(chunks)
                self.db.publish(doc_id)
            return {'doc_id': doc_id, 'chunk_count': len(chunks), 'duplicate': not needed}

    async def delete(self, doc_id):
        async with self.lock:
            return await self.engine.delete_document(doc_id)
