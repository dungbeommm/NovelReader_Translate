"""Reusable translation-model setup."""
import os
import subprocess
import sys
from pathlib import Path


def ensure_translation_model(repo_dir, model):
    from translation.engines import MODELS, is_model_downloaded

    if model not in MODELS:
        raise ValueError(f"Model dịch không hỗ trợ: {model}")
    if is_model_downloaded(model):
        return False
    root = Path(repo_dir)
    subprocess.run(
        [sys.executable, str(root / "scripts/download_model.py"), "--model", model],
        cwd=str(root), env=dict(os.environ), check=True)
    if not is_model_downloaded(model):
        raise RuntimeError(f"Model {model} thiếu file sau khi tải.")
    return True
