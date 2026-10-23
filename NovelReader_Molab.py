# /// script
# dependencies = ["marimo>=0.19,<1"]
# ///
"""NovelReader: bootstrap and launch the web app in a Molab session."""

import marimo

__generated_with = "0.25.1"
app = marimo.App(width="full", app_title="NovelReader · Molab")


@app.cell
def _intro():
    import marimo as mo
    import os
    import subprocess
    import sys
    from pathlib import Path

    engine = mo.ui.dropdown(
        options={"Piper · nhẹ": "piper", "VieNeu v3": "vieneu"},
        value="Piper · nhẹ", label="Bộ đọc",
    )
    piper_voice = mo.ui.dropdown(
        options=["ngochuyennew", "banmai", "calmwoman3688", "adam1", "chieuthanh", "deepman3909"],
        value="ngochuyennew", label="Giọng Piper",
    )
    vieneu_voice = mo.ui.dropdown(
        options=["truc_ly", "minh_quan_pro", "adam_bua", "mai_anh", "thuy_dung", "ngoc_huyen"],
        value="truc_ly", label="Giọng VieNeu",
    )

    mo.output.replace(mo.vstack([
        mo.md("# NovelReader"),
        mo.md("Nạp truyện **TXT/EPUB**, dịch sang tiếng Việt và tạo audio. Chạy cell theo thứ tự từ trên xuống; giữ phiên Molab mở khi sử dụng."),
        engine,
        mo.hstack([piper_voice, vieneu_voice], gap=2),
    ]))
    return Path, engine, mo, os, piper_voice, subprocess, sys, vieneu_voice


@app.cell
def _prepare(Path, mo, os, subprocess, sys):
    """Use the checked-out project, or fetch its source when only this file was uploaded."""
    import shutil
    import urllib.request as _urllib_bootstrap
    import zipfile

    cwd = Path.cwd().resolve()
    if (cwd / "main.py").is_file() and (cwd / "web").is_dir():
        root = cwd
    else:
        root = cwd / "NovelReader_Translate"
        root.mkdir(parents=True, exist_ok=True)
        archive = cwd / "novelreader-source.zip"
        _request = _urllib_bootstrap.Request(
            "https://github.com/dungbeommm/NovelReader_Translate/archive/refs/heads/main.zip",
            headers={"User-Agent": "NovelReader-Molab"},
        )
        with _urllib_bootstrap.urlopen(_request, timeout=90) as response, archive.open("wb") as output:
            shutil.copyfileobj(response, output)
        with zipfile.ZipFile(archive) as bundle:
            prefix = bundle.namelist()[0].split("/")[0] + "/"
            for item in bundle.infolist():
                if item.is_dir() or not item.filename.startswith(prefix):
                    continue
                relative = item.filename[len(prefix):]
                if not relative:
                    continue
                destination = root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(item) as source, destination.open("wb") as target:
                    shutil.copyfileobj(source, target)
        archive.unlink(missing_ok=True)

    os.chdir(root)
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    for name in ("data/logs", "models/translation", "models/voices", "output_text", "output_audio"):
        (root / name).mkdir(parents=True, exist_ok=True)

    try:
        gpu = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        gpu = None
    gpu_line = gpu.stdout.strip().splitlines()[0] if gpu and gpu.returncode == 0 and gpu.stdout.strip() else ""
    gpu_name, vram_mb = (part.strip() for part in gpu_line.split(",", 1)) if gpu_line else ("CPU", "0")
    mo.output.replace(mo.md(f"**Mã nguồn:** `{root}`  ·  **Thiết bị:** {gpu_name}  ·  **VRAM:** {int(vram_mb) / 1024:.1f} GB"))
    return Path, gpu_line, mo, os, root, subprocess, sys


