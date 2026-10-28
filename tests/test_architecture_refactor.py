"""Compatibility and multi-process protection after refactoring."""
from core.config import env_enabled
from core.state_manager import JobLease
from storage.store import Store
from server.tunnel.zrok import extract_share_host, public_url


def test_legacy_runtime_is_same_singleton():
    from core import runtime as canonical
    from web import runtime as legacy
    assert canonical is legacy


def test_boolean_environment_is_explicit(monkeypatch):
    monkeypatch.setenv("COLAB_GPU", "0")
    assert env_enabled("COLAB_GPU") is False
    monkeypatch.setenv("COLAB_GPU", "1")
    assert env_enabled("COLAB_GPU") is True


def test_lease_excludes_second_worker(tmp_path):
    first = JobLease(tmp_path / "job.lock")
    second = JobLease(tmp_path / "job.lock")
    assert first.acquire()
    assert second.held_by_another()
    assert not second.acquire()
    first.release()
    assert second.acquire()
    second.release()


def test_second_store_does_not_reset_active_chapter(tmp_path):
    db = tmp_path / "novel.sqlite3"
    owner = Store(db)
    owner.replace("x.txt", "utf8", [("Chương 1", "你好")])
    cid = owner.list()[0]["id"]
    owner.update(cid, status="translating", audio_status="generating")
    peer = Store(db, recover_incomplete=False)
    assert peer.get(cid)["status"] == "translating"
    assert peer.get(cid)["audio_status"] == "generating"
    recovered = Store(db)
    assert recovered.get(cid)["status"] == "pending"
    assert recovered.get(cid)["audio_status"] == "none"


def test_share_address_extracted_from_latest_log_line():
    log = "old: first.shares.zrok.io\nnew: SECOND.shares.zrok.io"
    assert extract_share_host(log) == "second.shares.zrok.io"
    assert public_url(log) == "https://second.shares.zrok.io/"


def test_legacy_app_factory():
    import main
    from server.app import create_app
    from web.application import create_app as legacy
    assert main.app is not None
    assert create_app is legacy


def test_job_lease_released_after_worker_exception(tmp_path):
    from core.job_manager import ManagedJob
    db = tmp_path / "novel.sqlite3"
    store = Store(db)
    job = ManagedJob(store)
    assert not job.lease.owned
    try:
        job.start({"engine": "HachimiMT-60-QT", "glossary": ""})
    except ValueError:
        pass
    assert not job.lease.owned
