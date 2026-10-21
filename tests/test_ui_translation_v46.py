"""v4.6 control wiring, fallback translation and unified export regression."""
import importlib,json,io,zipfile
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from bs4 import BeautifulSoup
from pathlib import Path
from web.schemas import Config
from translation.engines import LocalEngine
from workflows.jobs import translate_with_options
H={'X-App-Request':'novel-translator'}

@pytest.fixture
def client(tmp_path,monkeypatch):
 monkeypatch.setenv('NOVEL_DATA',str(tmp_path/'data'))
 import main
 importlib.reload(main)
 with TestClient(main.app) as c:yield c

@pytest.mark.parametrize('data,mode,enabled',[
 ({'normalize_t2s':False},'none',False),({'normalize_t2s':True},'auto',True),
 ({'normalize_mode':'none'},'none',False),({'normalize_mode':'t2s'},'t2s',True),
 ({'normalize_mode':'auto','normalize_t2s':False},'auto',True),
 ({'normalize_mode':'none','normalize_t2s':True},'none',False),
])
def test_normalization_canonical_and_legacy(data,mode,enabled):
 cfg=Config(**data);assert cfg.normalize_mode==mode and cfg.normalize_t2s==enabled


def fallback_engine():
 engine=LocalEngine();calls=[]
 engine.source=SimpleNamespace(encode=lambda text,out_type:[ord(c)+10 for c in text],id_to_piece=lambda i:str(i))
 engine.target=SimpleNamespace(decode=lambda pieces:''.join(chr(int(t)-10) for t in pieces))
 def translate(jobs,**kw):
  calls.append((jobs,kw));return [SimpleNamespace(hypotheses=[j[:-1]]) for j in jobs]
 engine.model=SimpleNamespace(translate_batch=translate)
 return engine,calls

@pytest.mark.parametrize('mode,job_count',[('sentence',2),('paragraph',1)])
def test_fallback_honors_chunk_and_beam(mode,job_count):
 engine,calls=fallback_engine()
 out=engine.translate_raw(['你好。世界！'],beam_size=4,chunk_mode=mode,normalize_mode='none')
 assert len(out)==1 and len(calls[0][0])==job_count
 assert calls[0][1]['beam_size']==4
 assert out[0].replace(' ','')=='你好。世界！'

@pytest.mark.parametrize('mode,expected',[('none','學校'),('auto','学校'),('t2s','学校')])
def test_fallback_normalization_real_opencc(mode,expected):
 engine,_=fallback_engine();assert engine.translate_raw(['學校'],normalize_mode=mode)==[expected]


def test_typeerror_inside_engine_not_retried_without_options():
 calls=[]
 class Broken:
  def translate(self,texts,glossary,**kw):calls.append(kw);raise TypeError('internal engine bug')
 with pytest.raises(TypeError,match='internal engine bug'):
  translate_with_options(Broken(),['x'],{},beam_size=4,chunk_mode='paragraph',normalize_mode='none')
 assert len(calls)==1 and calls[0]['beam_size']==4


def test_legacy_engine_signature_explicit_warning(caplog):
 class Legacy:
  def translate(self,texts,glossary):return texts
 assert translate_with_options(Legacy(),['x'],{},beam_size=4)==['x']
 assert 'không hỗ trợ' in caplog.text


def test_primary_engine_forwards_beam_chunk_normalize():
 from translation.core.chunker import split_chunks
 engine=LocalEngine();chunks=[];seen=[]
 class Core:
  @staticmethod
  def clamp_beam(v):return max(1,min(4,v))
  def _chunk_text(self,text,chunk_mode):seen.append((text,chunk_mode));return split_chunks(text,chunk_mode)
  def _translate_chunks_ct2(self,items,beam_size):chunks.append((items,beam_size));return items
 engine.translator=Core()
 assert engine.translate_raw(['學校。世界！'],beam_size=3,chunk_mode='paragraph',normalize_mode='t2s')==['学校。世界！']
 assert seen==[('学校。世界！','paragraph')] and chunks[0][1]==3


