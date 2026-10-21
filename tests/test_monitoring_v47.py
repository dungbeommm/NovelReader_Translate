import io,json,time,threading,wave
from types import SimpleNamespace
from pathlib import Path
import pytest
from monitoring.tasks import TaskTelemetry,audio_report,characters
from monitoring import resources


def test_character_counts_not_words_or_whitespace():
 assert characters('你好 a b\n c')==5


def test_translation_real_batch_resume_and_frozen_finish(monkeypatch):
 clock=[100.];monkeypatch.setattr('monitoring.tasks.time.monotonic',lambda:clock[0])
 m=TaskTelemetry();m.translation_start(1,1,'t',[(0,'hello'),(1,'你好')],['old',None]);clock[0]+=2
 m.translation_batch(2,.5);m.translation_end();a=m.snapshot()['translation'];clock[0]+=99;b=m.snapshot()['translation']
 assert a['percent']==100 and a['chars_per_second']==4 and a['elapsed_seconds']==2
 assert b['elapsed_seconds']==2 and m.snapshot()['translation_finished']==1


def test_audio_not_100_before_published_and_final_freezes(monkeypatch):
 clock=[10.];monkeypatch.setattr('monitoring.tasks.time.monotonic',lambda:clock[0]);m=TaskTelemetry()
 with m.audio_task(1,1,'t'):
  clock[0]+=2;audio_report(total=100,completed=100,audio_seconds=4,stage='encoding')
  a=m.snapshot()['audio'][0];assert a['percent']==99 and a['audio_per_second']==2 and a['rtf']==.5
 b=m.snapshot()['audio'][0];clock[0]+=20
 assert b['percent']==100 and b['elapsed_seconds']==2 and m.snapshot()['audio'][0]['elapsed_seconds']==2


def test_audio_error_does_not_report_complete():
 m=TaskTelemetry()
 with pytest.raises(ValueError):
  with m.audio_task(1,1,'t'):
   audio_report(total=10,completed=5);raise ValueError('test')
 a=m.snapshot()['audio'][0];assert a['state']=='error' and a['percent']==50
 audio_report(completed=10);assert m.snapshot()['audio'][0]['completed']==5


def test_thread_local_callbacks_are_isolated():
 m=TaskTelemetry();barrier=threading.Barrier(2)
 def worker(i):
  with m.audio_task(i,i,str(i)):
   barrier.wait();audio_report(total=100,completed=i,stage='synthesizing');barrier.wait()
 ts=[threading.Thread(target=worker,args=(i,)) for i in (1,2)]
 for t in ts:t.start()
 for t in ts:t.join(2)
 assert {a['chapter_id'] for a in m.snapshot()['audio']}=={1,2}
 assert all(a['state']=='done' and a['total']==100 for a in m.snapshot()['audio'])


def test_queued_cancel_and_book_reset():
 m=TaskTelemetry();m.book('first');m.queued(1,1,'t');m.cancel_queued(1)
 assert m.snapshot()['audio'][0]['state']=='cancelled'
 m.book('first');assert len(m.snapshot()['audio'])==1
 m.book('second');assert not m.snapshot()['audio']


def test_bounded_audio_history_keeps_running():
 m=TaskTelemetry()
 with m.audio_task(1,1,'active'):
  for i in range(2,240):
   with m.audio_task(i,i,'done'):pass
  assert 1 in m.audio and len(m.audio)==200


def test_nvidia_parse_multi_device_and_na(monkeypatch):
 monkeypatch.setattr(resources.subprocess,'run',lambda *a,**k:SimpleNamespace(stdout='0, NVIDIA T4, 75, 4096, 15360\n1, NVIDIA A10, [N/A], 0, 24576\n'))
 devices,note=resources.nvidia_devices();assert note is None and len(devices)==2
 assert devices[0]['percent']==75 and devices[1]['percent'] is None and devices[1]['used_bytes']==0


def test_nvidia_unavailable_is_not_zero(monkeypatch):
 def fail(*a,**k):raise FileNotFoundError()
 monkeypatch.setattr(resources.subprocess,'run',fail)
 devices,note=resources.nvidia_devices();assert devices==[] and 'không' in note


def test_resource_sample_missing_gpu_and_cached_no_subprocess_on_reads(tmp_path,monkeypatch):
 calls=[];monkeypatch.setattr(resources,'nvidia_devices',lambda:(calls.append(1) or [],'not available'))
 m=resources.ResourceSampler([('data',tmp_path)]);m.sample();monkeypatch.setattr(m,'start',lambda:None)
 a=m.snapshot();b=m.snapshot();assert len(calls)==1 and a['gpu']['percent'] is None and a['vram']['used_bytes'] is None
 assert a['disk']['total_bytes']>0 and b['sampled_at']==a['sampled_at']


def test_resource_aggregate_vram(tmp_path,monkeypatch):
 monkeypatch.setattr(resources,'nvidia_devices',lambda:([
 dict(index=0,name='a',percent=20,used_bytes=2,total_bytes=10),dict(index=1,name='b',percent=60,used_bytes=4,total_bytes=10)],None))
 m=resources.ResourceSampler([('data',tmp_path)]);m.sample();assert m.cached['gpu']['percent']==40 and m.cached['vram']['percent']==30


def test_monitor_api_with_no_book(tmp_path,monkeypatch):
 monkeypatch.setenv('NOVEL_DATA',str(tmp_path/'data'))
 from web.application import create_app
 from fastapi.testclient import TestClient
 with TestClient(create_app()) as c:
  res=c.get('/api/monitor');assert res.status_code==200 and res.headers['cache-control']=='no-store'
  data=res.json();assert data['tasks']['audio']==[] and data['job']['total']==0
  assert 'resources' in data


