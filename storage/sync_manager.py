"""Checkpoint uploader with periodic snapshots and a final flush per job."""
import logging
import threading
import time

log = logging.getLogger(__name__)


class CloudSyncManager:
    def __init__(self, store, on_success, on_error, *, enabled=False,
                 every=10, minutes=10):
        self.store = store
        self.on_success = on_success
        self.on_error = on_error
        self.enabled = bool(enabled)
        self.every = max(1, int(every))
        self.period = max(60, int(minutes) * 60)
        self.completed = 0
        self.submitted = 0
        self.last_started = time.monotonic()
        self.thread = None

    def _upload(self, include_audio=False):
        try:
            from storage.checkpoints import upload_checkpoint
            result = upload_checkpoint(self.store, include_audio=include_audio)
            self.on_success(result)
        except Exception as exc:
            log.exception("Hugging Face checkpoint upload failed")
            self.on_error(str(exc)[:300])

    def chapter_done(self):
        if not self.enabled:
            return
        self.completed += 1
        now = time.monotonic()
        if self.completed - self.submitted < self.every and now - self.last_started < self.period:
            return
        if self.thread is not None and self.thread.is_alive():
            return
        self.thread = threading.Thread(
            target=self._upload, name="hf-checkpoint", daemon=True)
        self.thread.start()
        self.submitted = self.completed
        self.last_started = now

    def finish(self, include_audio=False):
        if self.thread is not None:
            self.thread.join()
        if self.enabled:
            self._upload(include_audio=include_audio)
