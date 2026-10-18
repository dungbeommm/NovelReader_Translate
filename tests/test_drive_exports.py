import json
import threading
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from storage.store import Store
from gdrive import export_service as service
from gdrive.colab_bridge import process_drive_requests
from web import runtime


@pytest.fixture
def export_env(tmp_path, monkeypatch):
    monkeypatch.setenv('NOVEL_DATA', str(tmp_path/'data'))
    monkeypatch.setenv('NOVEL_COLAB_DRIVE_BRIDGE', '1')
    monkeypatch.setenv('NOVEL_COLAB_DRIVE_ROOT', str(tmp_path/'drive/MyDrive'))
    store = Store(tmp_path/'db', tmp_path/'text', tmp_path/'audio')
    store.replace('Truyện Việt.txt', 'utf8', [('第一章', '你好')])
    ch = store.list()[0]
    store.update(ch['id'], status='done', translated_title='Chương một', translated=['Xin chào'])
    return store, tmp_path/'drive'


def finish(task_id, mountpoint, mount=None):
    def fake_mount(path):
        (Path(path)/'MyDrive').mkdir(parents=True, exist_ok=True)
    until = time.monotonic() + 5
    while time.monotonic() < until:
        task = service.read_task(task_id)
        if task['status'] in service.TERMINAL:
            return task
        if task['status'] == 'waiting_permission':
            process_drive_requests(service.tasks_dir(), mount or fake_mount, str(mountpoint))
        time.sleep(.03)
    raise AssertionError('Drive export worker did not finish')


@pytest.mark.parametrize('kind', ['txt', 'epub'])
def test_export_translation_to_drive_after_permission(export_env, kind):
    store, mount = export_env
    task = service.start_export(kind, store, threading.RLock())
    result = finish(task['id'], mount)
    assert result['status'] == 'done', result
    output = mount/'MyDrive'/result['drive_path']
    assert output.is_file() and output.stat().st_size > 0
    assert store.get(store.list()[0]['id'])['translated'] == ['Xin chào']
    assert not (service.tasks_dir()/task['id']).exists()
    if kind == 'epub':
        assert zipfile.is_zipfile(output)


def test_audio_zip_excludes_partial_tts_files(export_env):
    store, mount = export_env
    (store.audio_dir/'chuong_0001.mp3').write_bytes(b'finished audio')
    private = store.audio_dir/'.audio-123'
    private.mkdir()
    (private/'chapter.wav').write_bytes(b'partial')
    task = service.start_export('audio', store, threading.RLock())
    result = finish(task['id'], mount)
    assert result['status'] == 'done'
    with zipfile.ZipFile(mount/'MyDrive'/result['drive_path']) as z:
        assert z.namelist() == ['chuong_0001.mp3']
        assert z.read('chuong_0001.mp3') == b'finished audio'
    assert (store.audio_dir/'chuong_0001.mp3').read_bytes() == b'finished audio'


def test_denied_drive_permission_keeps_original(export_env):
    store, mount = export_env
    def denied(path):
        raise RuntimeError('User declined')
    task = service.start_export('txt', store, threading.RLock())
    result = finish(task['id'], mount, denied)
    assert result['status'] == 'error'
    assert 'User declined' in result['message']
    assert store.book() is not None
    assert not (mount/'MyDrive').exists()


def test_permission_is_not_requested_without_click(export_env):
    calls = []
    store, mount = export_env
    assert process_drive_requests(service.tasks_dir(), calls.append, str(mount)) == 0
    assert calls == []


def test_task_id_cannot_traverse_paths(export_env):
    with pytest.raises(ValueError):
        service.read_task('../../secret')


def test_no_audio_reports_error_before_authorization(export_env):
    store, mount = export_env
    task = service.start_export('audio', store, threading.RLock())
    until = time.monotonic() + 3
    while time.monotonic() < until:
        result = service.read_task(task['id'])
        if result['status'] == 'error':
            break
        time.sleep(.02)
    assert result['status'] == 'error'
    assert 'Chưa có file audio' in result['message']


def test_capability_and_invalid_format_api(export_env, monkeypatch):
    from web.application import create_app
    with TestClient(create_app()) as client:
        assert client.get('/api/export/drive/capabilities').json()['colab_drive']
        response = client.post('/api/export/drive/bad', json={}, headers={'X-App-Request':'novel-translator'})
        assert response.status_code == 400
        assert client.get('/api/export/drive/status/invalid').status_code == 404


