"""Backend-only credentials. Never included in backups or returned by an API."""
import json
import os
import tempfile
from pathlib import Path
from paths import data_dir


def key_path():
    return data_dir() / 'private' / 'huggingface.json'


def load_key():
    token = os.getenv('HF_TOKEN', '').strip()
    if token:
        return token
    try:
        return str(json.loads(key_path().read_text(encoding='utf-8')).get('api_key', '')).strip()
    except (OSError, ValueError):
        return ''


def save_key(key):
    target = key_path()
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not key:
        target.unlink(missing_ok=True)
        return
    fd, name = tempfile.mkstemp(dir=target.parent, prefix='.hf-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump({'api_key': key.strip()}, f)
        os.chmod(name, 0o600)
        os.replace(name, target)
    finally:
        Path(name).unlink(missing_ok=True)

# Shared runtime configuration: both the Marimo and Uvicorn processes read this file.
DEFAULT_REPO_ID = "uri410/novelreader-storage"

def repo_id_path():
    return data_dir() / "private" / "huggingface_repo.json"

def validate_repo_id(value):
    import re
    if not isinstance(value, str) or len(value) > 256:
        raise ValueError("Bucket HF không hợp lệ.")
    parts = value.split("/")
    if len(parts) != 2 or any(
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", part) or part in {".", ".."}
        for part in parts
    ):
        raise ValueError("Bucket HF phải có dạng tài_khoản/tên_bucket.")
    return value

def load_repo_id():
    value = ""
    try:
        value = str(json.loads(repo_id_path().read_text(encoding="utf-8")).get("repo_id") or "").strip()
    except (OSError, ValueError, TypeError):
        pass
    return validate_repo_id(value or os.getenv("HF_BUCKET_ID", "").strip() or DEFAULT_REPO_ID)

def save_repo_id(value):
    value = validate_repo_id(value)
    target = repo_id_path()
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(dir=target.parent, prefix=".hf-repo-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"repo_id": value}, f)
        os.chmod(name, 0o600)
        os.replace(name, target)
    finally:
        Path(name).unlink(missing_ok=True)
    return value
