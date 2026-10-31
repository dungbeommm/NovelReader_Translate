"""Unit tests for the Rust Tomato integration (no live Fanqie network)."""
import pytest

from core.tomato_service import BOOK_ID_RE, TomatoClient, TomatoError, TomatoPipeline


@pytest.mark.parametrize("book_id", ["7318247498772674083", "12345678"])
def test_numeric_id(book_id):
    assert BOOK_ID_RE.fullmatch(book_id)


@pytest.mark.parametrize("book_id", ["../internal", "https://example.com", "123", "1234<script>"])
def test_reject_non_book_ids(book_id):
    assert BOOK_ID_RE.fullmatch(book_id) is None


def test_reject_malformed_service_url(monkeypatch):
    monkeypatch.setenv("TOMATO_WEB_URL", "http://example.com/path?url=1")
    with pytest.raises(TomatoError):
        TomatoClient()


def test_choose_newer_txt_for_book(monkeypatch):
    monkeypatch.setenv("TOMATO_WEB_URL", "http://127.0.0.1:18423")
    client = TomatoClient()
    entries = [
        {"kind": "file", "name": "仙路.epub", "rel_path": "仙路.epub",
         "ext": "epub", "size": 1024, "modified_ms": 1000},
        {"kind": "file", "name": "仙路.txt", "rel_path": "仙路.txt",
         "ext": "txt", "size": 2048, "modified_ms": 200000},
        {"kind": "file", "name": "别的书.txt", "rel_path": "别的书.txt",
         "ext": "txt", "size": 3072, "modified_ms": 199999},
    ]
    monkeypatch.setattr(client, "files", lambda path="": entries)
    requested = []
    def read(method, path, payload=None, binary=False):
        requested.append(path)
        return b"novel data"
    monkeypatch.setattr(client, "request", read)
    name, data = client.find_text("7318247498772674083", "仙路", 150000)
    assert name == "仙路.txt"
    assert data == b"novel data"
    assert requested == ["/download/%E4%BB%99%E8%B7%AF.txt"]


def test_never_import_ambiguous_unrelated_file(monkeypatch):
    client = object.__new__(TomatoClient)
    entries = [
        {"kind": "file", "name": "A.txt", "rel_path": "A.txt", "ext": "txt", "size": 50, "modified_ms": 100000},
        {"kind": "file", "name": "B.txt", "rel_path": "B.txt", "ext": "txt", "size": 50, "modified_ms": 100000},
    ]
    monkeypatch.setattr(client, "files", lambda path="": entries)
    with pytest.raises(TomatoError, match="không xác định"):
        client.find_text("7318247498772674083", "Không tồn tại", 99000)


def test_pipeline_initial_state_and_cancel_guard():
    bridge = TomatoPipeline()
    assert bridge.snapshot()["stage"] == "idle"
    assert not bridge.downloading()
    with pytest.raises(ValueError, match="Chỉ được hủy"):
        bridge.cancel()