def test_colab_web_secret_cookie_and_websocket_guard(tmp_path, monkeypatch):
    monkeypatch.setenv('NOVEL_DATA', str(tmp_path/'data'))
    monkeypatch.setenv('NOVEL_WEB_ACCESS_TOKEN', 'test-secret-only')
    from web.application import create_app
    with TestClient(create_app()) as client:
        assert client.get('/api/state').status_code == 403
        assert client.get('/api/state', headers={'X-Novel-Access':'wrong'}).status_code == 403
        assert client.get('/api/state', headers={'X-Novel-Access':'test-secret-only'}).status_code == 200
        from starlette.websockets import WebSocketDisconnect
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect('/ws/progress'):
                pass
        response = client.get('/?access_token=test-secret-only', follow_redirects=False)
        assert response.status_code == 303
        assert 'httponly' in response.headers['set-cookie'].lower()
        assert response.headers['location'] == '/'
        assert client.get('/api/state').status_code == 200
        with client.websocket_connect('/ws/progress') as ws:
            assert ws.receive_json()['type'] == 'snapshot'


def test_export_disabled_outside_notebook(export_env, monkeypatch):
    store, mount = export_env
    monkeypatch.delenv('NOVEL_COLAB_DRIVE_BRIDGE')
    with pytest.raises(ValueError, match='notebook Colab mới'):
        service.start_export('txt', store, threading.RLock())


def test_old_session_does_not_trigger_drive_consent(export_env, monkeypatch):
    store, mount = export_env
    monkeypatch.setenv('NOVEL_EXPORT_SESSION_ID', 'new-session')
    task = {'id': 'a'*32, 'status': 'waiting_permission', 'session_id': 'old-session'}
    service.write_task(task)
    calls = []
    assert process_drive_requests(service.tasks_dir(), calls.append, str(mount)) == 0
    assert calls == []
    assert service.read_task(task['id'])['status'] == 'waiting_permission'


def test_notebook_bootstrap_downloads_without_upload_and_applies_overlay(tmp_path, monkeypatch):
    import io
    import os
    import sys
    import types
    import urllib.request
    import subprocess
    import ast
    root = Path(__file__).resolve().parents[1]
    notebook = json.loads((root/'NovelReader_Colab.ipynb').read_text())
    code = ''.join(notebook['cells'][2]['source'])
    assert 'files.upload(' not in code
    code = code.replace('/content', str(tmp_path))
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, 'w') as archive:
        archive.writestr('NovelReader_T4_Web/main.py', '# downloaded source')
        archive.writestr('NovelReader_T4_Web/data/novel.sqlite3', 'must not overwrite')
        archive.writestr('NovelReader_T4_Web/.env', 'must not write secrets')
    existing = tmp_path/'NovelReader_T4_Web/data/novel.sqlite3'
    existing.parent.mkdir(parents=True)
    existing.write_text('existing user checkpoint')
    calls = []
    def fetch(url, **kwargs):
        calls.append(url)
        return io.BytesIO(payload.getvalue())
    monkeypatch.setattr(urllib.request, 'urlopen', fetch)
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: None)
    monkeypatch.setitem(sys.modules, 'google', types.ModuleType('google'))
    colab = types.ModuleType('google.colab')
    colab.files = types.SimpleNamespace()  # intentionally has NO upload method
    monkeypatch.setitem(sys.modules, 'google.colab', colab)
    original_cwd, original_path = os.getcwd(), sys.path[:]
    try:
        exec(compile(code, '<notebook bootstrap>', 'exec'), {})
    finally:
        os.chdir(original_cwd)
        sys.path[:] = original_path
    assert calls == ['https://raw.githubusercontent.com/dungbeommm/NovelReader_Translate/main/NovelReader_GPU_notebook.zip']
    project = tmp_path/'NovelReader_T4_Web'
    assert (project/'web/routes/drive_exports.py').is_file()
    assert 'protect_request' in (project/'web/application.py').read_text()
    assert existing.read_text() == 'existing user checkpoint'
    assert not (project/'.env').exists()
    server = ''.join(notebook['cells'][10]['source'])
    ast.parse(server)
    assert 'NOVEL_EXPORT_SESSION_ID' in server
    assert 'X-Novel-Access' in server
    assert 'process_drive_requests, secrets' not in server
