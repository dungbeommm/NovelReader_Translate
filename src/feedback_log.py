"""Ghi feedback/sửa câu dịch ra JSONL local (dev-only). KHÔNG import gradio."""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

SCHEMA_VERSION = 1

ROOT = Path(__file__).resolve().parent.parent


def _default_log_path() -> Path:
    env = os.environ.get("HACHIMIMT_FEEDBACK_LOG_PATH", "").strip()
    if env:
        return Path(env)
    return ROOT / "feedback" / "corrections.jsonl"


DEFAULT_LOG_PATH = _default_log_path()

_WRITE_LOCK = threading.Lock()


@dataclass
class FeedbackEntry:
    schema_version: int
    ts: str
    run_id: str
    source_kind: str       # "text" | "file"
    model: str
    backend: str
    chunk_mode: str
    normalize_mode: str
    honorific: str         # none|kinship|pronoun|kinship+pronoun
    pronoun_v9: bool
    category: str | None
    idx: int
    source: str            # nguồn SAU normalize
    mt_final: str          # bản dịch SAU hậu kỳ
    corrected: str | None
    rating: str | None     # "good" | "bad" | None


def append_feedback(entry: FeedbackEntry, log_path: Path = DEFAULT_LOG_PATH) -> None:
    """Append 1 dòng JSON UTF-8. Tạo thư mục nếu chưa có. Lock để click đồng thời
    không xen dòng. ensure_ascii=False giữ chữ Trung/dấu Việt."""
    line = json.dumps(asdict(entry), ensure_ascii=False)
    with _WRITE_LOCK:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
