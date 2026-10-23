from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from web import runtime
from storage import bucket_service

router = APIRouter()


class RestoreInput(BaseModel):
    book_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")


class TokenInput(BaseModel):
    token: str = Field(min_length=0, max_length=512)


@router.get('/api/bucket/status')
def bucket_status():
    return {**bucket_service.status(), "books": bucket_service.list_books()}


@router.post('/api/bucket/token')
def bucket_set_token(payload: TokenInput):
    try:
        bucket_service.set_runtime_token(payload.token)
        return bucket_service.status()
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post('/api/bucket/checkpoint')
def bucket_checkpoint():
    runtime.ensure_idle()
    try:
        return bucket_service.publish_checkpoint(runtime.store, include_audio=True)
    except Exception as exc:
        raise HTTPException(503, f"Chưa lưu được lên Hugging Face Bucket: {exc}") from exc


@router.post('/api/bucket/restore')
def bucket_restore(payload: RestoreInput):
    runtime.ensure_idle()
    try:
        result = bucket_service.restore_latest(runtime.store, payload.book_id)
        runtime.job.status = 'ready'
        runtime.job.message = ''
        runtime.job.target_chapter_ids = None
        runtime.job.scope_label = ''
        runtime.job.emit('book_loaded')
        return {**result, 'book': runtime.store.book(), 'chapters': runtime.store.list()}
    except Exception as exc:
        raise HTTPException(400, f"Không khôi phục được truyện từ Bucket: {exc}") from exc


@router.post('/api/bucket/audio')
def bucket_restore_audio(payload: RestoreInput):
    runtime.ensure_idle()
    try:
        return bucket_service.restore_audio(runtime.store, payload.book_id)
    except Exception as exc:
        raise HTTPException(400, f"Không tải được audio từ Bucket: {exc}") from exc
