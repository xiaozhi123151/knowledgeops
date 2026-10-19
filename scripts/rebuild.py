"""Explicitly reimport immutable raw files into a NEW directory; never delete an old index."""
import argparse
import asyncio
import hashlib
import sqlite3
from pathlib import Path

from knowledgeops.config import Settings
from knowledgeops.ingestion.extract import extract, make_chunks
from knowledgeops.runtime import Runtime


async def rebuild(args):
    source, target = args.source.resolve(), args.target.resolve()
    if source == target or source in target.parents or target in source.parents:
        raise ValueError('Source and target must be separate sibling directories')
    if not (source/'metadata.sqlite').is_file() or (target.exists() and any(target.iterdir())):
        raise ValueError('Source database must exist and target must be empty')
    settings = Settings(mode=args.mode, data_dir=target)
    with sqlite3.connect(f'file:{(source/"metadata.sqlite").as_posix()}?mode=ro', uri=True) as conn:
        rows = conn.execute("SELECT d.doc_id,d.title,s.source,s.raw_hash FROM documents d "
                            "JOIN sources s USING(doc_id) WHERE d.status='ready' ORDER BY d.doc_id").fetchall()
    runtime = await Runtime(settings).start()
    results = []
    try:
        # In live mode an existing collection is an unsafe target even with an empty metadata directory.
        if args.mode == 'live' and runtime.engine.client.count(runtime.engine.collection).count:
            raise ValueError('Live rebuild requires a new empty Qdrant instance/storage')
        for old_id, title, origin, raw_hash in rows:
            suffix = '.html' if origin.startswith(('https://','http://')) else Path(origin).suffix.lower()
            if suffix not in ('.pdf','.md','.txt','.html'):
                raise ValueError('Unknown stored source format')
            data = (source/'raw'/(raw_hash+suffix)).read_bytes()
            if hashlib.sha256(data).hexdigest() != raw_hash:
                raise ValueError('Stored raw hash mismatch; aborting rebuild')
            segments = extract(data,suffix,settings.max_pdf_pages)
            doc_id,chunks = make_chunks(segments,origin,title,settings.chunk_size,settings.chunk_overlap)
            (target/'raw'/(raw_hash+suffix)).write_bytes(data)
            if runtime.db.stage_document(doc_id,title,runtime.engine.fingerprint,chunks,origin,raw_hash):
                await runtime.engine.upsert(chunks)
                runtime.db.publish(doc_id)
            results.append({'old_doc_id':old_id,'new_doc_id':doc_id,'source':origin})
    finally:
        await runtime.close()
    from scripts.common import write_json
    write_json(target/'rebuild-manifest.json',{'source':str(source),'target':str(target),'documents':results})
    print(f'Rebuilt {len(results)} source aliases into {target}; old data retained. Sessions/tasks are not migrated.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True,help='Stopped existing data directory')
    parser.add_argument('--target',type=Path,required=True,help='Separate new empty data directory')
    parser.add_argument('--mode',choices=['offline','live'],default='offline')
    asyncio.run(rebuild(parser.parse_args()))


if __name__ == '__main__':
    main()
