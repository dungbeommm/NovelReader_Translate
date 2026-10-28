"""Exports and checkpoints in the single NovelReader Hugging Face bucket."""
import json
import shutil
import tempfile
import uuid
from itertools import islice
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote, urlsplit

from huggingface_hub import BucketFolder, HfApi
from storage.cloud_settings import load_key
from storage.files import export_txt, export_epub
from storage.store import _safe_filename

REPO_ID = 'uri410/novelreader-storage'
REPO_TYPE = 'bucket'
ENDPOINT = 'https://huggingface.co'
BASE_URL = f'{ENDPOINT}/buckets/{REPO_ID}'


def client():
    token = load_key()
    if not token:
        raise ValueError('Chưa cấu hình HF_TOKEN phía máy chủ.')
    return HfApi(endpoint=ENDPOINT, token=token)


def check_connection():
    api = client()
    info = api.bucket_info(REPO_ID)
    account = api.whoami()
    return {'ok': True, 'repo_id': REPO_ID, 'private': info.private,
            'username': account.get('name') if isinstance(account, dict) else None,
            'message': f'Đã kết nối {REPO_ID}.'}


def repository_path(value, *, allow_root=True):
    if (not isinstance(value, str) or len(value) > 1024 or '\\' in value or ':' in value
            or any(ord(c) < 32 for c in value) or value != value.strip()
            or (not value and not allow_root)):
        raise ValueError('Đường dẫn kho không hợp lệ.')
    if value and (PurePosixPath(value).is_absolute() or
                  any(part in {'', '.', '..'} for part in value.split('/'))):
        raise ValueError('Đường dẫn kho không hợp lệ.')
    return value


def _path_taken(api, path):
    if any(True for _ in islice(api.get_bucket_paths_info(REPO_ID, [path]), 1)):
        return True
    return any(True for _ in islice(api.list_bucket_tree(REPO_ID, prefix=path + '/', recursive=True), 1))


def list_directory(path=''):
    path = repository_path(path)
    entries = list(islice(client().list_bucket_tree(
        REPO_ID, prefix=path or None, recursive=False), 501))
    rows = []
    for entry in entries[:500]:
        name = PurePosixPath(entry.path).name
        if name == '.gitkeep':
            continue
        folder = isinstance(entry, BucketFolder)
        timestamp = getattr(entry, 'uploaded_at', None)
        rows.append({'name': name, 'path': entry.path, 'directory': folder,
                     'size': None if folder else entry.size,
                     'updated_at': timestamp.isoformat() if timestamp else None})
    rows.sort(key=lambda row: (not row['directory'], row['name'].casefold()))
    return {'path': path, 'entries': rows, 'truncated': len(entries) > 500,
            'file_bytes': sum(row['size'] or 0 for row in rows),
            'repo_id': REPO_ID}


def upload_to_directory(data, filename, path='', *, folder=False):
    path = repository_path(path)
    name = repository_path(filename, allow_root=False)
    if '/' in name:
        raise ValueError('Tên không được chứa đường dẫn thư mục.')
    destination = f'{path}/{name}' if path else name
    api = client()
    if _path_taken(api, destination):
        raise FileExistsError('Tên đã tồn tại trong thư mục.')
    # Buckets have no empty directories; a zero-byte marker keeps the folder visible.
    target = destination + '/.gitkeep' if folder else destination
    api.batch_bucket_files(REPO_ID, add=[(b'' if folder else data, target)])
    return {'ok': True, 'path': destination}


def download_repository_file(path, destination):
    path = repository_path(path, allow_root=False)
    api = client()
    info = list(api.get_bucket_paths_info(REPO_ID, [path]))
    if len(info) != 1:
        raise ValueError('Không tìm thấy tệp.')
    api.download_bucket_files(REPO_ID, [(info[0], destination)],
                              raise_on_missing_files=True)
    return Path(destination)


def batch_path(title, category):
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    return f'{category}/{_safe_filename(title)}/{stamp}_{uuid.uuid4().hex[:12]}'


def result(path, filename, size, *, files=1):
    url = f'{BASE_URL}/tree/main/{quote(path, safe="/")}'
    return {'ok': True, 'repo_id': REPO_ID, 'id': path, 'path': path,
            'url': url, 'filename': filename, 'size_bytes': size,
            'size_mb': round(size / 1024**2, 2), 'total_files': files}


