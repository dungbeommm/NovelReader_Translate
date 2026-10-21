import os
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from storage.files import MAX_FILE
from web import runtime
from web.access import protect_request, handle_login
from web.routes import books, translation, audio, gdrive, system, progress, drive_exports, drive_api, pixeldrain_routes, checkpoints

@asynccontextmanager
async def lifespan(app):
    runtime.job.loop=asyncio.get_running_loop()
    yield
    if runtime.job.active:
        runtime.job.stop_flag.set();runtime.job.gate.set()
        await asyncio.to_thread(runtime.job.thread.join,120)


async def local_guard(request:Request,call_next):
    if request.url.path == '/auth/login':
        return await handle_login(request)
    access = protect_request(request)
    if access is not None:
        return access
    origin=request.headers.get('origin')
    if origin:
        allow_tunnel = (
            os.environ.get("ALLOWED_HOSTS") == "*"
            or os.environ.get("ALLOW_TUNNEL") == "1"
            or bool(os.environ.get("COLAB_GPU"))
        )
        if not allow_tunnel:
            origin_host = origin.split("://")[-1].rstrip('/')
            base_host = str(request.base_url).split("://")[-1].rstrip('/')
            req_host = request.headers.get('host', '').rstrip('/')
            if origin_host not in (base_host, req_host) and origin != str(request.base_url).rstrip('/'):
                return Response('Chỉ cho phép cùng origin.', status_code=403)
    if request.url.path.startswith('/api/') and request.method in ('POST','PUT','DELETE','PATCH') and request.headers.get('x-app-request')!='novel-translator':
        return Response('Thiếu header bảo vệ.',status_code=403)
    max_request_size = 2 * 1024**3 if request.url.path == '/api/checkpoints/restore' else MAX_FILE
    size=request.headers.get('content-length')
    if size and (not size.isdigit() or int(size)>max_request_size+1024*1024):
        return Response('File quá lớn.',status_code=413)
    response = await call_next(request)
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response


def create_app():
    runtime.initialize()
    app = FastAPI(title='AI Novel Translator', lifespan=lifespan)
    
    env_hosts = os.environ.get("ALLOWED_HOSTS", "").strip()
    allow_tunnel = (
        env_hosts == "*"
        or os.environ.get("ALLOW_TUNNEL") == "1"
        or bool(os.environ.get("COLAB_GPU"))
    )
    if not allow_tunnel:
        allowed = [h.strip() for h in env_hosts.split(",")] if env_hosts else ['localhost', '127.0.0.1', '[::1]', 'testserver']
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed)

    app.middleware('http')(local_guard)
    # Static /api/export/audio must precede /api/export/{format}.
    for module in (audio, gdrive, translation, system, progress, drive_exports, drive_api, pixeldrain_routes, checkpoints, books):
        app.include_router(module.router)
    app.mount('/static', StaticFiles(directory=runtime.ROOT / 'web/static'), name='static')
    return app
