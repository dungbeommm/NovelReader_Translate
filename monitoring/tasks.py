"""Thread-safe bounded session telemetry. Counters advance only on real work."""
import contextlib
import copy
import threading
import time
from datetime import datetime, timezone

_local=threading.local()

def characters(text):
    return sum(not c.isspace() for c in text)

def stamp():
    return datetime.now(timezone.utc).isoformat()

def audio_report(**values):
    callback=getattr(_local,'audio_callback',None)
    if callback:callback(**values)

class TaskTelemetry:
    def __init__(self):
        self.lock=threading.RLock()
        self.book_key=None
        self.translation=None
        self.audio={}
        self.translation_finished=0
        self.started=time.monotonic()

    def book(self,key):
        with self.lock:
            if self.book_key!=key:
                self.book_key=key;self.translation=None;self.audio={};self.translation_finished=0

    def translation_start(self,cid,position,title,plan,values):
        with self.lock:
            self.translation=dict(chapter_id=cid,position=position,title=title,state='running',
                total=sum(characters(p[1]) for p in plan),completed=sum(characters(p[1]) for p,v in zip(plan,values) if v is not None),
                measured_chars=0,inference_seconds=0.,started=time.monotonic(),finished_at=None)

    def translation_batch(self,count,seconds):
        with self.lock:
            if self.translation:
                self.translation['completed']+=count;self.translation['measured_chars']+=count
                self.translation['inference_seconds']+=max(0,seconds)

    def translation_end(self,state='done'):
        with self.lock:
            if self.translation and self.translation['state']=='running':
                self.translation.update(state=state,elapsed_seconds=time.monotonic()-self.translation['started'],finished_at=stamp())
                if state=='done':self.translation_finished+=1

    def queued(self,cid,position,title):
        with self.lock:
            self.audio.pop(cid,None)
            self.audio[cid]=dict(chapter_id=cid,position=position,title=title,state='queued',stage='queued',
                completed=0,total=0,audio_seconds=0.,started=None,finished_at=None)
            self._prune()

    def _prune(self):
        while len(self.audio)>200:
            removable=next((k for k,v in self.audio.items() if v['state'] in ('done','error','cancelled')),None)
            if removable is None:break
            del self.audio[removable]

    def cancel_queued(self,cid):
        with self.lock:
            row=self.audio.get(cid)
            if row and row['state']=='queued':row.update(state='cancelled',stage='cancelled',finished_at=stamp())

    @contextlib.contextmanager
    def audio_task(self,cid,position,title):
        with self.lock:
            self.queued(cid,position,title)
            row=self.audio[cid];row.update(state='running',stage='loading',started=time.monotonic(),started_at=stamp())
        previous=getattr(_local,'audio_callback',None)
        def callback(**v):
            with self.lock:
                row.update({k:x for k,x in v.items() if k in ('completed','total','audio_seconds','stage')})
        _local.audio_callback=callback
        try:
            yield
        except BaseException:
            with self.lock:row.update(state='error',stage='error',elapsed_seconds=time.monotonic()-row['started'],finished_at=stamp())
            raise
        else:
            with self.lock:row.update(state='done',stage='done',completed=row['total'],elapsed_seconds=time.monotonic()-row['started'],finished_at=stamp())
        finally:
            _local.audio_callback=previous

    def snapshot(self):
        now=time.monotonic()
        with self.lock:
            translation=copy.deepcopy(self.translation);audio=copy.deepcopy(list(self.audio.values()))
            finished=self.translation_finished
        if translation:
            t=translation;t['elapsed_seconds']=t.get('elapsed_seconds',max(0,now-t['started']))
            t['chars_per_second']=t['measured_chars']/t['inference_seconds'] if t['inference_seconds']>0 else None
            t['percent']=min(100,100*t['completed']/t['total']) if t['total'] else None
            rate=t['chars_per_second'];t['eta_seconds']=(t['total']-t['completed'])/rate if rate and t['state']=='running' else None
            t.pop('started',None)
        for a in audio:
            a['elapsed_seconds']=a.get('elapsed_seconds',max(0,now-a['started']) if a['started'] is not None else 0)
            elapsed=a['elapsed_seconds'];a['percent']=(100 if a['state']=='done' else min(99,100*a['completed']/a['total'])) if a['total'] else (100 if a['state']=='done' else None)
            a['chars_per_second']=a['completed']/elapsed if elapsed>0 and a['completed'] else None
            a['audio_per_second']=a['audio_seconds']/elapsed if elapsed>0 and a['audio_seconds'] else None
            a['rtf']=elapsed/a['audio_seconds'] if a['audio_seconds'] else None
            a.pop('started',None)
        audio.sort(key=lambda a:(a['state'] not in ('running','queued'),-a['position']))
        return dict(translation=translation,translation_finished=finished,audio=audio,retained_limit=200,
                    history_scope='session',session_seconds=max(0,now-self.started))
