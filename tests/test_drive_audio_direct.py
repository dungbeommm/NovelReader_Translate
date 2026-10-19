import threading
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace
import pytest
from gdrive import api_drive, export_service as service
from storage.store import Store


@pytest.fixture
def audio_env(tmp_path,monkeypatch):
    monkeypatch.setenv('NOVEL_DATA',str(tmp_path/'data'))
    monkeypatch.setenv('NOVEL_DRIVE_BACKEND','colab')
    monkeypatch.setenv('NOVEL_COLAB_DRIVE_ROOT',str(tmp_path/'drive/MyDrive'))
    monkeypatch.setenv('NOVEL_DRIVE_CREDENTIAL_DIR',str(tmp_path/'private'))
    store=Store(tmp_path/'db',tmp_path/'text',tmp_path/'audio')
    store.replace('Truyện.txt','utf8',[('第一章','你好')])
    for name in ('chuong_0001.mp3','chuong_0002.wav','nhom/chuong_0001.mp3'):
        file=store.audio_dir/name;file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(name.encode())
    (tmp_path/'drive/MyDrive').mkdir(parents=True)
    monkeypatch.setattr(service,'wait_for_permission',lambda *a,**k:None)
    return store,tmp_path


def finish(task):
    until=time.monotonic()+5
    while time.monotonic()<until:
        result=service.read_task(task['id'])
        if result['status'] in service.TERMINAL:return result
        time.sleep(.02)
    raise AssertionError('export timeout')


def test_audio_snapshot_is_directory_not_zip_and_ignores_private_files(audio_env,monkeypatch):
    store,tmp=audio_env
    hidden=store.audio_dir/'.audio-part';hidden.mkdir();(hidden/'partial.wav').write_bytes(b'partial')
    (store.audio_dir/'outside.mp3').symlink_to(tmp/'outside.mp3')
    (tmp/'outside.mp3').write_bytes(b'outside')
    monkeypatch.setattr(zipfile,'ZipFile',lambda *a,**k:pytest.fail('Drive audio must never create ZIP'))
    work=tmp/'snapshot';work.mkdir()
    snapshot,folder=service.stage_export(store,'audio',work)
    assert snapshot.is_dir()
    assert sorted(str(p.relative_to(snapshot)) for p in snapshot.rglob('*') if p.is_file())==['chuong_0001.mp3','chuong_0002.wav','nhom/chuong_0001.mp3']
    (store.audio_dir/'chuong_0001.mp3').write_bytes(b'changed later')
    assert (snapshot/'chuong_0001.mp3').read_bytes()==b'chuong_0001.mp3'


def test_colab_copies_individual_audio_names_and_folders(audio_env,monkeypatch):
    store,tmp=audio_env
    monkeypatch.setattr(zipfile,'ZipFile',lambda *a,**k:pytest.fail('no ZIP on Drive'))
    result=finish(service.start_export('audio',store,threading.RLock()))
    assert result['status']=='done',result
    dest=tmp/'drive/MyDrive'/result['drive_path']
    assert dest.is_dir() and '/audio/' in result['drive_path']
    assert sorted(str(p.relative_to(dest)) for p in dest.rglob('*') if p.is_file())==['chuong_0001.mp3','chuong_0002.wav','nhom/chuong_0001.mp3']
    assert result['uploaded_files']==result['total_files']==3
    assert not list(tmp.rglob('*.zip'))
    assert not list(dest.rglob('*.tmp'))
    assert (store.audio_dir/'chuong_0001.mp3').is_file()


def test_colab_partial_failure_keeps_completed_files_and_reports_count(audio_env,monkeypatch):
    store,tmp=audio_env
    original=service._atomic_copy
    calls=[]
    def copy(source,dest):
        calls.append(source)
        if len(calls)==2:raise OSError('Drive disconnected')
        original(source,dest)
    monkeypatch.setattr(service,'_atomic_copy',copy)
    result=finish(service.start_export('audio',store,threading.RLock()))
    assert result['status']=='error'
    assert result['uploaded_files']==1
    assert '1/3' in result['message']
    assert len(list((tmp/'drive').rglob('*.mp3')))==1
    assert (store.audio_dir/'chuong_0002.wav').is_file()


