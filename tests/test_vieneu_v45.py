"""v4.5 regression; SDK mocked, FFmpeg/ffprobe real. No model inference claim."""
import importlib,io,json,sys,wave,zipfile,subprocess
from types import SimpleNamespace
import numpy as np
import pytest
from fastapi.testclient import TestClient
from audio import audio_service as a,vieneu_service as v
from web.schemas import Config
H={'X-App-Request':'novel-translator'}
@pytest.fixture
def client(tmp_path,monkeypatch):
 monkeypatch.setenv('NOVEL_DATA',str(tmp_path/'data'))
 import main
 importlib.reload(main)
 with TestClient(main.app) as c:yield c

def book(c):
 from web import runtime
 cid=c.post('/api/upload',headers=H,files={'file':('a.txt','第一章\n你好'.encode())}).json()['chapters'][0]['id']
 runtime.store.update(cid,status='done',translated=['Xin chào.'],translated_title='Chương một')
 return cid

def fake(monkeypatch):
 calls=[]
 def generate(cid,pos,title,paras,directory,**kw):
  calls.append(kw);p=directory/f'chuong_{pos:04d}.{kw["fmt"]}';p.write_bytes(b'audio');return p
 monkeypatch.setattr(a,'generate_chapter_audio',generate);return calls

@pytest.mark.parametrize('patch',[{'speed':1.25,'format':'wav','bitrate':'192k','noise_scale':1.2,'noise_w_scale':.4},{'audio_speed':.9,'audio_format':'opus','audio_bitrate':'64k','audio_sample_rate':48000},{'tts_engine':'vieneu','voice_id':'truc_ly','vieneu_temperature':1.1,'vieneu_top_p':.7,'vieneu_batch_size':16}])
def test_single_overrides(client,monkeypatch,patch):
 cid=book(client);calls=fake(monkeypatch);res=client.post(f'/api/chapters/{cid}/audio',headers=H,json=patch)
 assert res.status_code==200,res.text
 cfg=res.json()['settings'];assert calls==[a.generation_kwargs(cfg)]
 for k,val in patch.items():assert cfg[{'speed':'audio_speed','format':'audio_format','bitrate':'audio_bitrate'}.get(k,k)]==val

@pytest.mark.parametrize('patch',[{'audio_speed':0},{'audio_speed':3},{'vieneu_temperature':2},{'vieneu_top_p':1.5},{'vieneu_batch_size':65},{'audio_sample_rate':12345},{'noise_scale':3},{'voice_id':'../x'},{'tts_engine':'fake'},{'emotion':'sad'}])
def test_invalid_requests(client,monkeypatch,patch):
 cid=book(client);calls=fake(monkeypatch)
 assert client.post(f'/api/chapters/{cid}/audio',headers=H,json=patch).status_code==422
 assert not calls

def test_persist_settings_and_omitted_body(client,monkeypatch):
 from web import runtime
 cid=book(client);calls=fake(monkeypatch)
 runtime.store.configure(Config(glossary='龙\tRồng',beam_size=3).model_dump())
 runtime.store.update(cid,audio_status='done')
 patch={'tts_engine':'vieneu','vieneu_temperature':.65,'audio_format':'wav','audio_speed':1.25,'audio_sample_rate':44100}
 assert client.post('/api/settings/audio',headers=H,json=patch).status_code==200
 cfg=json.loads(runtime.store.book()['config']);assert cfg['glossary']=='龙\tRồng' and cfg['beam_size']==3 and cfg['voice_id']=='truc_ly'
 assert runtime.store.get(cid)['audio_status']=='none' and runtime.store.get(cid)['status']=='done'
 assert client.post(f'/api/chapters/{cid}/audio',headers=H).status_code==200
 assert calls[0]['tts_engine']=='vieneu' and calls[0]['speed']==1.25 and calls[0]['vieneu_temperature']==.65
 assert client.get('/api/settings/audio').json()['settings']['voice_id']=='truc_ly'
 assert client.get('/api/checkpoints/draft').json()['config']['vieneu_temperature']==.65

def test_busy_guard(client):
 from web import runtime
 cid=book(client);runtime.job.thread=SimpleNamespace(is_alive=lambda:True)
 try:
  assert client.post('/api/settings/audio',headers=H,json={}).status_code==409
  assert client.post(f'/api/chapters/{cid}/audio',headers=H,json={}).status_code==409
 finally:runtime.job.thread=None

def test_voice_catalog(client):
 assert len(client.get('/api/voices?tts_engine=piper').json())>=22
 voices=client.get('/api/voices?tts_engine=vieneu').json()
 assert len(voices)==25 and all(x['sample_rate']==48000 for x in voices)
 assert client.get('/api/voices?tts_engine=bad').status_code==400

