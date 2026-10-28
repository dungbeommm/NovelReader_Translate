"""Standalone launcher should neither create duplicate workers nor expose secret tokens."""
import ast
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "novelreader_webui_launcher_test", ROOT / "notebook/webui_launcher.py")
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


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


def test_two_notebooks_are_launchers_only():
    code = (ROOT / "NovelReader_Molab.py").read_text(encoding="utf-8")
    ast.parse(code)
    assert "mo.ui." not in code
    assert "ZROK_ACCOUNT_TOKEN_INLINE" in code
    notebook = json.loads((ROOT / "NovelReader_Colab.ipynb").read_text(encoding="utf-8"))
    assert notebook["nbformat"] == 4
    assert len([c for c in notebook["cells"] if c["cell_type"] == "code"]) == 2
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            ast.parse("".join(cell["source"]))
