import asyncio
import importlib.util
import json
import sys
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'telegram')]
from state import State
import runner
import bot

@pytest.fixture
def state(tmp_path):return State(tmp_path)

def test_queue_privacy_limits_and_restart(state):
    a=state.create(1,1,'translate','.txt',b'hello')
    b=state.create(1,1,'full','.txt',b'hello')
    assert state.get(a,2) is None
    assert state.get('../etc/passwd') is None
    with pytest.raises(ValueError):state.create(1,1,'audio','.txt',b'hello')
    assert state.next()['id']==a
    state.recover()
    assert state.get(a)['status']=='queued'
    state.set(a,'done');state.set(b,'failed')
    assert state.mode(1)=='full'
    state.mode(1,'audio');assert state.mode(1)=='audio'

def test_runner_translation_and_resume(tmp_path, monkeypatch):
    (tmp_path/'input.txt').write_text('第一章 出发\n你好世界。\n第二章 朋友\n我们走吧。',encoding='utf-8')
    (tmp_path/'request.json').write_text(json.dumps({'mode':'translate','input':'input.txt'}))
    class Fake:
        def load(self):pass
        def translate(self,texts,glossary,**kw):return ['Bản dịch '+t for t in texts]
    monkeypatch.setattr('workflows.jobs.create_engine',lambda _:Fake())
    runner.run(tmp_path)
    assert (tmp_path/'output/ban_dich.txt').stat().st_size
    assert (tmp_path/'output/ban_dich.epub').stat().st_size
    def fail(_):raise AssertionError('Should not reload engine on completed book')
    monkeypatch.setattr('workflows.jobs.create_engine',fail)
    runner.run(tmp_path)
    assert all(c['status']=='done' for c in runner.Store(tmp_path/'book.sqlite3').list())

def test_audio_pipeline_real_ffmpeg(tmp_path,monkeypatch):
    import subprocess
    source=tmp_path/'sample.mp3'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','sine=frequency=440:duration=1','-b:a','96k',str(source)],check=True)
    payload=source.read_bytes()
    (tmp_path/'input.txt').write_text('Chương 1\nXin chào bạn.',encoding='utf-8')
    (tmp_path/'request.json').write_text(json.dumps({'mode':'audio','input':'input.txt'}))
    class Response:
        def raise_for_status(self):pass
        def iter_content(self,n):yield payload
        def close(self):pass
    calls=[]
    def post(*args,**kw):calls.append(kw['json']['text']);return Response()
    monkeypatch.setattr(runner.requests,'post',post)
    runner.run(tmp_path)
    assert list((tmp_path/'output').glob('*.mp3'))
    count=len(calls);runner.run(tmp_path);assert len(calls)==count

def test_telegram_delivery_checkpoint_and_owner(tmp_path,monkeypatch):
    s=State(tmp_path);jid=s.create(1,1,'audio','.txt',b'hello');s.set(jid,'delivering')
    monkeypatch.setattr(bot,'state',s);monkeypatch.setattr(bot,'DATA',tmp_path)
    out=tmp_path/jid/'output';out.mkdir();(out/'a.mp3').write_bytes(b'mock')
    tg=SimpleNamespace(send_audio=AsyncMock(),send_document=AsyncMock(),send_message=AsyncMock())
    app=SimpleNamespace(bot=tg)
    row=s.get(jid)
    asyncio.run(bot.deliver(app,row));assert tg.send_audio.await_count==1
    s.set(jid,'delivering');asyncio.run(bot.deliver(app,row));assert tg.send_audio.await_count==1
    assert s.get(jid)['status']=='done'

def test_deny_unauthorized_and_groups(monkeypatch):
    monkeypatch.setattr(bot,'ALLOWED',{123})
    message=SimpleNamespace(reply_text=AsyncMock())
    u=SimpleNamespace(effective_user=SimpleNamespace(id=456),effective_chat=SimpleNamespace(type='private'),effective_message=message)
    assert asyncio.run(bot.permitted(u)) is False
    assert message.reply_text.await_count==1
    u.effective_user.id=123;assert asyncio.run(bot.permitted(u)) is True
    u.effective_chat.type='group';assert asyncio.run(bot.permitted(u)) is False

def test_retry_cannot_race_active_cancel(tmp_path,monkeypatch):
    s=State(tmp_path);jid=s.create(1,1,'audio','.txt',b'x');s.set(jid,'cancelled')
    monkeypatch.setattr(bot,'state',s);monkeypatch.setattr(bot,'ALLOWED',{1})
    message=SimpleNamespace(text='/retry '+jid,reply_text=AsyncMock())
    u=SimpleNamespace(effective_user=SimpleNamespace(id=1),effective_chat=SimpleNamespace(type='private'),effective_message=message,message=message)
    c=SimpleNamespace(args=[jid],application=SimpleNamespace(bot_data={'active':jid}))
    asyncio.run(bot.action(u,c));assert s.get(jid)['status']=='cancelled'

def test_tts_http_with_stub_voice_real_ffmpeg(monkeypatch):
    # Real HTTP validation, real WAV/MP3 conversion; voice is intentionally stubbed.
    from fastapi.testclient import TestClient
    sys.path.insert(0,str(ROOT))
    spec=importlib.util.spec_from_file_location('tts_server',ROOT/'tts/server.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    monkeypatch.setattr(module,'voice',lambda:object())
    def wav_stub(voice,text,path,work,chars,**kw):
        with wave.open(path,'wb') as w:
            w.setnchannels(1);w.setsampwidth(2);w.setframerate(22050);w.writeframes(b'\0\0'*22050)
    monkeypatch.setattr(module,'synth_chapter',wav_stub)
    client=TestClient(module.app)
    assert client.post('/synthesize',json={'text':''}).status_code==422
    assert client.post('/synthesize',json={'text':'x'*250001}).status_code==422
    result=client.post('/synthesize',json={'text':'Xin chào.'})
    assert result.status_code==200 and result.headers['content-type']=='audio/mpeg'
    assert len(result.content)>1000

def test_worker_subprocess_failure_marks_failed(tmp_path,monkeypatch):
    s=State(tmp_path);jid=s.create(1,1,'audio','.txt',b'hello')
    monkeypatch.setattr(bot,'state',s);monkeypatch.setattr(bot,'DATA',tmp_path)
    tg=SimpleNamespace(send_message=AsyncMock())
    app=SimpleNamespace(bot=tg,bot_data={})
    class FailedProcess:
        returncode=1
    async def spawn(*args,**kwargs):return FailedProcess()
    monkeypatch.setattr(asyncio,'create_subprocess_exec',spawn)
    async def scenario():
        task=asyncio.create_task(bot.worker(app))
        for _ in range(50):
            await asyncio.sleep(.01)
            if s.get(jid)['status']=='failed':break
        task.cancel()
        try:await task
        except asyncio.CancelledError:pass
    asyncio.run(scenario())
    assert s.get(jid)['status']=='failed'
    assert app.bot_data['active'] is None

def test_retry_respects_queue_limit_and_owner(state):
    first=state.create(1,1,'audio','.txt',b'x');state.set(first,'cancelled')
    state.create(1,1,'audio','.txt',b'x');state.create(1,1,'audio','.txt',b'x')
    with pytest.raises(ValueError):state.requeue(first,1)
    with pytest.raises(ValueError):state.requeue(first,2)
    assert state.get(first)['status']=='cancelled'
