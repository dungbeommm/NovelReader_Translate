from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from gdrive import gdrive_service
from web import runtime
from web.schemas import GDriveConfigInput

router = APIRouter()

@router.get('/api/settings/gdrive')
def get_gdrive_settings():
    return gdrive_service.public_gdrive_config()


@router.post('/api/settings/gdrive')
def save_gdrive_settings(payload: GDriveConfigInput):
    # Saving non-secret preferences must not erase existing OAuth tokens.
    updates = payload.model_dump(exclude_unset=True)
    for key in ('access_token', 'refresh_token', 'client_secret'):
        if not updates.get(key):
            updates.pop(key, None)
    gdrive_service.save_gdrive_config(updates)
    return gdrive_service.public_gdrive_config()


@router.post('/api/gdrive/auto-detect')
def auto_detect_gdrive():
    p = gdrive_service.auto_detect_desktop_gdrive()
    if p:
        return {'found': True, 'path': p}
    return {'found': False, 'message': 'Không tìm thấy thư mục Google Drive Desktop tự động. Hãy nhập thủ công hoặc dùng API.'}


@router.get('/api/gdrive/auth-url')
def get_gdrive_auth_url(request: Request):
    redirect_uri = f"{request.url.scheme}://{request.url.netloc}/api/gdrive/callback"
    try:
        url = gdrive_service.get_oauth_auth_url(redirect_uri)
        return {'ok': True, 'auth_url': url, 'redirect_uri': redirect_uri}
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get('/api/gdrive/callback')
def gdrive_oauth_callback(request: Request, code: str = None, error: str = None):
    if error:
        return Response(content=f"<html><body style='background:#121714; color:#f87171; text-align:center; padding:50px;'><h2>Lỗi xác thực Google: {error}</h2></body></html>", media_type="text/html")
    if not code:
        return Response(content="<html><body style='background:#121714; color:#f87171; text-align:center; padding:50px;'><h2>Thiếu authorization code từ Google.</h2></body></html>", media_type="text/html")

    redirect_uri = f"{request.url.scheme}://{request.url.netloc}/api/gdrive/callback"
    try:
        updated = gdrive_service.exchange_code_for_tokens(code, redirect_uri)
        email = updated.get('account_email', 'Đã kết nối')
        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Liên kết Google Drive thành công</title>
    <style>
        body {{ font-family: system-ui, sans-serif; background: #121714; color: #eef2ef; text-align: center; padding: 50px 20px; }}
        .card {{ max-width: 480px; margin: 0 auto; background: #1a221d; border: 1px solid #28332c; border-radius: 12px; padding: 30px; box-shadow: 0 4px 20px rgba(0,0,0,0.5); }}
        h1 {{ color: #4ade80; font-size: 20px; margin-bottom: 12px; }}
        p {{ color: #9ca3af; font-size: 14px; line-height: 1.6; margin: 6px 0; }}
        strong {{ color: #eef2ef; }}
        .btn {{ display: inline-block; margin-top: 20px; padding: 8px 20px; background: #4ade80; color: #0e1210; font-weight: bold; border-radius: 6px; text-decoration: none; cursor: pointer; border: none; }}
    </style>
</head>
<body>
    <div class="card">
        <h1>✓ Đã bắt liên kết Google Drive thành công!</h1>
        <p>Tài khoản: <strong>{email}</strong></p>
        <p>Thư mục lưu audio: <strong>Novel_Audio</strong></p>
        <p style="font-size:12px; color:#6b7280; margin-top:14px;">Cửa sổ này sẽ tự đóng sau 3 giây...</p>
        <button class="btn" onclick="window.close()">Đóng cửa sổ này</button>
    </div>
    <script>
        if (window.opener) {{
            window.opener.postMessage({{ type: 'gdrive_auth_success', email: '{email}' }}, '*');
        }}
        setTimeout(() => window.close(), 3000);
    </script>
</body>
</html>"""
        return Response(content=html, media_type="text/html")
    except Exception as exc:
        return Response(content=f"<html><body style='background:#121714; color:#f87171; text-align:center; padding:50px;'><h2>Lỗi xác thực: {exc}</h2></body></html>", media_type="text/html")


@router.post('/api/gdrive/test')
def test_gdrive():
    ok, msg = gdrive_service.test_gdrive_connection()
    return {'ok': ok, 'message': msg}


@router.post('/api/gdrive/upload-all')
def upload_all_gdrive():
    files = [p for p in runtime.store.audio_dir.rglob('*') if p.is_file() and p.suffix.lower() in ('.mp3', '.m4b', '.m4a', '.opus', '.wav')]
    if not files:
        raise HTTPException(404, 'Không có file audio nào để tải lên.')
    uploaded = 0
    for f in files:
        if f.is_file() and f.suffix.lower() in ('.mp3', '.m4b', '.m4a', '.opus', '.wav'):
            ok, _ = gdrive_service.upload_audio_file(f)
            if ok: uploaded += 1
    return {'ok': True, 'uploaded': uploaded, 'total': len(files)}