@app.cell
def _install(engine, gpu_line, mo, os, piper_voice, root, subprocess, sys, vieneu_voice):
    import hashlib

    worker_dir = root / ".worker-venv"
    python = worker_dir / "bin/python"
    if not python.exists():
        subprocess.run([sys.executable, "-m", "venv", "--system-site-packages", str(worker_dir)], check=True)
    requirements = [root / "requirements-worker.txt"]
    requirements.append(root / ("requirements-vieneu.txt" if engine.value == "vieneu" else "tts/requirements.txt"))
    signature = hashlib.sha256((engine.value + "|" + "|".join(hashlib.sha256(p.read_bytes()).hexdigest() for p in requirements)).encode()).hexdigest()
    marker = worker_dir / ".molab-requirements"
    if not marker.is_file() or marker.read_text(encoding="utf-8") != signature:
        for requirement in requirements:
            subprocess.run([str(python), "-m", "pip", "install", "-q", "-r", str(requirement)], check=True)
        if gpu_line and engine.value == "piper":
            subprocess.run([str(python), "-m", "pip", "uninstall", "-y", "onnxruntime"], check=False, stdout=subprocess.DEVNULL)
            subprocess.run([str(python), "-m", "pip", "install", "-q", "onnxruntime-gpu>=1.20,<2", "nvidia-cudnn-cu12", "nvidia-cublas-cu12"], check=True)
        marker.write_text(signature, encoding="utf-8")

    voice = vieneu_voice.value if engine.value == "vieneu" else piper_voice.value
    os.environ.update({
        "NOVEL_TTS_ENGINE": engine.value,
        "NOVEL_TTS_VOICE": voice,
        "VIENEU_DEVICE": "cuda" if gpu_line else "cpu",
        "PIPER_DEVICE": "cuda" if gpu_line else "cpu",
        "PIPER_REQUIRE_CUDA": "0",
        "HACHIMIMT_FORCE_CT2_CUDA": "1" if gpu_line else "0",
        "HACHIMIMT_COMPUTE_TYPE": "int8_float16" if gpu_line else "default",
        "HACHIMIMT_BATCH_SIZE": str(max(32, min(192, int(gpu_line.split(",", 1)[1]) // 1024 * 4)) if gpu_line else 16),
        "NOVEL_WORKER_PYTHON": str(python),
        "NOVEL_DATA": str(root / "data"),
        "NOVEL_MODELS": str(root / "models/translation"),
        "TTS_VOICE_DIR": str(root / "models/voices"),
        "NOVEL_OUTPUT_TEXT": str(root / "output_text"),
        "NOVEL_OUTPUT_AUDIO": str(root / "output_audio"),
        "ALLOWED_HOSTS": "*",
        "ALLOW_TUNNEL": "1",
        "PYTHONUNBUFFERED": "1",
    })
    voice_args = [str(python), str(root / "scripts/setup_tts.py"), "--engine", engine.value, "--voice", voice]
    if engine.value == "vieneu":
        voice_args += ["--device", os.environ["VIENEU_DEVICE"], "--install", "--preload"]
    subprocess.run(voice_args, cwd=root, check=True)
    mo.output.replace(mo.md("✅ **Môi trường đã sẵn sàng.** Chạy cell tiếp theo để mở ứng dụng."))
    return python, root


@app.cell
def _launch(mo, os, python, root, subprocess, sys):
    import secrets
    import queue
    import re
    import threading
    import time
    import urllib.request as _urllib_tunnel

    token = secrets.token_urlsafe(32)
    os.environ["NOVEL_WEB_ACCESS_TOKEN"] = token
    os.environ["NOVEL_EXPORT_SESSION_ID"] = secrets.token_hex(16)
    server_log = root / "data/logs/molab-server.log"
    tunnel_log = root / "data/logs/molab-tunnel.log"
    tunnel_log.unlink(missing_ok=True)
    log_handle = server_log.open("a", encoding="utf-8", buffering=1)
    server = subprocess.Popen(
        [str(python), "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"],
        cwd=root, env=os.environ.copy(), stdout=log_handle, stderr=subprocess.STDOUT,
    )

    ready = False
    for _ in range(90):
        if server.poll() is not None:
            break
        try:
            _request = _urllib_tunnel.Request("http://127.0.0.1:8000/api/state", headers={"X-Novel-Access": token})
            with _urllib_tunnel.urlopen(_request, timeout=2):
                ready = True
                break
        except Exception:
            time.sleep(1)

    public_url = None
    tunnel = None
    if ready and sys.platform.startswith("linux"):
        cloudflared = root / "data/cloudflared"
        if not cloudflared.is_file():
            arch = "arm64" if "aarch64" in __import__("platform").machine().lower() else "amd64"
            try:
                _urllib_tunnel.urlretrieve(f"https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-{arch}", cloudflared)
                cloudflared.chmod(0o755)
            except Exception:
                pass
        if cloudflared.is_file():
            tunnel = subprocess.Popen(
                [str(cloudflared), "tunnel", "--url", "http://127.0.0.1:8000", "--no-autoupdate", "--logfile", str(tunnel_log)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            for _ in range(40):
                if tunnel.poll() is not None:
                    break
                if tunnel_log.exists():
                    import re
                    match = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", tunnel_log.read_text(errors="replace"))
                    if match:
                        public_url = match.group(0)
                        break
                time.sleep(1)

    # A Quick Tunnel URL can be issued before Cloudflare has a healthy edge route.
    if ready and public_url:
        try:
            _urllib_tunnel.urlopen(f"{public_url}/?access_token={token}", timeout=8)
        except Exception:
            public_url = None

    if ready and not public_url and sys.platform.startswith("linux"):
        try:
            tunnel = subprocess.Popen(
                ["ssh", "-p", "443", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
                 "-o", "LogLevel=ERROR", "-o", "ConnectTimeout=15", "-o", "ServerAliveInterval=30",
                 "-R", "0:localhost:8000", "a.pinggy.io"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                env={**os.environ, "TERM": "dumb"},
            )
            lines = queue.Queue()
            threading.Thread(
                target=lambda: [lines.put(line) for line in iter(tunnel.stdout.readline, "")], daemon=True
            ).start()
            deadline = time.monotonic() + 40
            while time.monotonic() < deadline and tunnel.poll() is None:
                try:
                    match = re.search(r"https://[A-Za-z0-9.-]+\.pinggy[A-Za-z0-9.-]*\.link", lines.get(timeout=0.5))
                    if match:
                        public_url = match.group(0)
                        break
                except queue.Empty:
                    pass
        except Exception:
            public_url = None

    if ready and not public_url and sys.platform.startswith("linux"):
        try:
            tunnel = subprocess.Popen(
                ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
                 "-o", "LogLevel=ERROR", "-o", "ConnectTimeout=15", "-o", "ServerAliveInterval=30",
                 "-R", "80:localhost:8000", "nokey@localhost.run"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                env={**os.environ, "TERM": "dumb"},
            )
            lines = queue.Queue()
            threading.Thread(
                target=lambda: [lines.put(line) for line in iter(tunnel.stdout.readline, "")], daemon=True
            ).start()
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline and tunnel.poll() is None:
                try:
                    match = re.search(r"https://[A-Za-z0-9.-]+\.(?:lhr\.life|lhr\.pro|localhost\.run)", lines.get(timeout=0.5))
                    if match:
                        public_url = match.group(0)
                        break
                except queue.Empty:
                    pass
        except Exception:
            public_url = None

    if ready and public_url:
        app_url = f"{public_url}/?access_token={token}"
        # Render the actual web app inside the notebook so it can be used in place.
        # The backend is still served by the worker process and reached through its
        # authenticated public tunnel; the iframe keeps the full existing UI intact.
        panel = f'''<section style="font-family:system-ui,sans-serif;width:100%;">
          <iframe title="NovelReader" src="{app_url}" style="display:block;width:100%;height:min(88vh,1100px);min-height:720px;border:1px solid #263b34;border-radius:16px;background:#0b1110;" allow="clipboard-read; clipboard-write" loading="eager"></iframe>
          <p style="margin:10px 4px 0;color:#63736c;font:13px system-ui">Giữ phiên Molab mở trong khi dịch hoặc tạo audio. Đường dẫn chứa access token, không chia sẻ công khai.</p>
        </section>'''
        view = mo.Html(panel)
    elif ready:
        view = mo.callout(mo.md("Máy chủ đang chạy tại `http://127.0.0.1:8000`, nhưng Molab chưa cấp tunnel công khai. Dùng chức năng port forwarding của Molab cho cổng **8000** để mở giao diện."), kind="warn")
    else:
        error = server_log.read_text(errors="replace")[-4000:] if server_log.exists() else "Không có nhật ký máy chủ."
        view = mo.vstack([mo.callout(mo.md("Không khởi động được máy chủ."), kind="danger"), mo.ui.code_editor(value=error, language="text", disabled=True, min_height=180)])
    mo.output.replace(view)
    return


if __name__ == "__main__":
    app.run()
