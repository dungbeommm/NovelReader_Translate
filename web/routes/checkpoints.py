"""Local checkpoint and workspace draft routes."""
import shutil
import tempfile
from pathlib import Path
from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from pydantic import BaseModel
from storage import checkpoints as service
from web import runtime
from web.schemas import Config

router = APIRouter()


class CheckpointOptions(BaseModel):
    include_audio: bool = False


@router.post('/api/checkpoints/draft')
def save_draft(payload: Config):
    with runtime.job.lock:
        runtime.ensure_idle()
        return {'ok': True, 'config': service.save_draft(payload.model_dump())}


@router.get('/api/checkpoints/draft')
def load_draft():
    draft = service.load_draft()
    if draft is None:
        raise HTTPException(404, 'Chưa có bảng tạm đã lưu.')
    return {'config': draft}


@router.post('/api/checkpoints/download')
def download(payload: CheckpointOptions):
    work = Path(tempfile.mkdtemp(prefix='novel-download-'))
    try:
        with runtime.job.lock:
            runtime.ensure_idle()
            path = service.create_checkpoint(runtime.store, work / 'NovelReader_checkpoint.zip', payload.include_audio)
        return FileResponse(path, media_type='application/zip', filename=path.name,
                            background=BackgroundTask(shutil.rmtree, work, ignore_errors=True))
    except HTTPException:
        shutil.rmtree(work, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(work, ignore_errors=True)
        raise HTTPException(400, f'Không tạo được checkpoint: {exc}')


def apply_restore(path):
    result = service.restore_checkpoint(runtime.store, path)
    runtime.job.target_chapter_ids = None
    runtime.job.scope_label = ''
    runtime.job.status = 'ready'
    runtime.job.message = ''
    runtime.job.emit('book_loaded')
    return result


@router.post('/api/checkpoints/restore')
def restore_file(file: UploadFile):
    try:
        with runtime.job.lock:
            runtime.ensure_idle()
            with tempfile.TemporaryDirectory(prefix='novel-upload-') as work:
                path = Path(work) / 'checkpoint.zip'
                total = 0
                with path.open('wb') as out:
                    while chunk := file.file.read(1024 * 1024):
                        total += len(chunk)
                        if total > service.MAX_ARCHIVE:
                            raise ValueError('Checkpoint tối đa 2 GB.')
                        out.write(chunk)
                return apply_restore(path)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, f'Không khôi phục được: {exc}')
    finally:
        file.file.close()
