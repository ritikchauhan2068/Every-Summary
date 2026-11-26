"""SQLite persistence for workspaces, a durable ingestion queue, and source chats."""

import json
import sqlite3
from contextlib import contextmanager

from sourcewise.domain import SourceError


class Store:
    def __init__(self, path):
        self.path = path
        with self.connection() as con:
            con.execute("PRAGMA journal_mode = WAL")
            con.executescript("""
                CREATE TABLE IF NOT EXISTS source (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, kind TEXT NOT NULL,
                    url TEXT NOT NULL, filename TEXT NOT NULL, attachment TEXT NOT NULL,
                    title TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
                    stage TEXT NOT NULL DEFAULT 'Waiting to process',
                    created TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    result TEXT, error TEXT
                );
                CREATE INDEX IF NOT EXISTS source_owner ON source(owner, created);
                CREATE INDEX IF NOT EXISTS source_queue ON source(status, created);
                CREATE TABLE IF NOT EXISTS chat (
                    id INTEGER PRIMARY KEY, source_id TEXT NOT NULL REFERENCES source(id) ON DELETE CASCADE,
                    question TEXT NOT NULL, result TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS chat_source ON chat(source_id, id);
            """)

    @contextmanager
    def connection(self):
        con = sqlite3.connect(self.path, timeout=10)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        try:
            with con:
                yield con
        finally:
            con.close()

    def recover(self):
        with self.connection() as con:
            con.execute("UPDATE source SET status='queued', stage='Resuming after restart' WHERE status='processing'")

    def library(self, owner):
        with self.connection() as con:
            return [dict(row) for row in con.execute("""
                SELECT id, kind, url, filename, title, status, stage, created, error
                FROM source WHERE owner=? ORDER BY created DESC
            """, (owner,))]

    def create(self, source):
        with self.connection() as con:
            con.execute("BEGIN IMMEDIATE")
            self.check_limits(con, source["owner"], adding=True)
            con.execute("""
                INSERT INTO source(id, owner, kind, url, filename, attachment, title)
                VALUES(:id, :owner, :kind, :url, :filename, :attachment, :title)
            """, source)

    def check_limits(self, con, owner, adding=False):
        count, busy = con.execute("""
            SELECT COUNT(*), COALESCE(SUM(status IN ('queued','processing')), 0)
            FROM source WHERE owner=?
        """, (owner,)).fetchone()
        if adding and count >= 24:
            raise SourceError("This workspace has 24 sources. Delete an old source before adding another.")
        if busy >= 3:
            raise SourceError("This workspace already has three sources processing. Try again in a moment.")
        if con.execute("SELECT COUNT(*) FROM source WHERE status IN ('queued','processing')").fetchone()[0] >= 24:
            raise SourceError("The processing queue is full. Try again shortly.")

    def claim(self):
        with self.connection() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT * FROM source WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
            if row:
                con.execute("UPDATE source SET status='processing', stage='Opening source' WHERE id=?", (row["id"],))
                return dict(row)
        return None

    def progress(self, identifier, stage):
        with self.connection() as con:
            con.execute("UPDATE source SET stage=? WHERE id=? AND status='processing'", (stage, identifier))

    def finish(self, identifier, result=None, error=None):
        with self.connection() as con:
            if result:
                con.execute("""
                    UPDATE source SET status='ready', stage='Ready', title=?, result=?, error=NULL, attachment=''
                    WHERE id=?
                """, (result["title"], json.dumps(result, ensure_ascii=False), identifier))
            else:
                con.execute("UPDATE source SET status='failed', stage='Needs attention', error=? WHERE id=?",
                            (error, identifier))

    def source(self, owner, identifier):
        with self.connection() as con:
            row = con.execute("SELECT * FROM source WHERE owner=? AND id=?", (owner, identifier)).fetchone()
            if row:
                data = dict(row)
                data["result"] = json.loads(data["result"]) if data["result"] else None
                return data
        return None

    def retry(self, owner, identifier):
        with self.connection() as con:
            con.execute("BEGIN IMMEDIATE")
            self.check_limits(con, owner)
            return con.execute("""
                UPDATE source SET status='queued', stage='Waiting to process', error=NULL
                WHERE owner=? AND id=? AND status='failed'
            """, (owner, identifier)).rowcount

    def delete(self, owner, identifier):
        with self.connection() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT status, attachment FROM source WHERE owner=? AND id=?", (owner, identifier)).fetchone()
            if row and row["status"] in {"queued", "processing"}:
                raise SourceError("Wait for this source to finish processing before deleting it.")
            if row:
                con.execute("DELETE FROM source WHERE owner=? AND id=?", (owner, identifier))
                return row["attachment"]
        return None

    def history(self, identifier):
        with self.connection() as con:
            rows = con.execute("""
                SELECT question, result FROM chat WHERE source_id=? ORDER BY id DESC LIMIT 50
            """, (identifier,)).fetchall()
        return [{"question": row["question"], **json.loads(row["result"])} for row in reversed(rows)]

    def add_chat(self, identifier, question, result):
        with self.connection() as con:
            con.execute("INSERT INTO chat(source_id, question, result) VALUES(?,?,?)",
                        (identifier, question, json.dumps(result, ensure_ascii=False)))
            con.execute("""
                DELETE FROM chat WHERE source_id=? AND id NOT IN
                (SELECT id FROM chat WHERE source_id=? ORDER BY id DESC LIMIT 50)
            """, (identifier, identifier))
