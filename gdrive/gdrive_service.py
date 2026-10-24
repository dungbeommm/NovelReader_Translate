"""Google Drive integration service: supports local sync folder (Drive Desktop) and automatic OAuth2 API."""
import json
import tempfile
import threading
import logging
import os
import shutil
import urllib.request
import urllib.parse
from pathlib import Path

log = logging.getLogger(__name__)

from paths import data_dir

def config_path():
    return data_dir() / "gdrive_config.json"


def get_gdrive_config() -> dict:
    if config_path().is_file():
        try:
            return json.loads(config_path().read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "enabled": False,
        "mode": "local_folder",    # "local_folder" hoac "api"
        "local_path": "",          # Vi du: G:\My Drive\Novel_Audio
        "client_id": "",           # Google Cloud OAuth Client ID
        "client_secret": "",       # Google Cloud OAuth Client Secret
        "access_token": "",        # Google Drive API Access Token
        "refresh_token": "",       # Token lam moi tu dong vinh vien
        "account_email": "",       # Email tai khoan da lien ket
        "folder_id": "",           # Google Drive Folder ID
        "folder_name": "Novel_Audio",
        "auto_upload": False       # Tu dong upload sau khi tao audio
    }


_config_lock = threading.RLock()


def public_gdrive_config():
    cfg = get_gdrive_config()
    return {**{k: v for k, v in cfg.items() if k not in {'access_token', 'refresh_token', 'client_secret'}},
            'connected': bool(cfg.get('access_token') or cfg.get('refresh_token')),
            'has_client_secret': bool(cfg.get('client_secret'))}


def save_gdrive_config(cfg: dict) -> dict:
    with _config_lock:
        config_path().parent.mkdir(parents=True, exist_ok=True)
        current = get_gdrive_config()
        current.update(cfg)
        fd, name = tempfile.mkstemp(dir=config_path().parent, prefix='.gdrive-')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(current, f, ensure_ascii=False, indent=2)
            os.chmod(name, 0o600)
            os.replace(name, config_path())
        finally:
            Path(name).unlink(missing_ok=True)
        return current


def auto_detect_desktop_gdrive() -> str | None:
    """Tu dong tim kiem thu muc Google Drive Desktop tren Windows."""
    candidates = []
    # 1. Cac o dia ao cua Google Drive Desktop (G:, H:, I:, ...)
    for letter in "GHIJKLMNOPQRSTUVWXYZCDE":
        drive = Path(f"{letter}:/")
        if drive.exists():
            candidates.extend([
                drive / "My Drive",
                drive / "Mon Drive",
                drive / "Il mio Drive",
                drive / "Meu Drive",
                drive / "Mi unidad",
            ])
    # 2. Thu muc trong UserProfile
    user_home = Path.home()
    candidates.extend([
        user_home / "Google Drive",
        user_home / "Google Drive" / "My Drive",
    ])

    for c in candidates:
        if c.is_dir():
            target = c / "Novel_Audio"
            try:
                target.mkdir(parents=True, exist_ok=True)
                return str(target.resolve())
            except Exception:
                return str(c.resolve())
    return None


