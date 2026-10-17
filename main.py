from pathlib import Path
from contextlib import asynccontextmanager
from urllib.parse import urlsplit
import asyncio
import json
import logging
import os
from fastapi import FastAPI, HTTPException, UploadFile, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field
from app.store import Store
from app.jobs import Job
from app.files import parse_file, export_txt, export_epub, MAX_FILE
from app.engines import list_available_models
from app.hardware import detect_hardware_profile

ROOT=Path(__file__).resolve().parent
DATA=Path(os.getenv('NOVEL_DATA',str(ROOT/'data')));DATA.mkdir(parents=True,exist_ok=True)
logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(name)s %(message)s',
                    handlers=[logging.StreamHandler(),logging.FileHandler(DATA/'app.log',encoding='utf-8')])
store=Store(DATA/'novel.sqlite3');job=Job(store)

@asynccontextmanager
async def lifespan(app):
    job.loop=asyncio.get_running_loop()
    yield
    if job.active:
        job.stop_flag.set();job.gate.set()
        await asyncio.to_thread(job.thread.join,3)

app=FastAPI(title='AI Novel Translator',lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware,allowed_hosts=['localhost','127.0.0.1','[::1]','testserver'])

@app.middleware('http')
async def local_guard(request:Request,call_next):
    origin=request.headers.get('origin')
    if origin and origin != str(request.base_url).rstrip('/'):
        return Response('Chỉ cho phép cùng origin.',status_code=403)
    if request.url.path.startswith('/api/') and request.method in ('POST','PUT','DELETE','PATCH') and request.headers.get('x-app-request')!='novel-translator':
        return Response('Thiếu header bảo vệ.',status_code=403)
    size=request.headers.get('content-length')
    if size and (not size.isdigit() or int(size)>MAX_FILE+1024*1024):
        return Response('File quá lớn.',status_code=413)
    return await call_next(request)

class PathInput(BaseModel):path:str=Field(min_length=1,max_length=4096)
class ChapterIdsInput(BaseModel):ids:list[int]=Field(default_factory=list)
class Config(BaseModel):
    engine:str=Field(default='HachimiMT-60-QT',pattern=r'^(local|space|HachimiMT-60-QT|HachimiMT-60|HachimiMT-40-QT|HachimiMT-30)$')
    glossary:str=Field(default='',max_length=100000)
    batch_size:int=Field(default=8,ge=1,le=64)
    reset:bool=False
    honorific_mode:str=Field(default='safe',pattern=r'^(safe|xianxia_strict|off)$')
    pronoun_harmonizer:bool=True
    normalize_t2s:bool=True
    beam_size:int=Field(default=2,ge=1,le=4)
    chunk_mode:str=Field(default='sentence',pattern=r'^(sentence|paragraph)$')
    normalize_mode:str=Field(default='auto',pattern=r'^(auto|t2s|none)$')


def ensure_idle():
    if job.active:raise HTTPException(409,'Hãy dừng job dịch trước khi thực hiện thao tác này.')

def import_book(name,data):
    with job.lock:
        ensure_idle()
        try:
            chapters,encoding=parse_file(name,data)
            store.replace(name,encoding,chapters);job.status='ready';job.message=''
        except Exception as exc:
            logging.exception('Import failed');raise HTTPException(400,f'Không nạp được tệp: {exc}')
    job.emit('book_loaded');return {'book':store.book(),'chapters':store.list()}

@app.post('/api/upload')
def upload(file:UploadFile):
    ensure_idle();data=file.file.read(MAX_FILE+1)
    if len(data)>MAX_FILE:raise HTTPException(413,'File tối đa 50 MB.')
    return import_book(Path((file.filename or 'novel.txt').replace('\\','/')).name,data)

@app.post('/api/load-path')
def load_path(payload:PathInput):
    ensure_idle();p=Path(payload.path).expanduser()
    if p.suffix.lower() not in ('.txt','.epub'):raise HTTPException(400,'Chỉ hỗ trợ .txt/.epub.')
    try:
        with p.open('rb') as f:data=f.read(MAX_FILE+1)
    except OSError as exc:raise HTTPException(400,f'Không đọc được đường dẫn trên máy chạy backend: {exc}')
    return import_book(p.name,data)

@app.get('/api/models')
def models():
    return list_available_models()

@app.get('/api/hardware')
def hardware():
    profile = detect_hardware_profile()
    if profile:
        return {
            'cpu_count': profile.cpu_logical,
            'intra_threads': profile.ct2_threads,
            'is_gpu': profile.has_cuda,
            'device': profile.gpu_name or 'cpu',
            'vram_gb': profile.vram_gb or 0,
            'batch_size': profile.batch_size,
            'summary': profile.summary,
        }
    return {
        'cpu_count': os.cpu_count() or 2,
        'intra_threads': max(1, min(8, (os.cpu_count() or 2) - 1)),
        'is_gpu': False,
        'device': 'cpu',
        'vram_gb': 0,
        'batch_size': 8,
        'summary': f'CPU {os.cpu_count() or 2} luồng',
    }


@app.get('/api/state')
def state():return {'book':store.book(),'progress':job.summary()}


@app.get('/api/chapters')
def chapters():return store.list()

