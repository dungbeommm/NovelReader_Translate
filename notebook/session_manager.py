"""Marimo sends job commands to FastAPI when WebUI is running."""
import json
import os
import secrets
from urllib import error, request


class BackendClient:
    def __init__(self, url="http://127.0.0.1:8000"):
        self.url = url.rstrip("/")

    def _call(self, path, payload=None, *, method="GET", content_type=None):
        headers = {"X-App-Request": "novel-translator"}
        token = os.getenv("NOVEL_WEB_ACCESS_TOKEN", "").strip()
        if token:
            headers["X-Novel-Access"] = token
        data = payload
        if isinstance(payload, dict):
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            content_type = "application/json"
        if content_type:
            headers["Content-Type"] = content_type
        req = request.Request(self.url + path, data=data, headers=headers, method=method)
        try:
            with request.urlopen(req, timeout=15) as res:
                return json.loads(res.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read(2048).decode("utf-8", "replace")
            raise ValueError(f"WebUI HTTP {exc.code}: {detail}") from exc

    def available(self):
        try:
            self.state()
            return True
        except error.URLError:
            return False

    def state(self):
        return self._call("/api/state")

    def start_job(self, config):
        return self._call("/api/translate/start", config, method="POST")

    def control(self, action):
        if action not in {"pause", "resume", "stop"}:
            raise ValueError("Lệnh điều khiển không hợp lệ.")
        return self._call("/api/translate/" + action, b"", method="POST")

    def upload_book(self, filename, data):
        boundary = "novelreader-" + secrets.token_hex(12)
        safe_name = filename.replace("\\", "/").rsplit("/", 1)[-1].replace('"', "_")
        prefix = (
            "--" + boundary + "\r\n"
            'Content-Disposition: form-data; name="file"; filename="' + safe_name + '"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode("utf-8")
        body = prefix + data + ("\r\n--" + boundary + "--\r\n").encode("utf-8")
        return self._call(
            "/api/upload", body, method="POST",
            content_type="multipart/form-data; boundary=" + boundary)
