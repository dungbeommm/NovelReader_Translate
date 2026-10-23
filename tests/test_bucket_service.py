import hashlib
import json
from contextlib import contextmanager
from types import SimpleNamespace

from storage import bucket_service


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
    worker = bucket_service.BucketSyncWorker(FakeStore())

    worker.enqueue_artifact(artifact, "text")
    worker._queue.join()

    assert worker._outbox == []
    assert len(attempts) == 2
    assert worker.last_success
    assert (tmp_path / "bucket_last_success.txt").read_text("utf-8") == worker.last_success
