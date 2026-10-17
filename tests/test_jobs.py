import threading
import time
import pytest
from storage.store import Store
from workflows.jobs import Job

class Fake:
    def load(self):pass
    def translate(self,texts,glossary):return ['Dịch '+t for t in texts]

def setup(tmp_path,monkeypatch):
    s=Store(tmp_path/'test.sqlite');s.replace('test.txt','utf8',[('第一章','甲\n乙'),('第二章','丙')])
    j=Job(s);monkeypatch.setattr('workflows.jobs.create_engine',lambda _:Fake());return s,j

def test_job_resume(tmp_path,monkeypatch):
    s,j=setup(tmp_path,monkeypatch);cfg={'engine':'local','glossary':'','batch_size':2}
    j.start(cfg);j.thread.join(5);assert all(c['status']=='done' for c in s.list())
    j.start(cfg);j.thread.join(5);assert all(c['status']=='done' for c in s.list())
    with pytest.raises(ValueError):j.start({**cfg,'glossary':'甲 -> A'})
    j.start({**cfg,'glossary':'甲 -> A'},reset=True);j.thread.join(5)
    assert all(c['status']=='done' for c in s.list())

def test_stop_resume_checkpoints(tmp_path,monkeypatch):
    s,j=setup(tmp_path,monkeypatch);entered=threading.Event();release=threading.Event()
    class Blocking(Fake):
        calls=0
        def translate(self,texts,g):
            self.calls+=1
            if self.calls==2:entered.set();release.wait(5)
            return super().translate(texts,g)
    monkeypatch.setattr('workflows.jobs.create_engine',lambda _:Blocking())
    cfg={'engine':'local','glossary':'','batch_size':1};j.start(cfg);assert entered.wait(3)
    j.pause();assert j.status=='paused';j.resume();j.stop();release.set();j.thread.join(5)
    chapter=s.get(s.list()[0]['id']);assert chapter['outputs'][0] is not None and chapter['outputs'][1] is None
    monkeypatch.setattr('workflows.jobs.create_engine',lambda _:Fake());j.start(cfg);j.thread.join(5)
    assert all(c['status']=='done' for c in s.list())

def test_failure_continues(tmp_path,monkeypatch):
    s,j=setup(tmp_path,monkeypatch)
    class Failed(Fake):
        def translate(self,texts,g):
            if any('甲' in t for t in texts):raise RuntimeError('expected')
            return super().translate(texts,g)
    monkeypatch.setattr('workflows.jobs.create_engine',lambda _:Failed())
    j.start({'engine':'local','glossary':'','batch_size':8});j.thread.join(10)
    assert [c['status'] for c in s.list()]==['error','done']

def test_restart_recovers(tmp_path):
    p=tmp_path/'db';s=Store(p);s.replace('x.txt','utf8',[('a','b')]);id=s.list()[0]['id']
    s.update(id,status='translating',outputs=['saved',None]);s=Store(p)
    assert s.get(id)['status']=='pending' and s.get(id)['outputs']==['saved',None]
