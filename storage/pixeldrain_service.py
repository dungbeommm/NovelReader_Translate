"""Pixeldrain cloud storage service for NovelReader.

Provides direct upload for translated TXT, EPUB, and Audio files to Pixeldrain.
Supports both anonymous uploads (where permitted) and API-key authenticated uploads.
"""
import base64
import re
import socket
import io
import json
import logging
import os
import shutil
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from storage.files import export_txt, export_epub
from storage.store import _safe_filename

log = logging.getLogger(__name__)

PIXELDRAIN_API_URL = "https://pixeldrain.com/api/file"
PIXELDRAIN_FILE_URL = "https://pixeldrain.com/u"


def get_pixeldrain_api_key(passed_key: str | None = None) -> str | None:
    """Retrieve Pixeldrain API key from argument, saved config, or environment."""
    if passed_key and passed_key.strip():
        return passed_key.strip()
    from storage.cloud_settings import load_key
    saved = load_key()
    if saved:
        return saved
    env_key = os.getenv("PIXELDRAIN_API_KEY", "").strip()
    if env_key:
        return env_key
    return None


def check_connection(api_key=None):
    key = get_pixeldrain_api_key(api_key)
    if not key:
        raise ValueError("Chưa có API key Pixeldrain. Vui lòng nhập key và nhấn Lưu.")
    auth = base64.b64encode(f"api:{key}".encode()).decode()
    req = urllib.request.Request("https://pixeldrain.com/api/user", headers={
        "Authorization": f"Basic {auth}", "User-Agent": "NovelReader/4.4"})
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read(1024 * 1024))
        if not isinstance(data, dict) or data.get('success') is False:
            raise RuntimeError("API key không hợp lệ hoặc tài khoản bị khóa.")
        username = data.get('username') or 'Người dùng'
        return {"ok": True, "message": f"Kết nối Pixeldrain thành công! (Tài khoản: {username})"}
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise RuntimeError("API key Pixeldrain không đúng (HTTP 401 Unauthorized).")
        raise RuntimeError(f"Lỗi Pixeldrain HTTP {exc.code}: Vui lòng kiểm tra lại tài khoản.") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError("Không thể kết nối máy chủ Pixeldrain (kiểm tra Internet/DNS hoặc thử lại sau).") from exc


