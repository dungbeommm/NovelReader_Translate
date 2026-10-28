"""The only remote export backend."""
import tempfile
from pathlib import Path, PurePosixPath
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from pydantic import BaseModel, Field
from storage import huggingface_service as service
from storage.cloud_settings import load_key
from storage.files import MAX_FILE
from web import runtime

router = APIRouter()


class StorageFolderInput(BaseModel):
    path: str = Field(default='', max_length=1024)
    name: str = Field(min_length=1, max_length=200)


def storage_action(callback):
    try:
        return callback()
    except HTTPException:
        raise
    except FileExistsError:
        raise HTTPException(409, 'Tên đã tồn tại. Hãy chọn tên khác.')
    except ValueError:
        raise HTTPException(400, 'Đường dẫn không hợp lệ hoặc chưa cấu hình HF_TOKEN.')
    except Exception:
        raise HTTPException(502, 'Không truy cập được kho Hugging Face. Kiểm tra kết nối và quyền của token.')


@router.get('/api/storage/files')
def storage_files(path: str = ''):
    return storage_action(lambda: service.list_directory(path))


@router.post('/api/storage/folders')
def storage_folder(payload: StorageFolderInput):
    return storage_action(lambda: service.upload_to_directory(b'', payload.name, payload.path, folder=True))


@router.post('/api/storage/upload')
def storage_upload(file: UploadFile = File(...), path: str = Form('')):
    try:
        data = file.file.read(MAX_FILE + 1)
        if len(data) > MAX_FILE:
            raise HTTPException(413, 'Tệp tối đa 50 MB.')
        return storage_action(lambda: service.upload_to_directory(data, file.filename, path))
    finally:
        file.file.close()


@router.get('/api/storage/download')
def storage_download(path: str):
    with tempfile.NamedTemporaryFile(prefix='novel-hf-download-', delete=False) as handle:
        target = Path(handle.name)
    try:
        storage_action(lambda: service.download_repository_file(path, target))
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return FileResponse(target, filename=PurePosixPath(path).name,
                        background=BackgroundTask(target.unlink, missing_ok=True))


@router.get('/api/storage/status')
def status():
    return {'repo_id': service.repo_id(), 'repo_type': service.REPO_TYPE,
            'url': service.base_url(), 'has_key': bool(load_key()),
            'default_destination': 'huggingface'}


@router.post('/api/storage/test')
def test_connection():
    try:
        return service.check_connection()
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception:
        raise HTTPException(502, 'Không kết nối được kho Hugging Face. Kiểm tra token và quyền truy cập.')


def run_export(callback):
    try:
        with runtime.job.lock:
            runtime.ensure_idle()
            return callback()
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception:
        raise HTTPException(502, 'Không tải được lên Hugging Face. Bản gốc vẫn còn; kiểm tra kho trước khi thử lại.')


@router.post('/api/export/huggingface/file/{filename}')
def export_file(filename: str):
    return run_export(lambda: service.export_audio_file(runtime.store, filename))


@router.post('/api/export/huggingface/{kind}')
def export_book(kind: str):
    return run_export(lambda: service.export_book(runtime.store, kind))
