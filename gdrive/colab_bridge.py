"""Run ONLY from the Colab notebook kernel, never the Uvicorn subprocess."""
import json
import os
from pathlib import Path
from gdrive.export_service import read_task, write_task, drive_backend


def process_drive_requests(directory, mount_drive, mountpoint='/content/drive'):
    """Authorization UI is rendered by Colab, not faked inside a tunnel tab.

    mount_drive is google.colab.drive.mount, injectable for CPU-only tests.
    Consent is requested only after an explicit export click.
    """
    if drive_backend() != 'colab':
        return 0
    directory = Path(directory)
    if not directory.is_dir():
        return 0
    waiting = []
    for file in sorted(directory.glob('*.json')):
        try:
            task = read_task(file.stem)
            if task.get('status') == 'waiting_permission' and task.get('session_id', '') == os.getenv('NOVEL_EXPORT_SESSION_ID', ''):
                waiting.append(task['id'])
        except (ValueError, OSError, json.JSONDecodeError):
            continue
    if not waiting:
        return 0
    error = None
    try:
        print('Có yêu cầu xuất file: hãy cho phép kết nối Google Drive trong tab Colab.', flush=True)
        mount_drive(mountpoint)
        if not (Path(mountpoint) / 'MyDrive').is_dir():
            raise RuntimeError('Không tìm thấy MyDrive sau khi cấp quyền')
    except Exception as exc:
        error = str(exc)[:350]
    processed = 0
    for task_id in waiting:
        task = read_task(task_id)
        if task.get('status') != 'waiting_permission':
            continue
        task.update(status='auth_error' if error else 'authorized',
                    message=('Cấp quyền Drive chưa thành công: ' + error) if error else 'Đã kết nối Drive')
        write_task(task)
        processed += 1
    return processed
