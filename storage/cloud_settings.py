"""Backend-only credentials. Never included in backups or returned by an API."""
import json
import os
import tempfile
from pathlib import Path
from paths import data_dir


def key_path():
    return data_dir() / 'private' / 'pixeldrain.json'


def load_key():
    try:
        return str(json.loads(key_path().read_text(encoding='utf-8')).get('api_key', '')).strip()
    except (OSError, ValueError):
        return ''


def save_key(key):
    clean = (key or '').strip()
    target = key_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    if clean:
        os.environ["PIXELDRAIN_API_KEY"] = clean
    else:
        os.environ.pop("PIXELDRAIN_API_KEY", None)
    if not clean:
        target.unlink(missing_ok=True)
        return
    try:
        target.write_text(json.dumps({'api_key': clean}), encoding='utf-8')
    except Exception:
        pass