def tone(p,rate=48000):
 with wave.open(str(p),'wb') as f:
  f.setparams((1,2,rate,0,'NONE','not compressed'));f.writeframes((np.sin(np.arange(3*rate)*2*np.pi*440/rate)*16000).astype('<i2').tobytes())
def probe(p):return json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(p)]))

def test_real_codecs_speed_rates(tmp_path):
 raw=tmp_path/'raw.wav';tone(raw)
 for rate,k in [(24000,'64k'),(48000,'192k')]:
  out=tmp_path/f'{k}.mp3';a.convert_wav(raw,out,bitrate=k,sample_rate=rate);stream=probe(out)['streams'][0]
  assert stream['sample_rate']==str(rate) and stream['bit_rate']==str(int(k[:-1])*1000)
 assert (tmp_path/'192k.mp3').stat().st_size>(tmp_path/'64k.mp3').stat().st_size*2.5
 for speed in (.4,1.25,2.5):
  out=tmp_path/f'{speed}.wav';a.convert_wav(raw,out,'wav',sample_rate=22050,speed=speed)
  assert abs(float(probe(out)['format']['duration'])-3/speed)<.12
  assert probe(out)['streams'][0]['sample_rate']=='22050'
 out=tmp_path/'o.opus';a.convert_wav(raw,out,'opus',sample_rate=22050);assert probe(out)['streams'][0]['sample_rate']=='48000'
 x,y=tmp_path/'x.wav',tmp_path/'y.wav';a.convert_wav(raw,x,'wav','64k');a.convert_wav(raw,y,'wav','192k');assert x.read_bytes()==y.read_bytes()

def test_mp3_192_not_silently_downgraded(tmp_path):
 raw=tmp_path/'r.wav';tone(raw,22050)
 for rate in (0,22050):
  with pytest.raises(ValueError,match='192 kbps'):a.convert_wav(raw,tmp_path/'bad.mp3',bitrate='192k',sample_rate=rate)
 a.convert_wav(raw,tmp_path/'ok.mp3',bitrate='192k',sample_rate=44100);assert probe(tmp_path/'ok.mp3')['streams'][0]['bit_rate']=='192000'

@pytest.mark.parametrize('engine',['piper','vieneu'])
def test_dispatch_no_double_speed(tmp_path,monkeypatch,engine):
 calls=[];monkeypatch.setattr(a,'get_voice',lambda _:object())
 def piper(voice,text,out,work,**kw):calls.append(kw);tone(out)
 def vieneu(text,vid,out,**kw):calls.append(kw);tone(out)
 def convert(inp,out,**kw):calls.append(kw);out.write_bytes(inp.read_bytes())
 monkeypatch.setattr(a,'synth_text_to_wav',piper);monkeypatch.setattr(v,'synthesize_to_wav',vieneu);monkeypatch.setattr(a,'convert_wav',convert)
 a.generate_chapter_audio(1,1,'title',['text'],tmp_path,tts_engine=engine,speed=1.25,noise_scale=.35,noise_w_scale=.45,fmt='wav',sample_rate=24000,vieneu_temperature=.65,vieneu_top_p=.8,vieneu_batch_size=4)
 if engine=='piper':assert calls[0]=={'length_scale':.8,'noise_scale':.35,'noise_w_scale':.45} and 'speed' not in calls[1]
 else:assert calls[0]=={'temperature':.65,'top_p':.8,'batch_size':4} and calls[1]['speed']==1.25

def test_old_audio_kept_on_failure(tmp_path,monkeypatch):
 old=tmp_path/'chuong_0001.mp3';old.write_bytes(b'old');monkeypatch.setattr(a,'get_voice',lambda _:object())
 def synth(voice,text,out,work,**kw):tone(out)
 monkeypatch.setattr(a,'synth_text_to_wav',synth)
 def fail(*args,**kw):raise RuntimeError('failed')
 monkeypatch.setattr(a,'convert_wav',fail)
 with pytest.raises(RuntimeError):a.generate_chapter_audio(1,1,'t',['x'],tmp_path,fmt='wav')
 assert old.read_bytes()==b'old'
 monkeypatch.setattr(a,'convert_wav',lambda inp,out,**kw:out.write_bytes(inp.read_bytes()))
 p=a.generate_chapter_audio(1,1,'t',['x'],tmp_path,fmt='wav');assert not old.exists() and a.get_chapter_audio_path(tmp_path,1,1)==p

