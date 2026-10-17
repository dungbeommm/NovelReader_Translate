"""Shared progress state — polled by UI timer during long translation.

Per-session: mỗi phiên Gradio (tab/trình duyệt, key theo request.session_hash)
có ProgressState riêng — nhiều người dùng đồng thời (HF Space) không đè thanh
tiến trình của nhau. Handler không lấy được session (None) rơi về key mặc định,
tức hành vi global cũ — an toàn cho single-user local và mọi đường gọi cũ.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass


@dataclass
class ProgressState:
    pct: float = 0.0
    message: str = "Sẵn sàng."
    running: bool = False


_DEFAULT_KEY = "__default__"
_MAX_SESSIONS = 256  # LRU cap — Space chạy dài ngày không tích state vô hạn

_lock = threading.Lock()
_states: OrderedDict[str, ProgressState] = OrderedDict()


def _state_for(session: str | None) -> ProgressState:
    """Lấy state của session, tạo mới nếu chưa có. Phải gọi TRONG _lock."""
    key = session or _DEFAULT_KEY
    state = _states.get(key)
    if state is None:
        state = ProgressState()
        _states[key] = state
    _states.move_to_end(key)
    while len(_states) > _MAX_SESSIONS:
        _states.popitem(last=False)
    return state


def set_progress(
    pct: float,
    message: str,
    *,
    running: bool = True,
    session: str | None = None,
) -> None:
    with _lock:
        state = _state_for(session)
        state.pct = max(0.0, min(100.0, float(pct)))
        state.message = message
        state.running = running


def finish_progress(message: str, *, session: str | None = None) -> None:
    with _lock:
        state = _state_for(session)
        state.pct = 100.0
        state.message = message
        state.running = False


def reset_progress(message: str = "Sẵn sàng.", *, session: str | None = None) -> None:
    with _lock:
        state = _state_for(session)
        state.pct = 0.0
        state.message = message
        state.running = False


def snapshot(session: str | None = None) -> ProgressState:
    with _lock:
        state = _state_for(session)
        return ProgressState(
            pct=state.pct,
            message=state.message,
            running=state.running,
        )
