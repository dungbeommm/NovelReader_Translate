import io
import json
import urllib.error
import pytest
from storage import pixeldrain_service
from storage.store import Store


def test_get_pixeldrain_api_key(monkeypatch):
    assert pixeldrain_service.get_pixeldrain_api_key(None) is None
    assert pixeldrain_service.get_pixeldrain_api_key("custom_key") == "custom_key"
    monkeypatch.setenv("PIXELDRAIN_API_KEY", "env_key_123")
    assert pixeldrain_service.get_pixeldrain_api_key(None) == "env_key_123"
    assert pixeldrain_service.get_pixeldrain_api_key("override_key") == "override_key"


def test_upload_to_pixeldrain_success(monkeypatch):
    captured_req = {}

    class DummyResponse:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self):
            return json.dumps({"id": "abc12345", "success": True}).encode("utf-8")

    def dummy_urlopen(req, timeout=300):
        captured_req['url'] = req.full_url
        captured_req['method'] = req.get_method()
        captured_req['headers'] = dict(req.headers)
        captured_req['data'] = req.data
        return DummyResponse()

    monkeypatch.setattr(urllib.request, "urlopen", dummy_urlopen)

    res = pixeldrain_service.upload_to_pixeldrain(
        b"hello audio content", "test.mp3", api_key="my_secret_key"
    )
    assert res["ok"] is True
    assert res["id"] == "abc12345"
    assert res["url"] == "https://pixeldrain.com/u/abc12345"
    assert res["download_url"] == "https://pixeldrain.com/api/file/abc12345"
    assert captured_req["method"] == "PUT"
    assert "https://pixeldrain.com/api/file/test.mp3" in captured_req["url"]
    assert "Authorization" in captured_req["headers"]


def test_upload_to_pixeldrain_401_error(monkeypatch):
    class DummyHTTPError(urllib.error.HTTPError):
        def __init__(self):
            super().__init__("https://pixeldrain.com", 401, "Unauthorized", {}, None)
        def read(self):
            return b'{"message": "authentication required"}'

    def dummy_urlopen(req, timeout=300):
        raise DummyHTTPError()

    monkeypatch.setattr(urllib.request, "urlopen", dummy_urlopen)

    with pytest.raises(RuntimeError, match="Pixeldrain yêu cầu API Key"):
        pixeldrain_service.upload_to_pixeldrain(b"some data", "sample.txt")


def test_export_book_to_pixeldrain(tmp_path, monkeypatch):
    store = Store(tmp_path / "data.db")
    with store.connect() as c:
        c.execute("INSERT INTO book(title, filename, encoding, output_folder) VALUES (?, ?, ?, ?)",
                  ("Truyện Test", "source.txt", "utf-8", "Truyen_Test"))
        c.execute("INSERT INTO chapter(position, title, source, status, translated_title, translated) VALUES (?, ?, ?, ?, ?, ?)",
                  (1, "Chương 1", json.dumps(["Source text"]), "done", "Chương 1 Đã Dịch", json.dumps(["Đoạn dịch 1"])))

    uploaded = []
    def dummy_upload(data_or_path, filename, api_key=None, timeout=300):
        uploaded.append((filename, len(data_or_path), api_key))
        return {
            "ok": True,
            "id": "file999",
            "url": "https://pixeldrain.com/u/file999",
            "download_url": "https://pixeldrain.com/api/file/file999",
            "filename": filename,
            "size_bytes": len(data_or_path),
            "size_mb": 0.01,
        }

    monkeypatch.setattr(pixeldrain_service, "upload_to_pixeldrain", dummy_upload)

    res_txt = pixeldrain_service.export_book_to_pixeldrain(store, "txt", api_key="key1")
    assert res_txt["ok"] is True
    assert uploaded[0][0].endswith(".txt")
    assert uploaded[0][2] == "key1"

    res_epub = pixeldrain_service.export_book_to_pixeldrain(store, "epub", api_key="key2")
    assert res_epub["ok"] is True
    assert uploaded[1][0].endswith(".epub")
    assert uploaded[1][2] == "key2"


def test_pixeldrain_api_endpoints(monkeypatch):
    from fastapi.testclient import TestClient
    from web.application import create_app
    from web import runtime

    app = create_app()
    with runtime.store.connect() as c:
        c.execute("INSERT OR REPLACE INTO book(id, title, filename, encoding, output_folder) VALUES (1, ?, ?, ?, ?)",
                  ("Truyện Test Web", "web.txt", "utf-8", "Truyen_Web"))
        c.execute("INSERT OR REPLACE INTO chapter(id, position, title, source, status, translated_title, translated) VALUES (1, ?, ?, ?, ?, ?, ?)",
                  (1, "Chương 1", json.dumps(["Source"]), "done", "Chương 1 Web", json.dumps(["Dịch"])))

    def dummy_upload(data_or_path, filename, api_key=None, timeout=300):
        return {
            "ok": True,
            "id": "pd_abc123",
            "url": "https://pixeldrain.com/u/pd_abc123",
            "download_url": "https://pixeldrain.com/api/file/pd_abc123",
            "filename": filename,
            "size_bytes": 100,
            "size_mb": 0.01,
            "message": "Upload thành công"
        }

    monkeypatch.setattr(pixeldrain_service, "upload_to_pixeldrain", dummy_upload)

    client = TestClient(app)
    headers = {"X-App-Request": "novel-translator"}

    r_status = client.get("/api/export/pixeldrain/status")
    assert r_status.status_code == 200

    r_txt = client.post("/api/export/pixeldrain/txt", headers=headers, json={"api_key": "user_key_777"})
    assert r_txt.status_code == 200
    assert r_txt.json()["ok"] is True
    assert r_txt.json()["url"] == "https://pixeldrain.com/u/pd_abc123"

