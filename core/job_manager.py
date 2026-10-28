"""One active novel job per database, across Marimo and FastAPI processes."""
from workflows.jobs import Job
from core.state_manager import JobLease, read_state, write_state


class ManagedJob(Job):
    def __init__(self, store):
        super().__init__(store)
        self.lease = JobLease(store.path.with_name("job.lock"))

    @property
    def active(self):
        return super().active or self.lease.held_by_another()

    def summary(self):
        local = super().summary()
        if self.lease.held_by_another():
            remote = read_state(self.store.path)
            for key in ("status", "message", "scope", "done", "total"):
                if key in remote:
                    local[key] = remote[key]
            local["active"] = True
            if local["status"] in ("ready", "stopped"):
                local["status"] = "running"
        return local

    def _persist(self):
        if self.lease.owned:
            write_state(self.store.path, super().summary())

    def emit(self, type, **data):
        self._persist()
        super().emit(type, **data)

    def start(self, config, reset=False):
        if not self.lease.acquire():
            raise ValueError("Một tiến trình NovelReader khác đang chạy; không thể khởi động job thứ hai.")
        try:
            result = super().start(config, reset)
            self._persist()
            return result
        except BaseException:
            self.lease.release()
            raise

    def run(self, config, glossary, target_chapter_ids=None):
        try:
            return super().run(config, glossary, target_chapter_ids)
        finally:
            self._persist()
            self.lease.release()

    def pause(self):
        result = super().pause()
        self._persist()
        return result

    def resume(self):
        result = super().resume()
        self._persist()
        return result

    def stop(self):
        result = super().stop()
        self._persist()
        return result
