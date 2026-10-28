"""Standalone launcher should neither create duplicate workers nor expose secret tokens."""
from notebook import webui_launcher as launcher


def test_log_tail(tmp_path):
    p = tmp_path / "test.log"
    p.write_text("a\nb\nc\n", encoding="utf-8")
    assert launcher.tail(p, 2) == "b\nc"


def test_access_token_preserved_when_existing_server(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher, "_server_process", lambda: (431, "existing-server-code"))
    monkeypatch.setattr(launcher, "_http_state", lambda token, timeout=3: (200, {}))
    assert launcher.ensure_webui(tmp_path) == "existing-server-code"
    assert (tmp_path / "data/private/web_access_token").read_text() == "existing-server-code"


def test_environment_keeps_cpu_detection_boolean(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher, "_gpu", lambda: "")
    monkeypatch.setenv("COLAB_GPU", "0")
    assert launcher.prepare_environment(tmp_path) == ""
    assert "COLAB_GPU" not in __import__("os").environ


def test_no_token_zrok_does_not_block_webui(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher, "prepare_environment", lambda root: "")
    monkeypatch.setattr(launcher, "ensure_dependencies", lambda root: None)
    monkeypatch.setattr(launcher, "ensure_webui", lambda root: "login-code")
    (tmp_path / "main.py").write_text("# stub")
    result = launcher.launch(tmp_path, zrok_token="")
    assert result["url"] == ""
    assert result["access_code"] == "login-code"
