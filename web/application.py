"""FastAPI composition; business logic lives in the sibling service modules."""
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from storage.files import MAX_FILE
from web import runtime
from web.routes import books, translation, audio, gdrive, system, progress

@asynccontextmanager
async def lifespan(app):
    runtime.job.loop=asyncio.get_running_loop()
    yield
    if runtime.job.active:
        runtime.job.stop_flag.set();runtime.job.gate.set()
        await asyncio.to_thread(runtime.job.thread.join,3)


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


def create_app():
    runtime.initialize()
    app = FastAPI(title='AI Novel Translator', lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['localhost', '127.0.0.1', '[::1]', 'testserver'])
    app.middleware('http')(local_guard)
    # Static /api/export/audio must precede /api/export/{format}.
    for module in (audio, gdrive, translation, system, progress, books):
        app.include_router(module.router)
    app.mount('/static', StaticFiles(directory=runtime.ROOT / 'web/static'), name='static')
    return app
