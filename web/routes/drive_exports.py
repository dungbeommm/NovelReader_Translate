from fastapi import APIRouter, HTTPException
from gdrive import export_service
from web import runtime

router = APIRouter()


@router.get('/api/export/drive/capabilities')
def capabilities():
    backend = export_service.drive_backend()
    return {'backend':backend, 'drive_enabled':export_service.bridge_enabled(),
            'colab_drive': export_service.bridge_enabled(),
            'permission_location': 'web_oauth' if backend=='api' else 'colab_notebook', 'default_destination': 'gdrive' if export_service.bridge_enabled() else 'download'}


@router.post('/api/export/drive/{format}', status_code=202)
def export_to_drive(format: str):
    try:
        return export_service.start_export(format, runtime.store, runtime.job.lock)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get('/api/export/drive/status/{task_id}')
def export_status(task_id: str):
    try:
        return export_service.read_task(task_id)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(404, str(exc))
