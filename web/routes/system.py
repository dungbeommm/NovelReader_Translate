from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response
from web import runtime
from web.schemas import SystemPurgeInput

router = APIRouter()

@router.post('/api/system/purge')
def system_purge_endpoint(payload: SystemPurgeInput):
    runtime.ensure_idle()
    try:
        res = runtime.store.purge_all(purge_data=payload.purge_data, purge_cache=payload.purge_cache)
        if payload.purge_data:
            runtime.job.target_chapter_ids = None
            runtime.job.scope_label = ''
            runtime.job.status = 'ready'
            runtime.job.message = ''
            runtime.job.emit('book_deleted')
        return res
    except Exception as exc:
        raise HTTPException(500, f"Lỗi xóa cache/data: {exc}")


@router.get('/')
def index():
    return FileResponse(runtime.ROOT / 'web/static/index.html')


@router.get('/classic')
def classic_index():
    return FileResponse(runtime.ROOT / 'web/static/index.html')


@router.get('/favicon.ico')
def favicon_ico():
    return Response(status_code=204)



@router.get('/api/monitor')
def monitor_snapshot(response: Response):
    response.headers['Cache-Control']='no-store'
    book=runtime.store.book()
    runtime.job.telemetry.book((book.get('output_folder') or book['filename']) if book else None)
    return {'resources':runtime.resources.snapshot(),'tasks':runtime.job.telemetry.snapshot(),
            'job':runtime.job.summary()}


@router.get('/api/system/environment')
def system_environment():
    return runtime.environment()


@router.get('/api/tunnel/status')
def tunnel_status():
    return runtime.tunnel.status()


@router.post('/api/tunnel/start')
def tunnel_start():
    try:
        return runtime.tunnel.start()
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))


@router.post('/api/tunnel/stop')
def tunnel_stop():
    return runtime.tunnel.stop()
