"""Cross-process lease and atomic, non-secret job snapshots."""
import json
import os
import tempfile
from pathlib import Path


class JobLease:
    """At most one translation worker can own a given database's job.lock."""
    def __init__(self, path):
        self.path = Path(path)
        self._file = None

    @staticmethod
    def _try_lock(handle):
        if os.name == "nt":
            import msvcrt
            try:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                return True
            except OSError:
                return False
        import fcntl
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False

    @staticmethod
    def _unlock(handle):
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _open(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        return handle

    @property
    def owned(self):
        return self._file is not None

    def acquire(self):
        if self.owned:
            return False
        handle = self._open()
        if not self._try_lock(handle):
            handle.close()
            return False
        self._file = handle
        return True

    def held_by_another(self):
        if self.owned:
            return False
        handle = self._open()
        try:
            if not self._try_lock(handle):
                return True
            self._unlock(handle)
            return False
        finally:
            handle.close()

    def release(self):
        handle = self._file
        self._file = None
        if handle is not None:
            try:
                self._unlock(handle)
            finally:
                handle.close()


def state_path(database_path):
    return Path(database_path).with_name("job_state.json")


def read_state(database_path):
    try:
        data = json.loads(state_path(database_path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_state(database_path, progress):
    target = state_path(database_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=target.parent, prefix=".job-state-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(progress, f, ensure_ascii=False)
        os.replace(name, target)
    finally:
        Path(name).unlink(missing_ok=True)