@app.get('/api/chapters/{id}')
def chapter(id:int):
    value=store.get(id)
    if not value:raise HTTPException(404,'Không tìm thấy chương.')
    return value

@app.post('/api/book/delete')
def delete_book():
    ensure_idle()
    with job.lock:
        store.clear()
        job.status='ready';job.message=''
    job.emit('book_deleted')
    return {'ok':True,'book':None,'chapters':[]}

@app.post('/api/chapters/reset')
def reset_chapters_endpoint(payload:ChapterIdsInput):
    ensure_idle()
    if not payload.ids:raise HTTPException(400,'Danh sách chương rỗng.')
    with job.lock:
        store.reset_chapters(payload.ids)
    job.emit('chapters_updated')
    return {'ok':True,'reset_count':len(payload.ids)}

@app.post('/api/chapters/delete')
def delete_chapters_endpoint(payload:ChapterIdsInput):
    ensure_idle()
    if not payload.ids:raise HTTPException(400,'Danh sách chương rỗng.')
    with job.lock:
        store.delete_chapters(payload.ids)
    job.emit('chapters_updated')
    return {'ok':True,'deleted_count':len(payload.ids),'chapters':store.list()}

@app.post('/api/chapters/{id}/reset')
def reset_single_chapter(id:int):
    ensure_idle()
    with job.lock:
        store.reset_chapters([id])
    job.emit('chapters_updated')
    return {'ok':True,'reset_id':id}

@app.post('/api/chapters/{id}/delete')
def delete_single_chapter(id:int):
    ensure_idle()
    with job.lock:
        store.delete_chapters([id])
    job.emit('chapters_updated')
    return {'ok':True,'deleted_id':id}

@app.post('/api/translate/start')
async def start(config:Config):
    try:
        job.start(config.model_dump(exclude={'reset'}),config.reset)
    except ValueError as exc:raise HTTPException(409,str(exc))
    return job.summary()

@app.post('/api/translate/{action}')
async def control(action:str):
    if action not in ('pause','resume','stop'):raise HTTPException(404,'Lệnh không hợp lệ.')
    try:getattr(job,action)()
    except ValueError as exc:raise HTTPException(409,str(exc))
    return job.summary()

@app.get('/api/export/{format}')
def export(format:str):
    if format not in ('txt','epub'):raise HTTPException(404,'Định dạng không hợp lệ.')
    with store.connect() as c:
        # Atomic snapshot: do not combine chapter states from different batches.
        c.execute('BEGIN')
        b=c.execute('SELECT * FROM book LIMIT 1').fetchone()
        rows=c.execute('SELECT * FROM chapter ORDER BY position').fetchall()
    if not b:raise HTTPException(400,'Chưa có truyện.')
    cs=[]
    for r in rows:
        d=dict(r);d['translated']=json.loads(d['translated']);cs.append(d)
    data=export_txt(dict(b),cs) if format=='txt' else export_epub(dict(b),cs)
    return Response(data,media_type='text/plain; charset=utf-8' if format=='txt' else 'application/epub+zip',
                    headers={'Content-Disposition':f'attachment; filename="translated.{format}"'})

@app.websocket('/ws/progress')
async def progress(ws:WebSocket):
    origin=ws.headers.get('origin');host=ws.headers.get('host')
    if origin and urlsplit(origin).netloc != host:
        await ws.close(code=1008);return
    await ws.accept();job.clients.add(ws)
    try:
        await ws.send_json({'type':'snapshot','progress':job.summary()})
        while True:await ws.receive_text()
    except (WebSocketDisconnect,RuntimeError):pass
    finally:job.clients.discard(ws)

@app.get('/')
def index():
    return FileResponse(ROOT / 'static/index.html')

@app.get('/classic')
def classic_index():
    return FileResponse(ROOT / 'static/index.html')

app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')

# Mount HachimiMT Gradio UI
import sys
import tempfile
import importlib.util

if str(ROOT / 'src') not in sys.path:
    sys.path.insert(0, str(ROOT / 'src'))

spec = importlib.util.spec_from_file_location("hachimi_app", ROOT / "src" / "app.py")
hachimi_app = importlib.util.module_from_spec(spec)
sys.modules["hachimi_app"] = hachimi_app
spec.loader.exec_module(hachimi_app)

import gradio as gr

demo = hachimi_app.build_ui()
demo.queue(default_concurrency_limit=8)
@app.get('/favicon.ico')
def favicon_ico():
    fav = ROOT / 'src' / 'assets' / 'favicon.svg'
    if fav.exists():
        return FileResponse(fav, media_type='image/svg+xml')
    return Response(status_code=204)

app = gr.mount_gradio_app(
    app,
    demo,
    path='/gradio',
    theme=gr.themes.Soft(primary_hue='orange', neutral_hue='stone'),
    css=hachimi_app.CUSTOM_CSS,
    head=hachimi_app.HEAD_HTML,
    allowed_paths=[str(hachimi_app.EXPORTS_DIR), tempfile.gettempdir()],
)

if __name__=='__main__':
    import uvicorn
    print('\nAI Novel Translator -> http://localhost:8000\n')
    uvicorn.run(app,host='127.0.0.1',port=8000)
