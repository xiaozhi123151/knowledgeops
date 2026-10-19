import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from knowledgeops.schemas import Chunk


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class Database:
    def __init__(self, root: Path):
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "metadata.sqlite"
        with self.connect() as conn:
            conn.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT OR IGNORE INTO meta VALUES ('schema_version','1');
            INSERT OR IGNORE INTO meta VALUES ('index_version','0');
            CREATE TABLE IF NOT EXISTS documents(
              doc_id TEXT PRIMARY KEY, title TEXT NOT NULL, status TEXT NOT NULL,
              fingerprint TEXT NOT NULL, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS sources(
              doc_id TEXT NOT NULL, source TEXT NOT NULL, raw_hash TEXT NOT NULL,
              PRIMARY KEY(doc_id,source,raw_hash));
            CREATE TABLE IF NOT EXISTS chunks(
              chunk_id TEXT PRIMARY KEY, doc_id TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS chunks_doc ON chunks(doc_id);
            CREATE TABLE IF NOT EXISTS tasks(
              task_id TEXT PRIMARY KEY, kind TEXT NOT NULL, session_id TEXT,
              payload TEXT NOT NULL, status TEXT NOT NULL, result TEXT, error TEXT,
              created REAL NOT NULL, updated REAL NOT NULL, owner TEXT, lease REAL,
              started REAL, deadline REAL, limits_json TEXT NOT NULL DEFAULT '{}',
              budget TEXT NOT NULL DEFAULT '{}');
            CREATE INDEX IF NOT EXISTS tasks_status ON tasks(status,created);
            CREATE TABLE IF NOT EXISTS events(
              seq INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
              at REAL NOT NULL, type TEXT NOT NULL, data TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS events_task ON events(task_id,seq);
            CREATE TABLE IF NOT EXISTS tool_results(
              task_id TEXT NOT NULL, call_key TEXT NOT NULL, result TEXT NOT NULL,
              PRIMARY KEY(task_id,call_key));
            CREATE TABLE IF NOT EXISTS sessions(
              session_id TEXT PRIMARY KEY, messages TEXT NOT NULL DEFAULT '[]');
            """)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=20)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=20000")
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def version(self):
        with self.connect() as c:
            return int(c.execute("SELECT value FROM meta WHERE key='index_version'").fetchone()[0])

    def stage_document(self, doc_id, title, fingerprint, chunks, source, raw_hash):
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            old = c.execute("SELECT * FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
            if old and old['fingerprint'] != fingerprint:
                raise ValueError("INDEX_CONFIG_CHANGED: rebuild into a new data directory")
            c.execute("INSERT OR IGNORE INTO sources VALUES(?,?,?)", (doc_id, source, raw_hash))
            if old and old['status'] == 'ready':
                return False
            c.execute("INSERT OR REPLACE INTO documents VALUES(?,?,?,?,?)",
                      (doc_id, title, 'indexing', fingerprint, time.time()))
            c.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))
            c.executemany("INSERT INTO chunks VALUES(?,?,?)",
                          [(x.chunk_id, doc_id, x.model_dump_json()) for x in chunks])
        return True

    def publish(self, doc_id):
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            c.execute("UPDATE documents SET status='ready' WHERE doc_id=?", (doc_id,))
            c.execute("UPDATE meta SET value=CAST(value AS INTEGER)+1 WHERE key='index_version'")

    def snapshot(self):
        with self.connect() as c:
            c.execute("BEGIN")
            version = int(c.execute("SELECT value FROM meta WHERE key='index_version'").fetchone()[0])
            rows = c.execute("SELECT payload FROM chunks JOIN documents USING(doc_id) "
                             "WHERE status='ready' ORDER BY chunk_id").fetchall()
            return version, [Chunk.model_validate_json(x[0]) for x in rows]

    def documents(self):
        with self.connect() as c:
            docs = [dict(x) for x in c.execute("SELECT * FROM documents ORDER BY created")]
            for d in docs:
                d['sources'] = [dict(x) for x in c.execute(
                    "SELECT source,raw_hash FROM sources WHERE doc_id=?", (d['doc_id'],))]
                d['chunk_count'] = c.execute("SELECT count(*) FROM chunks WHERE doc_id=?", (d['doc_id'],)).fetchone()[0]
            return docs

    def chunk(self, doc_id, chunk_id):
        with self.connect() as c:
            row = c.execute("SELECT payload FROM chunks JOIN documents USING(doc_id) "
                            "WHERE doc_id=? AND chunk_id=? AND status='ready'", (doc_id, chunk_id)).fetchone()
            return Chunk.model_validate_json(row[0]) if row else None
