import base64
import hashlib
import json
import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from fastapi.testclient import TestClient
from gdrive import api_drive, export_service
from gdrive.colab_bridge import process_drive_requests
from storage.store import Store

CLIENT = json.dumps({'installed':{'client_id':'123-test.apps.googleusercontent.com','client_secret':'private-client-secret'}})


@pytest.fixture
def api_env(tmp_path, monkeypatch):
    monkeypatch.setenv('NOVEL_DRIVE_BACKEND','api')
    monkeypatch.setenv('NOVEL_DRIVE_CREDENTIAL_DIR',str(tmp_path/'private'))
    monkeypatch.setenv('NOVEL_DATA',str(tmp_path/'data'))
    monkeypatch.setenv('NOVEL_COLAB_DRIVE_BRIDGE','1') # old setting must not trigger mount
    return tmp_path


def test_kaggle_is_detected_before_old_mount_flag(monkeypatch):
    monkeypatch.delenv('NOVEL_DRIVE_BACKEND',raising=False)
    monkeypatch.setenv('KAGGLE_KERNEL_RUN_TYPE','Interactive')
    monkeypatch.setenv('NOVEL_COLAB_DRIVE_BRIDGE','1')
    assert export_service.drive_backend()=='api'


def test_kaggle_never_calls_colab_mount(api_env):
    calls=[]
    task={'id':'a'*32,'status':'waiting_permission','session_id':os.getenv('NOVEL_EXPORT_SESSION_ID','')}
    export_service.write_task(task)
    assert process_drive_requests(export_service.tasks_dir(),calls.append)==0
    assert not calls


def test_desktop_oauth_link_has_pkce_and_limited_scope(api_env):
    result=api_drive.begin(CLIENT)
    query=parse_qs(urlsplit(result['auth_url']).query)
    pending=api_drive._read('pending.json')
    assert query['redirect_uri']==[api_drive.REDIRECT]
    assert query['scope']==api_drive.SCOPES
    assert query['code_challenge_method']==['S256']
    challenge=base64.urlsafe_b64encode(hashlib.sha256(pending['verifier'].encode()).digest()).decode().rstrip('=')
    assert query['code_challenge']==[challenge]
    assert query['state']==[pending['state']]
    assert 'urn:ietf:wg:oauth:2.0:oob' not in result['auth_url']
    assert pending['verifier'] not in json.dumps(result)
    assert 'private-client-secret' not in json.dumps(result)
    assert (api_env/'private/pending.json').stat().st_mode & 0o777 == 0o600
    assert (api_env/'private').stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize('client',[{}, {'web':{}}, {'type':'service_account'}, {'installed':{'client_id':'https://evil.example','client_secret':'s'}}])
def test_invalid_oauth_clients_are_rejected(api_env,client):
    with pytest.raises(ValueError):api_drive.begin(json.dumps(client))


def test_uploaded_oauth_endpoints_cannot_redirect_secrets(api_env):
    client=json.loads(CLIENT)
    client['installed']['token_uri']='https://evil.example/token'
    api_drive.begin(json.dumps(client))
    assert api_drive._read('pending.json')['config']['installed']['token_uri']=='https://oauth2.googleapis.com/token'


def test_finish_verifies_state_expiry_and_redirect(api_env,monkeypatch):
    api_drive.begin(CLIENT)
    pending=api_drive._read('pending.json')
    for url in ['http://127.0.0.1:8765/?code=test&state=wrong','https://evil.example/?code=test',
                'http://127.0.0.1:9999/?code=test','test-code-only']:
        with pytest.raises(ValueError):api_drive.finish(url)
    pending['created_at']=time.time()-601
    api_drive._write('pending.json',pending)
    with pytest.raises(ValueError,match='hết hạn'):
        api_drive.finish(api_drive.REDIRECT+'?'+urlencode({'state':pending['state'],'code':'test'}))
    assert not api_drive.status()['connected']


