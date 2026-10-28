"""Test scheduling without contacting Hugging Face."""
from storage.sync_manager import CloudSyncManager


def test_disabled_manager_never_uploads():
    manager = CloudSyncManager(None, lambda result: None, lambda error: None, enabled=False)
    manager.chapter_done()
    manager.finish()
    assert manager.thread is None


def test_every_chapter_and_final_upload(monkeypatch):
    successes = []
    errors = []
    from storage import checkpoints
    monkeypatch.setattr(checkpoints, "upload_checkpoint",
                        lambda store, include_audio=False: {"url": "hf://test"})
    manager = CloudSyncManager(object(), successes.append, errors.append,
                               enabled=True, every=1)
    manager.chapter_done()
    manager.finish()
    assert successes == [{"url": "hf://test"}, {"url": "hf://test"}]
    assert errors == []


def test_periodic_checkpoint_honors_audio_option(monkeypatch):
    from storage import checkpoints
    captured = []
    def upload(store, include_audio=False):
        captured.append(include_audio)
        return {'url': 'hf://test'}
    monkeypatch.setattr(checkpoints, 'upload_checkpoint', upload)
    manager = CloudSyncManager(object(), lambda result: None, lambda error: None,
                               enabled=True, every=1, include_audio=True)
    manager.chapter_done()
    manager.finish(include_audio=True)
    assert captured == [True, True]
