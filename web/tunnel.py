"""Tunnel URL extraction, formatting, and management utilities.

Supports Pinggy HTTPS tunnels, Cloudflare HTTP/2 tunnels, and Localhost.run SSH tunnels.
"""
from __future__ import annotations

import queue
import re
import subprocess
import threading
import time
import os
from pathlib import Path
from typing import Callable, Optional

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\([a-zA-Z]|\x1b\][^\a\x1b]*(?:\a|\x1b\\)")
PINGGY_RE = re.compile(r"https://[a-zA-Z0-9.-]+\.pinggy[a-zA-Z0-9.-]*\.link")
CLOUDFLARE_RE = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")
LHR_RE = re.compile(r"https://[a-zA-Z0-9.-]+\.(?:lhr\.life|lhr\.pro|localhost\.run)")


def strip_ansi(text: str) -> str:
    """Remove ANSI / VT100 terminal escape sequences from text."""
    if not text:
        return ""
    return ANSI_ESCAPE_RE.sub("", text)


def extract_pinggy_url(text: str) -> Optional[str]:
    """Extract Pinggy HTTPS tunnel URL from terminal line or banner text."""
    clean = strip_ansi(text)
    match = PINGGY_RE.search(clean)
    if match:
        return match.group(0).rstrip("/.")
    return None


def extract_cloudflare_url(text: str) -> Optional[str]:
    """Extract Cloudflare quick tunnel URL from log file text."""
    clean = strip_ansi(text)
    match = CLOUDFLARE_RE.search(clean)
    if match:
        return match.group(0).rstrip("/.")
    return None


def extract_localhost_run_url(text: str) -> Optional[str]:
    """Extract Localhost.run SSH tunnel URL from terminal line."""
    clean = strip_ansi(text)
    match = LHR_RE.search(clean)
    if match:
        return match.group(0).rstrip("/.")
    return None


def format_access_url(base_url: str, token: str) -> str:
    """Format the final authenticated access link with query parameter."""
    clean_base = base_url.strip().rstrip("/")
    clean_token = token.strip()
    return f"{clean_base}/?access_token={clean_token}"


def read_stream_url(
    proc,
    extract_fn: Callable[[str], Optional[str]],
    timeout: float = 25.0
) -> Optional[str]:
    """Read lines from proc.stdout in a non-blocking thread with a strict timeout.

    Prevents hanging the notebook cell when SSH handshakes stall or buffer.
    """
    if proc is None or proc.stdout is None:
        return None

    q: queue.Queue[Optional[str]] = queue.Queue()

    def _reader():
        try:
            for line in iter(proc.stdout.readline, ""):
                if line:
                    q.put(line)
                else:
                    break
        except Exception:
            pass
        finally:
            q.put(None)

    worker = threading.Thread(target=_reader, daemon=True)
    worker.start()

    start = time.time()
    while time.time() - start < timeout:
        remaining = max(0.1, timeout - (time.time() - start))
        try:
            line = q.get(timeout=min(0.5, remaining))
            if line is None:
                break
            found = extract_fn(line)
            if found:
                return found
        except queue.Empty:
            if proc.poll() is not None:
                while not q.empty():
                    buffered = q.get_nowait()
                    if buffered:
                        found = extract_fn(buffered)
                        if found:
                            return found
                break
            continue

    return None


def cleanup_tunnels(subp=subprocess) -> None:
    """Kill lingering tunnel processes (uvicorn, cloudflared, Pinggy SSH, Localhost.run SSH)."""
    targets = [
        ["pkill", "-f", "uvicorn.*main:app"],
        ["pkill", "-f", "cloudflared"],
        ["pkill", "-f", "a.pinggy.io"],
        ["pkill", "-f", "nokey@localhost.run"],
    ]
    for cmd in targets:
        try:
            subp.run(cmd, check=False, stdout=subp.DEVNULL, stderr=subp.DEVNULL)
        except Exception:
            pass


class CloudflareTunnel:
    """Lifecycle wrapper for the only supported public access path."""
    def __init__(self, port: int = 8000, log_path: Path | None = None):
        self.port = port
        self.log_path = Path(log_path or 'data/logs/cloudflared.log')
        self.process = None
        self._log_handle = None

    @property
    def active(self):
        return self.process is not None and self.process.poll() is None

    def start(self):
        if self.active:
            return self.status()
        executable = os.getenv('CLOUDFLARED_BIN', 'cloudflared')
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_handle = self.log_path.open('a', encoding='utf-8', buffering=1)
        try:
            self.process = subprocess.Popen(
                [executable, 'tunnel', '--no-autoupdate', '--protocol', 'http2', '--url', f'http://127.0.0.1:{self.port}'],
                stdout=self._log_handle, stderr=subprocess.STDOUT, cwd=str(Path.cwd()), env=dict(os.environ),
            )
        except OSError as exc:
            self._log_handle.close()
            self._log_handle = None
            raise RuntimeError('Không tìm thấy cloudflared hoặc không thể khởi động Cloudflare Tunnel.') from exc
        return self.status()

    def stop(self):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.process = None
        if self._log_handle:
            self._log_handle.close()
            self._log_handle = None
        return self.status()

    def status(self):
        text = self.log_path.read_text(encoding='utf-8', errors='replace') if self.log_path.is_file() else ''
        return {'provider': 'cloudflare', 'active': self.active, 'pid': self.process.pid if self.active else None,
                'url': extract_cloudflare_url(text)}
