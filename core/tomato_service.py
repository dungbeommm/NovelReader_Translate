"""Bridge from NovelReader to the official Tomato-Novel-Downloader Web API.

No Fanqie endpoint, token or private parser is copied into NovelReader.
The independent Rust service must be started separately (TOMATO_WEB_URL).
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from collections import deque
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen

from storage.files import MAX_FILE, parse_file

BOOK_ID_RE = re.compile(r"^[0-9]{8,25}$")


class TomatoError(RuntimeError):
    pass


class TomatoClient:
    def __init__(self):
        self.url = os.getenv("TOMATO_WEB_URL", "http://127.0.0.1:18423").rstrip("/")
        parts = urlsplit(self.url)
        if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password or parts.path or parts.query or parts.fragment:
            raise TomatoError("TOMATO_WEB_URL không hợp lệ. Chỉ được đặt địa chỉ gốc của dịch vụ Rust.")
        self.password = os.getenv("TOMATO_WEB_PASSWORD", "")

    def request(self, method, path, payload=None, binary=False):
        if not path.startswith("/") or path.startswith("//"):
            raise TomatoError("Đường dẫn dịch vụ Tomato không hợp lệ.")
        headers = {"Accept": "application/octet-stream" if binary else "application/json"}
        if self.password:
            headers["X-Tomato-Password"] = self.password
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        try:
            with urlopen(Request(self.url + path, data=data, headers=headers, method=method), timeout=35 if binary else 15) as response:
                if binary:
                    length = response.headers.get("Content-Length")
                    if length and int(length) > MAX_FILE:
                        raise TomatoError("Truyện vượt giới hạn nhập tệp 50 MB.")
                    data = response.read(MAX_FILE + 1)
                    if len(data) > MAX_FILE:
                        raise TomatoError("Truyện vượt giới hạn nhập tệp 50 MB.")
                    return data
                return json.loads(response.read(2 * 1024 * 1024))
        except HTTPError as exc:
            detail = exc.read(500).decode("utf-8", errors="replace")
            raise TomatoError(f"Tomato API HTTP {exc.code}: {detail}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise TomatoError("Không kết nối được Tomato Downloader. Kiểm tra TOMATO_WEB_URL và dịch vụ Rust.") from exc

    def job(self, job_id):
        data = self.request("GET", "/api/jobs?" + urlencode({"id": job_id, "all": "true"}))
        return next((j for j in data.get("items", []) if str(j.get("id")) == str(job_id)), None)

    def files(self, folder=""):
        query = urlencode({"path": folder, "start": "true"})
        data = {}
        for _ in range(24):
            data = self.request("GET", "/api/library?" + query)
            if data.get("error"):
                raise TomatoError("Không đọc được thư viện Tomato: " + str(data["error"]))
            if not data.get("running"):
                return data.get("items", [])
            time.sleep(.5)
            query = urlencode({"path": folder, "start": "false"})
        raise TomatoError("Tomato chưa hoàn tất quét thư viện tệp.")

    def find_text(self, book_id, book_title, started_ms):
        """Match output to the requested title/ID; do not import an unrelated book."""
        pending = deque([("", 0)])
        visited = set()
        candidates = []
        while pending and len(visited) < 80:
            folder, depth = pending.popleft()
            if folder in visited:
                continue
            visited.add(folder)
            for item in self.files(folder):
                rel = str(item.get("rel_path", ""))
                if not rel or ".." in rel.replace("\\", "/").split("/"):
                    continue
                if item.get("kind") == "dir" and depth < 3:
                    pending.append((rel, depth + 1))
                elif item.get("kind") == "file" and item.get("ext") in ("txt", "epub") and int(item.get("size", 0)) > 0:
                    candidates.append(item)
        title_key = "".join((book_title or "").casefold().split())
        matches = [
            item for item in candidates
            if book_id in item["rel_path"] or (title_key and title_key in "".join(item["rel_path"].casefold().split()))
        ]
        if not matches:
            # Fallback only if there is a unique NEW text file for this job.
            matches = [i for i in candidates if int(i.get("modified_ms") or 0) >= started_ms - 5000]
            if len(matches) != 1:
                raise TomatoError("Đã tải nhưng không xác định được tệp TXT/EPUB của truyện. Hãy đặt định dạng xuất TXT trong Tomato.")
        matches.sort(key=lambda i: (int(i.get("modified_ms") or 0) >= started_ms - 5000, i.get("ext") == "txt", int(i.get("modified_ms") or 0)), reverse=True)
        chosen = matches[0]
        return chosen["name"], self.request("GET", "/download/" + quote(chosen["rel_path"], safe="/"), binary=True)


class TomatoPipeline:
    """Single novel at a time, with observable stages for the existing WebUI."""
    def __init__(self):
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._thread = None
        self._job_id = None
        self._status = {"stage": "idle", "active": False, "message": "Chưa tải truyện.", "book_id": None,
                        "book_title": None, "saved": 0, "total": 0, "error": None}

    def snapshot(self):
        with self._lock:
            return dict(self._status)

    def downloading(self):
        with self._lock:
            return bool(self._status["active"])

    def _set(self, **fields):
        with self._lock:
            self._status.update(fields)

    def start(self, book_id, config, replace_existing=False):
        from core import runtime
        if not BOOK_ID_RE.fullmatch(book_id):
            raise ValueError("ID truyện phải gồm 8–25 chữ số.")
        with self._lock:
            if self._status["active"]:
                raise ValueError("Đang tải một truyện khác. Chỉ được chạy một tác vụ.")
            if runtime.job.active:
                raise ValueError("Hãy kết thúc job dịch hiện tại trước khi tải truyện mới.")
            if runtime.store.book() and not replace_existing:
                raise ValueError("Đã có truyện trong NovelReader. Cần xác nhận thay thế truyện.")
            client = TomatoClient()
            # Refuse to start a job when the local downloader is unavailable.
            client.request("GET", "/api/status")
            self._cancel.clear()
            self._job_id = None
            self._status = {"stage": "starting", "active": True, "message": "Đang gửi ID đến Tomato Downloader…",
                            "book_id": book_id, "book_title": None, "saved": 0, "total": 0, "error": None}
            self._thread = threading.Thread(target=self._run, args=(client, book_id, config), daemon=True, name="tomato-pipeline")
            self._thread.start()
            return dict(self._status)

    def cancel(self):
        with self._lock:
            if not self._status["active"] or self._status["stage"] not in ("starting", "downloading"):
                raise ValueError("Chỉ được hủy khi đang tải chương.")
        self._cancel.set()
        job_id = self._job_id
        if job_id is not None and self.downloading():
            try:
                TomatoClient().request("POST", f"/api/jobs/{job_id}/cancel")
            except TomatoError:
                pass
        self._set(message="Đang hủy tác vụ tải…")
        return self.snapshot()

    def _run(self, client, book_id, config):
        from core import runtime
        try:
            started_ms = int(time.time() * 1000)
            job = client.request("POST", "/api/jobs", {"book_id": book_id})
            self._job_id = job["id"]
            while True:
                if self._cancel.is_set():
                    try:
                        client.request("POST", f"/api/jobs/{self._job_id}/cancel")
                    except TomatoError:
                        pass
                    raise TomatoError("Đã hủy tải truyện.")
                info = client.job(self._job_id)
                if info is None:
                    raise TomatoError("Tomato không còn lưu trạng thái tác vụ.")
                progress = info.get("progress") or {}
                title = info.get("title") or self._status.get("book_title")
                self._set(stage="downloading", book_title=title,
                          saved=int(progress.get("saved_chapters") or 0),
                          total=int(progress.get("chapter_total") or 0),
                          message=info.get("message") or "Đang tải nội dung chữ Hán…")
                # Some downloader configurations ask for a title and an output format.
                if info.get("book_name_options"):
                    first = info["book_name_options"][0]
                    client.request("POST", f"/api/jobs/{self._job_id}/book_name", {"value": first["value"]})
                if info.get("format_options"):
                    choices = info["format_options"]
                    preferred = next((x["value"] for x in choices if x.get("value") == "txt"), choices[0]["value"])
                    client.request("POST", f"/api/jobs/{self._job_id}/format", {"value": preferred})
                if info.get("state") == "done":
                    total = int(progress.get("chapter_total") or 0)
                    saved = int(progress.get("saved_chapters") or 0)
                    if total and saved < total:
                        raise TomatoError(f"Chỉ tải được {saved}/{total} chương. Tải lại để hoàn tất.")
                    break
                if info.get("state") in ("failed", "canceled"):
                    raise TomatoError(info.get("message") or "Tomato không tải được truyện.")
                self._cancel.wait(1.5)

            self._set(stage="importing", message="Đang nhập TXT/EPUB và tách danh sách chương…")
            filename, data = client.find_text(book_id, self._status.get("book_title"), started_ms)
            if self._cancel.is_set():
                raise TomatoError("Đã hủy tải truyện.")
            chapters, encoding = parse_file(filename, data)
            if not chapters:
                raise TomatoError("Tệp tải về không chứa chương hợp lệ.")
            rust_count = int(progress.get("saved_chapters") or 0)
            if rust_count and len(chapters) < int(rust_count * 0.9):
                raise TomatoError(f"Tệp đầu ra chỉ tách được {len(chapters)}/{rust_count} chương. Kiểm tra định dạng TXT/EPUB của Tomato.")
            with runtime.job.lock:
                if runtime.job.active:
                    raise TomatoError("Đã có job dịch khác hoạt động; không thể thay truyện.")
                runtime.store.replace(filename, encoding, chapters)
                runtime.job.status = "ready"
                runtime.job.message = ""
                runtime.job.target_chapter_ids = None
                runtime.job.scope_label = ""
                runtime.job.emit("book_loaded")
            self._set(stage="translating", message=f"Đã nhập {len(chapters)} chương; bắt đầu dịch và TTS…",
                      total=len(chapters), saved=len(chapters))
            runtime.job.start(config, reset=False)
            self._set(stage="done", active=False,
                      message="Đã chuyển toàn bộ chương vào hàng đợi dịch/TTS của NovelReader.")
        except Exception as exc:
            self._set(stage="canceled" if self._cancel.is_set() else "error", active=False,
                      message=str(exc), error=str(exc))
        finally:
            self._job_id = None


pipeline = TomatoPipeline()
