"""Checkpoint, scratch workspace and backend Pixeldrain settings routes."""
import json
import shutil
import tempfile
from pathlib import Path
from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from pydantic import BaseModel, Field
from paths import data_dir
from storage import checkpoints as service, cloud_settings, pixeldrain_service
from web import runtime
from web.schemas import Config

router = APIRouter()


class CloudKey(BaseModel):
    api_key: str = Field(default='', max_length=4096)


class CheckpointOptions(BaseModel):
    include_audio: bool = False


class RestoreCloud(BaseModel):
    file_id: str = Field(min_length=4, max_length=256)


@router.post('/api/settings/pixeldrain')
def save_key(payload: CloudKey):
    cloud_settings.save_key(payload.api_key)
    return {'ok': True, 'has_key': bool(pixeldrain_service.get_pixeldrain_api_key())}


@router.post('/api/settings/pixeldrain/test')
def test_connection():
    try:
        return pixeldrain_service.check_connection()
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(502, str(exc))


@router.get('/api/checkpoints/status')
def checkpoint_status():
    path = data_dir() / 'cloud_checkpoint_last.json'
    try:
        last = json.loads(path.read_text('utf-8'))
    except (OSError, ValueError):
        last = None
    return {'last_cloud': last, 'has_draft': service.draft_path().is_file(), 'max_archive_bytes': service.MAX_ARCHIVE}


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


@router.post('/api/checkpoints/pixeldrain')
def upload_cloud(payload: CheckpointOptions):
    try:
        with runtime.job.lock:
            runtime.ensure_idle()
            return service.upload_checkpoint(runtime.store, payload.include_audio)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(502, f'Không lưu được Pixeldrain: {exc}')


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


@router.post('/api/checkpoints/restore-pixeldrain')
def restore_cloud(payload: RestoreCloud):
    try:
        with runtime.job.lock:
            runtime.ensure_idle()
            with tempfile.TemporaryDirectory(prefix='novel-cloud-restore-') as work:
                path = service.download_checkpoint(payload.file_id, Path(work) / 'checkpoint.zip')
                return apply_restore(path)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, f'Không khôi phục được từ Pixeldrain: {exc}')
