"""Interactive MoLab controller. No HTTP listener, tunnel, or keep-alive service."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile


def safe_error(error):
    message = str(error)
    for key in ('HF_TOKEN', 'HUGGING_FACE_HUB_TOKEN', 'ZROK_ACCOUNT_TOKEN'):
        secret = os.getenv(key, '')
        if secret:
            message = message.replace(secret, '[REDACTED]')
    return re.sub(r'hf_[A-Za-z0-9]+', '[REDACTED]', message)[:600]


class NativeController:
    def __init__(self, runtime):
        self.runtime = runtime
        self.notice = 'Sẵn sàng. Nạp truyện hoặc khôi phục checkpoint để tiếp tục.'

    @property
    def store(self):
        return self.runtime.store

    @property
    def job(self):
        return self.runtime.job

    def _idle(self):
        if self.job.active:
            raise ValueError('Hãy dừng tác vụ và đợi hoàn tất trước khi thay đổi truyện hoặc khôi phục.')

    def saved_config(self):
        from web.schemas import Config
        book = self.store.book()
        raw = json.loads(book['config'] or '{}') if book else {}
        return Config.model_validate(raw).model_dump() if raw else Config(batch_size=8).model_dump()

    def load_book(self, name, content):
        from storage.files import MAX_FILE, parse_file
        with self.job.lock:
            self._idle()
            if not content or len(content) > MAX_FILE:
                raise ValueError('Tệp truyện phải có nội dung và tối đa 50 MB.')
            name = Path(name.replace('\\', '/')).name
            chapters, encoding = parse_file(name, content)
            self.store.replace(name, encoding, chapters)
            self._restored()
        return f'Đã nạp {len(chapters)} chương.'

    def start(self, settings, bucket=''):
        from web.schemas import Config
        config = Config.model_validate(settings).model_dump(exclude={'reset'})
        with self.job.lock:
            self._idle()
            if config.get('cloud_checkpoint'):
                from storage.cloud_settings import save_repo_id
                from storage.huggingface_service import check_connection
                from storage.checkpoints import upload_checkpoint
                # Protect even a first run interrupted while downloading its models.
                save_repo_id(bucket.strip())
                check_connection()
                upload_checkpoint(self.store, include_audio=config.get('checkpoint_include_audio', False))
            self.job.start(config, reset=False)
        return 'Đang chạy trong notebook. Dùng Cập nhật tiến độ để theo dõi.'

    def control(self, action):
        if action not in {'pause', 'resume', 'stop'}:
            raise ValueError('Lệnh không hợp lệ.')
        getattr(self.job, action)()
        return self.job.summary()['message'] or self.job.status

    def _restored(self):
        self.job.status = 'ready'
        self.job.message = ''
        self.job.target_chapter_ids = None
        self.job.scope_label = ''

    def save_cloud(self, bucket, include_audio=False):
        from storage.cloud_settings import save_repo_id
        from storage.checkpoints import upload_checkpoint
        with self.job.lock:
            self._idle()
            save_repo_id(bucket.strip())
            result = upload_checkpoint(self.store, include_audio=include_audio)
        return 'Đã lưu HF: ' + result['id']

    def list_cloud(self, bucket):
        from itertools import islice
        from storage.cloud_settings import save_repo_id
        from storage.huggingface_service import client, repo_id
        save_repo_id(bucket.strip())
        entries = list(islice(client().list_bucket_tree(repo_id(), prefix='checkpoints/', recursive=True), 2001))
        rows = [{'path': entry.path, 'updated_at': str(getattr(entry, 'uploaded_at', '') or '')}
                for entry in entries[:2000] if entry.path.endswith('.zip')]
        rows.sort(key=lambda row: (row['updated_at'], row['path']), reverse=True)
        return rows[:30]

    def restore_cloud(self, bucket, value):
        from storage.cloud_settings import save_repo_id
        from storage.checkpoints import download_checkpoint, restore_checkpoint
        with self.job.lock:
            self._idle()
            save_repo_id(bucket.strip())
            with tempfile.TemporaryDirectory(prefix='novel-molab-restore-') as work:
                path = download_checkpoint(value, Path(work) / 'checkpoint.zip')
                result = restore_checkpoint(self.store, path)
            self._restored()
        return result['message']

    def restore_file(self, content):
        from storage.checkpoints import MAX_ARCHIVE, restore_checkpoint
        with self.job.lock:
            self._idle()
            if not content or len(content) > MAX_ARCHIVE:
                raise ValueError('Checkpoint phải có nội dung và tối đa 2 GB.')
            with tempfile.TemporaryDirectory(prefix='novel-molab-restore-') as work:
                path = Path(work) / 'checkpoint.zip'
                path.write_bytes(content)
                result = restore_checkpoint(self.store, path)
            self._restored()
        return result['message']

    def download_checkpoint(self, include_audio=False):
        from paths import data_dir
        from storage.checkpoints import create_checkpoint
        with self.job.lock:
            self._idle()
            path = data_dir() / 'exports' / 'NovelReader_checkpoint.zip'
            path.parent.mkdir(parents=True, exist_ok=True)
            create_checkpoint(self.store, path, include_audio=include_audio)
        return path

    def snapshot(self):
        from paths import data_dir
        import psutil
        state = self.job.summary()
        rows = self.store.list()
        state['audio_done'] = sum(row['audio_status'] == 'done' for row in rows)
        state['book'] = (self.store.book() or {}).get('title', '(chưa nạp truyện)')
        # Process RSS is real consumption, not the misleading host RAM percentage.
        try:
            state['process_ram_mib'] = round(psutil.Process().memory_info().rss / 2**20, 1)
        except (psutil.Error, OSError):
            state['process_ram_mib'] = 'không đọc được'
        try:
            state['last_cloud'] = json.loads((data_dir() / 'cloud_checkpoint_last.json').read_text('utf-8'))
        except (OSError, ValueError):
            state['last_cloud'] = None
        state['cloud_error'] = safe_error(getattr(self.job, 'cloud_error', ''))
        return state

    def invoke(self, callback):
        try:
            self.notice = callback()
        except Exception as exc:
            self.notice = 'Lỗi: ' + safe_error(exc)
        return self.notice


_controller = None


def initialize():
    """Rerunning an initialization cell adopts the existing worker in this kernel."""
    global _controller
    if _controller is None:
        from core import runtime
        runtime.initialize()
        _controller = NativeController(runtime)
    return _controller
