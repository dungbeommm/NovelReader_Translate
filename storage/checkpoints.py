"""Portable single-book snapshots. SQLite online backup, bounded ZIP import, no secrets."""
import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit
import urllib.request
from paths import data_dir
from storage.store import _safe_filename

MAX_ARCHIVE = 2 * 1024**3
MAX_EXPANDED = 8 * 1024**3
TEXT_EXT = {'.txt', '.json', '.epub'}
AUDIO_EXT = {'.mp3', '.m4a', '.m4b', '.wav', '.opus', '.ogg', '.aac', '.json'}


def clean_config(raw):
    from web.schemas import Config
    return Config.model_validate(raw or {}).model_dump()


def draft_path():
    return data_dir() / 'workspace_draft.json'


def save_draft(config):
    clean = clean_config(config)
    path = draft_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.draft-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(clean, f, ensure_ascii=False)
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)
    return clean


def load_draft():
    path = draft_path()
    return clean_config(json.loads(path.read_text('utf-8'))) if path.is_file() else None


def digest(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def create_checkpoint(store, destination, include_audio=False):
    if not store.book():
        raise ValueError('Hãy nạp truyện trước khi tạo checkpoint.')
    entries = {}
    with tempfile.TemporaryDirectory(prefix='novel-snapshot-') as temp:
        snap = Path(temp) / 'novel.sqlite3'
        with store.connect() as source, sqlite3.connect(snap) as target:
            source.backup(target)
            row = target.execute('SELECT config FROM book LIMIT 1').fetchone()
            target.execute('UPDATE book SET config=?', (json.dumps(clean_config(json.loads(row[0] or '{}')), ensure_ascii=False),))
        with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            def add(path, name):
                archive.write(path, name)
                entries[name] = digest(path)
            add(snap, 'data/novel.sqlite3')
            for kind, root, allowed in [('text', store.text_dir, TEXT_EXT)] + ([('audio', store.audio_dir, AUDIO_EXT)] if include_audio else []):
                for path in sorted(root.rglob('*')):
                    rel = path.relative_to(root)
                    if path.is_file() and not path.is_symlink() and not any(p.startswith('.') for p in rel.parts) and path.suffix.lower() in allowed:
                        add(path, f'{kind}/{rel.as_posix()}')
            draft = load_draft()
            if draft:
                draft_file = Path(temp) / 'draft.json'
                draft_file.write_text(json.dumps(draft, ensure_ascii=False), 'utf-8')
                add(draft_file, 'workspace_draft.json')
            archive.writestr('manifest.json', json.dumps({
                'format': 'novelreader-checkpoint', 'version': 1,
                'created_at': datetime.now(timezone.utc).isoformat(),
                'include_audio': include_audio, 'sha256': entries,
            }, ensure_ascii=False))
    if Path(destination).stat().st_size > MAX_ARCHIVE:
        Path(destination).unlink(missing_ok=True)
        raise ValueError('Checkpoint vượt 2 GB; bỏ chọn kèm audio và xuất audio riêng.')
    return Path(destination)


def upload_checkpoint(store, include_audio=False, api_key=None):
    from storage.pixeldrain_service import upload_to_pixeldrain
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    name = f'{_safe_filename(store.book()["title"] if store.book() else "novel")}_checkpoint_{stamp}.zip'
    with tempfile.TemporaryDirectory(prefix='novel-cloud-') as temp:
        path = create_checkpoint(store, Path(temp) / name, include_audio)
        if path.stat().st_size > MAX_ARCHIVE:
            raise ValueError('Checkpoint vượt 2 GB; bỏ chọn kèm audio và xuất audio riêng.')
        result = upload_to_pixeldrain(path, name, api_key=api_key)
    (data_dir() / 'cloud_checkpoint_last.json').write_text(json.dumps({
        'url': result['url'], 'id': result['id'], 'created_at': datetime.now(timezone.utc).isoformat()
    }), 'utf-8')
    return result


def parse_pixeldrain_id(value):
    value = value.strip()
    if value.startswith('https://'):
        parsed = urlsplit(value)
        if parsed.netloc != 'pixeldrain.com' or parsed.query or parsed.fragment:
            raise ValueError('Chỉ nhận link https://pixeldrain.com/u/ID hoặc ID file.')
        match = re.fullmatch(r'/(?:u|api/file)/([A-Za-z0-9_-]{4,64})', parsed.path)
        value = match.group(1) if match else ''
    if not re.fullmatch(r'[A-Za-z0-9_-]{4,64}', value):
        raise ValueError('ID Pixeldrain không hợp lệ.')
    return value


def download_checkpoint(value, destination):
    file_id = parse_pixeldrain_id(value)
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            raise ValueError('Không cho phép chuyển hướng khi tải checkpoint.')
    opener = urllib.request.build_opener(NoRedirect)
    req = urllib.request.Request(f'https://pixeldrain.com/api/file/{file_id}', headers={'User-Agent': 'NovelReader/4.4'})
    with opener.open(req, timeout=120) as response, Path(destination).open('wb') as out:
        total = 0
        while chunk := response.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_ARCHIVE:
                raise ValueError('Checkpoint vượt giới hạn 2 GB.')
            out.write(chunk)
    return Path(destination)


def restore_checkpoint(store, archive_path):
    """Validate everything first; copy only data rows, never untrusted SQL schema.

    Restored exports get a fresh folder. Previous exports remain untouched, and DB
    replacement is a single transaction. Existing runtime Store/job objects stay valid.
    """
    if Path(archive_path).stat().st_size > MAX_ARCHIVE:
        raise ValueError('Checkpoint vượt giới hạn 2 GB.')
    with tempfile.TemporaryDirectory(prefix='novel-restore-') as temp:
        stage = Path(temp)
        with zipfile.ZipFile(archive_path) as archive:
            members = archive.infolist()
            names = [m.filename for m in members]
            if len(members) > 100000 or len(names) != len(set(names)) or sum(m.file_size for m in members) > MAX_EXPANDED:
                raise ValueError('ZIP quá lớn hoặc có file trùng lặp.')
            for member in members:
                path = PurePosixPath(member.filename)
                valid = (member.filename in {'manifest.json', 'data/novel.sqlite3', 'workspace_draft.json'}
                         or (len(path.parts) >= 2 and path.parts[0] in {'text', 'audio'} and path.suffix.lower() in (TEXT_EXT if path.parts[0] == 'text' else AUDIO_EXT)))
                if not valid or path.is_absolute() or '..' in path.parts or '\\' in member.filename or member.is_dir() or (member.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError('Đường dẫn/nội dung ZIP không hợp lệ.')
                if member.filename == 'manifest.json' and member.file_size > 16 * 1024**2:
                    raise ValueError('Manifest quá lớn.')
            if 'manifest.json' not in names or 'data/novel.sqlite3' not in names:
                raise ValueError('Không phải checkpoint NovelReader v1. Hãy dùng ZIP tạo từ mục Checkpoint & bảng tạm.')
            manifest = json.loads(archive.read('manifest.json'))
            if manifest.get('format') != 'novelreader-checkpoint' or manifest.get('version') != 1:
                raise ValueError('Phiên bản checkpoint không được hỗ trợ.')
            checks = manifest.get('sha256', {})
            if not isinstance(checks, dict) or set(checks) != set(names) - {'manifest.json'}:
                raise ValueError('Manifest không khớp nội dung ZIP.')
            for member in members:
                if member.filename == 'manifest.json':
                    continue
                dest = stage.joinpath(*PurePosixPath(member.filename).parts)
                dest.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as src, dest.open('wb') as out:
                    shutil.copyfileobj(src, out, 1024 * 1024)
                if digest(dest) != checks[member.filename]:
                    raise ValueError('Checkpoint bị hỏng: SHA256 không khớp.')
        with sqlite3.connect((stage / 'data/novel.sqlite3').as_uri() + '?mode=ro&immutable=1', uri=True) as db:
            db.row_factory = sqlite3.Row
            if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise ValueError('SQLite checkpoint bị hỏng.')
            schema = db.execute("SELECT type, name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
            if {(s['type'], s['name']) for s in schema} != {('table', 'book'), ('table', 'chapter')}:
                raise ValueError('Schema checkpoint không hợp lệ.')
            books = db.execute('SELECT * FROM book').fetchall()
            if len(books) != 1:
                raise ValueError('Checkpoint phải chứa đúng một truyện.')
            book = dict(books[0])
            config = clean_config(json.loads(book.get('config') or '{}'))
            rows = [dict(row) for row in db.execute('SELECT * FROM chapter ORDER BY position')]
        for row in rows:
            if row['status'] not in {'done', 'pending', 'translating', 'error'} or row['audio_status'] not in {'none', 'queued', 'generating', 'done', 'error'}:
                raise ValueError('Trạng thái chương không hợp lệ.')
            for key in ('source', 'plan', 'outputs', 'translated'):
                if not isinstance(json.loads(row[key] or '[]'), list):
                    raise ValueError('Dữ liệu chương không hợp lệ.')
        draft_file = stage / 'workspace_draft.json'
        draft = clean_config(json.loads(draft_file.read_text('utf-8'))) if draft_file.exists() else None
        folder = store._available_folder(_safe_filename(book['title']))
        new_text, new_audio = store._text_root / folder, store._audio_root / folder
        try:
            for kind, destination in [('text', new_text), ('audio', new_audio)]:
                if (stage / kind).exists():
                    shutil.copytree(stage / kind, destination)
                else:
                    destination.mkdir(parents=True)
            from audio.audio_service import get_chapter_audio_path
            with store.connect() as conn:
                conn.execute('DELETE FROM chapter')
                conn.execute('DELETE FROM book')
                conn.execute('INSERT INTO book(id,title,filename,encoding,config,output_folder) VALUES(1,?,?,?,?,?)',
                             (book['title'], book['filename'], book['encoding'], json.dumps(config, ensure_ascii=False), folder))
                columns = ['id', 'position', 'title', 'source', 'status', 'plan', 'outputs', 'translated_title', 'translated', 'error', 'audio_status']
                for row in rows:
                    if row['status'] == 'translating':
                        row['status'] = 'pending'
                    if row['audio_status'] in {'queued', 'generating'} or not get_chapter_audio_path(new_audio, row['id'], row['position']):
                        row['audio_status'] = 'none'
                    conn.execute('INSERT INTO chapter(' + ','.join(columns) + ') VALUES(' + ','.join('?' for _ in columns) + ')', [row[c] for c in columns])
        except Exception:
            shutil.rmtree(new_text, ignore_errors=True)
            shutil.rmtree(new_audio, ignore_errors=True)
            raise
        if draft is not None:
            save_draft(draft)
        else:
            draft_path().unlink(missing_ok=True)
        return {'ok': True, 'chapters': len(rows), 'message': 'Đã khôi phục checkpoint. Audio không có trong ZIP sẽ được tạo lại khi tiếp tục.'}
