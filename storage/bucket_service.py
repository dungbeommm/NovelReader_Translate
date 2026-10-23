"""Versioned NovelReader backups in a Hugging Face Storage Bucket."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import queue
import threading
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from storage.checkpoints import create_checkpoint, download_bucket_checkpoint, restore_checkpoint
from paths import data_dir

BUCKET_ID = os.getenv("NOVEL_HF_BUCKET", "uri410/NovelReader_Cloud_Audio")
BUCKET_URI = f"hf://buckets/{BUCKET_ID}"
_runtime_token: str | None = None


def _token() -> str | None:
    return _runtime_token or os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_HUB_TOKEN") or None


def set_runtime_token(token: str) -> None:
    global _runtime_token
    clean = token.strip()
    if clean and (not clean.startswith("hf_") or len(clean) < 20):
        raise ValueError("Token Hugging Face không đúng định dạng.")
    _runtime_token = clean or None


def _book_id(store) -> str:
    book = store.book() or {}
    digest = hashlib.sha256()
    try:
        with store.connect() as connection:
            rows = connection.execute("SELECT position, title, source FROM chapter ORDER BY position")
            for position, title, source in rows:
                digest.update(str(position).encode("ascii"))
                digest.update(b"\0")
                digest.update(str(title or "").encode("utf-8"))
                digest.update(b"\0")
                digest.update(str(source or "").encode("utf-8"))
                digest.update(b"\0")
        fingerprint = digest.hexdigest()[:20]
    except (AttributeError, OSError):
        # Lightweight stores used by tooling can fall back to the available metadata.
        source = "\n".join((book.get("filename", ""), book.get("title", "")))
        fingerprint = hashlib.sha256(source.encode("utf-8")).hexdigest()[:20]
    return f"novel-{fingerprint}"


def status() -> dict:
    return {"bucket_id": BUCKET_ID, "uri": BUCKET_URI, "configured": True,
            "write_enabled": bool(_token()), "visibility": "public"}


def write_enabled() -> bool:
    return bool(_token())


def _api():
    try:
        from huggingface_hub import HfApi
    except ImportError as exc:
        raise RuntimeError("Cần huggingface-hub có hỗ trợ Storage Buckets.") from exc
    api = HfApi(token=_token())
    if not hasattr(api, "batch_bucket_files"):
        raise RuntimeError("Phiên bản huggingface-hub hiện tại chưa hỗ trợ Storage Buckets.")
    return api


def upload_artifact(store, path: Path, kind: str) -> str:
    if not path.is_file():
        raise FileNotFoundError(path)
    if kind not in {"text", "audio"}:
        raise ValueError("Loại tệp không hợp lệ.")
    book = store.book()
    if not book:
        raise ValueError("Chưa nạp truyện.")
    token = _token()
    if not token:
        raise RuntimeError("Chưa cấu hình HF_TOKEN để ghi vào Bucket.")
    relative = path.relative_to(store.text_dir if kind == "text" else store.audio_dir)
    destination = f"books/{_book_id(store)}/{kind}/{relative.as_posix()}"
    _api().batch_bucket_files(BUCKET_ID, add=[(str(path), destination)])
    return destination


def publish_checkpoint(store, *, include_audio: bool = True) -> dict:
    if not _token():
        raise RuntimeError("Chưa cấu hình HF_TOKEN để ghi vào Bucket.")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    book_id = _book_id(store)
    prefix = f"books/{book_id}/checkpoints"
    name = f"{stamp}-{os.urandom(3).hex()}.zip"
    with tempfile.TemporaryDirectory(prefix="novel-hf-bucket-") as temp:
        archive = create_checkpoint(store, Path(temp) / name, include_audio=include_audio)
        with archive.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        archive_path = f"{prefix}/{name}"
        api = _api()
        api.batch_bucket_files(BUCKET_ID, add=[(str(archive), archive_path)])
        manifest = {
            "format": "novelreader-bucket-checkpoint",
            "version": 1,
            "book_id": book_id,
            "archive": archive_path,
            "sha256": digest,
            "size": archive.stat().st_size,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        manifest_path = f"{prefix}/{name}.json"
        data = json.dumps(manifest, ensure_ascii=False).encode("utf-8")
        # The archive is immutable; publish its manifest only after it succeeds.
        api.batch_bucket_files(BUCKET_ID, add=[(data, manifest_path)])
        latest = json.dumps({"manifest": manifest_path, "created_at": manifest["created_at"]}).encode("utf-8")
        api.batch_bucket_files(BUCKET_ID, add=[(latest, f"books/{book_id}/latest.json")])
    return {"book_id": book_id, "manifest": manifest_path, "created_at": manifest["created_at"]}


def list_books() -> list[dict]:
    from huggingface_hub import download_bucket_files
    api = _api()
    tree = api.list_bucket_tree(BUCKET_ID, prefix="books", recursive=True)
    latest_paths = [item.path for item in tree if item.type == "file" and item.path.endswith("/latest.json")]
    output = []
    for latest_path in latest_paths:
        try:
            with tempfile.TemporaryDirectory(prefix="novel-hf-list-") as temp:
                local = Path(temp) / "latest.json"
                download_bucket_files(BUCKET_ID, files=[(latest_path, str(local))], token=_token())
                latest = json.loads(local.read_text("utf-8"))
            output.append({"book_id": latest_path.split("/")[1], **latest})
        except Exception:
            continue
    return output


def restore_latest(store, book_id: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", book_id):
        raise ValueError("ID truyện không hợp lệ.")
    api = _api()
    latest_path = f"books/{book_id}/latest.json"
    from huggingface_hub import download_bucket_files
    with tempfile.TemporaryDirectory(prefix="novel-hf-restore-meta-") as temp:
        local = Path(temp) / "latest.json"
        download_bucket_files(BUCKET_ID, files=[(latest_path, str(local))], token=_token())
        latest = json.loads(local.read_text("utf-8"))
    manifest_path = latest.get("manifest", "")
    if not manifest_path.startswith(f"books/{book_id}/checkpoints/") or not manifest_path.endswith(".json"):
        raise ValueError("Manifest checkpoint không hợp lệ.")
    with tempfile.TemporaryDirectory(prefix="novel-hf-restore-manifest-") as temp:
        manifest_local = Path(temp) / "manifest.json"
        download_bucket_files(BUCKET_ID, files=[(manifest_path, str(manifest_local))], token=_token())
        manifest = json.loads(manifest_local.read_text("utf-8"))
    if manifest.get("format") != "novelreader-bucket-checkpoint" or manifest.get("book_id") != book_id:
        raise ValueError("Checkpoint không đúng định dạng hoặc truyện.")
    archive_rel = manifest.get("archive", "")
    if not archive_rel.startswith(f"books/{book_id}/checkpoints/") or not archive_rel.endswith(".zip"):
        raise ValueError("Đường dẫn checkpoint không hợp lệ.")
    with tempfile.TemporaryDirectory(prefix="novel-hf-restore-") as temp:
        archive = download_bucket_checkpoint(BUCKET_ID, archive_rel, Path(temp) / "checkpoint.zip", token=_token())
        with archive.open("rb") as source:
            actual = hashlib.file_digest(source, "sha256").hexdigest()
        if actual != manifest.get("sha256"):
            raise ValueError("Checksum checkpoint không khớp.")
        restore_checkpoint(store, archive)
    return {"book_id": book_id, "restored": True, "created_at": manifest.get("created_at")}


def restore_audio(store, book_id: str) -> dict:
    """Fetch previously uploaded audio on demand after a text-first restore."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", book_id) or _book_id(store) != book_id:
        raise ValueError("ID truyện không khớp với truyện đang mở.")
    from huggingface_hub import download_bucket_files

    prefix = f"books/{book_id}/audio"
    tree = _api().list_bucket_tree(BUCKET_ID, prefix=prefix, recursive=True)
    root = Path(store.audio_dir).resolve()
    files = []
    destinations = []
    for item in tree:
        if item.type != "file" or not item.path.startswith(prefix + "/"):
            continue
        relative = PurePosixPath(item.path).relative_to(PurePosixPath(prefix))
        if relative.is_absolute() or ".." in relative.parts or "\\" in item.path:
            raise ValueError("Đường dẫn audio trong Bucket không hợp lệ.")
        destination = (root / Path(*relative.parts)).resolve()
        if not destination.is_relative_to(root):
            raise ValueError("Đường dẫn audio vượt khỏi thư mục truyện.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        files.append((item.path, str(destination)))
        destinations.append(destination)
    if files:
        download_bucket_files(BUCKET_ID, files=files, token=_token())
    return {"book_id": book_id, "files": len(destinations), "bytes": sum(p.stat().st_size for p in destinations if p.is_file())}


class BucketSyncWorker:
    """One bounded writer for chapter artifacts and periodic snapshots."""
    def __init__(self, store, capacity: int = 4):
        self.store = store
        self._queue: queue.Queue = queue.Queue(maxsize=capacity)
        self._lock = threading.Lock()
        self._data_dir = data_dir()
        self._outbox_path = self._data_dir / "bucket_outbox.json"
        self._last_success_path = self._data_dir / "bucket_last_success.txt"
        self._outbox: list[dict] = self._read_outbox()
        try:
            self.last_success = self._last_success_path.read_text("utf-8").strip() or None
        except OSError:
            self.last_success = None
        self.last_error = None
        self._fill_queue()
        self.thread = threading.Thread(target=self._run, name="huggingface-bucket-writer", daemon=True)
        self.thread.start()

    def _read_outbox(self) -> list[dict]:
        try:
            raw = json.loads(self._outbox_path.read_text("utf-8"))
            if isinstance(raw, list):
                return [item for item in raw if isinstance(item, dict) and item.get("kind") in {"text", "audio", "snapshot"}]
        except (OSError, ValueError):
            pass
        return []

    def _persist_outbox(self) -> None:
        self._outbox_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self._outbox_path.with_suffix(".tmp")
        temp.write_text(json.dumps(self._outbox, ensure_ascii=False), "utf-8")
        os.replace(temp, self._outbox_path)

    @staticmethod
    def _task_from_record(item: dict):
        if item.get("kind") == "snapshot":
            return ("snapshot", bool(item.get("include_audio", False)), item["id"], int(item.get("attempts", 0)))
        return ("artifact", Path(item["path"]), item["kind"], item["id"], int(item.get("attempts", 0)))

    def _fill_queue(self) -> None:
        queued_ids = {task[-2] for task in list(self._queue.queue) if task}
        with self._lock:
            pending = [item for item in self._outbox if item.get("id") not in queued_ids]
        for item in pending:
            try:
                self._queue.put_nowait(self._task_from_record(item))
            except queue.Full:
                break

    def _enqueue_record(self, item: dict) -> bool:
        with self._lock:
            if item["kind"] == "snapshot" and any(record.get("kind") == "snapshot" for record in self._outbox):
                return False
            self._outbox.append(item)
            self._persist_outbox()
        try:
            self._queue.put_nowait(self._task_from_record(item))
            return True
        except queue.Full:
            # The durable outbox is drained when a worker slot becomes available.
            return False

    @property
    def pending(self):
        return self._queue.qsize()

    def enqueue_artifact(self, path: Path, kind: str):
        if _token():
            if kind not in {"text", "audio"}:
                raise ValueError("Loại tệp không hợp lệ.")
            self._enqueue_record({"id": os.urandom(8).hex(), "kind": kind, "path": str(Path(path).resolve())})

    def enqueue_snapshot(self, include_audio: bool = False):
        if not _token():
            return False
        # Coalesce periodic snapshots rather than queueing a stale backlog.
        return self._enqueue_record({"id": os.urandom(8).hex(), "kind": "snapshot", "include_audio": bool(include_audio)})

    def _remove_outbox_record(self, record_id: str) -> None:
        with self._lock:
            self._outbox = [record for record in self._outbox if record.get("id") != record_id]
            self._persist_outbox()

    def _run(self):
        while True:
            task = self._queue.get()
            try:
                if task is None:
                    return
                if task[0] == "artifact":
                    upload_artifact(self.store, task[1], task[2])
                else:
                    publish_checkpoint(self.store, include_audio=task[1])
                self._remove_outbox_record(task[-2])
                with self._lock:
                    self.last_success = datetime.now(timezone.utc).isoformat()
                    self._last_success_path.parent.mkdir(parents=True, exist_ok=True)
                    temp = self._last_success_path.with_suffix(".tmp")
                    temp.write_text(self.last_success, "utf-8")
                    os.replace(temp, self._last_success_path)
                    self.last_error = None
            except Exception as exc:
                with self._lock:
                    self.last_error = str(exc)[:240]
                # Keep the item on disk and retry with bounded exponential backoff.
                attempt = task[-1] if task and isinstance(task[-1], int) else 0
                with self._lock:
                    for record in self._outbox:
                        if record.get("id") == task[-2]:
                            record["attempts"] = attempt + 1
                            break
                    self._persist_outbox()
                time.sleep(min(300, 2 ** min(attempt + 1, 8)))
                try:
                    self._queue.put(self._task_from_record(next(item for item in self._outbox if item.get("id") == task[-2])), timeout=5)
                except queue.Full:
                    pass
                except StopIteration:
                    pass
            finally:
                self._queue.task_done()
                self._fill_queue()

    def snapshot_status(self):
        with self._lock:
            return {"pending": self.pending, "last_success": self.last_success,
                    "last_error": self.last_error, "write_enabled": bool(_token())}
