"""Cached measurements of the backend host/runtime, not the viewer's device."""
import csv
import io
import shutil
import subprocess
import threading
import time
from pathlib import Path
try:
    import psutil
except ImportError:
    psutil=None

def number(value):
    try:
        value=float(value)
        return value if __import__('math').isfinite(value) and value>=0 else None
    except (ValueError,TypeError):return None

def nvidia_devices():
    try:
        result=subprocess.run(['nvidia-smi','--query-gpu=index,name,utilization.gpu,memory.used,memory.total',
            '--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=2,check=True)
        devices=[]
        for row in csv.reader(io.StringIO(result.stdout)):
            if len(row)!=5:continue
            idx,name,use,used,total=[v.strip() for v in row]
            u,t=number(used),number(total)
            devices.append(dict(index=idx,name=name,percent=number(use),used_bytes=u*1024**2 if u is not None else None,
                                total_bytes=t*1024**2 if t is not None else None))
        return devices,None if devices else 'Không nhận được số liệu NVIDIA.'
    except (OSError,subprocess.SubprocessError):
        return [],'Không có NVIDIA hoặc nvidia-smi không khả dụng; không giả định GPU bằng 0%.'

def memory_usage():
    if psutil is None:return dict(percent=None,used_bytes=None,total_bytes=None,scope='unavailable')
    m=psutil.virtual_memory();used,total=m.total-m.available,m.total;scope='host_available'
    # cgroup v2 / v1: prefer notebook/container allowance to the host RAM.
    for maximum,current in [('/sys/fs/cgroup/memory.max','/sys/fs/cgroup/memory.current'),
                            ('/sys/fs/cgroup/memory/memory.limit_in_bytes','/sys/fs/cgroup/memory/memory.usage_in_bytes')]:
        try:
            limit=int(Path(maximum).read_text().strip());usage=int(Path(current).read_text().strip())
            if 0<limit<total:total=limit;used=usage;scope='container';break
        except (OSError,ValueError):pass
    return dict(percent=min(100,100*used/total) if total else None,used_bytes=used,total_bytes=total,scope=scope)

class ResourceSampler:
    def __init__(self,paths):
        self.paths=paths;self.lock=threading.Lock();self.stop_event=threading.Event();self.thread=None
        self.cached={'sampled_at':None,'cpu':{'percent':None},'ram':{'percent':None},'disk':{'percent':None},
            'gpu':{'percent':None},'vram':{'percent':None},'gpus':[],'disks':[], 'warming_up':True}
        self.peaks={}

    def start(self):
        with self.lock:
            if self.thread is None:
                self.thread=threading.Thread(target=self._run,daemon=True,name='resource-sampler');self.thread.start()

    def close(self):
        self.stop_event.set()
        if self.thread:self.thread.join(3)

    def _run(self):
        if psutil:psutil.cpu_percent(interval=None)
        self.stop_event.wait(.2)
        while not self.stop_event.is_set():
            try:self.sample()
            except Exception:pass  # Keep prior timestamp: UI will mark stale, not invent data.
            self.stop_event.wait(2)

    def sample(self):
        cpu=dict(percent=psutil.cpu_percent(interval=None) if psutil else None,
            logical_cores=psutil.cpu_count() if psutil else None,scope='host_visible')
        ram=memory_usage();devices,reason=nvidia_devices();disks=[];seen=set()
        for label,path in self.paths:
            path=Path(path)
            while not path.exists() and path!=path.parent:path=path.parent
            try:
                device=path.stat().st_dev
                if device in seen:continue
                seen.add(device);d=shutil.disk_usage(path)
                disks.append(dict(label=label,percent=100*d.used/d.total if d.total else None,
                                  used_bytes=d.used,total_bytes=d.total,free_bytes=d.free))
            except OSError:pass
        gpu_values=[g['percent'] for g in devices if g['percent'] is not None]
        gpu=dict(percent=sum(gpu_values)/len(gpu_values) if gpu_values else None)
        # Never pretend that a partially unmeasured device has zero VRAM.
        valid=bool(devices) and all(g['used_bytes'] is not None and g['total_bytes'] for g in devices)
        used=sum(g['used_bytes'] for g in devices) if valid else None
        total=sum(g['total_bytes'] for g in devices) if valid else None
        vram=dict(percent=100*used/total if total else None,used_bytes=used,total_bytes=total)
        data=dict(cpu=cpu,ram=ram,gpu=gpu,vram=vram,disk=disks[0] if disks else {'percent':None},
                  gpus=devices,disks=disks,gpu_note=reason,sampled_at=time.time(),warming_up=False,
                  process_rss_bytes=psutil.Process().memory_info().rss if psutil else None,
                  note='CPU/GPU: toàn máy khả kiến; RAM: hạn mức container nếu đọc được; ổ đĩa: filesystem chứa dữ liệu, không phải quota nhà cung cấp.')
        for key in ('cpu','ram','gpu','vram','disk'):
            p=data[key].get('percent')
            if p is not None:self.peaks[key]=max(self.peaks.get(key,0),p)
            data[key]['peak_percent']=self.peaks.get(key)
        with self.lock:self.cached=data

    def snapshot(self):
        self.start()
        with self.lock:data=__import__('copy').deepcopy(self.cached)
        data['age_seconds']=time.time()-data['sampled_at'] if data['sampled_at'] else None
        return data