def test_finish_saves_token_privately_and_never_returns_secrets(api_env,monkeypatch):
    api_drive.begin(CLIENT)
    pending=api_drive._read('pending.json')
    captured=[]
    class Flow:
        credentials=SimpleNamespace(has_scopes=lambda scopes:True,
            to_json=lambda:json.dumps({'token':'private-access','refresh_token':'private-refresh'}))
        def fetch_token(self,**kwargs):captured.append(kwargs)
    monkeypatch.setattr(api_drive,'_flow',lambda config,verifier:Flow())
    result=api_drive.finish(api_drive.REDIRECT+'?'+urlencode({'state':pending['state'],'code':'private-code'}))
    assert result['connected']
    assert captured==[{'code':'private-code','timeout':60}]
    assert 'private-' not in json.dumps(result)
    assert not (api_env/'private/pending.json').exists()
    assert not any('token' in p.name for p in (api_env/'data').glob('**/*'))
    assert api_drive.disconnect()=={'connected':False}
    assert not (api_env/'private/token.json').exists()


def test_export_uses_api_not_mount_and_keeps_original(api_env,monkeypatch):
    api_drive._write('token.json',{'token':'private-access'})
    store=Store(api_env/'db',api_env/'text',api_env/'audio')
    store.replace('Truyện.txt','utf8',[('第一章','你好')])
    chapter=store.list()[0]
    store.update(chapter['id'],status='done',translated=['Xin chào'])
    calls=[]
    def upload(file,folder,name,progress):
        calls.append(file.read_bytes());progress(50)
        return {'drive_path':f'NovelReader_Exports/{folder}/{name}','drive_url':'https://drive.google.com/file/d/test/view'}
    monkeypatch.setattr(api_drive,'upload',upload)
    monkeypatch.setattr(export_service,'wait_for_permission',lambda *a:pytest.fail('Kaggle must not wait for mount'))
    task=export_service.start_export('txt',store,threading.RLock())
    until=time.monotonic()+5
    while time.monotonic()<until:
        result=export_service.read_task(task['id'])
        if result['status'] in export_service.TERMINAL:break
        time.sleep(.03)
    assert result['status']=='done',result
    assert calls and 'Xin chào'.encode() in calls[0]
    assert store.get(chapter['id'])['translated']==['Xin chào']
    assert not (export_service.tasks_dir()/task['id']).exists()


def test_api_requires_explicit_connection_before_export(api_env):
    store=Store(api_env/'db',api_env/'text',api_env/'audio')
    store.replace('Truyện.txt','utf8',[('第一章','你好')])
    with pytest.raises(ValueError,match='Chưa kết nối'):
        export_service.start_export('txt',store,threading.RLock())


def test_drive_api_endpoints_remain_authenticated(api_env,monkeypatch):
    monkeypatch.setenv('NOVEL_WEB_ACCESS_TOKEN','web-private-code')
    from web.application import create_app
    with TestClient(create_app()) as client:
        assert client.get('/api/drive-api/status').status_code==403
        client.get('/?access_token=web-private-code')
        response=client.get('/api/export/drive/capabilities')
        assert response.json()['backend']=='api'
        assert response.json()['permission_location']=='web_oauth'
        assert client.post('/api/drive-api/begin',json={'client_json':CLIENT}).status_code==403
        headers={'X-App-Request':'novel-translator'}
        response=client.post('/api/drive-api/begin',json={'client_json':CLIENT},headers=headers)
        assert response.status_code==200
        assert 'private-client-secret' not in response.text
        response=client.get('/api/drive-api/status')
        assert response.json()['connected'] is False
        assert 'private-client-secret' not in response.text