def test_piper_reports_completed_groups_after_success(tmp_path,monkeypatch):
 from audio import audio_service as a
 import tts.synthesis
 monkeypatch.setattr(a,'is_cuda_available_for_piper',lambda:False)
 monkeypatch.setattr(a,'split_text_for_tts',lambda *x,**y:['abc','de'])
 def synth(voice,text,w,set_wav_format,**kw):
  if set_wav_format:w.setnchannels(1);w.setsampwidth(2);w.setframerate(24000)
  w.writeframes(b'\0\0'*2400)
 monkeypatch.setattr(tts.synthesis,'synthesize_wav',synth)
 events=[];monkeypatch.setattr(a,'audio_report',lambda **v:events.append(v))
 a.synth_text_to_wav(None,'text',tmp_path/'a.wav',tmp_path)
 assert [e['completed'] for e in events if 'completed' in e]==[0,3,5]
 assert events[-1]['audio_seconds']==.2


def test_vieneu_outer_groups_emit_real_progress(tmp_path,monkeypatch):
 import numpy as np
 from audio import vieneu_service as v,audio_service as a
 import monitoring.tasks as tasks
 monkeypatch.setattr(v,'ensure_references',lambda:{'voices':{'x':{'speaker_emb':[0.],'codes':[0]}}})
 calls=[];monkeypatch.setattr(v,'get_runtime',lambda:SimpleNamespace(infer=lambda **kw:(calls.append(kw) or np.zeros(480))))
 monkeypatch.setattr(a,'split_text_for_tts',lambda *x,**k:['abc','defg'])
 events=[];monkeypatch.setattr(tasks,'audio_report',lambda **x:events.append(x))
 v.synthesize_to_wav('text','x',tmp_path/'a.wav',batch_size=8)
 assert len(calls)==2 and all(x['batch_size']==8 for x in calls)
 assert [x['completed'] for x in events if x.get('stage')=='synthesizing' and 'completed' in x]==[3,7]
 assert events[-1]['audio_seconds']==.02


def test_ram_prefers_container_allowance(monkeypatch):
 monkeypatch.setattr(resources,'psutil',SimpleNamespace(virtual_memory=lambda:SimpleNamespace(total=1000,available=800)))
 original=Path.read_text
 def read(p,*a,**k):
  if Path(p).as_posix().endswith('sys/fs/cgroup/memory.max'):return '400'
  if Path(p).as_posix().endswith('sys/fs/cgroup/memory.current'):return '100'
  return original(p,*a,**k)
 monkeypatch.setattr(Path,'read_text',read)
 m=resources.memory_usage();assert m['total_bytes']==400 and m['used_bytes']==100 and m['percent']==25 and m['scope']=='container'


def test_no_psutil_does_not_invent_ram(monkeypatch):
 monkeypatch.setattr(resources,'psutil',None)
 assert resources.memory_usage()['percent'] is None


def test_manual_audio_monitor_not_blocked_by_generation_lock(tmp_path,monkeypatch):
 from web.application import create_app
 from web import runtime
 from fastapi.testclient import TestClient
 from audio import audio_service
 monkeypatch.setenv('NOVEL_DATA',str(tmp_path/'data'))
 monkeypatch.setenv('NOVEL_OUTPUT_AUDIO',str(tmp_path/'audio'))
 monkeypatch.setenv('NOVEL_OUTPUT_TEXT',str(tmp_path/'text'))
 started=threading.Event();release=threading.Event();response=[]
 def generate(cid,pos,title,paras,directory,**kw):
  audio_report(total=100,completed=40,audio_seconds=2,stage='synthesizing');started.set();release.wait(4)
  p=directory/'chuong_0001.mp3';p.write_bytes(b'audio');return p
 monkeypatch.setattr(audio_service,'generate_chapter_audio',generate)
 with TestClient(create_app()) as client:
  runtime.import_book('test.txt','第一章\n你好。'.encode());row=runtime.store.list()[0]
  runtime.store.update(row['id'],status='done',translated=['Xin chào'])
  worker=threading.Thread(target=lambda:response.append(client.post(f"/api/chapters/{row['id']}/audio",headers={'X-App-Request':'novel-translator'})))
  worker.start()
  try:
   assert started.wait(2)
   snap=client.get('/api/monitor').json()['tasks']['audio'][0]
   assert snap['percent']==40 and snap['state']=='running'
  finally:release.set();worker.join(5)
  assert response[0].status_code==200 and client.get('/api/monitor').json()['tasks']['audio'][0]['percent']==100


def test_job_updates_translation_telemetry(tmp_path,monkeypatch):
 from workflows import jobs
 from storage.store import Store
 from web.schemas import Config
 store=Store(tmp_path/'b.sqlite3',text_dir=tmp_path/'text',audio_dir=tmp_path/'audio')
 store.replace('book.txt','utf-8',[('第一章','你好。\n世界。')])
 engine=SimpleNamespace(load=lambda:None,translate=lambda texts,glossary,**kw:['Xin chào.' for _ in texts])
 monkeypatch.setattr(jobs,'create_engine',lambda *a,**k:engine)
 job=jobs.Job(store);job.start(Config(generate_audio=False,batch_size=1).model_dump());job.thread.join(5)
 snap=job.telemetry.snapshot()['translation'];assert snap['percent']==100 and snap['measured_chars']>0 and snap['chars_per_second']>0 and snap['state']=='done'