def test_api_dispatches_audio_directory_not_single_file(audio_env,monkeypatch):
    store,tmp=audio_env
    monkeypatch.setenv('NOVEL_DRIVE_BACKEND','api')
    monkeypatch.setattr(api_drive,'status',lambda:{'connected':True})
    monkeypatch.setattr(api_drive,'upload',lambda *a:pytest.fail('audio must use multi-file upload'))
    calls=[]
    def upload_audio(directory,book,batch,progress):
        paths=sorted(p for p in directory.rglob('*') if p.is_file())
        calls.extend(str(p.relative_to(directory)) for p in paths)
        progress(3,3,'nhom/chuong_0001.mp3',100)
        return {'drive_path':f'NovelReader_Exports/{book}/audio/{batch}', 'drive_url':'https://drive.google.com/drive/folders/test', 'uploaded_files':3,'total_files':3}
    monkeypatch.setattr(api_drive,'upload_audio',upload_audio)
    result=finish(service.start_export('audio',store,threading.RLock()))
    assert result['status']=='done'
    assert calls==['chuong_0001.mp3','chuong_0002.wav','nhom/chuong_0001.mp3']
    assert result['uploaded_files']==3
    assert not list(tmp.rglob('*.zip'))


def test_api_audio_upload_preserves_names_and_nested_folders(audio_env,monkeypatch):
    store,tmp=audio_env
    made=[];uploads=[];closed=[];progress=[]
    monkeypatch.setattr(api_drive,'_drive',lambda:SimpleNamespace(close=lambda:closed.append(True)))
    def folder(drive,name,parent=None):
        made.append((name,parent));return f'folder{len(made)}'
    monkeypatch.setattr(api_drive,'_folder',folder)
    def upload(drive,file,parent,name,callback):
        uploads.append((name,parent,file.read_bytes()));callback(50);return {'id':'file'}
    monkeypatch.setattr(api_drive,'_upload_file',upload)
    result=api_drive.upload_audio(store.audio_dir,'book','batch',lambda *args:progress.append(args))
    assert made[:4]==[('NovelReader_Exports',None),('book','folder1'),('audio','folder2'),('batch','folder3')]
    assert made[-1]==('nhom','folder4')
    assert [x[:2] for x in uploads]==[('chuong_0001.mp3','folder4'),('chuong_0002.wav','folder4'),('chuong_0001.mp3','folder5')]
    assert result['drive_url'].endswith('folder4')
    assert result['uploaded_files']==3 and progress[-1][0:2]==(3,3) and closed==[True]


def test_api_partial_failure_keeps_progress_and_originals(audio_env,monkeypatch):
    store,tmp=audio_env
    monkeypatch.setenv('NOVEL_DRIVE_BACKEND','api')
    monkeypatch.setattr(api_drive,'status',lambda:{'connected':True})
    monkeypatch.setattr(api_drive,'_drive',lambda:SimpleNamespace(close=lambda:None))
    monkeypatch.setattr(api_drive,'_folder',lambda *a,**k:'folder')
    calls=[]
    def upload(*args):
        calls.append(args)
        if len(calls)==2:raise RuntimeError('secret-token-must-not-leak')
        return {'id':'first'}
    monkeypatch.setattr(api_drive,'_upload_file',upload)
    result=finish(service.start_export('audio',store,threading.RLock()))
    assert result['status']=='error' and result['uploaded_files']==1
    assert '1/3' in result['message']
    assert 'secret-token-must-not-leak' not in result['message']
    assert all((store.audio_dir/name).is_file() for name in ('chuong_0001.mp3','chuong_0002.wav'))
    assert not (service.tasks_dir()/result['id']).exists()
