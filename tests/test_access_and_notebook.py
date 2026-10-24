import json
import os
import zipfile
from pathlib import Path
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient

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
        assert response.headers['location'] == '/?cookie_check=1'
        assert client.get('/api/state').status_code == 200
        with client.websocket_connect('/ws/progress') as ws:
            assert ws.receive_json()['type'] == 'snapshot'


def test_notebook_bootstrap_embedded_source_without_network_or_upload(tmp_path, monkeypatch):
    import io
    import os
    import sys
    import types
    import urllib.request
    import subprocess
    import ast
    root = Path(__file__).resolve().parents[1]
    notebook = json.loads((root/'NovelReader_Colab.ipynb').read_text(encoding='utf-8'))
    code = ''.join(notebook['cells'][2]['source'])
    assert 'files.upload(' not in code
    code = code.replace('/content', str(tmp_path).replace('\\', '/'))
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
    colab.files = types.SimpleNamespace()
    monkeypatch.setitem(sys.modules, 'google.colab', colab)
    original_cwd, original_path = os.getcwd(), sys.path[:]
    try:
        exec(compile(code, '<notebook bootstrap>', 'exec'), {})
    finally:
        os.chdir(original_cwd)
        sys.path[:] = original_path
    assert calls == []
    project = tmp_path/'NovelReader_T4_Web'
    assert existing.read_text() == 'existing user checkpoint'
    assert not (project/'.env').exists()
    server = ''.join(notebook['cells'][10]['source'])
    ast.parse(server)
    assert 'X-Novel-Access' in server


def test_access_error_has_explicit_utf8_and_recovery_steps(tmp_path, monkeypatch):
    from web.access import protect_request
    monkeypatch.setenv('NOVEL_WEB_ACCESS_TOKEN', 'private-test-secret')
    request = SimpleNamespace(query_params={}, url=SimpleNamespace(path='/api/state'), headers={}, cookies={})
    response = protect_request(request)
    assert response.status_code == 403
    assert response.headers['content-type'].lower() == 'text/plain; charset=utf-8'
    text = response.body.decode('utf-8')
    assert 'Chưa được phép truy cập' in text
    assert 'Mở NovelReader' in text
    assert 'link mới' in text
    assert 'private-test-secret' not in text


def test_old_session_link_is_denied_without_echoing_secrets(monkeypatch):
    from web.access import protect_request
    monkeypatch.setenv('NOVEL_WEB_ACCESS_TOKEN', 'current-secret')
    request = SimpleNamespace(method='GET', query_params={'access_token': 'old-secret'}, url=SimpleNamespace(path='/'), headers={}, cookies={})
    response = protect_request(request)
    assert response.status_code == 200
    assert 'Mã không đúng' in response.body.decode()
    assert b'old-secret' not in response.body
    assert b'current-secret' not in response.body


def test_login_form_recovers_missing_link_token(tmp_path, monkeypatch):
    monkeypatch.setenv('NOVEL_DATA', str(tmp_path/'data'))
    monkeypatch.setenv('NOVEL_WEB_ACCESS_TOKEN', 'login-only-secret')
    from web.application import create_app
    with TestClient(create_app()) as client:
        response = client.get('/')
        assert response.status_code == 200
        assert 'name="token"' in response.text
        assert 'login-only-secret' not in response.text
        assert client.get('/api/state').status_code == 403
        for code in ['wrong-secret', 'mã sai tiếng Việt']:
            response = client.post('/auth/login', data={'token':code})
            assert 'Mã không đúng' in response.text
            assert client.get('/api/state').status_code == 403
        response = client.post('/auth/login', data={'token':'login-only-secret'}, follow_redirects=False)
        assert response.status_code == 303
        cookie = response.headers['set-cookie'].lower()
        assert 'samesite=lax' in cookie and 'httponly' in cookie
        assert 'login-only-secret' not in response.headers['location']
        assert client.get(response.headers['location']).status_code == 200
        assert client.get('/api/state').status_code == 200
        with client.websocket_connect('/ws/progress') as ws:
            assert ws.receive_json()['type'] == 'snapshot'


def test_login_rejects_cross_origin_and_large_body(tmp_path, monkeypatch):
    monkeypatch.setenv('NOVEL_DATA', str(tmp_path/'data'))
    monkeypatch.setenv('NOVEL_WEB_ACCESS_TOKEN', 'login-only-secret')
    from web.application import create_app
    with TestClient(create_app()) as client:
        assert client.post('/auth/login', data={'token':'login-only-secret'}, headers={'Origin':'https://evil.example'}).status_code == 403
        assert client.post('/auth/login', content=b'x'*2049).status_code == 413
        assert client.get('/auth/login').status_code == 405
        assert client.get('/api/state').status_code == 403
        response = client.get('/?access_token=%C4%91%C3%A2y-kh%C3%B4ng-ph%E1%BA%A3i-m%C3%A3')
        assert response.status_code == 200
        assert client.get('/api/state').status_code == 403


def test_cookie_failure_shows_help_without_redirect_loop(tmp_path, monkeypatch):
    monkeypatch.setenv('NOVEL_DATA', str(tmp_path/'data'))
    monkeypatch.setenv('NOVEL_WEB_ACCESS_TOKEN', 'login-only-secret')
    from web.application import create_app
    with TestClient(create_app()) as client:
        response = client.get('/?access_token=login-only-secret', follow_redirects=False)
        client.cookies.clear()
        response = client.get(response.headers['location'])
        assert response.status_code == 200
        assert 'chưa lưu cookie' in response.text
        assert client.get('/api/state').status_code == 403

def test_kaggle_bootstrap_keeps_legacy_checkpoint(tmp_path,monkeypatch):
    import io,sys,subprocess,urllib.request,zipfile
    root=Path(__file__).resolve().parents[1]
    notebook=json.loads((root/'NovelReader_Colab.ipynb').read_text(encoding='utf-8'))
    legacy=tmp_path/'legacy/NovelReader_T4_Web'
    (legacy/'data').mkdir(parents=True)
    (legacy/'data/novel.sqlite3').write_text('existing checkpoint')
    code=''.join(notebook['cells'][2]['source']).replace('/content',(tmp_path/'legacy').as_posix()).replace('/kaggle/working',(tmp_path/'working').as_posix())
    payload=io.BytesIO()
    with zipfile.ZipFile(payload,'w') as z:
        z.writestr('NovelReader_T4_Web/main.py','# source')
        z.writestr('NovelReader_T4_Web/data/novel.sqlite3','must not replace')
    monkeypatch.setenv('KAGGLE_KERNEL_RUN_TYPE','Interactive')
    monkeypatch.setattr(urllib.request,'urlopen',lambda *a,**kw:io.BytesIO(payload.getvalue()))
    monkeypatch.setattr(subprocess,'run',lambda *a,**kw:None)
    before,path=os.getcwd(),sys.path[:]
    scope={}
    try:
        exec(compile(code,'<Kaggle bootstrap>','exec'),scope)
    finally:
        os.chdir(before);sys.path[:]=path
    assert scope['IS_KAGGLE']
    assert scope['REPO_DIR']==legacy
    assert (legacy/'data/novel.sqlite3').read_text()=='existing checkpoint'
    assert not (tmp_path/'working/NovelReader_GPU_notebook.zip').exists()
    assert (legacy/'audio/vieneu_service.py').is_file()