def upload_file(source, filename, *, category='exports', title='novel'):
    path = f'{batch_path(title, category)}/{Path(filename).name}'
    client().batch_bucket_files(REPO_ID, add=[(source, path)])
    size = len(source) if isinstance(source, bytes) else Path(source).stat().st_size
    return result(path, filename, size)


def export_book(store, kind):
    if kind not in {'txt', 'epub', 'audio'}:
        raise ValueError('Định dạng phải là txt, epub hoặc audio.')
    with store.connect() as conn:
        conn.execute('BEGIN')
        book = conn.execute('SELECT * FROM book LIMIT 1').fetchone()
        rows = conn.execute('SELECT * FROM chapter ORDER BY position').fetchall()
    if not book:
        raise ValueError('Chưa có truyện.')
    book = dict(book)
    title = _safe_filename(book['title'])
    if kind != 'audio':
        chapters = [dict(row) for row in rows]
        for chapter in chapters:
            chapter['translated'] = json.loads(chapter['translated'] or '[]')
        payload = (export_txt if kind == 'txt' else export_epub)(book, chapters)
        return upload_file(payload, f'{title}.{kind}', title=title)
    from audio.audio_service import exportable_audio_files
    files = exportable_audio_files(store.audio_dir)
    if not files:
        raise ValueError('Chưa có audio để xuất.')
    path = batch_path(title, 'audio')
    # Snapshot only finished audio; the upload never sees credentials or temp files.
    with tempfile.TemporaryDirectory(prefix='novel-hf-audio-') as work:
        size = 0
        add = []
        for source in files:
            target = Path(work) / source.relative_to(store.audio_dir)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            size += target.stat().st_size
            add.append((target, f'{path}/{target.relative_to(work).as_posix()}'))
        client().batch_bucket_files(REPO_ID, add=add)
    return result(path, title, size, files=len(files))


def export_audio_file(store, filename):
    if Path(filename).name != filename or '\\' in filename:
        raise ValueError('Tên file không hợp lệ.')
    from audio.audio_service import exportable_audio_files
    matches = [p for p in exportable_audio_files(store.audio_dir) if p.name == filename]
    if len(matches) != 1:
        raise ValueError('Không tìm thấy audio hoặc tên file bị trùng.')
    with tempfile.TemporaryDirectory(prefix='novel-hf-file-') as work:
        snapshot = Path(work) / filename
        shutil.copy2(matches[0], snapshot)
        return upload_file(snapshot, filename, category='audio', title=store.book()['title'])


def checkpoint_path(value):
    value = value.strip()
    if value.startswith('https://'):
        parsed = urlsplit(value)
        prefixes = (f'/buckets/{REPO_ID}/tree/main/', f'/buckets/{REPO_ID}/resolve/')
        prefix = next((p for p in prefixes if parsed.path.startswith(p)), None)
        if (parsed.netloc != 'huggingface.co' or parsed.query or parsed.fragment
                or prefix is None):
            raise ValueError('Chỉ nhận checkpoint trong kho Hugging Face cố định.')
        value = unquote(parsed.path[len(prefix):])
    path = PurePosixPath(value)
    if (path.is_absolute() or '..' in path.parts or '\\' in value or ':' in value
            or not value.startswith('checkpoints/') or path.suffix != '.zip'
            or str(path) != value):
        raise ValueError('Đường dẫn checkpoint không hợp lệ.')
    return value


def download_checkpoint(value, destination, max_bytes):
    filename = checkpoint_path(value)
    api = client()
    info = list(api.get_bucket_paths_info(REPO_ID, [filename]))
    if len(info) != 1 or not isinstance(getattr(info[0], 'size', None), int) or info[0].size > max_bytes:
        raise ValueError('Checkpoint không tồn tại hoặc vượt giới hạn 2 GB.')
    api.download_bucket_files(REPO_ID, [(info[0], destination)],
                              raise_on_missing_files=True)
    if Path(destination).stat().st_size > max_bytes:
        Path(destination).unlink(missing_ok=True)
        raise ValueError('Checkpoint vượt giới hạn 2 GB.')
    return Path(destination)
