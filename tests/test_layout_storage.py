import importlib
import io
import json
import sqlite3
import wave
import zipfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from storage.store import Store, _safe_filename
from audio import audio_service, merge_service
from scripts.migrate_layout import migrate
from translation.engines import LocalEngine
from translation.core.translator import MODELS_DIR
from paths import ROOT, translation_models, voice_models


def new_store(tmp_path):
    return Store(tmp_path/'data/db.sqlite', text_dir=tmp_path/'output_text', audio_dir=tmp_path/'output_audio')


def load(store, name='Truyện A.txt'):
    store.replace(name, 'utf8', [('Chương 1', 'Nội dung một'), ('Chương 2', 'Nội dung hai')])
    return store


def done(store):
    c = store.list()[0]
    store.update(c['id'], status='done', translated_title='Chương một', translated=['Bản dịch'])
    store.export_chapter_text(c['id'], 'Chương một', ['Bản dịch'], 1)
    store.export_full_book_text()


def test_title_folder_and_aggregate(tmp_path):
    store = load(new_store(tmp_path))
    done(store)
    assert store.text_dir == tmp_path/'output_text/Truyện A'
    assert store.audio_dir == tmp_path/'output_audio/Truyện A'
    assert (store.text_dir/'chuong_0001.txt').is_file()
    assert (store.text_dir/'toan_bo_truyen.txt').is_file()
    assert not list((tmp_path/'output_text').glob('*.txt'))


def test_import_preserves_previous_book_output(tmp_path):
    store = load(new_store(tmp_path))
    done(store)
    old_text, old_audio = store.text_dir, store.audio_dir
    (old_audio/'chuong_0001.mp3').write_bytes(b'old')
    load(store, 'Truyện B.txt')
    assert store.audio_dir.name == 'Truyện B'
    assert (old_text/'chuong_0001.txt').is_file()
    assert (old_audio/'chuong_0001.mp3').read_bytes() == b'old'
    store.clear()
    assert (old_text/'chuong_0001.txt').is_file()
    assert (old_audio/'chuong_0001.mp3').is_file()


def test_same_title_never_overwrites_existing_output(tmp_path):
    store = load(new_store(tmp_path))
    done(store)
    original = store.text_dir
    load(store)
    assert store.text_dir.name == 'Truyện A_2'
    assert (original/'chuong_0001.txt').is_file()
    current = store.text_dir
    store.set_title('Truyện A')
    assert store.text_dir == current


def test_folder_persists_on_restart(tmp_path):
    store = load(new_store(tmp_path))
    expected = store.text_dir
    assert new_store(tmp_path).text_dir == expected


def test_rename_moves_both_outputs_without_loss(tmp_path):
    store = load(new_store(tmp_path))
    done(store)
    (store.audio_dir/'chuong_0001.mp3').write_bytes(b'audio')
    old_text = store.text_dir
    store.set_title('Tên truyện đã dịch')
    assert store.text_dir.name == store.audio_dir.name == 'Tên truyện đã dịch'
    assert not old_text.exists()
    assert (store.audio_dir/'chuong_0001.mp3').read_bytes() == b'audio'
    assert 'TÊN TRUYỆN ĐÃ DỊCH' in (store.text_dir/'toan_bo_truyen.txt').read_text(encoding='utf-8')


@pytest.mark.parametrize('name', ['../abc', '..', 'CON', 'nul.txt', 'Truyện:/A?', '  Tên. ', 'a'*200])
def test_portable_safe_names(tmp_path, name):
    store = load(new_store(tmp_path))
    store.set_title(name)
    assert store.text_dir.resolve().is_relative_to(tmp_path/'output_text')
    assert store.text_dir.name == _safe_filename(store.text_dir.name)
    assert '/' not in store.text_dir.name and '\\' not in store.text_dir.name
    assert len(store.text_dir.name) <= 80


def test_long_colliding_titles(tmp_path):
    store = load(new_store(tmp_path), 'a'*150+'.txt')
    old = store.text_dir
    load(store, 'a'*150+'.txt')
    assert store.text_dir != old
    assert len(store.text_dir.name) <= 80


