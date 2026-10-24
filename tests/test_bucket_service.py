import hashlib
import json
from contextlib import contextmanager
from types import SimpleNamespace

from storage import bucket_service
from storage.store import Store


class FakeStore:
    def book(self):
        return {"filename": "story.txt", "title": "A Story", "output_folder": "a-story"}


def test_publish_checkpoint_uploads_archive_before_manifest_and_latest(tmp_path, monkeypatch):
    archive = tmp_path / "snapshot.zip"
    archive.write_bytes(b"checkpoint bytes")
    uploads = []

    class FakeApi:
        def batch_bucket_files(self, bucket_id, *, add):
            uploads.extend(add)

    monkeypatch.setattr(bucket_service, "_runtime_token", "hf_" + "x" * 30)
    monkeypatch.setattr(bucket_service, "create_checkpoint", lambda *args, **kwargs: archive)
    monkeypatch.setattr(bucket_service, "_api", FakeApi)

    result = bucket_service.publish_checkpoint(FakeStore())

    assert len(uploads) == 3
    assert uploads[0][0] == str(archive)
    manifest = json.loads(uploads[1][0])
    assert manifest["sha256"] == hashlib.sha256(b"checkpoint bytes").hexdigest()
    assert manifest["archive"] == uploads[0][1]
    latest = json.loads(uploads[2][0])
    assert latest["manifest"] == uploads[1][1]
    assert result["manifest"] == uploads[1][1]


def test_book_id_is_stable_for_the_same_source():
    class Connection:
        def execute(self, query):
            return [(0, "Chapter 1", '["raw text"]')]

    class RenamedStore(FakeStore):
        @contextmanager
        def connect(self):
            yield Connection()

        def book(self):
            return {"filename": "renamed.txt", "title": "Renamed title", "output_folder": "other"}

    first = bucket_service._book_id(RenamedStore())
    second = bucket_service._book_id(RenamedStore())
    assert first == second


def test_restore_audio_downloads_only_under_the_active_story(tmp_path, monkeypatch):
    class Connection:
        def execute(self, query):
            return [(0, "Chapter 1", '["raw text"]')]

    class Store:
        audio_dir = tmp_path / "audio"

        def book(self):
            return {"filename": "story.txt", "title": "A Story", "output_folder": "a-story"}

        @contextmanager
        def connect(self):
            yield Connection()

    class FakeApi:
        def list_bucket_tree(self, bucket_id, *, prefix, recursive):
            return [SimpleNamespace(path=f"{prefix}/chapter.mp3", type="file")]

    def download(bucket_id, *, files, token=None):
        for _, path in files:
            from pathlib import Path
            Path(path).write_bytes(b"audio")

    monkeypatch.setattr(bucket_service, "_api", FakeApi)
    monkeypatch.setattr(bucket_service, "_runtime_token", None)
    monkeypatch.setattr("huggingface_hub.download_bucket_files", download)
    store = Store()

    result = bucket_service.restore_audio(store, bucket_service._book_id(store))

    assert result["files"] == 1
    assert result["bytes"] == 5
    assert (store.audio_dir / "chapter.mp3").read_bytes() == b"audio"


def test_bucket_worker_clears_successful_outbox_entries(tmp_path, monkeypatch):
    artifact = tmp_path / "chapter.txt"
    artifact.write_text("done", "utf-8")
    attempts = []

    def flaky_upload(*args, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("temporary network error")
        return "text/chapter.txt"

    monkeypatch.setattr(bucket_service, "_runtime_token", "hf_" + "x" * 30)
    monkeypatch.setattr(bucket_service, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(bucket_service, "upload_artifact", flaky_upload)
    monkeypatch.setattr(bucket_service.time, "sleep", lambda _: None)
    class StoreWithFiles(FakeStore):
        text_dir = tmp_path
        audio_dir = tmp_path

    worker = bucket_service.BucketSyncWorker(StoreWithFiles())

    worker.enqueue_artifact(artifact, "text")
    worker._queue.join()

    assert worker._outbox == []
    assert len(attempts) == 2
    assert worker.last_success
    assert (tmp_path / "bucket_last_success.txt").read_text("utf-8") == worker.last_success


def test_connecting_token_queues_existing_text_epub_audio_and_checkpoint(tmp_path, monkeypatch):
    store = Store(tmp_path / 'novel.sqlite3', tmp_path / 'text', tmp_path / 'audio')
    store.replace('story.txt', 'utf-8', [('Chapter 1', 'Source')])
    chapter = store.list()[0]
    store.update(chapter['id'], status='done', translated=['Translated'])
    store.export_chapter_text(chapter['id'], 'Chapter 1', ['Translated'], 1)
    store.export_full_book_text()
    (store.audio_dir / 'chapter.mp3').write_bytes(b'audio')
    (store.audio_dir / 'audio_gop').mkdir()
    (store.audio_dir / 'audio_gop' / 'group.mp3').write_bytes(b'group')

    monkeypatch.setattr(bucket_service, 'data_dir', lambda: tmp_path / 'outbox')
    monkeypatch.setattr(bucket_service.threading.Thread, 'start', lambda self: None)
    monkeypatch.setattr(bucket_service, '_runtime_token', 'hf_' + 'x' * 30)
    worker = bucket_service.BucketSyncWorker(store)
    assert worker.enqueue_existing() == 5
    assert worker.pending == 6
    assert {item['relative_path'] for item in worker._outbox if item['kind'] == 'text'} == {
        'chuong_0001.txt', 'toan_bo_truyen.txt', 'toan_bo_truyen.epub'
    }
    assert {item['relative_path'] for item in worker._outbox if item['kind'] == 'audio'} == {
        'chapter.mp3', 'audio_gop/group.mp3'
    }
    assert worker.enqueue_existing() == 0
    assert worker.pending == 6


def test_queued_artifact_keeps_original_book_id_after_switch(tmp_path, monkeypatch):
    store = Store(tmp_path / 'novel.sqlite3', tmp_path / 'text', tmp_path / 'audio')
    store.replace('first.txt', 'utf-8', [('First', 'Source')])
    original_id = bucket_service._book_id(store)
    path = store.export_chapter_text(1, 'First', ['Translated'], 1)
    uploaded = []

    class FakeApi:
        def batch_bucket_files(self, bucket_id, *, add):
            uploaded.extend(add)

    monkeypatch.setattr(bucket_service, '_runtime_token', 'hf_' + 'x' * 30)
    monkeypatch.setattr(bucket_service, '_api', FakeApi)
    store.replace('second.txt', 'utf-8', [('Second', 'Other source')])
    destination = bucket_service.upload_artifact(store, path, 'text', book_id=original_id, relative_path=path.name)
    assert destination == f'books/{original_id}/text/{path.name}'
    assert uploaded == [(str(path), destination)]
