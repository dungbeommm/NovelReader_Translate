# /// script
# dependencies = [
#     "marimo>=0.23.3",
# ]
# ///
"""NovelReader running as an interactive, notebook-native Molab app."""

import marimo

__generated_with = "0.25.1"
app = marimo.App(width="full", app_title="NovelReader · Molab")


@app.cell
def _intro():
    import marimo as mo

    engine = mo.ui.dropdown(
        options={"Piper · nhẹ": "piper", "VieNeu v3": "vieneu"},
        value="Piper · nhẹ",
        label="Bộ đọc",
    )
    piper_voice = mo.ui.dropdown(
        options=["ngochuyennew", "banmai", "calmwoman3688", "adam1", "chieuthanh", "deepman3909"],
        value="ngochuyennew",
        label="Giọng Piper",
    )
    vieneu_voice = mo.ui.dropdown(
        options=["truc_ly", "minh_quan_pro", "adam_bua", "mai_anh", "thuy_dung", "ngoc_huyen"],
        value="truc_ly",
        label="Giọng VieNeu",
    )
    model = mo.ui.dropdown(
        options={
            "HachimiMT-60-QT · Cổ trang": "HachimiMT-60-QT",
            "HachimiMT-60 · Hiện đại": "HachimiMT-60",
            "HachimiMT-40-QT · Nhanh": "HachimiMT-40-QT",
            "HachimiMT-30 · Nhẹ": "HachimiMT-30",
            "MoxhiMT-60": "MoxhiMT-60",
            "MoxhiMT-30": "MoxhiMT-30",
            "HirashibaMT-Medium": "HirashibaMT-Medium",
            "HirashibaMT-Tiny · Siêu tốc": "HirashibaMT-Tiny",
        },
        value="HachimiMT-60-QT",
        label="Mô hình dịch",
    )
    return engine, mo, model, piper_voice, vieneu_voice


@app.cell
def _prepare():
    import os
    import subprocess
    import sys
    import shutil
    import urllib.request
    import zipfile
    from pathlib import Path

    cwd = Path.cwd().resolve()
    if (cwd / "main.py").is_file() and (cwd / "web").is_dir():
        root = cwd
    else:
        root = cwd / "NovelReader_Translate"
        root.mkdir(parents=True, exist_ok=True)
        archive = cwd / "novelreader-source.zip"
        request = urllib.request.Request(
            "https://github.com/dungbeommm/NovelReader_Translate/archive/refs/heads/main.zip",
            headers={"User-Agent": "NovelReader-Molab"},
        )
        with urllib.request.urlopen(request, timeout=90) as response, archive.open("wb") as output:
            shutil.copyfileobj(response, output)
        with zipfile.ZipFile(archive) as bundle:
            prefix = bundle.namelist()[0].split("/")[0] + "/"
            for item in bundle.infolist():
                if item.is_dir() or not item.filename.startswith(prefix):
                    continue
                relative = item.filename[len(prefix):]
                if relative:
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
    device_note = f"**Máy:** {gpu_name} · **VRAM:** {int(vram_mb) / 1024:.1f} GB"
    return device_note, gpu_line, os, root, subprocess, sys


@app.cell
def _install(
    engine,
    gpu_line,
    os,
    piper_voice,
    root,
    subprocess,
    sys,
    vieneu_voice,
):
    import hashlib

    worker_dir = root / ".worker-venv"
    python = worker_dir / "bin/python"
    if not python.exists():
        subprocess.run([sys.executable, "-m", "venv", "--system-site-packages", str(worker_dir)], check=True)
    requirements = [root / "requirements-worker.txt"]
    requirements.append(root / ("requirements-vieneu.txt" if engine.value == "vieneu" else "tts/requirements.txt"))
    signature = hashlib.sha256(
        (engine.value + "|" + "|".join(hashlib.sha256(path.read_bytes()).hexdigest() for path in requirements)).encode()
    ).hexdigest()
    marker = worker_dir / ".molab-requirements"
    if not marker.is_file() or marker.read_text(encoding="utf-8") != signature:
        for requirement in requirements:
            subprocess.run([str(python), "-m", "pip", "install", "-q", "-r", str(requirement)], check=True)
        if gpu_line and engine.value == "piper":
            subprocess.run([str(python), "-m", "pip", "uninstall", "-y", "onnxruntime"], check=False, stdout=subprocess.DEVNULL)
            subprocess.run(
                [str(python), "-m", "pip", "install", "-q", "onnxruntime-gpu>=1.20,<2", "nvidia-cudnn-cu12", "nvidia-cublas-cu12"],
                check=True,
            )
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
        "ALLOW_TUNNEL": "0",
        "PYTHONUNBUFFERED": "1",
    })
    voice_args = [str(python), str(root / "scripts/setup_tts.py"), "--engine", engine.value, "--voice", voice]
    if engine.value == "vieneu":
        voice_args += ["--device", os.environ["VIENEU_DEVICE"], "--install", "--preload"]
    subprocess.run(voice_args, cwd=root, check=True)
    return (python,)


