"""The only remote export backend."""
from fastapi import APIRouter, HTTPException
from storage import huggingface_service as service
from storage.cloud_settings import load_key
from web import runtime

router = APIRouter()


@router.get('/api/storage/status')
def status():
    return {'repo_id': service.REPO_ID, 'repo_type': service.REPO_TYPE,
            'url': service.BASE_URL, 'has_key': bool(load_key()),
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