def test_sqlite_old_schema_upgrade(tmp_path):
    db=tmp_path/'data/db.sqlite'; db.parent.mkdir()
    with sqlite3.connect(db) as c:
        c.execute("CREATE TABLE book(id INTEGER PRIMARY KEY,title TEXT,filename TEXT,encoding TEXT,config TEXT DEFAULT '{}')")
        c.execute("INSERT INTO book(id,title,filename,encoding) VALUES(1,'Tên cũ','old.txt','utf8')")
    store = new_store(tmp_path)
    assert store.book()['output_folder'] == 'Tên cũ'
    assert store.text_dir.name == 'Tên cũ'


def test_reset_invalidates_only_affected_groups(tmp_path):
    store = load(new_store(tmp_path))
    done(store)
    groups = store.audio_dir/'audio_gop'; groups.mkdir()
    for name in ['chuong_0001_0050.mp3', 'chuong_0001_0050.mp3.sources.json', 'chuong_0051_0100.mp3']:
        (groups/name).write_bytes(b'a')
    store.reset_chapters([store.list()[0]['id']])
    assert not (groups/'chuong_0001_0050.mp3').exists()
    assert not (groups/'chuong_0001_0050.mp3.sources.json').exists()
    assert (groups/'chuong_0051_0100.mp3').is_file()
    assert not (store.text_dir/'toan_bo_truyen.txt').exists()


def test_canonical_audio_no_duplicate_alias(tmp_path, monkeypatch):
    store = load(new_store(tmp_path))
    monkeypatch.setattr(audio_service, 'get_voice', lambda _: object())
    def synth(voice,text,wav,work,**kw):
        with wave.open(str(wav), 'wb') as f:
            f.setparams((1,2,16000,0,'NONE','not compressed'));f.writeframes(b'\0\0'*1600)
    monkeypatch.setattr(audio_service, 'synth_text_to_wav', synth)
    path=audio_service.generate_chapter_audio(1,1,'Chương một',['Nội dung'],store.audio_dir,fmt='wav')
    assert path.name=='chuong_0001.wav'
    assert [p.name for p in store.audio_dir.iterdir()]==['chuong_0001.wav']


def test_api_title_group_download_and_zip(tmp_path, monkeypatch):
    monkeypatch.setenv('NOVEL_DATA',str(tmp_path/'api'))
    import main; importlib.reload(main)
    store=load(new_store(tmp_path))
    monkeypatch.setattr(main.runtime,'store',store)
    from workflows.jobs import Job
    monkeypatch.setattr(main.runtime,'job',Job(store))
    for pos in (1,2):
        with wave.open(str(store.audio_dir/f'chuong_{pos:04d}.wav'),'wb') as f:
            f.setparams((1,2,16000,0,'NONE','not compressed'));f.writeframes(b'\0\0'*1600)
    with TestClient(main.app) as client:
        h={'X-App-Request':'novel-translator'}
        result=client.post('/api/book/title',json={'title':'Tên Việt'},headers=h)
        assert result.status_code==200
        result=client.post('/api/audio/auto-group',json={'group_size':2,'format':'wav'},headers=h)
        assert result.status_code==200
        group=result.json()['groups'][0]
        assert Path(group['file_path']).parent==store.audio_dir/'audio_gop'
        assert not (store.audio_dir/group['filename']).exists()
        assert client.get(group['url']).status_code==200
        assert client.get('/api/chapters/1/audio').status_code==200
        result=client.get('/api/export/audio')
        assert result.status_code==200
        with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
            assert sorted(archive.namelist())==['audio_gop/chuong_0001_0002.wav','chuong_0001.wav','chuong_0002.wav']


def test_model_and_voice_paths_are_root_level():
    assert translation_models()==ROOT/'models/translation'
    assert MODELS_DIR==ROOT/'models/translation'
    assert voice_models()==ROOT/'models/voices'
    assert not (ROOT/'translator').exists()