@app.cell
def _launch(mo, os, python, root, subprocess):
    import json
    import secrets
    import time
    import urllib.error
    import urllib.request

    token = os.environ.get("NOVEL_WEB_ACCESS_TOKEN") or secrets.token_urlsafe(32)
    os.environ["NOVEL_WEB_ACCESS_TOKEN"] = token
    os.environ["ALLOW_TUNNEL"] = "0"
    server_log = root / "data/logs/molab-server.log"
    _handle = server_log.open("a", encoding="utf-8", buffering=1)
    try:
        probe = urllib.request.Request("http://127.0.0.1:8000/api/state", headers={"X-Novel-Access": token})
        with urllib.request.urlopen(probe, timeout=2):
            running = True
    except Exception:
        running = False
    if not running:
        subprocess.Popen(
            [str(python), "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000", "--workers", "1", "--no-access-log"],
            cwd=root, env=os.environ.copy(), stdout=_handle, stderr=subprocess.STDOUT,
        )
        for _ in range(60):
            try:
                probe = urllib.request.Request("http://127.0.0.1:8000/api/state", headers={"X-Novel-Access": token})
                with urllib.request.urlopen(probe, timeout=2):
                    break
            except Exception:
                time.sleep(1)

    def api_request(path, method="GET", payload=None, upload=None):
        headers = {"X-Novel-Access": token, "X-App-Request": "novel-translator"}
        body = None
        if upload is not None:
            filename, contents = upload
            boundary = "----NovelReaderMolabBoundary" + secrets.token_hex(8)
            safe_name = filename.replace('"', "_").replace("\\", "_").replace("\r", "_").replace("\n", "_")
            body = (
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{safe_name}\"\r\n"
                "Content-Type: application/octet-stream\r\n\r\n"
            ).encode() + contents + f"\r\n--{boundary}--\r\n".encode()
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        elif payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request("http://127.0.0.1:8000" + path, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = response.read()
                content_type = response.headers.get("Content-Type", "")
                return data if "json" not in content_type else json.loads(data.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            try:
                detail = json.loads(detail).get("detail", detail)
            except Exception:
                pass
            raise RuntimeError(f"Lỗi máy chủ ({exc.code}): {detail}") from exc

    mo.output.replace(mo.callout(mo.md("✅ Backend đã chạy. Giao diện dịch truyện nằm ngay trong notebook bên dưới; không cần tunnel hoặc mở tab khác."), kind="success"))
    return (api_request,)


@app.cell
def _controls(engine, mo, model, piper_voice, vieneu_voice):
    book_file = mo.ui.file(filetypes=[".txt", ".epub"], kind="area", label="Kéo thả hoặc chọn truyện TXT/EPUB", max_size=50 * 1024 * 1024)
    upload_button = mo.ui.run_button(label="Nạp truyện", kind="neutral")
    audio_enabled = mo.ui.checkbox(value=True, label="Tự động tạo audio sau khi dịch mỗi chương")
    start_button = mo.ui.run_button(label="Dịch truyện", kind="success", full_width=True)
    pause_button = mo.ui.run_button(label="Tạm dừng", kind="neutral")
    resume_button = mo.ui.run_button(label="Tiếp tục", kind="neutral")
    stop_button = mo.ui.run_button(label="Dừng", kind="danger")
    export_txt_button = mo.ui.run_button(label="Tải bản dịch TXT")
    export_epub_button = mo.ui.run_button(label="Tải bản dịch EPUB")
    export_audio_button = mo.ui.run_button(label="Tải gói audio ZIP")
    refresh = mo.ui.refresh(default_interval="5s")
    controls = mo.vstack([
        mo.md("# NovelReader\n\nNạp truyện **TXT/EPUB**, dịch sang tiếng Việt và tạo audio ngay trong Molab."),
        mo.hstack([engine, model], widths="equal"),
        mo.hstack([piper_voice, vieneu_voice], widths="equal"),
        book_file,
        upload_button,
        audio_enabled,
        start_button,
        mo.hstack([pause_button, resume_button, stop_button]),
        mo.hstack([export_txt_button, export_epub_button, export_audio_button]),
        mo.md("**Tiến độ tự cập nhật mỗi 5 giây**"),
        refresh,
    ], gap=1.1)
    mo.output.replace(controls)
    return (
        audio_enabled,
        book_file,
        export_audio_button,
        export_epub_button,
        export_txt_button,
        pause_button,
        refresh,
        resume_button,
        start_button,
        stop_button,
        upload_button,
    )


@app.cell
def _actions(
    api_request,
    audio_enabled,
    book_file,
    engine,
    export_audio_button,
    export_epub_button,
    export_txt_button,
    mo,
    model,
    pause_button,
    piper_voice,
    resume_button,
    start_button,
    stop_button,
    upload_button,
    vieneu_voice,
):
    try:
        if upload_button.value:
            if not book_file.value:
                action_message = "Chọn tệp TXT hoặc EPUB trước khi nạp."
            else:
                file = book_file.value[0]
                uploaded = api_request("/api/upload", method="POST", upload=(file.name, file.contents))
                book_title = (uploaded.get("book") or {}).get("title") or file.name
                action_message = f"Đã nạp **{book_title}** · {len(uploaded.get('chapters', []))} chương."
        elif start_button.value:
            voice = vieneu_voice.value if engine.value == "vieneu" else piper_voice.value
            result = api_request("/api/translate/start", method="POST", payload={
                "engine": model.value, "backend": "ct2", "generate_audio": audio_enabled.value,
                "audio_pipeline": audio_enabled.value, "tts_engine": engine.value, "voice_id": voice,
                "reset": False, "beam_size": 2, "chunk_mode": "sentence",
            })
            action_message = result.get("message") or "Đã bắt đầu dịch."
        elif pause_button.value:
            api_request("/api/translate/pause", method="POST")
            action_message = "Đã gửi lệnh tạm dừng."
        elif resume_button.value:
            api_request("/api/translate/resume", method="POST")
            action_message = "Đã gửi lệnh tiếp tục."
        elif stop_button.value:
            api_request("/api/translate/stop", method="POST")
            action_message = "Đã gửi lệnh dừng."
        elif export_txt_button.value:
            download = mo.download(data=api_request("/api/export/txt"), filename="ban-dich.txt", mimetype="text/plain", label="Tải bản dịch TXT")
            action_message = download
        elif export_epub_button.value:
            download = mo.download(data=api_request("/api/export/epub"), filename="ban-dich.epub", mimetype="application/epub+zip", label="Tải bản dịch EPUB")
            action_message = download
        elif export_audio_button.value:
            download = mo.download(data=api_request("/api/export/audio"), filename="audio.zip", mimetype="application/zip", label="Tải gói audio ZIP")
            action_message = download
        else:
            action_message = None
    except Exception as exc:
        action_message = f"⚠️ {exc}"
    if action_message:
        mo.output.replace(action_message if not isinstance(action_message, str) else mo.md(action_message))
    return


@app.cell
def _dashboard(api_request, device_note, mo, refresh):
    import html

    refresh.value
    try:
        state = api_request("/api/state")
        chapters = api_request("/api/chapters")
        book = state.get("book") or {}
        progress = state.get("progress") or {}
        status = progress.get("status", "ready")
        message = progress.get("message") or ("Sẵn sàng." if not book else "Đã nạp truyện.")
        done = int(progress.get("done", 0) or 0)
        total = int(progress.get("total", len(chapters)) or len(chapters))
        percent = round(done * 100 / total) if total else 0
        title = html.escape(str(book.get("title") or "Chưa có truyện"))
        summary = mo.md(
            f"### {title}\n\n**Trạng thái:** {html.escape(str(status))} · **Tiến độ:** {percent}% ({done}/{total})\n\n"
            f"{html.escape(str(message))}\n\n{device_note}"
        )
        rows = []
        for chapter in chapters[:40]:
            chapter_title = html.escape(str(chapter.get("title") or f"Chương {chapter.get('position', '')}"))
            chapter_status = html.escape(str(chapter.get("status") or "waiting"))
            rows.append(f"| {chapter.get('position', '')} | {chapter_title} | {chapter_status} |")
        chapter_table = "\n".join(["| # | Chương | Trạng thái |", "|---:|---|---|", *rows]) if rows else "Chưa có chương."
        dashboard = mo.vstack([summary, mo.md("### Mục lục\n\n" + chapter_table)])
    except Exception as exc:
        dashboard = mo.callout(mo.md(f"Chưa lấy được trạng thái: {html.escape(str(exc))}"), kind="warn")
    mo.output.replace(dashboard)
    return


if __name__ == "__main__":
    app.run()