def test_sdk_contract(monkeypatch,tmp_path):
 calls=[]
 def infer(**kw):calls.append(kw);return np.ones(4800,dtype=np.float32)*.1
 monkeypatch.setattr(v,'ensure_references',lambda:{'voices':{'truc_ly':{'speaker_emb':[.1]*192,'codes':[[1]*16]*3}}})
 monkeypatch.setattr(v,'get_runtime',lambda:SimpleNamespace(infer=infer));out=tmp_path/'out.wav';v.synthesize_to_wav('Nội dung','truc_ly',out,.6,.7,12)
 kw=calls[0];assert kw['temperature']==.6 and kw['top_p']==.7 and kw['batch_size']==12
 assert kw['voice']['speaker_emb'].shape==(192,) and kw['voice']['codes'].shape==(3,16)
 assert 'style' not in kw and 'noise_scale' not in kw and probe(out)['streams'][0]['sample_rate']=='48000'
 with pytest.raises(ValueError):v.synthesize_to_wav('x','unknown',out)

@pytest.mark.parametrize('device,backend',[('cpu','onnx'),('cuda','pytorch')])
def test_official_backbone_not_gguf(monkeypatch,device,backend):
 calls=[]
 def factory(**kw):calls.append(kw);return SimpleNamespace(backend=kw['backend'])
 monkeypatch.setitem(sys.modules,'vieneu',SimpleNamespace(Vieneu=factory));monkeypatch.setenv('VIENEU_DEVICE',device);monkeypatch.setattr(v,'_runtime',None);monkeypatch.setattr(v,'_runtime_key',None)
 assert v.get_runtime().backend==backend and v.get_runtime() is v.get_runtime() and len(calls)==1
 assert calls[0]['mode']=='v3turbo' and '.gguf' not in str(calls[0])

def test_refs_converter_guards():
 ids=[x['id'] for x in v.catalog()]
 def archive(unsafe=False):
  b=io.BytesIO()
  with zipfile.ZipFile(b,'w',zipfile.ZIP_DEFLATED) as z:
   z.writestr('config.json',json.dumps({'model_type':'vieneu','voices':ids,'speaker_id_map':{k:i for i,k in enumerate(ids)}}))
   for vid in ids:
    z.writestr(f'voices/{vid}/speaker.emb.txt',','.join(['.1']*192));z.writestr(f'voices/{vid}/ref_codes.txt',' '.join(['1']*16))
   if unsafe:z.writestr('../escape','x')
  b.seek(0);return b
 assert len(v.read_references(archive())['voices'])==25
 with pytest.raises(ValueError):v.read_references(archive(True))

def test_pipeline_shared_worker(tmp_path,monkeypatch):
 from tests.test_range_audio_workflow import make_store,FakeEngine
 from workflows.jobs import Job
 import threading,time
 store=make_store(tmp_path,4);lock=threading.Lock();active=0;peak=0;calls=[]
 monkeypatch.setattr('workflows.jobs.create_engine',lambda _:FakeEngine())
 def generate(cid,pos,title,paras,directory,**kw):
  nonlocal active,peak
  with lock:active+=1;peak=max(peak,active)
  time.sleep(.02);calls.append(kw)
  with lock:active-=1
  p=directory/f'chuong_{pos:04d}.wav';p.write_bytes(b'x');return p
 monkeypatch.setattr(a,'generate_chapter_audio',generate);job=Job(store);job.start(Config(tts_engine='vieneu',audio_workers=4,vieneu_batch_size=16).model_dump());job.thread.join(10)
 assert len(calls)==4 and peak==1 and all(x['vieneu_batch_size']==16 for x in calls)

def test_checkpoint_keeps_vieneu(client,tmp_path):
 from storage import checkpoints
 from web import runtime
 book(client);cfg={'tts_engine':'vieneu','voice_id':'ngoc_huyen','vieneu_temperature':.65,'vieneu_top_p':.8,'vieneu_batch_size':4,'audio_sample_rate':44100}
 assert client.post('/api/settings/audio',headers=H,json=cfg).status_code==200
 path=checkpoints.create_checkpoint(runtime.store,tmp_path/'state.zip');checkpoints.restore_checkpoint(runtime.store,path)
 saved=client.get('/api/settings/audio').json()['settings'];assert all(saved[k]==val for k,val in cfg.items())

def test_environment_defaults(monkeypatch):
 monkeypatch.setenv('NOVEL_TTS_ENGINE','vieneu');monkeypatch.setenv('NOVEL_TTS_VOICE','ngoc_huyen');cfg=Config();assert cfg.tts_engine=='vieneu' and cfg.voice_id=='ngoc_huyen'

def test_settings_validation(client):
 for data in [{'audio_sample_rate':12345},{'audio_format':'mp3','audio_bitrate':'192k','audio_sample_rate':24000}]:assert client.post('/api/settings/audio',headers=H,json=data).status_code==422

def test_opus_reports_actual_rate():assert Config(audio_format='opus',audio_sample_rate=22050).audio_sample_rate==48000
