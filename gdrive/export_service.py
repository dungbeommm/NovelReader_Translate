"""User-requested exports staged locally, then copied to Colab-mounted Drive.
No OAuth credentials cross the Web UI. Only the notebook kernel can request the
interactive Colab Drive mount. Original output is retained.
"""
import json
import os
import re
import shutil
import threading
import time
import uuid
import zipfile
from pathlib import Path
from storage.files import export_txt, export_epub
from storage.store import _safe_filename
from paths import data_dir

_lock = threading.RLock()
_active = set()
FORMATS = {'txt', 'epub', 'audio'}
TERMINAL = {'done', 'error'}


def tasks_dir():
    path = data_dir() / 'drive_exports'
    path.mkdir(parents=True, exist_ok=True)
    return path


def task_path(task_id):
    if not re.fullmatch(r'[a-f0-9]{32}', task_id):
        raise ValueError('Mã xuất không hợp lệ')
    return tasks_dir() / (task_id + '.json')


def read_task(task_id):
    path = task_path(task_id)
    if not path.is_file():
        raise FileNotFoundError('Không tìm thấy tác vụ xuất')
    return json.loads(path.read_text(encoding='utf-8'))


def write_task(task):
    path = task_path(task['id'])
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temp.write_text(json.dumps(task, ensure_ascii=False), encoding='utf-8')
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def bridge_enabled():
    return os.getenv('NOVEL_COLAB_DRIVE_BRIDGE') == '1'


def stage_export(store, kind, directory):
    """Disk-backed audio ZIP (no whole-book audio ZIP in Python RAM)."""
    with store.connect() as conn:
        conn.execute('BEGIN')
        book = conn.execute('SELECT * FROM book LIMIT 1').fetchone()
        rows = conn.execute('SELECT * FROM chapter ORDER BY position').fetchall()
    if not book:
        raise ValueError('Chưa có truyện')
    book = dict(book)
    folder = _safe_filename(book.get('output_folder') or book['title'])
    filename = _safe_filename(book['title']) + ('_audio.zip' if kind == 'audio' else '.' + kind)
    target = directory / filename
    if kind in {'txt', 'epub'}:
        chapters = []
        for row in rows:
            chapter = dict(row)
            chapter['translated'] = json.loads(chapter['translated'] or '[]')
            chapters.append(chapter)
        target.write_bytes((export_txt if kind == 'txt' else export_epub)(book, chapters))
    elif kind == 'audio':
        audio_dir = store.audio_dir
        files = [p for p in sorted(audio_dir.rglob('*'))
                 if p.is_file() and not p.is_symlink()
                 and p.suffix.lower() in {'.mp3', '.wav', '.m4b', '.m4a', '.opus'}
                 and not any(part.startswith('.') for part in p.relative_to(audio_dir).parts)]
        if not files:
            raise ValueError('Chưa có file audio nào để xuất')
        with zipfile.ZipFile(target, 'w', zipfile.ZIP_STORED, allowZip64=True) as archive:
            for path in files:
                archive.write(path, str(path.relative_to(audio_dir)))
    else:
        raise ValueError('Chỉ hỗ trợ TXT, EPUB hoặc audio ZIP')
    return target, folder


def wait_for_permission(task_id, timeout=300):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        task = read_task(task_id)
        if task['status'] == 'authorized':
            return
        if task['status'] in {'auth_error', 'error'}:
            raise RuntimeError(task.get('message') or 'Chưa được cấp quyền Google Drive')
        time.sleep(.5)
    raise TimeoutError('Hết thời gian chờ cấp quyền. Quay lại Colab cấp quyền Drive rồi bấm xuất lại.')


def _run(task_id, store, job_lock):
    work = tasks_dir() / task_id
    work.mkdir(exist_ok=True)
    try:
        task = read_task(task_id)
        with job_lock:
            if (store.book() or {}).get('output_folder') != task['book_folder']:
                raise RuntimeError('Truyện hiện tại đã thay đổi. Hãy bấm xuất lại.')
            file, folder = stage_export(store, task['format'], work)
        task.update(status='waiting_permission', message='Quay lại tab Colab và cho phép kết nối Google Drive. Nếu đã kết nối, sẽ lưu ngay.')
        write_task(task)
        wait_for_permission(task_id)
        task = read_task(task_id)
        task.update(status='uploading', message='Đang sao chép bản xuất lên Google Drive…')
        write_task(task)
        # Fixed by the notebook, never accepted as a user-supplied request path.
        drive_root = Path(os.getenv('NOVEL_COLAB_DRIVE_ROOT', '/content/drive/MyDrive'))
        if not drive_root.is_dir():
            raise RuntimeError('Drive chưa được mount hoặc đã mất kết nối; bản gốc vẫn còn ở Colab.')
        dest_dir = drive_root / 'NovelReader_Exports' / folder
        dest_dir.mkdir(parents=True, exist_ok=True)
        destination = dest_dir / (time.strftime('%Y%m%d_%H%M%S') + '_' + task_id[:8] + '_' + file.name)
        temp = destination.with_name('.' + destination.name + '.tmp')
        try:
            shutil.copy2(file, temp)
            os.replace(temp, destination)
        finally:
            temp.unlink(missing_ok=True)
        task.update(status='done', message='Đã lưu vào Google Drive; bản gốc được giữ nguyên.',
                    drive_path=str(destination.relative_to(drive_root)),
                    drive_url='https://drive.google.com/drive/u/0/my-drive')
        write_task(task)
    except Exception as exc:
        task = read_task(task_id)
        task.update(status='error', message=str(exc)[:500])
        write_task(task)
    finally:
        shutil.rmtree(work, ignore_errors=True)
        with _lock:
            _active.discard(task_id)


def start_export(kind, store, job_lock):
    if kind not in FORMATS:
        raise ValueError('Định dạng xuất không hợp lệ')
    if not bridge_enabled():
        raise ValueError('Xuất Drive một chạm cần chạy notebook Colab mới. Vẫn có thể chọn Tải về máy.')
    book = store.book()
    if not book:
        raise ValueError('Chưa có truyện')
    with _lock:
        if len(_active) >= 2:
            raise ValueError('Đang có hai tác vụ xuất. Đợi hoàn tất rồi thử lại.')
        task = {'id': uuid.uuid4().hex, 'format': kind, 'status': 'preparing',
                'message': 'Đang chuẩn bị bản xuất…', 'book_folder': book.get('output_folder'),
                'created_at': time.time(), 'session_id': os.getenv('NOVEL_EXPORT_SESSION_ID', '')}
        write_task(task)
        _active.add(task['id'])
        threading.Thread(target=_run, args=(task['id'], store, job_lock),
                         daemon=True, name='drive-export').start()
        return task
