"""Single-book library, transactional batch checkpoints, WAL and short connections."""
import sqlite3
import json
from contextlib import contextmanager
from pathlib import Path
from .text import paragraphs

class Store:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as c:
            c.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS book(id INTEGER PRIMARY KEY,title TEXT,filename TEXT,encoding TEXT,config TEXT DEFAULT '{}');
            CREATE TABLE IF NOT EXISTS chapter(id INTEGER PRIMARY KEY,position INTEGER,title TEXT,source TEXT,status TEXT DEFAULT 'pending',
            plan TEXT DEFAULT '[]',outputs TEXT DEFAULT '[]',translated_title TEXT DEFAULT '',translated TEXT DEFAULT '[]',error TEXT DEFAULT '');
            UPDATE chapter SET status='pending' WHERE status='translating';
            ''')
    @contextmanager
    def connect(self):
        c=sqlite3.connect(self.path,timeout=30);c.row_factory=sqlite3.Row
        try:
            yield c;c.commit()
        except Exception: c.rollback();raise
        finally:c.close()
    def book(self):
        with self.connect() as c:
            row=c.execute('SELECT * FROM book LIMIT 1').fetchone()
            return dict(row) if row else None
    def replace(self,name,encoding,chapters):
        with self.connect() as c:
            c.execute('DELETE FROM chapter');c.execute('DELETE FROM book')
            c.execute('INSERT INTO book(id,title,filename,encoding) VALUES(1,?,?,?)',(Path(name).stem,name,encoding))
            c.executemany('INSERT INTO chapter(position,title,source) VALUES(?,?,?)',
                          [(i+1,title,json.dumps(paragraphs(body),ensure_ascii=False)) for i,(title,body) in enumerate(chapters)])
    def list(self):
        with self.connect() as c:
            return [dict(r) for r in c.execute('SELECT id,position,title,translated_title,status,error FROM chapter ORDER BY position')]
    def get(self,id):
        with self.connect() as c:
            r=c.execute('SELECT * FROM chapter WHERE id=?',(id,)).fetchone()
        if not r:return None
        d=dict(r)
        for k in ('source','plan','outputs','translated'): d[k]=json.loads(d[k])
        return d
    def update(self,id,**fields):
        allowed={'status','plan','outputs','translated_title','translated','error'}
        if not fields.keys()<=allowed:raise ValueError('Unknown fields')
        with self.connect() as c:
            c.execute('UPDATE chapter SET '+','.join(f'{k}=?' for k in fields)+' WHERE id=?',
                      [json.dumps(v,ensure_ascii=False) if isinstance(v,list) else v for v in fields.values()]+[id])
    def configure(self,config,reset=False):
        with self.connect() as c:
            if reset:c.execute("UPDATE chapter SET status='pending',plan='[]',outputs='[]',translated_title='',translated='[]',error=''")
            c.execute('UPDATE book SET config=?',(json.dumps(config,ensure_ascii=False),))
    def clear(self):
        with self.connect() as c:
            c.execute('DELETE FROM chapter');c.execute('DELETE FROM book')
    def reset_chapters(self,ids):
        if not ids:return
        placeholders=','.join('?' for _ in ids)
        with self.connect() as c:
            c.execute(f"UPDATE chapter SET status='pending',plan='[]',outputs='[]',translated_title='',translated='[]',error='' WHERE id IN ({placeholders})",list(ids))
    def delete_chapters(self,ids):
        if not ids:return
        placeholders=','.join('?' for _ in ids)
        with self.connect() as c:
            c.execute(f"DELETE FROM chapter WHERE id IN ({placeholders})",list(ids))
            rows=c.execute("SELECT id FROM chapter ORDER BY position, id").fetchall()
            for new_pos,row in enumerate(rows,start=1):
                c.execute("UPDATE chapter SET position=? WHERE id=?",(new_pos,row['id']))
