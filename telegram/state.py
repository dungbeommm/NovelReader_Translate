"""Durable, single-worker queue. Only opaque IDs are used as directory names."""
import json
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

class State:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / 'queue.sqlite3'
        with self.connect() as c:
            c.executescript('''PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, owner INTEGER, chat INTEGER,
                mode TEXT, status TEXT, created REAL, error TEXT DEFAULT '');
            CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, mode TEXT);
            ''')
    @contextmanager
    def connect(self):
        c = sqlite3.connect(self.db, timeout=30)
        c.row_factory = sqlite3.Row
        try:
            with c:
                yield c
        finally:
            c.close()
    def recover(self):
        with self.connect() as c:
            c.execute("UPDATE jobs SET status='queued' WHERE status IN ('running','delivering')")
    def mode(self, uid, value=None):
        with self.connect() as c:
            if value:
                c.execute('INSERT OR REPLACE INTO users VALUES(?,?)', (uid, value))
            row = c.execute('SELECT mode FROM users WHERE id=?', (uid,)).fetchone()
            return row['mode'] if row else 'full'
    def create(self, owner, chat, mode, suffix, data):
        if mode not in ('translate', 'audio', 'full') or suffix not in ('.txt', '.epub'):
            raise ValueError('Chế độ/định dạng không hợp lệ.')
        jid = uuid.uuid4().hex[:16]
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','running','delivering')").fetchone()[0] >= 10:
                raise ValueError('Hàng đợi đầy (10 truyện).')
            if c.execute("SELECT count(*) FROM jobs WHERE owner=? AND status IN ('queued','running','delivering')", (owner,)).fetchone()[0] >= 2:
                raise ValueError('Bạn đang có 2 truyện chờ/chạy. Hãy đợi hoặc hủy bớt.')
            folder = self.root / jid
            folder.mkdir()
            (folder / ('input' + suffix)).write_bytes(data)
            (folder / 'request.json').write_text(json.dumps({'mode': mode, 'input': 'input' + suffix}), encoding='utf-8')
            c.execute('INSERT INTO jobs(id,owner,chat,mode,status,created) VALUES(?,?,?,?,?,?)',
                      (jid, owner, chat, mode, 'queued', time.time()))
        return jid
    def requeue(self, jid, owner):
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT * FROM jobs WHERE id=? AND owner=?', (jid, owner)).fetchone()
            if not row or row['status'] not in ('failed','cancelled'):
                raise ValueError('Tác vụ không thể tiếp tục.')
            if c.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','running','delivering')").fetchone()[0] >= 10:
                raise ValueError('Hàng đợi đầy (10 truyện).')
            if c.execute("SELECT count(*) FROM jobs WHERE owner=? AND status IN ('queued','running','delivering')", (owner,)).fetchone()[0] >= 2:
                raise ValueError('Bạn đang có 2 truyện chờ/chạy.')
            c.execute("UPDATE jobs SET status='queued',error='' WHERE id=?", (jid,))

    def get(self, jid, owner=None):
        if not re.fullmatch(r'[a-f0-9]{16}', jid):
            return None
        with self.connect() as c:
            row = c.execute('SELECT * FROM jobs WHERE id=?', (jid,)).fetchone()
        return dict(row) if row and (owner is None or row['owner'] == owner) else None
    def list(self, owner):
        with self.connect() as c:
            return [dict(r) for r in c.execute('SELECT * FROM jobs WHERE owner=? ORDER BY created DESC LIMIT 10', (owner,))]
    def next(self):
        with self.connect() as c:
            row = c.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
            if row:
                c.execute("UPDATE jobs SET status='running' WHERE id=?", (row['id'],))
        return dict(row) if row else None
    def set(self, jid, status, error=''):
        with self.connect() as c:
            c.execute('UPDATE jobs SET status=?,error=? WHERE id=?', (status, error[:300], jid))