def test_kaggle_notebook_config_uses_api_and_keeps_gpu_zero(tmp_path,monkeypatch):
    import subprocess,sys
    x=json.loads((Path(__file__).resolve().parents[1]/'NovelReader_Colab.ipynb').read_text())
    monkeypatch.setattr(subprocess,'run',lambda *a,**k:SimpleNamespace(stdout='2\n'))
    before=dict(os.environ)
    try:
        code=''.join(x['cells'][6]['source'])
        exec(compile(code,'<Kaggle config>','exec'),{'os':os,'sys':sys,'subprocess':subprocess,'Path':Path,'REPO_DIR':tmp_path,'IS_KAGGLE':True})
        assert os.environ['NOVEL_DRIVE_BACKEND']=='api'
        assert os.environ['NOVEL_COLAB_DRIVE_BRIDGE']=='0'
        assert os.environ['HACHIMIMT_GPU_INDICES']=='0'
        assert os.environ['HACHIMIMT_AUTO_ALL_GPUS']=='0'
        assert 'NOVEL_BALANCE_GPUS' not in code
        assert os.environ['COLAB_GPU']=='1'  # original v4.2 config kept unchanged
    finally:
        os.environ.clear();os.environ.update(before)
    assert "if not IS_KAGGLE:\n    from google.colab import drive" in ''.join(x['cells'][10]['source'])
    assert 'from google.colab' not in ''.join(x['cells'][2]['source'])
    assert 'FileLink' in ''.join(x['cells'][12]['source'])


def test_api_upload_is_disk_backed_resumable_and_reports_completion(api_env,monkeypatch):
    calls=[]
    class Request:
        count=0
        def next_chunk(self,**kwargs):
            self.count+=1
            return (SimpleNamespace(progress=lambda:.5),None) if self.count==1 else (None,{'id':'test-file','webViewLink':'https://drive.google.com/file/d/test-file/view'})
    class Files:
        def list(self,**kwargs):
            calls.append(('list',kwargs))
            return SimpleNamespace(execute=lambda **k:{'files':[{'id':'folder'}]})
        def create(self,**kwargs):
            calls.append(('create',kwargs))
            return Request()
    closed=[]
    monkeypatch.setattr(api_drive,'_drive',lambda:SimpleNamespace(files=lambda:Files(),close=lambda:closed.append(True)))
    path=api_env/'export.zip';path.write_bytes(b'qa only')
    progress=[]
    result=api_drive.upload(path,"Truyện 'A'",'qa_export.zip',progress.append)
    assert result['drive_path']=="NovelReader_Exports/Truyện 'A'/qa_export.zip"
    media=next(k['media_body'] for action,k in calls if action=='create')
    assert media.resumable() and media.chunksize()==8*1024*1024
    assert progress==[50] and closed==[True]


def test_api_failure_does_not_expose_access_token(api_env,monkeypatch):
    class Files:
        def list(self,**kwargs):raise RuntimeError('private-access-token')
    monkeypatch.setattr(api_drive,'_drive',lambda:SimpleNamespace(files=lambda:Files(),close=lambda:None))
    path=api_env/'export.txt';path.write_text('original')
    with pytest.raises(ValueError) as exc:
        api_drive.upload(path,'book','export.txt')
    assert 'private-access-token' not in str(exc.value)
    assert path.read_text()=='original'


def test_valid_short_lived_access_token_without_refresh_can_upload(api_env,monkeypatch):
    import googleapiclient.discovery
    api_drive._write('token.json',{'token':'private-access','client_id':'test-client',
        'client_secret':'private-secret','expiry':'2035-01-01T00:00:00Z',
        'token_uri':'https://oauth2.googleapis.com/token','scopes':api_drive.SCOPES})
    fake=object()
    monkeypatch.setattr(googleapiclient.discovery,'build',lambda *a,**k:fake)
    assert api_drive._drive() is fake


def test_kaggle_bootstrap_keeps_legacy_checkpoint(tmp_path,monkeypatch):
    import io,sys,subprocess,urllib.request,zipfile
    root=Path(__file__).resolve().parents[1]
    notebook=json.loads((root/'NovelReader_Colab.ipynb').read_text())
    legacy=tmp_path/'legacy/NovelReader_T4_Web'
    (legacy/'data').mkdir(parents=True)
    (legacy/'data/novel.sqlite3').write_text('existing checkpoint')
    code=''.join(notebook['cells'][2]['source']).replace('/content',str(tmp_path/'legacy')).replace('/kaggle/working',str(tmp_path/'working'))
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
    assert (legacy/'gdrive/api_drive.py').is_file()
    assert (tmp_path/'working/NovelReader_GPU_notebook.zip').is_file()