def test_migration_preview_apply_and_conflict(tmp_path):
    old=tmp_path/'old';new=tmp_path/'new'
    (old/'translator/models/ModelA').mkdir(parents=True)
    (old/'translator/models/ModelA/model.bin').write_bytes(b'weights')
    (old/'tts/voice').mkdir(parents=True)
    (old/'tts/voice/test.onnx').write_bytes(b'voice')
    migrate(old,new)
    assert not new.exists()
    migrate(old,new,apply=True)
    assert (new/'models/translation/ModelA/model.bin').read_bytes()==b'weights'
    assert (old/'tts/voice/test.onnx').is_file()
    (new/'models/voices/test.onnx').write_bytes(b'other')
    with pytest.raises(ValueError): migrate(old,new,apply=True)
    assert (new/'models/voices/test.onnx').read_bytes()==b'other'


def test_flat_output_migration_is_opt_in(tmp_path):
    old=tmp_path/'old';new=tmp_path/'new';(old/'translator/data').mkdir(parents=True)
    with sqlite3.connect(old/'translator/data/novel.sqlite3') as c:
        c.execute('CREATE TABLE book(id INTEGER PRIMARY KEY,title TEXT)')
        c.execute("INSERT INTO book VALUES(1,'Truyện cũ')")
    (old/'output_audio/groups').mkdir(parents=True)
    (old/'output_audio/chuong_0001.mp3').write_bytes(b'a')
    (old/'output_audio/groups/chuong_0001_0050.mp3').write_bytes(b'group')
    migrate(old,new,apply=True)
    assert not (new/'output_audio').exists()
    migrate(old,new,apply=True,flat_output=True)
    assert (new/'output_audio/Truyện cũ/chuong_0001.mp3').read_bytes()==b'a'
    assert (new/'output_audio/Truyện cũ/audio_gop/chuong_0001_0050.mp3').read_bytes()==b'group'


def test_engine_uses_the_relocated_core(monkeypatch):
    import translation.core.translator as core
    calls=[]
    class Fake:
        def load(self, key, backend): calls.append((key, backend))
    monkeypatch.setattr(core,'HachimiTranslator',Fake)
    engine=LocalEngine('HachimiMT-60-QT')
    engine.load()
    assert isinstance(engine.translator,Fake)
    assert calls[0][0]=='HachimiMT-60-QT'


def test_shared_piper_adapter_for_web_and_tts(tmp_path):
    from tts.synthesis import synthesize_wav
    from tts.pipeline.batch_tts import synth_to_wav
    calls=[]
    class Voice:
        def synthesize_wav(self,text,wav_file,syn_config=None):
            calls.append((text,syn_config))
            wav_file.setparams((1,2,16000,0,'NONE','not compressed'))
            wav_file.writeframes(b'\0\0'*1600)
    with wave.open(str(tmp_path/'web.wav'),'wb') as f:
        synthesize_wav(Voice(),'web',f,length_scale=1.2,noise_scale=0.4,noise_w_scale=0.6)
    synth_to_wav(Voice(),'service',str(tmp_path/'service.wav'),length_scale=1.2,noise_scale=0.4,noise_w=0.6)
    assert [text for text,config in calls]==['web','service']
    assert all(config.length_scale==1.2 and config.noise_scale==0.4 and config.noise_w_scale==0.6 for text,config in calls)


def test_paths_do_not_depend_on_current_directory(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert translation_models()==ROOT/'models/translation'
    assert voice_models()==ROOT/'models/voices'


@pytest.mark.parametrize('operation', ['import', 'delete'])
def test_new_book_or_delete_clears_old_job_scope(tmp_path,monkeypatch,operation):
    monkeypatch.setenv('NOVEL_DATA',str(tmp_path/'api'))
    import main;importlib.reload(main)
    main.runtime.store.replace('old.txt','utf8',[('Chapter 1','a')])
    main.runtime.job.target_chapter_ids=[1]
    main.runtime.job.scope_label='Chương 1 - 1'
    with TestClient(main.app) as client:
        headers={'X-App-Request':'novel-translator'}
        if operation=='import':
            response=client.post('/api/upload',files={'file':('new.txt','第一章\n你好'.encode())},headers=headers)
        else:
            response=client.post('/api/book/delete',headers=headers)
        assert response.status_code==200
        assert client.get('/api/state').json()['progress']['scope']==''
