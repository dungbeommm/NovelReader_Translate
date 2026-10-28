"""NovelReader MoLab — start WebUI + LocalTunnel and print URL/access code/logs.

All book, translation, audio and Hugging Face controls live in the FastAPI WebUI.
"""
import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    # Chỉ điền token thật trong BẢN NOTEBOOK RIÊNG TƯ; không commit lên public GitHub.
    HF_TOKEN_INLINE = ""

    import os
    import sys
    from pathlib import Path
    import subprocess
    import zipfile
    import urllib.request

    if HF_TOKEN_INLINE.strip():
        os.environ["HF_TOKEN"] = HF_TOKEN_INLINE.strip()

    return os, sys, Path, subprocess, zipfile, urllib


@app.cell
def _(os, sys, Path, subprocess, zipfile, urllib):
    base = Path.cwd().resolve()
    if (base / "main.py").is_file() and (base / "notebook/webui_launcher.py").is_file():
        repo_dir = base
    elif (base / "NovelReader_T4_Web/main.py").is_file() and (
            base / "NovelReader_T4_Web/notebook/webui_launcher.py").is_file():
        repo_dir = base / "NovelReader_T4_Web"
    else:
        repo_dir = base / "NovelReader_T4_Web"
        if (repo_dir / "main.py").exists():
            raise RuntimeError(
                "Sandbox còn source cũ. Hãy sao lưu dữ liệu, dừng job và cập nhật source; "
                "không xóa data/ hoặc output_audio/.")
        print("Tải mã nguồn NovelReader từ GitHub...", flush=True)
        clone = subprocess.run(
            ["git", "clone", "--depth", "1",
             "https://github.com/dungbeommm/NovelReader_Translate.git", str(repo_dir)],
            capture_output=True, text=True, timeout=120)
        if clone.returncode:
            print("git clone thất bại, thử ZIP source...", flush=True)
            with urllib.request.urlopen(
                "https://github.com/dungbeommm/NovelReader_Translate/archive/refs/heads/main.zip",
                timeout=120
            ) as response:
                archive = response.read()
            repo_dir.mkdir(parents=True, exist_ok=True)
            from io import BytesIO
            with zipfile.ZipFile(BytesIO(archive)) as z:
                for entry in z.infolist():
                    parts = Path(entry.filename).parts[1:]
                    if not parts:
                        continue
                    dest = repo_dir.joinpath(*parts)
                    if not dest.resolve().is_relative_to(repo_dir.resolve()):
                        raise ValueError("ZIP source chứa đường dẫn không an toàn.")
                    if entry.is_dir():
                        dest.mkdir(parents=True, exist_ok=True)
                    else:
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_bytes(z.read(entry))
        if not (repo_dir / "notebook/webui_launcher.py").is_file():
            raise RuntimeError("Mã nguồn tải về thiếu notebook/webui_launcher.py.")

    if str(repo_dir) not in sys.path:
        sys.path.insert(0, str(repo_dir))
    os.chdir(repo_dir)
    # Import by path, so Jupyter's preloaded 'notebook' package cannot shadow us.
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "novelreader_webui_launcher", repo_dir / "notebook/webui_launcher.py")
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    session = launcher.launch(repo_dir, tunnel="localtunnel")
    return launcher, repo_dir, session


@app.cell
def _(launcher, session):
    launcher.print_logs(session, lines=45)
    return


if __name__ == "__main__":
    app.run()
