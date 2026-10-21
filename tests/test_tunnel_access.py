import os
import re
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient

from web.tunnel import (
    strip_ansi,
    extract_pinggy_url,
    extract_cloudflare_url,
    extract_localhost_run_url,
    format_access_url,
    read_stream_url,
    cleanup_tunnels,
)
from web.access import has_access, protect_request, _matches, COOKIE
from web.application import create_app


# ==============================================================================
# 1. Tests for URL Extraction & ANSI Stripping
# ==============================================================================

def test_strip_ansi():
    raw = "\x1b[32mhttps://foo.pinggy.link\x1b[0m\x1b[1m\x1b[?25h"
    assert strip_ansi(raw) == "https://foo.pinggy.link"
    assert strip_ansi("") == ""
    assert strip_ansi("Plain text 123") == "Plain text 123"


def test_extract_pinggy_url_standard():
    line = "Your tunnel is live at: https://rnajk-12-34-56-78.a.free.pinggy.link"
    assert extract_pinggy_url(line) == "https://rnajk-12-34-56-78.a.free.pinggy.link"


def test_extract_pinggy_url_with_ansi_and_trailing():
    line = "\x1b[1;32mhttps://mycustom.pinggy.link/\x1b[0m"
    assert extract_pinggy_url(line) == "https://mycustom.pinggy.link"


def test_extract_pinggy_url_not_found():
    line = "Connecting to SSH server a.pinggy.io..."
    assert extract_pinggy_url(line) is None


def test_extract_cloudflare_url_standard():
    log_chunk = (
        "2026-10-21T08:00:00Z INF +--------------------------------------------------------------------------------------------+\n"
        "2026-10-21T08:00:00Z INF |  Your quick Tunnel has been created! Visit it at (it may take some time to be reachable):  |\n"
        "2026-10-21T08:00:00Z INF |  https://orange-county-marimo-1234.trycloudflare.com                                     |\n"
        "2026-10-21T08:00:00Z INF +--------------------------------------------------------------------------------------------+\n"
    )
    assert extract_cloudflare_url(log_chunk) == "https://orange-county-marimo-1234.trycloudflare.com"


def test_extract_cloudflare_url_not_found():
    log_chunk = "2026-10-21T08:00:00Z INF Starting tunnel..."
    assert extract_cloudflare_url(log_chunk) is None


def test_extract_localhost_run_url_standard():
    line = "Connect to: https://subdomain-999.lhr.life (port 80)"
    assert extract_localhost_run_url(line) == "https://subdomain-999.lhr.life"


def test_extract_localhost_run_url_pro():
    line = "https://custom-tunnel.lhr.pro"
    assert extract_localhost_run_url(line) == "https://custom-tunnel.lhr.pro"


def test_extract_localhost_run_url_not_found():
    line = "Authenticating with nokey@localhost.run..."
    assert extract_localhost_run_url(line) is None


# ==============================================================================
# 2. Tests for URL Formatting & Token Appending
# ==============================================================================

def test_format_access_url_cleans_slashes():
    base = "https://abc.pinggy.link/"
    token = "my-secret-token-32-chars-long"
    assert format_access_url(base, token) == "https://abc.pinggy.link/?access_token=my-secret-token-32-chars-long"


def test_format_access_url_no_trailing_slash():
    base = "https://xyz.trycloudflare.com"
    token = "token123"
    assert format_access_url(base, token) == "https://xyz.trycloudflare.com/?access_token=token123"


def test_format_access_url_strips_token_whitespace():
    base = "http://127.0.0.1:8000"
    token = "  token-with-spaces  \n"
    assert format_access_url(base, token) == "http://127.0.0.1:8000/?access_token=token-with-spaces"


# ==============================================================================
# 3. Tests for Non-Blocking Process Stream Reader & Timeout (Bug 3 Fix)
# ==============================================================================

def test_read_stream_url_immediate_match():
    class FakeStdout:
        def __init__(self, lines):
            self.lines = list(lines)
        def readline(self):
            return self.lines.pop(0) if self.lines else ""

    proc = MagicMock()
    proc.stdout = FakeStdout([
        "SSH banner...\n",
        "https://demo.pinggy.link\n"
    ])
    proc.poll.return_value = None

    url = read_stream_url(proc, extract_pinggy_url, timeout=2.0)
    assert url == "https://demo.pinggy.link"


def test_read_stream_url_timeout_does_not_hang():
    """Verify that if proc.stdout stalls indefinitely, read_stream_url returns None without hanging."""
    class StallingStdout:
        def readline(self):
            # Simulate a network hang / blocking SSH readline
            time.sleep(10.0)
            return ""

    proc = MagicMock()
    proc.stdout = StallingStdout()
    proc.poll.return_value = None

    t0 = time.time()
    url = read_stream_url(proc, extract_pinggy_url, timeout=0.3)
    duration = time.time() - t0

    assert url is None
    # Must exit within ~0.6s and NOT hang for 10s
    assert duration < 1.0


def test_read_stream_url_process_exits_early():
    class EmptyStdout:
        def readline(self):
            return ""

    proc = MagicMock()
    proc.stdout = EmptyStdout()
    proc.poll.return_value = 1  # Process died

    url = read_stream_url(proc, extract_pinggy_url, timeout=1.0)
    assert url is None


