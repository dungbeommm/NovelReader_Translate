"""Pixeldrain cloud storage service for NovelReader.

Provides direct upload for translated TXT, EPUB, and Audio files to Pixeldrain.
Supports both anonymous uploads (where permitted) and API-key authenticated uploads.
"""
import base64
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
    """Retrieve Pixeldrain API key from argument, environment, or saved config."""
    if passed_key and passed_key.strip():
        return passed_key.strip()
    env_key = os.getenv("PIXELDRAIN_API_KEY", "").strip()
    if env_key:
        return env_key
    return None


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
    safe_name = urllib.parse.quote(filename.strip())
    url = f"{PIXELDRAIN_API_URL}/{safe_name}"

    if isinstance(data_or_path, (str, Path)):
        file_path = Path(data_or_path)
        if not file_path.is_file():
            raise FileNotFoundError(f"Không tìm thấy file để upload: {file_path}")
        payload = file_path.read_bytes()
        size_bytes = len(payload)
    elif isinstance(data_or_path, io.BytesIO):
        payload = data_or_path.getvalue()
        size_bytes = len(payload)
    elif isinstance(data_or_path, bytes):
        payload = data_or_path
        size_bytes = len(payload)
    else:
        raise TypeError(f"Dữ liệu không hợp lệ cho upload: {type(data_or_path)}")

    headers = {
        "User-Agent": "NovelReader/4.3",
        "Content-Type": "application/octet-stream",
    }

    if key:
        # Pixeldrain Basic Auth: username is 'api' or blank, password is API key
        auth_str = f"api:{key}"
        encoded_auth = base64.b64encode(auth_str.encode("utf-8")).decode("utf-8")
        headers["Authorization"] = f"Basic {encoded_auth}"

    req = urllib.request.Request(url, data=payload, headers=headers, method="PUT")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            resp_bytes = response.read()
            data = json.loads(resp_bytes.decode("utf-8"))
            file_id = data.get("id")
            if not file_id:
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
        raise RuntimeError(f"Không thể kết nối đến Pixeldrain: {exc.reason}") from exc


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
        audio_files = [
            f for f in sorted(store.audio_dir.rglob("*.*"))
            if f.is_file() and not f.name.startswith(".")
            and f.suffix.lower() in {".mp3", ".m4b", ".m4a", ".opus", ".wav", ".aac", ".ogg"}
        ]
        if not audio_files:
            raise ValueError("Chưa có file audio nào để xuất.")

        filename = f"{safe_title}_audio.zip"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for f in audio_files:
                z.write(f, arcname=str(f.relative_to(store.audio_dir)))

        return upload_to_pixeldrain(buf.getvalue(), filename, api_key=api_key)


def export_audio_file_to_pixeldrain(store, filename: str, api_key: str | None = None) -> dict:
    """Upload a specific chapter audio or merged audio file to Pixeldrain."""
    # Look in audio_dir root or audio_gop
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
