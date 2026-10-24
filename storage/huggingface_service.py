"""Exports and checkpoints in the single NovelReader Hugging Face dataset."""
import json
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote, urlsplit

from huggingface_hub import HfApi, hf_hub_download
from storage.cloud_settings import load_key
from storage.files import export_txt, export_epub
from storage.store import _safe_filename

REPO_ID = 'uri410/novelreader-storage'
REPO_TYPE = 'dataset'
ENDPOINT = 'https://huggingface.co'
BASE_URL = f'{ENDPOINT}/datasets/{REPO_ID}'


def client():
    token = load_key()
    if not token:
        raise ValueError('Chưa cấu hình HF_TOKEN phía máy chủ.')
    return HfApi(endpoint=ENDPOINT, token=token)


def check_connection():
    info = client().repo_info(repo_id=REPO_ID, repo_type=REPO_TYPE)
    return {'ok': True, 'repo_id': REPO_ID, 'private': info.private,
            'message': f'Đã kết nối {REPO_ID}.'}


def batch_path(title, category):
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    return f'{category}/{_safe_filename(title)}/{stamp}_{uuid.uuid4().hex[:12]}'


def result(path, filename, size, *, directory=False, files=1):
    url = f'{BASE_URL}/{"tree" if directory else "blob"}/main/{quote(path, safe="/")}'
    return {'ok': True, 'repo_id': REPO_ID, 'id': path, 'path': path,
            'url': url, 'filename': filename, 'size_bytes': size,
            'size_mb': round(size / 1024**2, 2), 'total_files': files}


def upload_file(source, filename, *, category='exports', title='novel'):
    path = f'{batch_path(title, category)}/{Path(filename).name}'
    client().upload_file(path_or_fileobj=source, path_in_repo=path,
                         repo_id=REPO_ID, repo_type=REPO_TYPE,
                         commit_message=f'NovelReader {category}: {filename}')
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
    # Snapshot only finished audio; upload_folder never sees credentials or temp files.
    with tempfile.TemporaryDirectory(prefix='novel-hf-audio-') as work:
        size = 0
        for source in files:
            target = Path(work) / source.relative_to(store.audio_dir)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            size += target.stat().st_size
        client().upload_folder(folder_path=work, path_in_repo=path,
                               repo_id=REPO_ID, repo_type=REPO_TYPE,
                               commit_message=f'NovelReader audio: {title}')
    return result(path, title, size, directory=True, files=len(files))


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
        prefix = f'/datasets/{REPO_ID}/'
        if parsed.netloc != 'huggingface.co' or parsed.query or parsed.fragment or not parsed.path.startswith(prefix):
            raise ValueError('Chỉ nhận checkpoint trong kho Hugging Face cố định.')
        suffix = parsed.path[len(prefix):]
        if not suffix.startswith(('blob/main/', 'resolve/main/')):
            raise ValueError('Link checkpoint không hợp lệ.')
        value = unquote(suffix.split('/', 2)[2])
    path = PurePosixPath(value)
    if (path.is_absolute() or '..' in path.parts or '\\' in value or ':' in value
            or not value.startswith('checkpoints/') or path.suffix != '.zip'
            or str(path) != value):
        raise ValueError('Đường dẫn checkpoint không hợp lệ.')
    return value


def download_checkpoint(value, destination, max_bytes):
    filename = checkpoint_path(value)
    api = client()
    # Pin metadata and download to the same revision to avoid a size-check race.
    revision = api.repo_info(REPO_ID, repo_type=REPO_TYPE).sha
    info = api.get_paths_info(REPO_ID, [filename], repo_type=REPO_TYPE, revision=revision)
    if len(info) != 1 or not isinstance(getattr(info[0], 'size', None), int) or info[0].size > max_bytes:
        raise ValueError('Checkpoint không tồn tại hoặc vượt giới hạn 2 GB.')
    cached = hf_hub_download(repo_id=REPO_ID, filename=filename, repo_type=REPO_TYPE,
                             revision=revision, token=load_key(), endpoint=ENDPOINT)
    if Path(cached).stat().st_size > max_bytes:
        raise ValueError('Checkpoint vượt giới hạn 2 GB.')
    shutil.copyfile(cached, destination)
    return Path(destination)
