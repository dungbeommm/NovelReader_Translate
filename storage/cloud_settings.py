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
    target = key_path()
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not key:
        target.unlink(missing_ok=True)
        return
    fd, name = tempfile.mkstemp(dir=target.parent, prefix='.pd-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump({'api_key': key.strip()}, f)
        os.chmod(name, 0o600)
        os.replace(name, target)
    finally:
        Path(name).unlink(missing_ok=True)
