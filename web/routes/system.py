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