def upload_to_pixeldrain(
    data_or_path: bytes | io.BytesIO | Path,
    filename: str,
    api_key: str | None = None,
    timeout: int = 300
) -> dict:
    """Upload data or a local file to Pixeldrain via REST API.

    Returns dict with keys: ok, id, url, download_url, filename, size_bytes, size_mb
    """
    key = get_pixeldrain_api_key(api_key)
    safe_name = urllib.parse.quote(Path(filename).name.strip(), safe="")
    url = f"{PIXELDRAIN_API_URL}/{safe_name}"

    if isinstance(data_or_path, (str, Path)):
        file_path = Path(data_or_path)
        if not file_path.is_file():
            raise FileNotFoundError(f"Không tìm thấy file để upload: {file_path}")
        payload = file_path
        size_bytes = file_path.stat().st_size
    elif isinstance(data_or_path, io.BytesIO):
        payload = data_or_path.getvalue()
        size_bytes = len(payload)
    elif isinstance(data_or_path, bytes):
        payload = data_or_path
        size_bytes = len(payload)
    else:
        raise TypeError(f"Dữ liệu không hợp lệ cho upload: {type(data_or_path)}")

    headers = {
        "User-Agent": "NovelReader/4.4",
        "Content-Length": str(size_bytes),
        "Content-Type": "application/octet-stream",
    }

    if key:
        auth_str = f"api:{key}"
        encoded_auth = base64.b64encode(auth_str.encode("utf-8")).decode("utf-8")
        headers["Authorization"] = f"Basic {encoded_auth}"

    from contextlib import nullcontext
    source = payload.open('rb') if isinstance(payload, Path) else nullcontext(payload)
    try:
        with source as body:
            req = urllib.request.Request(url, data=body, headers=headers, method="PUT")
            response = urllib.request.urlopen(req, timeout=timeout)
        with response:
            resp_bytes = response.read()
            data = json.loads(resp_bytes.decode("utf-8"))
            file_id = data.get("id")
            if data.get("success") is False or not isinstance(file_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", file_id):
                raise RuntimeError(f"Pixeldrain không trả về file ID: {data}")

            view_url = f"{PIXELDRAIN_FILE_URL}/{file_id}"
            download_url = f"{PIXELDRAIN_API_URL}/{file_id}"
            log.info("Upload Pixeldrain thành công: %s -> %s", filename, view_url)

            return {
                "ok": True,
                "id": file_id,
                "url": view_url,
                "download_url": download_url,
                "filename": filename,
                "size_bytes": size_bytes,
                "size_mb": round(size_bytes / (1024 * 1024), 2),
                "message": f"Đã tải lên Pixeldrain thành công: {filename}"
            }
    except urllib.error.HTTPError as exc:
        err_msg = ""
        try:
            body = exc.read().decode("utf-8", errors="ignore")
            parsed = json.loads(body)
            err_msg = parsed.get("message", body)
        except Exception:
            err_msg = str(exc)

        if exc.code == 401:
            raise RuntimeError(
                "Pixeldrain yêu cầu API Key. Vui lòng tạo tài khoản miễn phí tại "
                "https://pixeldrain.com/user/api_keys và nhập API Key vào Cài đặt hoặc biến môi trường PIXELDRAIN_API_KEY."
            ) from exc
        if exc.code == 413:
            raise RuntimeError(f"File quá lớn ({round(size_bytes / (1024*1024), 1)} MB), vượt giới hạn Pixeldrain.") from exc
        raise RuntimeError(f"Lỗi Pixeldrain HTTP {exc.code}: {err_msg}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError("Không thể kết nối đến Pixeldrain. Kiểm tra mạng và thử lại.") from exc
    except (TimeoutError, socket.timeout) as exc:
        raise RuntimeError("Pixeldrain hết thời gian chờ; kiểm tra tài khoản trước khi tải lại để tránh file trùng.") from exc


def export_book_to_pixeldrain(store, kind: str, api_key: str | None = None) -> dict:
    """Export current book TXT, EPUB, or Audio ZIP directly to Pixeldrain."""
    kind = kind.lower().strip()
    if kind not in {"txt", "epub", "audio"}:
        raise ValueError("Định dạng phải là txt, epub hoặc audio")

    with store.connect() as conn:
        book = conn.execute("SELECT * FROM book LIMIT 1").fetchone()
        rows = conn.execute("SELECT * FROM chapter ORDER BY position").fetchall()

    if not book:
        raise ValueError("Chưa có truyện nào trong dự án.")

    book = dict(book)
    safe_title = _safe_filename(book.get("title") or "novel")

    if kind in {"txt", "epub"}:
        chapters = []
        for row in rows:
            chapter = dict(row)
            chapter["translated"] = json.loads(chapter.get("translated") or "[]")
            chapters.append(chapter)

        filename = f"{safe_title}.{kind}"
        payload = export_txt(book, chapters) if kind == "txt" else export_epub(book, chapters)
        return upload_to_pixeldrain(payload, filename, api_key=api_key)

    elif kind == "audio":
        import zipfile
        from audio.audio_service import exportable_audio_files
        audio_files = exportable_audio_files(store.audio_dir)
        if not audio_files:
            raise ValueError("Chưa có file audio nào để xuất.")

        filename = f"{safe_title}_audio.zip"
        with tempfile.TemporaryDirectory(prefix="novel-audio-export-") as work:
            archive = Path(work) / filename
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_STORED) as z:
                for f in audio_files:
                    if not f.is_symlink():
                        z.write(f, arcname=str(f.relative_to(store.audio_dir)))
            return upload_to_pixeldrain(archive, filename, api_key=api_key)



def export_audio_file_to_pixeldrain(store, filename: str, api_key: str | None = None) -> dict:
    """Upload a specific chapter audio or merged audio file to Pixeldrain."""
    candidates = [
        (store.audio_dir / filename).resolve(),
        (store.audio_dir / "audio_gop" / filename).resolve(),
    ]
    target_file = None
    for cand in candidates:
        if cand.is_file() and (store.audio_dir == cand.parent or store.audio_dir in cand.parents):
            target_file = cand
            break

    if not target_file:
        raise FileNotFoundError(f"Không tìm thấy file audio: {filename}")

    return upload_to_pixeldrain(target_file, target_file.name, api_key=api_key)
