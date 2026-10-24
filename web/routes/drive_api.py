from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from gdrive import api_drive, export_service

router = APIRouter()

class BeginInput(BaseModel):
    client_json: str = Field(max_length=32768)

class FinishInput(BaseModel):
    return_url: str = Field(max_length=8192)


def require_api():
    if export_service.drive_backend() != 'api':
        raise HTTPException(400,'Kết nối Drive API chỉ dùng trong chế độ Kaggle/API.')


@router.get('/api/drive-api/status')
def status():
    require_api()
    return api_drive.status()


@router.post('/api/drive-api/begin')
def begin(payload:BeginInput):
    require_api()
    try:
        return api_drive.begin(payload.client_json)
    except ValueError as exc:
        raise HTTPException(400,str(exc))
    except Exception:
        raise HTTPException(400,'Không tạo được link Google. Kiểm tra thư viện OAuth và JSON Desktop app.') from None


@router.post('/api/drive-api/finish')
def finish(payload:FinishInput):
    require_api()
    try:
        return api_drive.finish(payload.return_url)
    except ValueError as exc:
        raise HTTPException(400,str(exc))


@router.post('/api/drive-api/disconnect')
def disconnect():
    require_api()
    return api_drive.disconnect()