def test_export_options_and_zip_exclude_partial_files(client):
 from web import runtime
 assert client.get('/api/export/options').json()['chapters']==0
 client.post('/api/upload',headers=H,files={'file':('a.txt','第一章\n你好\n第二章\n世界'.encode())})
 cid=runtime.store.list()[0]['id'];runtime.store.update(cid,status='done',translated=['Xin chào'])
 (runtime.store.audio_dir/'chuong_0001.mp3').write_bytes(b'audio')
 work=runtime.store.audio_dir/'.audio-inprogress';work.mkdir();(work/'partial.wav').write_bytes(b'not finished')
 data=client.get('/api/export/options').json()
 assert data['chapters']==2 and data['translated']==1 and data['audio_files']==1 and data['audio_bytes']==5
 res=client.get('/api/export/audio');assert res.status_code==200
 with zipfile.ZipFile(io.BytesIO(res.content)) as z:assert z.namelist()==['chuong_0001.mp3']


def test_draft_normalization_round_trip(client):
 r=client.post('/api/checkpoints/draft',headers=H,json={'normalize_t2s':False})
 assert r.status_code==200
 data=client.get('/api/checkpoints/draft').json()['config'];assert data['normalize_mode']=='none' and data['normalize_t2s'] is False


def test_html_single_export_and_simple_sections():
 html=BeautifulSoup((Path(__file__).resolve().parents[1]/'web/static/index.html').read_text(encoding='utf-8'),'html.parser')
 assert html.select_one('.header-right #btn-open-export')
 assert not html.select('.header-right #export-txt,.header-right #export-epub,.header-right #export-audio')
 assert html.select_one('#legacy-export-actions').has_attr('hidden')
 assert len(html.select('input[name="export-kind"]'))==3
 assert len(html.select('.settings-nav .modal-tab'))==5
 assert html.select_one('#pane-tab-translation #opt-t2s')
 assert html.select_one('#pane-tab-backup #checkpoint-file')
 assert not html.select('#modal-auto-remove-toc')
 ids=[x['id'] for x in html.select('[id]')];assert len(ids)==len(set(ids))


def test_audio_filter_preserves_formats_and_rejects_linked_dirs(tmp_path):
 from audio.audio_service import exportable_audio_files
 root=tmp_path/'audio';root.mkdir()
 for ext in ('mp3','wav','m4b','m4a','opus','aac','ogg'):(root/f'good.{ext}').write_bytes(b'a')
 hidden=root/'.partial';hidden.mkdir();(hidden/'scratch.wav').write_bytes(b'a')
 outside=tmp_path/'other';outside.mkdir();(outside/'external.mp3').write_bytes(b'a')
 (root/'linked').symlink_to(outside,target_is_directory=True)
 (root/'direct.mp3').symlink_to(outside/'external.mp3')
 files=exportable_audio_files(root)
 assert {p.suffix for p in files}=={'.mp3','.wav','.m4b','.m4a','.opus','.aac','.ogg'}
 assert len(files)==7 and all(p.name.startswith('good.') for p in files)


def test_pixeldrain_audio_uses_completed_files_only(tmp_path,monkeypatch):
 from storage.store import Store
 from storage import pixeldrain_service as pd
 store=Store(tmp_path/'book.sqlite3',text_dir=tmp_path/'text',audio_dir=tmp_path/'audio')
 # Use the same book creation path as the existing API tests.
 from storage.files import parse_file
 parsed=parse_file('test.txt','第一章\n你好。'.encode())
 store.replace("test.txt",parsed[1],parsed[0])
 (store.audio_dir/'good.aac').write_bytes(b'audio')
 hidden=store.audio_dir/'.partial';hidden.mkdir();(hidden/'scratch.wav').write_bytes(b'partial')
 def upload(path,filename,api_key=None):
  with zipfile.ZipFile(path) as z:assert z.namelist()==['good.aac']
  return {'url':'https://pixeldrain.com/u/MockFile'}
 monkeypatch.setattr(pd,'upload_to_pixeldrain',upload)
 assert pd.export_book_to_pixeldrain(store,'audio')['url'].endswith('MockFile')
