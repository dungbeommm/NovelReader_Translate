"""Audio consumer queue, bounded backlog, multi-worker support, and deterministic shutdown.

Only the translation producer mutates the book scope. The job stays active until
close() joins the consumer workers, so reset/delete/rename cannot race audio output.
"""
import queue
import threading


class AudioQueue:
    def __init__(self, consume, checkpoint, cancel, maxsize=2, workers=1):
        self.consume = consume
        self.checkpoint = checkpoint
        self.cancel = cancel
        self.queue = queue.Queue(maxsize=maxsize)
        self.error = None
        self.closed = False
        self.workers = []
        for i in range(max(1, int(workers))):
            t = threading.Thread(target=self._run, name=f'chapter-audio-{i}', daemon=True)
            t.start()
            self.workers.append(t)

    @property
    def worker(self):
        """Backward compatibility for checks like `q.worker.is_alive()`."""
        return self.workers[0] if self.workers else None

    def submit(self, item):
        if self.closed:
            raise RuntimeError('Audio queue is closed')
        while any(w.is_alive() for w in self.workers):
            if self.error:
                raise RuntimeError('Audio worker failed') from self.error
            if not self.checkpoint():
                self.cancel(item)
                return False
            try:
                self.queue.put(item, timeout=0.2)
                return True
            except queue.Full:
                continue
        raise RuntimeError('Audio worker stopped unexpectedly') from self.error

    def _run(self):
        while True:
            item = self.queue.get()
            try:
                if item is None:
                    return
                if self.error is not None or not self.checkpoint():
                    self.cancel(item)
                else:
                    self.consume(item)
            except Exception as exc:
                self.error = exc
            finally:
                self.queue.task_done()

    def close(self):
        if not self.closed:
            self.closed = True
            for _ in self.workers:
                self.queue.put(None)
            for w in self.workers:
                w.join()
        if self.error:
            raise RuntimeError('Audio worker failed') from self.error
