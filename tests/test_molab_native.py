"""Native notebook lifecycle and recovery, without a tunnel or live HF writes."""
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import zipfile

import pytest
from core.job_manager import ManagedJob
from storage.store import Store
from storage import checkpoints, huggingface_service, cloud_settings

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location('test_' + name, ROOT / 'notebook' / (name + '.py'))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


@pytest.fixture
def native(tmp_path, monkeypatch):
    monkeypatch.setenv('NOVEL_DATA', str(tmp_path / 'data'))
    store = Store(tmp_path / 'data/novel.sqlite3')
    job = ManagedJob(store)
    return module('molab_native').NativeController(SimpleNamespace(store=store, job=job))


def test_native_translation_uses_existing_job_and_never_starts_a_server(native, monkeypatch):
    from workflows import jobs
    monkeypatch.setattr('subprocess.Popen', Mock(side_effect=AssertionError('No subprocess server')))
    class Engine:
        def load(self):
            pass
        def translate(self, texts, glossary, **kwargs):
            return ['Bản dịch' for text in texts]
    monkeypatch.setattr(jobs, 'create_engine', lambda *args, **kwargs: Engine())
    native.load_book('novel.txt', '第1章 测试\n你好世界。'.encode())
    native.start({'generate_audio': False, 'pronoun_harmonizer': False, 'honorific_mode': 'off'})
    native.job.thread.join(5)
    assert not native.job.active
    assert native.job.summary()['done'] == 1
    assert native.store.list()[0]['status'] == 'done'
    assert native.store.text_dir.joinpath('chuong_0001.txt').exists()


def test_checkpoint_recovers_text_and_resets_interrupted_audio(native):
    native.load_book('x.txt', '第1章 测试\n你好世界。'.encode())
    cid = native.store.list()[0]['id']
    native.store.update(cid, status='done', translated=['Xin chào'], translated_title='Chương 1', audio_status='generating')
    archive = native.download_checkpoint().read_bytes()
    with zipfile.ZipFile(io.BytesIO(archive)) as saved:
        assert not any('private' in name for name in saved.namelist())
    native.load_book('different.txt', 'Nội dung khác'.encode())
    native.restore_file(archive)
    assert native.store.get(cid)['translated'] == ['Xin chào']
    assert native.store.get(cid)['audio_status'] == 'none'
    assert native.job.status == 'ready'


def test_active_job_cannot_be_replaced_or_restored(native, monkeypatch):
    native.load_book('x.txt', b'hello')
    monkeypatch.setattr(type(native.job), 'active', property(lambda self: True))
    with pytest.raises(ValueError, match='đợi hoàn tất'):
        native.load_book('y.txt', b'other')
    with pytest.raises(ValueError, match='đợi hoàn tất'):
        native.restore_file(b'zip')
    assert native.store.book()['filename'] == 'x.txt'


def test_cloud_failure_prevents_unprotected_start(native, monkeypatch):
    native.load_book('x.txt', b'hello')
    monkeypatch.setattr(huggingface_service, 'check_connection', Mock(side_effect=ValueError('HF offline')))
    with pytest.raises(ValueError, match='HF offline'):
        native.start({'cloud_checkpoint': True}, 'example/bucket')
    assert not native.job.active


def test_initial_checkpoint_precedes_worker_start(native, monkeypatch):
    native.load_book('x.txt', b'hello')
    events = []
    monkeypatch.setattr(huggingface_service, 'check_connection', lambda: None)
    monkeypatch.setattr(checkpoints, 'upload_checkpoint', lambda *args, **kwargs: events.append('uploaded'))
    monkeypatch.setattr(native.job, 'start', lambda *args, **kwargs: events.append('started'))
    native.start({'cloud_checkpoint': True}, 'example/bucket')
    assert events == ['uploaded', 'started']


def test_initialize_adopts_existing_controller(monkeypatch):
    from core import runtime
    native = module('molab_native')
    initialize = Mock()
    monkeypatch.setattr(runtime, 'initialize', initialize)
    first = native.initialize()
    assert native.initialize() is first
    initialize.assert_called_once()


def test_cloud_errors_visible_without_websocket_and_redacted(native, monkeypatch):
    monkeypatch.setenv('HF_TOKEN', 'hf_private123')
    native.job.emit('cloud_checkpoint_error', error='failed hf_private123')
    assert native.snapshot()['cloud_error'] == 'failed [REDACTED]'
    native.job.emit('cloud_checkpoint_done')
    assert native.snapshot()['cloud_error'] == ''


def archive_payload(entries):
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, 'w') as archive:
        for name, data in entries.items():
            archive.writestr('source/' + name, data)
    return payload.getvalue()


def test_bootstrap_repairs_requirements_without_overwriting_source_or_data(tmp_path, monkeypatch):
    bootstrap = module('molab_bootstrap')
    (tmp_path / 'main.py').write_text('# user change')
    payload = archive_payload({'main.py': '# upstream', 'paths.py': '# paths',
        'notebook/molab_native.py': '# native', 'requirements.txt': 'fastapi',
        'data/novel.sqlite3': 'must not restore', '.env': 'must not restore',
        'web/static/style.css': 'css'})
    monkeypatch.setattr(bootstrap.urllib.request, 'urlopen', lambda *args, **kwargs: io.BytesIO(payload))
    restored = bootstrap.restore_missing(tmp_path, 'reviewed-ref')
    assert 'requirements.txt' in restored
    assert (tmp_path / 'main.py').read_text() == '# user change'
    assert not (tmp_path / 'data/novel.sqlite3').exists()
    assert not (tmp_path / '.env').exists()
    assert (tmp_path / 'web/static/style.css').read_text() == 'css'
    assert bootstrap.restore_missing(tmp_path, 'reviewed-ref') == []


def test_bootstrap_rejects_zip_traversal(tmp_path, monkeypatch):
    bootstrap = module('molab_bootstrap')
    payload = archive_payload({'../outside.txt': 'bad'})
    monkeypatch.setattr(bootstrap.urllib.request, 'urlopen', lambda *args, **kwargs: io.BytesIO(payload))
    with pytest.raises(ValueError, match='ZIP'):
        bootstrap.restore_missing(tmp_path, 'reviewed-ref')
