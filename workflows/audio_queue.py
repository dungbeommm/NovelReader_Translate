"""One audio consumer, bounded backlog, and deterministic shutdown.

Only the translation producer mutates the book scope. The job stays active until
close() joins the consumer, so reset/delete/rename cannot race audio output.
"""
import queue
import threading


class AudioQueue:
    def __init__(self, consume, checkpoint, cancel, maxsize=2):
        self.consume = consume
        self.checkpoint = checkpoint
        self.cancel = cancel
        self.queue = queue.Queue(maxsize=maxsize)
        self.error = None
        self.closed = False
        self.worker = threading.Thread(target=self._run, name='chapter-audio', daemon=True)
        self.worker.start()

    def submit(self, item):
        if self.closed:
            raise RuntimeError('Audio queue is closed')
        while self.worker.is_alive():
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
                # Do not abandon a full queue and deadlock its producer.
                self.error = exc
            finally:
                self.queue.task_done()

    def close(self):
        if not self.closed:
            self.closed = True
            self.queue.put(None)
            self.worker.join()
        if self.error:
            raise RuntimeError('Audio worker failed') from self.error
