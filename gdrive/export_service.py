"""User-requested exports staged locally, then copied/uploaded to Google Drive.
Colab uses the kernel's native mount; Kaggle uses private API OAuth credentials
managed by api_drive. Original output is retained in either mode.
"""
import json
import os
import re
import shutil
import threading
import time
import uuid
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


def drive_backend():
    explicit = os.getenv('NOVEL_DRIVE_BACKEND', '').strip().lower()
    if explicit in {'api','colab','disabled'}:
        return explicit
    if os.getenv('KAGGLE_KERNEL_RUN_TYPE') or os.getenv('KAGGLE_URL_BASE') or Path('/kaggle/working').is_dir():
        return 'api'
    return 'colab' if os.getenv('NOVEL_COLAB_DRIVE_BRIDGE') == '1' else 'disabled'


def bridge_enabled():
    return drive_backend() in {'colab','api'}


def stage_export(store, kind, directory):
    """Snapshot TXT/EPUB or individual audio files; never ZIP a Drive export."""
    with store.connect() as conn:
        conn.execute('BEGIN')
        book = conn.execute('SELECT * FROM book LIMIT 1').fetchone()
        rows = conn.execute('SELECT * FROM chapter ORDER BY position').fetchall()
    if not book:
        raise ValueError('Chưa có truyện')
    book = dict(book)
    folder = _safe_filename(book.get('output_folder') or book['title'])
    filename = 'audio' if kind == 'audio' else _safe_filename(book['title']) + '.' + kind
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
        from audio.audio_service import exportable_audio_files
        files = exportable_audio_files(audio_dir)
        if not files:
            raise ValueError('Chưa có file audio nào để xuất')
        target.mkdir(parents=True, exist_ok=True)
        for path in files:
            snapshot = target / path.relative_to(audio_dir)
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, snapshot)
    else:
        raise ValueError('Chỉ hỗ trợ TXT, EPUB hoặc các file audio')
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


def _atomic_copy(source, destination):
    temp = destination.with_name('.' + destination.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        shutil.copy2(source, temp)
        os.replace(temp, destination)
    finally:
        temp.unlink(missing_ok=True)


def _run(task_id, store, job_lock):
    work = tasks_dir() / task_id
    work.mkdir(exist_ok=True)
    try:
        task = read_task(task_id)
        with job_lock:
            if (store.book() or {}).get('output_folder') != task['book_folder']:
                raise RuntimeError('Truyện hiện tại đã thay đổi. Hãy bấm xuất lại.')
            file, folder = stage_export(store, task['format'], work)
        batch_name = time.strftime('%Y%m%d_%H%M%S') + '_' + task_id[:8]
        if task['format'] == 'audio':
            task.update(total_files=sum(p.is_file() for p in file.rglob('*')), uploaded_files=0,
                        drive_path=f'NovelReader_Exports/{folder}/audio/{batch_name}')
            write_task(task)
        backend = drive_backend()
        if backend == 'api':
            from gdrive import api_drive
            task.update(status='uploading', message='Đang tải lên Drive bằng API (không mount)…')
            write_task(task)
            def progress(percent):
                task['message'] = f'Đang tải lên Drive: {percent}%'
                write_task(task)
            if task['format'] == 'audio':
                def audio_progress(completed, total, name, percent):
                    task.update(uploaded_files=completed, total_files=total,
                                message=f'Đang tải audio {completed}/{total}: {name} ({percent}%)')
                    write_task(task)
                result = api_drive.upload_audio(file, folder, batch_name, audio_progress)
            else:
                filename = batch_name + '_' + file.name
                result = api_drive.upload(file, folder, filename, progress)
            task.update(status='done', message='Đã lưu Google Drive; bản gốc vẫn được giữ.', **result)
            write_task(task)
            return
        task.update(status='waiting_permission', message='Quay lại tab Colab và cho phép kết nối Google Drive. Nếu đã kết nối, sẽ lưu ngay.')
        write_task(task)
        wait_for_permission(task_id)
        task = read_task(task_id)
        task.update(status='uploading', message='Đang sao chép bản xuất lên Google Drive…')
        write_task(task)
        drive_root = Path(os.getenv('NOVEL_COLAB_DRIVE_ROOT', '/content/drive/MyDrive'))
        if not drive_root.is_dir():
            raise RuntimeError('Drive chưa được mount hoặc đã mất kết nối; bản gốc vẫn còn ở Colab.')
        dest_dir = drive_root / 'NovelReader_Exports' / folder
        dest_dir.mkdir(parents=True, exist_ok=True)
        if task['format'] == 'audio':
            destination = dest_dir / 'audio' / batch_name
            destination.mkdir(parents=True, exist_ok=True)
            for index, source in enumerate(sorted(p for p in file.rglob('*') if p.is_file()), 1):
                dest_file = destination / source.relative_to(file)
                dest_file.parent.mkdir(parents=True, exist_ok=True)
                _atomic_copy(source, dest_file)
                task.update(uploaded_files=index, message=f'Đã lưu audio {index}/{task["total_files"]}: {source.name}')
                write_task(task)
        else:
            destination = dest_dir / (batch_name + '_' + file.name)
            _atomic_copy(file, destination)
        task.update(status='done', message='Đã lưu vào Google Drive; bản gốc được giữ nguyên.',
                    drive_path=str(destination.relative_to(drive_root)),
                    drive_url='https://drive.google.com/drive/u/0/my-drive')
        write_task(task)
    except Exception as exc:
        task = read_task(task_id)
        message = str(exc)[:400]
        if task.get('format') == 'audio' and task.get('uploaded_files'):
            message += f' Đã lưu {task["uploaded_files"]}/{task.get("total_files", 0)} file audio; các file đã lưu và bản gốc vẫn giữ nguyên.'
        task.update(status='error', message=message)
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
    if drive_backend() == 'api':
        from gdrive import api_drive
        if not api_drive.status()['connected']:
            raise ValueError('Chưa kết nối Google Drive API. Bấm Kết nối Drive trong Web trước khi xuất.')
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
