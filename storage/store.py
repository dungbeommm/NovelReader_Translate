"""Single-book library, transactional batch checkpoints, WAL, output_text and output_audio synchronization."""
import sqlite3
import json
import re
import os
import shutil
import unicodedata
from paths import ROOT
from contextlib import contextmanager
from pathlib import Path
from translation.text import paragraphs


def _safe_filename(name: str) -> str:
    name = unicodedata.normalize('NFC', str(name))
    cleaned = re.sub(r'[\\/*?:"<>|\x00-\x1f]', '_', name).strip(' .')[:80].rstrip(' .')
    if not cleaned:
        cleaned = 'truyen'
    if cleaned.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *[f'COM{i}' for i in range(1, 10)], *[f'LPT{i}' for i in range(1, 10)]}:
        cleaned = '_' + cleaned
    return cleaned


class Store:
    def __init__(self, path, text_dir=None, audio_dir=None):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._text_root = Path(text_dir or os.getenv('NOVEL_OUTPUT_TEXT', ROOT / 'output_text')).expanduser().resolve()
        self._audio_root = Path(audio_dir or os.getenv('NOVEL_OUTPUT_AUDIO', ROOT / 'output_audio')).expanduser().resolve()
        self._text_root.mkdir(parents=True, exist_ok=True)
        self._audio_root.mkdir(parents=True, exist_ok=True)

        with self.connect() as c:
            c.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS book(id INTEGER PRIMARY KEY,title TEXT,filename TEXT,encoding TEXT,config TEXT DEFAULT '{}');
            CREATE TABLE IF NOT EXISTS chapter(id INTEGER PRIMARY KEY,position INTEGER,title TEXT,source TEXT,status TEXT DEFAULT 'pending',
            plan TEXT DEFAULT '[]',outputs TEXT DEFAULT '[]',translated_title TEXT DEFAULT '',translated TEXT DEFAULT '[]',error TEXT DEFAULT '',audio_status TEXT DEFAULT 'none');
            UPDATE chapter SET status='pending' WHERE status='translating';
            ''')
            try:
                c.execute("ALTER TABLE chapter ADD COLUMN audio_status TEXT DEFAULT 'none'")
            except Exception:
                pass

        with self.connect() as c:
            c.execute("UPDATE chapter SET audio_status='none' WHERE audio_status IN ('queued', 'generating')")

        with self.connect() as c:
            columns = {row['name'] for row in c.execute('PRAGMA table_info(book)')}
            if 'output_folder' not in columns:
                c.execute("ALTER TABLE book ADD COLUMN output_folder TEXT DEFAULT ''")
            book = c.execute('SELECT id, title, output_folder FROM book LIMIT 1').fetchone()
            if book and not book['output_folder']:
                c.execute('UPDATE book SET output_folder=? WHERE id=?', (_safe_filename(book['title']), book['id']))

    def _book_dir(self, root):
        book = self.book()
        folder = (book.get('output_folder') or _safe_filename(book['title'])) if book else '_chua_nap_truyen'
        if folder != _safe_filename(folder):
            raise ValueError('Tên thư mục truyện không hợp lệ.')
        directory = root / folder
        if not directory.resolve().is_relative_to(root):
            raise ValueError('Thư mục truyện không được nằm ngoài thư mục output.')
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def _available_folder(self, title):
        base = _safe_filename(title)
        candidate = base
        suffix = 2
        while any((root / candidate).exists() for root in (self._text_root, self._audio_root)):
            tail = f'_{suffix}'
            candidate = f'{base[:80-len(tail)]}{tail}'
            suffix += 1
        return candidate

    @property
    def text_dir(self) -> Path:
        return self._book_dir(self._text_root)

    @property
    def audio_dir(self) -> Path:
        return self._book_dir(self._audio_root)

    def set_title(self, title):
        title = title.strip()
        if not title or len(title) > 200:
            raise ValueError('Tên truyện phải có từ 1 đến 200 ký tự.')
        book = self.book()
        if not book:
            raise ValueError('Hãy nạp truyện trước.')
        if title == book['title']:
            return book
        old_folder = book['output_folder']
        new_folder = old_folder if _safe_filename(title) == old_folder else self._available_folder(title)
        moved = []
        try:
            if new_folder != old_folder:
                for root in (self._text_root, self._audio_root):
                    old = self._book_dir(root)
                    new = root / new_folder
                    if new.exists():
                        raise ValueError('Thư mục đích đã tồn tại.')
                    old.rename(new)
                    moved.append((new, old))
            with self.connect() as c:
                c.execute('UPDATE book SET title=?, output_folder=?', (title, new_folder))
        except Exception:
            for new, old in reversed(moved):
                new.rename(old)
            raise
        self.export_full_book_text()
        return self.book()

    def _clear_outputs(self, text_dir, audio_dir):
        for directory, root in ((text_dir, self._text_root), (audio_dir, self._audio_root)):
            if directory == root or not directory.resolve().is_relative_to(root):
                raise ValueError('Không thể xóa thư mục ngoài phạm vi truyện.')
            if directory.exists():
                shutil.rmtree(directory)

    def _invalidate_groups(self, positions=None):
        for name in ('audio_gop', 'groups', 'merged'):
            directory = self.audio_dir / name
            if not directory.is_dir():
                continue
            for path in directory.iterdir():
                match = re.match(r'chuong_(\d+)_(\d+)\.', path.name)
                if path.is_file() and (positions is None or (match and any(int(match[1]) <= pos <= int(match[2]) for pos in positions))):
                    path.unlink(missing_ok=True)

    @contextmanager
    def connect(self):
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    def book(self):
        with self.connect() as c:
            row = c.execute('SELECT * FROM book LIMIT 1').fetchone()
            return dict(row) if row else None

    def export_chapter_text(self, chapter_id: int, title: str, paras: list[str], position: int) -> Path:
        """Lưu bản dịch chương truyện vào thư mục output_text."""
        self.text_dir.mkdir(parents=True, exist_ok=True)
        clean_title = (title or f"Chương {position}").strip()
        clean_paras = [p.strip() for p in paras if p and p.strip() and not p.strip().startswith("(")]
        body = "\n\n".join(clean_paras)
        content = f"{clean_title}\n\n{body}\n" if body else f"{clean_title}\n"

        target_file = self.text_dir / f"chuong_{position:04d}.txt"
        target_file.write_text(content, encoding='utf-8')
        return target_file

    def export_full_book_text(self) -> Path | None:
        """Xuất toàn bộ các chương đã dịch thành 1 file tổng hợp trong output_text."""
        b = self.book()
        if not b:
            return None
        with self.connect() as c:
            rows = c.execute("SELECT position, title, translated_title, translated FROM chapter WHERE status='done' ORDER BY position").fetchall()
        full_file = self.text_dir / 'toan_bo_truyen.txt'
        if not rows:
            try:
                full_file.unlink(missing_ok=True)
            except Exception:
                pass
            return None

        self.text_dir.mkdir(parents=True, exist_ok=True)
        raw_title = b.get('title') or 'truyen'

        lines = [f"=== {raw_title.upper()} ===", "\n\n"]
        for r in rows:
            c_title = r['translated_title'] or r['title'] or f"Chương {r['position']}"
            lines.append(f"\n\n--- {c_title} ---\n\n")
            try:
                paras = json.loads(r['translated'] or '[]')
            except Exception:
                paras = []
            lines.append("\n\n".join(p.strip() for p in paras if p and p.strip()))

        temp_file = full_file.with_suffix('.txt.tmp')
        try:
            temp_file.write_text("".join(lines), encoding='utf-8')
            os.replace(temp_file, full_file)
        finally:
            temp_file.unlink(missing_ok=True)
        return full_file

    def export_full_book_epub(self) -> Path | None:
        """Write an EPUB copy of the current translation for Bucket sync."""
        from storage.files import export_epub

        book = self.book()
        if not book:
            return None
        chapters = [self.get(item['id']) for item in self.list()]
        if not any(chapter['status'] == 'done' for chapter in chapters):
            return None
        target = self.text_dir / 'toan_bo_truyen.epub'
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix('.epub.tmp')
        try:
            temporary.write_bytes(export_epub(book, chapters))
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return target

    def replace(self, name, encoding, chapters):
        title = Path(name.replace('\\', '/')).stem
        folder = self._available_folder(title)
        with self.connect() as c:
            c.execute('DELETE FROM chapter')
            c.execute('DELETE FROM book')
            c.execute('INSERT INTO book(id,title,filename,encoding,output_folder) VALUES(1,?,?,?,?)', (title, name, encoding, folder))
            c.executemany('INSERT INTO chapter(position,title,source) VALUES(?,?,?)',
                          [(i+1, title, json.dumps(paragraphs(body), ensure_ascii=False)) for i, (title, body) in enumerate(chapters)])
        self.text_dir.mkdir(parents=True, exist_ok=True)
        self.audio_dir.mkdir(parents=True, exist_ok=True)

    def list(self):
        with self.connect() as c:
            return [dict(r) for r in c.execute('SELECT id,position,title,translated_title,status,error,audio_status FROM chapter ORDER BY position')]

    def get(self, id):
        with self.connect() as c:
            r = c.execute('SELECT * FROM chapter WHERE id=?', (id,)).fetchone()
        if not r:
            return None
        d = dict(r)
        for k in ('source', 'plan', 'outputs', 'translated'):
            d[k] = json.loads(d[k])
        return d

    def update(self, id, **fields):
        allowed = {'status', 'plan', 'outputs', 'translated_title', 'translated', 'error', 'audio_status'}
        if not fields.keys() <= allowed:
            raise ValueError('Unknown fields')
        with self.connect() as c:
            c.execute('UPDATE chapter SET ' + ','.join(f'{k}=?' for k in fields) + ' WHERE id=?',
                      [json.dumps(v, ensure_ascii=False) if isinstance(v, list) else v for v in fields.values()] + [id])

    def configure(self, config, reset=False):
        if reset:
            self._clear_outputs(self.text_dir, self.audio_dir)
        with self.connect() as c:
            if reset:
                c.execute("UPDATE chapter SET status='pending',plan='[]',outputs='[]',translated_title='',translated='[]',error='',audio_status='none'")
            c.execute('UPDATE book SET config=?', (json.dumps(config, ensure_ascii=False),))

    def clear(self):
        if self.book():
            self._clear_outputs(self.text_dir, self.audio_dir)
        with self.connect() as c:
            c.execute('DELETE FROM chapter')
            c.execute('DELETE FROM book')

    def reset_chapters(self, ids):
        if not ids:
            return
        placeholders = ','.join('?' for _ in ids)
        id_list = list(ids)
        with self.connect() as c:
            rows = c.execute(f"SELECT id, position FROM chapter WHERE id IN ({placeholders})", id_list).fetchall()
            self._invalidate_groups([r['position'] for r in rows])
            for r in rows:
                try:
                    (self.text_dir / f"chuong_{r['position']:04d}.txt").unlink(missing_ok=True)
                except Exception:
                    pass
                for ext in ('mp3', 'm4b', 'm4a', 'opus', 'wav'):
                    try:
                        (self.audio_dir / f"chapter_{r['id']}.{ext}").unlink(missing_ok=True)
                    except Exception:
                        pass
                    try:
                        (self.audio_dir / f"chuong_{r['position']:04d}.{ext}").unlink(missing_ok=True)
                    except Exception:
                        pass
            c.execute(f"UPDATE chapter SET status='pending',plan='[]',outputs='[]',translated_title='',translated='[]',error='',audio_status='none' WHERE id IN ({placeholders})", id_list)
        self.export_full_book_text()

    def delete_chapters(self, ids):
        if not ids:
            return
        placeholders = ','.join('?' for _ in ids)
        id_list = list(ids)
        with self.connect() as c:
            rows = c.execute(f"SELECT id, position FROM chapter WHERE id IN ({placeholders})", id_list).fetchall()
            if not rows:
                return
            self._invalidate_groups()
            for r in rows:
                try:
                    (self.text_dir / f"chuong_{r['position']:04d}.txt").unlink(missing_ok=True)
                except Exception:
                    pass
                for ext in ('mp3', 'm4b', 'm4a', 'opus', 'wav'):
                    try:
                        (self.audio_dir / f"chapter_{r['id']}.{ext}").unlink(missing_ok=True)
                    except Exception:
                        pass
                    try:
                        (self.audio_dir / f"chuong_{r['position']:04d}.{ext}").unlink(missing_ok=True)
                    except Exception:
                        pass
            c.execute(f"DELETE FROM chapter WHERE id IN ({placeholders})", id_list)
            remaining = c.execute("SELECT id, position FROM chapter ORDER BY position, id").fetchall()
            updates = []
            shifts = []
            for new_pos, row in enumerate(remaining, start=1):
                old_pos = row['position']
                if old_pos != new_pos:
                    updates.append((new_pos, row['id']))
                    shifts.append((old_pos, new_pos))
            if updates:
                c.executemany("UPDATE chapter SET position=? WHERE id=?", updates)

        if shifts:
            existing_txt = {}
            if self.text_dir.is_dir():
                try:
                    for p in self.text_dir.iterdir():
                        if p.is_file():
                            m = re.match(r"^chuong_(\d+)\.txt$", p.name)
                            if m:
                                existing_txt[int(m.group(1))] = p
                except Exception:
                    pass

            existing_audio = {}
            if self.audio_dir.is_dir():
                try:
                    for p in self.audio_dir.iterdir():
                        if p.is_file():
                            m = re.match(r"^chuong_(\d+)\.(mp3|m4b|m4a|opus|wav)$", p.name, re.IGNORECASE)
                            if m:
                                existing_audio.setdefault(int(m.group(1)), []).append(p)
                except Exception:
                    pass

            def _safe_move(src_p: Path, dst_p: Path):
                if not src_p.is_file() or src_p == dst_p:
                    return
                try:
                    if dst_p.exists():
                        try:
                            dst_p.unlink(missing_ok=True)
                        except Exception:
                            pass
                    src_p.replace(dst_p)
                except Exception:
                    try:
                        shutil.copy2(src_p, dst_p)
                        try:
                            src_p.unlink(missing_ok=True)
                        except Exception:
                            pass
                    except Exception:
                        pass

            for old_pos, new_pos in shifts:
                if old_pos in existing_txt:
                    src = existing_txt[old_pos]
                    dst = self.text_dir / f"chuong_{new_pos:04d}.txt"
                    _safe_move(src, dst)

                if old_pos in existing_audio:
                    for src in existing_audio[old_pos]:
                        dst = self.audio_dir / f"chuong_{new_pos:04d}{src.suffix}"
                        _safe_move(src, dst)

        self.export_full_book_text()

    def purge_empty_chapters(self):
        """Xóa toàn bộ các chương rỗng không có nội dung chữ."""
        with self.connect() as c:
            rows = c.execute("SELECT id, source FROM chapter").fetchall()
            empty_ids = []
            for r in rows:
                try:
                    s_list = json.loads(r['source'])
                    if not s_list or not any(s.strip() for s in s_list):
                        empty_ids.append(r['id'])
                except Exception:
                    pass
        if empty_ids:
            self.delete_chapters(empty_ids)
        return len(empty_ids)

    def purge_all(self, purge_data: bool = True, purge_cache: bool = True) -> dict:
        """Xóa toàn bộ cache và data của mọi thứ."""
        deleted_text = 0
        deleted_audio = 0
        deleted_cache = 0

        if purge_data:
            if self.book():
                text_dir, audio_dir = self.text_dir, self.audio_dir
                deleted_text = sum(p.is_file() for p in text_dir.rglob('*'))
                deleted_audio = sum(p.is_file() for p in audio_dir.rglob('*'))
                self._clear_outputs(text_dir, audio_dir)
            with self.connect() as c:
                c.execute('DELETE FROM chapter')
                c.execute('DELETE FROM book')

        if purge_cache:
            for pattern in ('*.tmp', '*.temp', '*.log'):
                for p in list(self.path.parent.glob(pattern)):
                    if p.is_file() and p.name != 'novel.sqlite3':
                        try:
                            if p.suffix == '.log':
                                p.write_text('', encoding='utf-8')
                            else:
                                p.unlink(missing_ok=True)
                            deleted_cache += 1
                        except Exception:
                            pass

            import tempfile
            tmp_dir = Path(tempfile.gettempdir())
            for p in list(tmp_dir.glob('chunk_*.wav')) + list(tmp_dir.glob('chapter_*.wav')) + list(tmp_dir.glob('chapter.*')):
                try:
                    p.unlink(missing_ok=True)
                    deleted_cache += 1
                except Exception:
                    pass

        return {
            'ok': True,
            'deleted_text_count': deleted_text,
            'deleted_audio_count': deleted_audio,
            'deleted_cache_count': deleted_cache,
            'message': f"Đã xóa thành công {deleted_text} file text, {deleted_audio} file audio và {deleted_cache} file cache/tạm."
        }