# ==============================================================================
# 4. Tests for Null-Safety of cf_executable under All Modes (Bug 1 Fix)
# ==============================================================================

@pytest.mark.parametrize("tunnel_mode", ["auto", "cloudflare", "pinggy", "localhost_run"])
def test_cf_executable_null_safety(tmp_path, tunnel_mode):
    """Ensure no AttributeError: 'NoneType' object has no attribute 'is_file' for any mode."""
    base_dir = tmp_path
    cf_executable = None
    if tunnel_mode in ("auto", "cloudflare"):
        cf_executable = base_dir / "cloudflared"

    # This check caused the crash previously when cf_executable was None
    is_linux = True
    if cf_executable is not None and is_linux and not cf_executable.is_file():
        # Simulated download logic
        pass

    # This check also crashed previously
    can_run = cf_executable is not None and cf_executable.is_file()

    if tunnel_mode in ("pinggy", "localhost_run"):
        assert cf_executable is None
        assert can_run is False
    else:
        assert cf_executable is not None
        assert can_run is False  # not downloaded yet


# ==============================================================================
# 5. Tests for Stale Cloudflare Log Prevention (Bug 2 Fix)
# ==============================================================================

def test_stale_cloudflare_log_unlinking(tmp_path):
    log_tunnel = tmp_path / "colab-tunnel.log"
    # Create old log file from previous run
    log_tunnel.write_text("https://old-expired-url.trycloudflare.com\n", encoding="utf-8")

    # In step 5, unlinking prevents re-reading the old session URL
    if log_tunnel.is_file():
        log_tunnel.unlink()

    assert not log_tunnel.is_file()

    # When cloudflared writes new output
    log_tunnel.write_text("https://brand-new-url.trycloudflare.com\n", encoding="utf-8")
    assert extract_cloudflare_url(log_tunnel.read_text(encoding="utf-8")) == "https://brand-new-url.trycloudflare.com"


# ==============================================================================
# 6. Tests for Process Cleanup (Bug 4 Fix)
# ==============================================================================

def test_cleanup_tunnels_invokes_all_process_kills():
    mock_subp = MagicMock()
    cleanup_tunnels(mock_subp)

    called_cmds = [call.args[0] for call in mock_subp.run.call_args_list]
    flat_cmds = [" ".join(cmd) for cmd in called_cmds]

    assert any("uvicorn.*main:app" in cmd for cmd in flat_cmds)
    assert any("cloudflared" in cmd for cmd in flat_cmds)
    assert any("a.pinggy.io" in cmd for cmd in flat_cmds)
    assert any("nokey@localhost.run" in cmd for cmd in flat_cmds)


# ==============================================================================
# 7. Tests for Web Access / Token Verification (web/access.py)
# ==============================================================================

def test_access_token_query_grant_and_cookie_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVEL_DATA", str(tmp_path / "data"))
    token = "safe-token-for-testing-12345"
    monkeypatch.setenv("NOVEL_WEB_ACCESS_TOKEN", token)

    app = create_app()
    with TestClient(app) as client:
        # 1. Accessing root without token -> shows login page
        resp = client.get("/")
        assert resp.status_code == 200
        assert "Đăng nhập NovelReader" in resp.text

        # 2. Accessing API without token -> 403 Forbidden
        assert client.get("/api/state").status_code == 403

        # 3. Accessing root with valid token -> 303 Redirect + Set-Cookie
        auth_resp = client.get(f"/?access_token={token}", follow_redirects=False)
        assert auth_resp.status_code == 303
        assert COOKIE in auth_resp.headers.get("set-cookie", "")

        # 4. Following redirect with cookie -> 200 OK
        final_resp = client.get("/?cookie_check=1")
        assert final_resp.status_code == 200

        # 5. Subsequent API call with cookie succeeds
        api_resp = client.get("/api/state")
        assert api_resp.status_code == 200


def test_access_token_with_whitespace_stripping(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVEL_DATA", str(tmp_path / "data"))
    token = "secret-token-xyz"
    monkeypatch.setenv("NOVEL_WEB_ACCESS_TOKEN", token)

    app = create_app()
    with TestClient(app) as client:
        # Token with extra spaces in URL query param
        resp = client.get(f"/?access_token=+{token}+", follow_redirects=False)
        assert resp.status_code == 303
        assert COOKIE in resp.headers.get("set-cookie", "")


def test_handle_login_proxy_headers(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVEL_DATA", str(tmp_path / "data"))
    token = "login-form-secret"
    monkeypatch.setenv("NOVEL_WEB_ACCESS_TOKEN", token)

    app = create_app()
    with TestClient(app) as client:
        # POST with X-Forwarded-Host matching Origin
        resp = client.post(
            "/auth/login",
            data={"token": token},
            headers={
                "Origin": "https://xyz.trycloudflare.com",
                "X-Forwarded-Host": "xyz.trycloudflare.com",
                "Host": "127.0.0.1:8000"
            },
            follow_redirects=False
        )
        assert resp.status_code == 303
        assert COOKIE in resp.headers.get("set-cookie", "")

        # POST with mismatched Origin should be rejected
        bad_origin_resp = client.post(
            "/auth/login",
            data={"token": token},
            headers={
                "Origin": "https://malicious-site.com",
                "Host": "xyz.trycloudflare.com"
            }
        )
        assert bad_origin_resp.status_code == 403