def get_oauth_auth_url(redirect_uri: str, client_id: str = None) -> str:
    """Tao URL xac thuc OAuth2 cua Google de mo tren trinh duyet."""
    cfg = get_gdrive_config()
    cid = (client_id or cfg.get("client_id", "")).strip()
    if not cid:
        raise ValueError("Chưa có Google Client ID. Vui lòng nhập Client ID hoặc nạp file client_secret.json.")

    params = {
        "client_id": cid,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/userinfo.email",
        "access_type": "offline",
        "prompt": "consent"
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"


def exchange_code_for_tokens(code: str, redirect_uri: str) -> dict:
    """Doi authorization code lay access_token va refresh_token."""
    cfg = get_gdrive_config()
    cid = cfg.get("client_id", "").strip()
    csecret = cfg.get("client_secret", "").strip()
    if not cid or not csecret:
        raise ValueError("Thiếu Client ID hoặc Client Secret của Google.")

    token_url = "https://oauth2.googleapis.com/token"
    payload = urllib.parse.urlencode({
        "code": code,
        "client_id": cid,
        "client_secret": csecret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code"
    }).encode("utf-8")

    req = urllib.request.Request(token_url, data=payload, headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        token_data = json.loads(resp.read().decode("utf-8"))

    access_token = token_data.get("access_token", "")
    refresh_token = token_data.get("refresh_token") or cfg.get("refresh_token", "")

    # Lay email tai khoan da lien ket
    account_email = ""
    try:
        user_req = urllib.request.Request("https://www.googleapis.com/oauth2/v2/userinfo", headers={"Authorization": f"Bearer {access_token}"})
        with urllib.request.urlopen(user_req, timeout=10) as uresp:
            udata = json.loads(uresp.read().decode("utf-8"))
            account_email = udata.get("email", "")
    except Exception:
        pass

    # Tu dong tao thu muc Novel_Audio tren Google Drive neu chua co
    folder_id = cfg.get("folder_id", "")
    try:
        folder_id = ensure_drive_folder(access_token, folder_name="Novel_Audio")
    except Exception as exc:
        log.warning("Khong the tu tao thu muc tren Drive: %s", exc)

    updated = {
        "enabled": True,
        "mode": "api",
        "access_token": access_token,
        "refresh_token": refresh_token,
        "account_email": account_email,
        "folder_id": folder_id
    }
    save_gdrive_config(updated)
    return updated


def refresh_access_token_if_needed() -> str:
    """Tu dong lam moi access_token khi bi het han bang refresh_token."""
    cfg = get_gdrive_config()
    rtoken = cfg.get("refresh_token", "").strip()
    cid = cfg.get("client_id", "").strip()
    csecret = cfg.get("client_secret", "").strip()
    if not rtoken or not cid or not csecret:
        return cfg.get("access_token", "")

    token_url = "https://oauth2.googleapis.com/token"
    payload = urllib.parse.urlencode({
        "client_id": cid,
        "client_secret": csecret,
        "refresh_token": rtoken,
        "grant_type": "refresh_token"
    }).encode("utf-8")

    try:
        req = urllib.request.Request(token_url, data=payload, headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            new_token = data.get("access_token")
            if new_token:
                cfg["access_token"] = new_token
                save_gdrive_config(cfg)
                log.info("Da tu dong lam moi Google Drive Access Token thanh cong!")
                return new_token
    except Exception as e:
        log.error("Loi tu dong refresh Google token: %s", e)

    return cfg.get("access_token", "")


def ensure_drive_folder(token: str, folder_name: str = "Novel_Audio") -> str:
    """Kiem tra hoac tu dong tao thu muc Novel_Audio tren Google Drive."""
    headers = {"Authorization": f"Bearer {token}"}
    
    # 1. Tim kiem thu muc da ton tai
    query = f"mimeType = 'application/vnd.google-apps.folder' and name = '{folder_name}' and trashed = false"
    search_url = f"https://www.googleapis.com/drive/v3/files?q={urllib.parse.quote(query)}&fields=files(id,name)"
    req = urllib.request.Request(search_url, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        files = res.get("files", [])
        if files:
            return files[0]["id"]

    # 2. Neu chua co, tu dong tao thu muc moi
    create_url = "https://www.googleapis.com/drive/v3/files"
    meta = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder"
    }
    req2 = urllib.request.Request(
        create_url,
        data=json.dumps(meta).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req2, timeout=10) as resp2:
        res2 = json.loads(resp2.read().decode("utf-8"))
        return res2.get("id", "")


def test_gdrive_connection() -> tuple[bool, str]:
    cfg = get_gdrive_config()
    mode = cfg.get("mode", "local_folder")

    if mode == "local_folder":
        p = cfg.get("local_path", "").strip()
        if not p:
            return False, "Chưa cấu hình đường dẫn thư mục Google Drive Desktop."
        folder = Path(p)
        if not folder.exists():
            try:
                folder.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                return False, f"Không thể tạo hoặc truy cập thư mục '{p}': {e}"
        test_file = folder / ".antigravity_test.tmp"
        try:
            test_file.write_text("ok", encoding="utf-8")
            test_file.unlink(missing_ok=True)
            return True, f"Kết nối thư mục Google Drive thành công: {folder.resolve()}"
        except Exception as e:
            return False, f"Thư mục không có quyền ghi: {e}"

    elif mode == "api":
        token = cfg.get("access_token", "").strip()
        if not token:
            token = refresh_access_token_if_needed()
        if not token:
            return False, "Chưa liên kết Google Drive API. Hãy bấm nút 'Đăng nhập Google' bên dưới."

        folder_id = cfg.get("folder_id", "root").strip() or "root"
        try:
            url = f"https://www.googleapis.com/drive/v3/files/{folder_id}?fields=id,name"
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                email_info = f" ({cfg.get('account_email')})" if cfg.get('account_email') else ""
                return True, f"Kết nối Google Drive API thành công: Thư mục '{data.get('name', folder_id)}'{email_info}"
        except urllib.error.HTTPError as e:
            if e.code == 401 and cfg.get("refresh_token"):
                # Thu refresh token mot lan nua
                token = refresh_access_token_if_needed()
                if token:
                    return test_gdrive_connection()
            return False, f"Lỗi xác thực Google Drive API ({e.code}): {e.reason}"
        except Exception as e:
            return False, f"Lỗi kết nối Google Drive API: {e}"

    return False, "Chế độ không hợp lệ."


def upload_audio_file(file_path: Path, subfolder_name: str = None) -> tuple[bool, str]:
    """Tải 1 file audio lên Google Drive (theo local folder hoặc API)."""
    cfg = get_gdrive_config()
    if not cfg.get("enabled"):
        return False, "Google Drive chưa được bật trong Cài đặt."
    if not file_path.is_file():
        return False, f"File không tồn tại: {file_path}"

    mode = cfg.get("mode", "local_folder")
    if mode == "local_folder":
        base_dir = Path(cfg.get("local_path", "").strip())
        if not base_dir.exists():
            base_dir.mkdir(parents=True, exist_ok=True)
        target_dir = base_dir / subfolder_name if subfolder_name else base_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        dest = target_dir / file_path.name
        shutil.copy2(str(file_path), str(dest))
        log.info("Đã sao chép vào Google Drive Desktop: %s", dest)
        return True, str(dest)

    elif mode == "api":
        token = cfg.get("access_token", "").strip()
        if not token:
            token = refresh_access_token_if_needed()
        if not token:
            return False, "Thiếu Google Drive Access Token. Vui lòng bấm 'Đăng nhập Google' trong Cài đặt."

        folder_id = cfg.get("folder_id", "").strip()
        metadata = {"name": file_path.name}
        if folder_id and folder_id != "root":
            metadata["parents"] = [folder_id]

        def _do_upload(tok: str):
            boundary = "-------314159265358979323846"
            content_type = f"multipart/related; boundary={boundary}"
            body = bytearray()
            body.extend(f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode("utf-8"))
            body.extend(json.dumps(metadata).encode("utf-8"))
            body.extend(f"\r\n--{boundary}\r\nContent-Type: audio/mpeg\r\n\r\n".encode("utf-8"))
            body.extend(file_path.read_bytes())
            body.extend(f"\r\n--{boundary}--\r\n".encode("utf-8"))

            url = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart"
            req = urllib.request.Request(url, data=body, headers={
                "Authorization": f"Bearer {tok}",
                "Content-Type": content_type
            })
            with urllib.request.urlopen(req, timeout=120) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                return res.get("id")

        try:
            file_id = _do_upload(token)
            log.info("Upload thành công lên Google Drive: File ID = %s", file_id)
            return True, f"Google Drive File ID: {file_id}"
        except urllib.error.HTTPError as e:
            if e.code == 401 and cfg.get("refresh_token"):
                # Token het han -> Tu dong refresh va thu lai
                log.info("Google token het han, dang tu dong refresh token...")
                new_token = refresh_access_token_if_needed()
                if new_token:
                    try:
                        file_id = _do_upload(new_token)
                        return True, f"Google Drive File ID: {file_id}"
                    except Exception as exc2:
                        return False, f"Lỗi upload sau khi refresh token: {exc2}"
            return False, f"Lỗi upload ({e.code}): {e.reason}"
        except Exception as e:
            log.exception("Lỗi upload Google Drive API")
            return False, f"Lỗi upload: {e}"

    return False, "Chưa cấu hình chế độ Google Drive."
