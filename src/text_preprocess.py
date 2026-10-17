"""Chinese text normalization before translation."""

from __future__ import annotations

from functools import lru_cache

NORMALIZE_AUTO = "auto"
NORMALIZE_T2S = "t2s"
NORMALIZE_NONE = "none"
NORMALIZE_MODES = {NORMALIZE_AUTO, NORMALIZE_T2S, NORMALIZE_NONE}


@lru_cache(maxsize=1)
def _t2s_converter():
    from opencc import OpenCC

    return OpenCC("t2s")


def normalize_mode(mode: str | None) -> str:
    mode = (mode or NORMALIZE_AUTO).strip().lower()
    return mode if mode in NORMALIZE_MODES else NORMALIZE_AUTO


def normalize_chinese_text(text: str, mode: str | None = NORMALIZE_AUTO) -> str:
    mode = normalize_mode(mode)
    if mode == NORMALIZE_NONE or not text:
        return text
    return _t2s_converter().convert(text)


def normalization_message(original: str, normalized: str, mode: str | None) -> str:
    mode = normalize_mode(mode)
    if mode == NORMALIZE_NONE:
        return "Giữ nguyên chữ Hán gốc."
    if original == normalized:
        return "Đã kiểm tra chữ Hán: không cần chuyển phồn thể."
    return "Đã chuyển phồn thể sang giản thể trước khi dịch."
