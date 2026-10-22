import importlib.util
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

def test_tts_http_with_stub_voice_real_ffmpeg(monkeypatch):
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

