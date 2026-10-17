import importlib
import pytest
from fastapi.testclient import TestClient

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('NOVEL_DATA',str(tmp_path));import main;importlib.reload(main)
    with TestClient(main.app) as c:yield c

H={'X-App-Request':'novel-translator'}
def test_upload_export(client):
    r=client.post('/api/upload',files={'file':('a.txt','第一章\n你好'.encode())},headers=H)
    assert r.status_code==200 and len(r.json()['chapters'])==1
    id=r.json()['chapters'][0]['id'];assert client.get(f'/api/chapters/{id}').json()['source']==['你好']
    assert 'Chưa dịch' in client.get('/api/export/txt').text
    assert client.get('/api/export/epub').headers['content-type']=='application/epub+zip'
    with client.websocket_connect('/ws/progress') as ws:assert ws.receive_json()['type']=='snapshot'

def test_csrf(client):
    assert client.post('/api/translate/start',json={}).status_code==403
    assert client.post('/api/translate/start',json={},headers={**H,'Origin':'https://evil.example'}).status_code==403

def test_errors(client):
    assert client.get('/api/chapters/999').status_code==404
    assert client.post('/api/translate/start',json={},headers=H).status_code==409
    assert client.post('/api/upload',files={'file':('x.exe',b'test')},headers=H).status_code==400
    assert client.post('/api/translate/start',json={'batch_size':0},headers=H).status_code==422
    assert client.post('/api/translate/pause',json={},headers=H).status_code==409

def test_delete_book(client):
    r=client.post('/api/upload',files={'file':('a.txt','第一章\n你好'.encode())},headers=H)
    assert r.status_code==200
    assert client.get('/api/state').json()['book'] is not None
    del_r=client.post('/api/book/delete',headers=H)
    assert del_r.status_code==200 and del_r.json()['ok'] is True
    assert client.get('/api/state').json()['book'] is None
    assert len(client.get('/api/chapters').json())==0

def test_reset_and_delete_chapters(client):
    content = '第一章\n你好\n第二章\n世界\n第三章\n再见'.encode('utf-8')
    r=client.post('/api/upload',files={'file':('book.txt',content)},headers=H)
    assert r.status_code==200
    chaps=client.get('/api/chapters').json()
    assert len(chaps)==3
    id1,id2,id3=chaps[0]['id'],chaps[1]['id'],chaps[2]['id']
    # Reset chapter 1
    res1=client.post(f'/api/chapters/{id1}/reset',headers=H)
    assert res1.status_code==200 and res1.json()['ok'] is True
    # Reset chapters 2 and 3 batch
    res_batch=client.post('/api/chapters/reset',json={'ids':[id2,id3]},headers=H)
    assert res_batch.status_code==200 and res_batch.json()['reset_count']==2
    # Delete chapter 2
    del2=client.post(f'/api/chapters/{id2}/delete',headers=H)
    assert del2.status_code==200
    chaps_after=client.get('/api/chapters').json()
    assert len(chaps_after)==2
    assert [c['position'] for c in chaps_after]==[1,2]
    # Delete batch
    del_batch=client.post('/api/chapters/delete',json={'ids':[id3]},headers=H)
    assert del_batch.status_code==200 and del_batch.json()['deleted_count']==1
    assert len(client.get('/api/chapters').json())==1
