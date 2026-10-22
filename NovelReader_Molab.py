# /// script

import marimo

__generated_with = "0.25.1"
app = marimo.App(
    width="full",
    app_title="NovelReader AI — Molab Marimo Edition",
)


@app.cell
def shared_imports():
    import datetime
    import hashlib
    import importlib.metadata
    import json
    import os
    import platform
    import queue
    import re
    import secrets
    import shutil
    import site
    import socket
    import sqlite3
    import stat
    import subprocess
    import sys
    import tempfile
    import threading
    import time
    import urllib.request
    import zipfile
    from pathlib import Path
    import marimo as mo

    return (
        Path,
        datetime,
        importlib,
        mo,
        os,
        platform,
        queue,
        re,
        secrets,
        shutil,
        site,
        sqlite3,
        subprocess,
        sys,
        tempfile,
        threading,
        time,
        urllib,
        zipfile,
    )


@app.cell
def intro_ui(mo):
    model_selector = mo.ui.dropdown(
        options={
            "HachimiMT-60-QT (Khuyên dùng - Nhanh, chuẩn)": "HachimiMT-60-QT",
            "HachimiMT-125-QT (Chất lượng cao hơn)": "HachimiMT-125-QT",
            "HachimiMT-Small (Siêu nhẹ)": "HachimiMT-Small",
        },
        value="HachimiMT-60-QT (Khuyên dùng - Nhanh, chuẩn)",
        label="Dịch thuật (Model)",
    )

    voice_selector = mo.ui.dropdown(
        options={
            "Ngọc Huyền (Mới) (ngochuyennew)": "ngochuyennew",
            "Ban Mai (banmai)": "banmai",
            "Calm Woman (calmwoman3688)": "calmwoman3688",
            "Adam (adam1)": "adam1",
            "Chiêu Thành (chieuthanh)": "chieuthanh",
            "Deep Man (deepman3909)": "deepman3909",
            "Kinh Phật (kinhphat)": "kinhphat",
            "Duy Oryx (duyoryx3175)": "duyoryx3175",
            "Lạc Phi (lacphi)": "lacphi",
            "Mai Phương (maiphuong)": "maiphuong",
            "Mạnh Dũng (manhdung)": "manhdung",
            "Minh Quang (minhquang)": "minhquang",
            "Minh Khang (minhkhang)": "minhkhang",
            "Ngọc Huyền (ngochuyen)": "ngochuyen",
            "Ngọc Ngân (ngocngan3701)": "ngocngan3701",
            "Tài An (taian4)": "taian4",
            "Phương Trang (phuongtrang)": "phuongtrang",
            "VAIS 1000 (vais1000medium)": "vais1000medium",
            "Thanh Phương (thanhphuong2)": "thanhphuong2",
            "Thiện Tâm (thientam)": "thientam",
            "Vũ Nga (vunga)": "vunga",
            "Việt Thảo (vietthao3886)": "vietthao3886",
        },
        value="Ngọc Huyền (Mới) (ngochuyennew)",
        label="Giọng đọc TTS",
    )
    tts_engine_selector = mo.ui.dropdown(options={"Piper (nhẹ, ONNX)":"piper","VieNeu v3 Turbo (25 giọng, 48 kHz)":"vieneu"},value="Piper (nhẹ, ONNX)",label="Bộ đọc")
    vieneu_voice_selector = mo.ui.dropdown(options={'Minh Quân Pro (minh_quan_pro)': 'minh_quan_pro', 'Adam bựa (adam_bua)': 'adam_bua', 'Trúc Ly (truc_ly)': 'truc_ly', 'Anh Khôi (anh_khoi)': 'anh_khoi', 'Mai Anh (mai_anh)': 'mai_anh', 'Thùy Dung (thuy_dung)': 'thuy_dung', 'Thiền Tâm Đức (thien_tam_duc)': 'thien_tam_duc', 'Ngọc Huyền (ngoc_huyen)': 'ngoc_huyen', 'Quang Sơn (quang_son)': 'quang_son', 'Ngọc Trân (ngoc_tran)': 'ngoc_tran', 'Minh Đức (minh_duc)': 'minh_duc', 'Phạm Tuyên (pham_tuyen)': 'pham_tuyen', 'Thái Sơn (thai_son)': 'thai_son', 'Xuân Vĩnh (xuan_vinh)': 'xuan_vinh', 'Thanh Bình (thanh_binh)': 'thanh_binh', 'Ngọc Linh (ngoc_linh)': 'ngoc_linh', 'Đoan Trang (doan_trang)': 'doan_trang', 'Thục Đoan (thuc_doan)': 'thuc_doan', 'Minh Triết (minh_triet)': 'minh_triet', 'Mỹ Duyên (my_duyen)': 'my_duyen', 'Quỳnh Anh (quynh_anh)': 'quynh_anh', 'Đức Trí (duc_tri)': 'duc_tri', 'Kim Thanh (kim_thanh)': 'kim_thanh', 'Adam (adam)': 'adam', 'Mạnh Dũng (manh_dung)': 'manh_dung'},value="Trúc Ly (truc_ly)",label="Giọng VieNeu")
    voice_download_mode = mo.ui.dropdown(
        options={"Đầy đủ JSON + model giọng đã chọn (gọn)": "catalog", "Tải toàn bộ JSON + tất cả model ONNX (nhiều GB)": "all"},
        value="Đầy đủ JSON + model giọng đã chọn (gọn)",
        label="Tải giọng đọc",
    )

    tunnel_selector = mo.ui.dropdown(
        options={
            "Tự động (Cloudflare HTTP/2 + Pinggy + Localhost.run)": "auto",
            "Cloudflare HTTPS Tunnel (Port 443)": "cloudflare",
            "Pinggy SSH Tunnel (Port 443)": "pinggy",
            "Localhost.run SSH Tunnel (Port 80)": "localhost_run",
        },
        value="Tự động (Cloudflare HTTP/2 + Pinggy + Localhost.run)",
        label="Chế độ Tunnel Web",
    )

    intro_markdown = mo.md(
        r"""
        # 🚀 NovelReader AI — Molab Marimo Edition v4.7

        Bản notebook tối ưu hóa riêng cho **Molab Marimo** (reactive environment), tương thích 100% với Google Colab / Kaggle.
        Tự động cấu hình **CTranslate2 CUDA + Piper ONNX hoặc VieNeu v3 Turbo** và hệ thống kết nối **Tunnel HTTP/2 đa tầng**.

        ### 📋 Các bước chạy tự động:
        1. 📥 **Bước 1:** Khởi tạo môi trường & Mã nguồn NovelReader
        2. 📦 **Bước 2:** Cài đặt thư viện + ONNX Runtime GPU + NVIDIA cuDNN 12
        3. ⚙️ **Bước 3:** Cấu hình tham số GPU tối ưu (Batch 96, int8_float16)
        4. 🔍 **Bước 4:** Tải model theo bộ đọc. VieNeu: 25 giọng Vbook + backbone/codec chính thức tải riêng, không chạy GGUF.
        5. 🌐 **Bước 5:** Khởi chạy máy chủ Web + Link truy cập bảo mật
        6. 📦 **Bước 6:** Xem log trực tiếp & Sao lưu kết quả dịch ra file ZIP
        """
    )

    settings_panel = mo.vstack([
        mo.md("### ⚙️ Tuỳ chọn cấu hình khởi động:"),
        mo.hstack([model_selector, voice_selector, tunnel_selector], justify="start", gap=2),
        mo.hstack([tts_engine_selector,vieneu_voice_selector],justify="start",gap=2),
        voice_download_mode,
    ])

    intro_view = mo.vstack([intro_markdown, settings_panel])
    mo.output.replace(intro_view)
    return model_selector, tunnel_selector, voice_selector, voice_download_mode, tts_engine_selector, vieneu_voice_selector


@app.cell
def step1_source_setup(Path, os, shutil, subprocess, sys, urllib, zipfile):
    print("=" * 65)
    print("📥 BƯỚC 1: KHỞI TẠO MÔI TRƯỜNG & MÃ NGUỒN NOVELREADER")
    print("=" * 65)

    base_dir = Path.cwd().resolve()

    if (base_dir / "main.py").is_file() and (base_dir / "translation").is_dir():
        repo_dir = base_dir
        print(f"✅ Đang chạy trực tiếp trong thư mục dự án: {repo_dir}")
    elif (base_dir / "NovelReader_T4_Web" / "main.py").is_file():
        repo_dir = base_dir / "NovelReader_T4_Web"
        print(f"✅ Đã tìm thấy thư mục NovelReader_T4_Web: {repo_dir}")
    else:
        repo_dir = base_dir / "NovelReader_T4_Web"
        repo_dir.mkdir(parents=True, exist_ok=True)
        print("📦 Đang tải mã nguồn NovelReader v4.7 từ kho lưu trữ GitHub...")
        zip_url = "https://github.com/dungbeommm/NovelReader_Translate/archive/refs/heads/main.zip"
        zip_dest = base_dir / "repo_main.zip"
        try:
            req = urllib.request.Request(zip_url, headers={"User-Agent": "NovelReader-Molab"})
            with urllib.request.urlopen(req, timeout=60) as resp, open(zip_dest, "wb") as _zip_out:
                shutil.copyfileobj(resp, _zip_out)
            with zipfile.ZipFile(zip_dest, "r") as z:
                for member in z.infolist():
                    parts = Path(member.filename).parts
                    if len(parts) <= 1:
                        continue
                    rel_parts = parts[1:]
                    if rel_parts[0] in {'data', 'models', 'output_text', 'output_audio'}:
                        continue
                    target = repo_dir / Path(*rel_parts)
                    if member.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with z.open(member) as src, open(target, "wb") as dst:
                            shutil.copyfileobj(src, dst)
            zip_dest.unlink(missing_ok=True)
            print("✅ Đã giải nén mã nguồn NovelReader v4.7 thành công!")
        except Exception as dl_err:
            print(f"⚠️ Lỗi tải ZIP từ GitHub ({dl_err}), thử dùng git clone...")
            subprocess.run(["git", "clone", "--depth", "1", "https://github.com/dungbeommm/NovelReader_Translate.git", str(repo_dir)], check=False)

    repo_path_str = str(repo_dir)
    if repo_path_str not in sys.path:
        sys.path.insert(0, repo_path_str)
    os.chdir(repo_dir)

    for folder_name in (
        "data/logs", "models/translation", "models/voices",
        "output_text", "output_audio", "web/static", "web/templates"
    ):
        (repo_dir / folder_name).mkdir(parents=True, exist_ok=True)

    gpu_detected = False
    gpu_label = "Không phát hiện GPU (Chế độ CPU)"
    vram_display = "0 GB"
    try:
        smi_proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10
        )
        if smi_proc.returncode == 0 and smi_proc.stdout.strip():
            smi_parts = [p.strip() for p in smi_proc.stdout.strip().split(",", 1)]
            gpu_label = smi_parts[0]
            if len(smi_parts) > 1:
                mem_gb = float(smi_parts[1]) / 1024.0
                vram_display = f"{mem_gb:.1f} GB"
            gpu_detected = True
            print(f"✅ GPU Phát hiện: {gpu_label} (VRAM: {vram_display})")
        else:
            print("⚠️ Runtime chưa gắn GPU NVIDIA (đang chạy CPU).")
    except Exception:
        print("⚠️ Không thể gọi nvidia-smi.")

    return base_dir, gpu_detected, repo_dir
@app.cell
def step2_install_libraries(
    gpu_detected,
    importlib,
    repo_dir,
    subprocess,
    sys,
):
    print("=" * 65)
    print("📦 BƯỚC 2: CÀI ĐẶT THƯ VIỆN & CẤU HÌNH PIPER CUDA")
    print("=" * 65)

    pip_executable = [sys.executable, "-m", "pip"]

    needed_packages = ["fastapi", "uvicorn", "ctranslate2", "piper-tts", "psutil"]
    if gpu_detected:
        needed_packages.extend(["onnxruntime-gpu", "nvidia-cudnn-cu12", "nvidia-cublas-cu12"])

    missing_packages = []
    for package_name in needed_packages:
        try:
            importlib.metadata.version(package_name)
        except importlib.metadata.PackageNotFoundError:
            missing_packages.append(package_name)

    if missing_packages:
        print(f"📦 Đang bổ sung các thư viện: {', '.join(missing_packages)}...")
        req_path = repo_dir / "requirements.txt"
        if req_path.is_file():
            subprocess.run(pip_executable + ["install", "-q", "-r", str(req_path)], check=False)

        if gpu_detected:
            print("🔧 Cấu hình bộ tăng tốc ONNX Runtime GPU & NVIDIA cuDNN 12...")
            subprocess.run(
                pip_executable + ["uninstall", "-y", "onnxruntime", "onnxruntime-gpu"],
                check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            subprocess.run(
                pip_executable + [
                    "install", "-q", "--upgrade",
                    "onnxruntime-gpu>=1.20,<2",
                    "nvidia-cudnn-cu12",
                    "nvidia-cublas-cu12",
                    "nvidia-cuda-runtime-cu12>=12,<13",
                    "ctranslate2>=4.5,<5"
                ],
                check=False
            )
        print("   ✅ Cài đặt thư viện Python hoàn tất.")
    else:
        print("   ✅ Toàn bộ thư viện cốt lõi đã sẵn sàng.")

    if sys.platform.startswith("linux"):
        print("📦 Kiểm tra tiện ích âm thanh hệ thống (ffmpeg, espeak-ng)...")
        try:
            apt_run = subprocess.run(
                ["apt-get", "install", "-y", "-qq", "ffmpeg", "espeak-ng"],
                capture_output=True, text=True, timeout=60
            )
            if apt_run.returncode != 0:
                subprocess.run(["apt-get", "update", "-qq"], capture_output=True, text=True, timeout=60)
                subprocess.run(
                    ["apt-get", "install", "-y", "-qq", "ffmpeg", "espeak-ng"],
                    capture_output=True, text=True, timeout=120
                )
            print("   ✅ ffmpeg & espeak-ng đã sẵn sàng.")
        except Exception as exc:
            print(f"   ⚠️ apt-get bỏ qua: {exc}")

    step2_ready = True
    return (step2_ready,)


@app.cell
def step3_configure_env(Path, gpu_detected, os, repo_dir, site, step2_ready, tts_engine_selector, voice_selector, vieneu_voice_selector):
    assert step2_ready
    print("=" * 65)
    print("⚙️ BƯỚC 3: THIẾT LẬP BIẾN MÔI TRƯỜNG & LIÊN KẾT CUDA")
    print("=" * 65)

    env_map = {
        "HACHIMIMT_WEB_BATCH_SIZE": "96",
        "HACHIMIMT_BATCH_SIZE": "96",
        "HACHIMIMT_CT2_BATCH_TYPE": "tokens",
        "HACHIMIMT_CT2_WINDOW_MULTIPLIER": "16",
        "HACHIMIMT_INTER_THREADS": "1",
        "HACHIMIMT_COMPUTE_TYPE": "int8_float16" if gpu_detected else "default",
        "HACHIMIMT_FORCE_CT2_CUDA": "1" if gpu_detected else "0",
        "HACHIMIMT_GPU_INDICES": "0",
        "HACHIMIMT_AUTO_ALL_GPUS": "0",
        "HACHIMIMT_TOKENIZE_WORKERS": str(min(os.cpu_count() or 2, 4)),
        "NOVEL_TTS_ENGINE": tts_engine_selector.value or "piper",
        "NOVEL_TTS_VOICE": (vieneu_voice_selector.value or "truc_ly") if tts_engine_selector.value=="vieneu" else (voice_selector.value or "ngochuyennew"),
        "VIENEU_DEVICE": "cuda" if gpu_detected else "cpu",
        "VIENEU_MODEL_DIR": str(repo_dir/"models/vieneu"),
        "PIPER_DEVICE": "cuda" if gpu_detected else "cpu",
        "PIPER_REQUIRE_CUDA": "1" if gpu_detected else "0",
        "PIPER_CUDNN_ALGO": "DEFAULT",
        "AUDIO_WORKERS": "2" if gpu_detected else "1",
        "TTS_CHUNK_MAX_CHARS": "4000" if gpu_detected else "2500",
        "ALLOWED_HOSTS": "*",
        "ALLOW_TUNNEL": "1",
        "COLAB_GPU": "1" if gpu_detected else "0",
        "NOVEL_DATA": str(repo_dir / "data"),
        "NOVEL_MODELS": str(repo_dir / "models/translation"),
        "TTS_VOICE_DIR": str(repo_dir / "models/voices"),
        "NOVEL_OUTPUT_TEXT": str(repo_dir / "output_text"),
        "NOVEL_OUTPUT_AUDIO": str(repo_dir / "output_audio"),
        "PYTHONUNBUFFERED": "1",
        "NOVEL_DRIVE_BACKEND": "api",
        "NOVEL_COLAB_DRIVE_BRIDGE": "0",
        "NOVEL_DRIVE_CREDENTIAL_DIR": "/tmp/novelreader-drive",
    }
    os.environ.update(env_map)

    discovered_nvidia_libs = []
    for site_directory in site.getsitepackages():
        nv_dir = Path(site_directory) / "nvidia"
        if nv_dir.is_dir():
            discovered_nvidia_libs.extend(str(p) for p in nv_dir.glob("*/lib") if p.is_dir())

    original_ld = os.environ.get("LD_LIBRARY_PATH", "")
    os.environ["LD_LIBRARY_PATH"] = ":".join(
        discovered_nvidia_libs + ([original_ld] if original_ld else [])
    )

    print(f"   Batch Size: {env_map['HACHIMIMT_BATCH_SIZE']}")
    print(f"   Compute Type: {env_map['HACHIMIMT_COMPUTE_TYPE']}")
    print(f"   Piper Device: {env_map['PIPER_DEVICE']}")
    print(f"   NVIDIA Dynamic Libs: Đã nạp {len(discovered_nvidia_libs)} thư mục")
    print("✅ Cấu hình môi trường GPU hoàn tất.")

    step3_ready = True
    return (step3_ready,)


@app.cell
def step4_models_and_smoke_test(
    gpu_detected,
    model_selector,
    os,
    repo_dir,
    shutil,
    subprocess,
    sys,
    urllib,
    voice_selector,
    voice_download_mode,
    step3_ready,
    tts_engine_selector,
    vieneu_voice_selector,
):
    assert step3_ready
    print("=" * 65)
    print("🔍 BƯỚC 4: TẢI MODEL GIỌNG ĐỌC & KIỂM TRA GPU CUDA")
    print("=" * 65)

    selected_tts=os.environ["NOVEL_TTS_ENGINE"]
    chosen_voice=os.environ["NOVEL_TTS_VOICE"]
    tts_command=[sys.executable,str(repo_dir/"scripts/setup_tts.py"),"--engine",selected_tts,"--voice",chosen_voice]
    if selected_tts=="vieneu":
        tts_command += ["--device",os.environ["VIENEU_DEVICE"],"--install","--preload"]
    elif voice_download_mode.value=="all":
        tts_command += ["--all"]
    subprocess.run(tts_command,cwd=str(repo_dir),env=dict(os.environ),check=True)

    if gpu_detected:
        try:
            clean_env = dict(os.environ)
            ort_test = subprocess.run(
                [
                    sys.executable, "-c",
                    "import onnxruntime as ort; "
                    "p = ort.get_available_providers(); "
                    "print('PROVIDERS=' + ','.join(p)); "
                    "print('CUDA_OK=' + str('CUDAExecutionProvider' in p))"
                ],
                capture_output=True, text=True, timeout=60, env=clean_env
            )
            if "CUDA_OK=True" in ort_test.stdout:
                print("🎉 ORT có CUDAExecutionProvider (chưa chứng minh inference).")
            else:
                print("⚠️ CUDAExecutionProvider chưa xuất hiện trong phiên kiểm tra.")
        except Exception as ort_err:
            print(f"⚠️ Kiểm tra ORT: {ort_err}")

        chosen_model = model_selector.value or "HachimiMT-60-QT"
        print(f"🚀 Chạy GPU smoke-test với model '{chosen_model}'...")
        try:
            smoke_test = subprocess.run(
                [
                    sys.executable, "scripts/check_gpu.py",
                    "--model", chosen_model,
                    "--voice", chosen_voice, "--tts-engine", selected_tts
                ],
                capture_output=True, text=True, timeout=300,
                cwd=str(repo_dir), env=dict(os.environ)
            )
            if smoke_test.returncode == 0:
                print("   ✅ GPU Smoke Test THÀNH CÔNG RỰC RỠ!")
            else:
                print("   ⚠️ GPU Smoke Test trả về thông tin:")
                print("   " + (smoke_test.stderr or smoke_test.stdout)[-400:].replace("\n", "\n   "))
        except Exception as smoke_err:
            print(f"   ⚠️ Bỏ qua smoke test: {smoke_err}")
    else:
        print("ℹ️ Đang chạy chế độ CPU, bỏ qua kiểm tra CUDA.")

    step4_ready = True
    return (step4_ready,)


@app.cell
def step5_launch_server(
    step4_ready,
    Path,
    base_dir,
    mo,
    os,
    platform,
    queue,
    re,
    repo_dir,
    secrets,
    subprocess,
    sys,
    threading,
    time,
    tunnel_selector,
    urllib,
):
    assert step4_ready
    print("=" * 65)
    print("🌐 BƯỚC 5: KHỞI CHẠY MÁY CHỦ WEB & HỆ THỐNG TUNNEL ĐA TẦNG")
    print("=" * 65)

    for old_cmd in [
        ["pkill", "-f", "uvicorn.*main:app"],
        ["pkill", "-f", "cloudflared"],
        ["pkill", "-f", "a.pinggy.io"],
        ["pkill", "-f", "nokey@localhost.run"],
    ]:
        subprocess.run(old_cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.0)

    try:
        ssh_dir = Path.home() / ".ssh"
        ssh_key = ssh_dir / "id_ed25519"
        if not ssh_key.is_file():
            ssh_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            subprocess.run(["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(ssh_key)], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

    token_str = secrets.token_urlsafe(32)
    session_str = secrets.token_hex(16)
    os.environ["NOVEL_WEB_ACCESS_TOKEN"] = token_str
    os.environ["NOVEL_EXPORT_SESSION_ID"] = session_str
    os.environ["ALLOW_TUNNEL"] = "1"
    os.environ["ALLOWED_HOSTS"] = "*"

    log_server = repo_dir / "data/logs/colab-server.log"
    log_tunnel = repo_dir / "data/logs/colab-tunnel.log"

    if log_tunnel.is_file():
        try:
            log_tunnel.unlink()
        except Exception:
            pass

    server_out = open(str(log_server), "a", buffering=1, encoding="utf-8", errors="replace")

    print("🚀 Đang khởi động máy chủ Uvicorn trên 127.0.0.1:8000...")
    server_process = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "main:app",
            "--host", "127.0.0.1", "--port", "8000",
            "--workers", "1", "--no-access-log",
            "--timeout-graceful-shutdown", "120"
        ],
        cwd=str(repo_dir),
        stdout=server_out,
        stderr=subprocess.STDOUT,
        env=dict(os.environ)
    )

    server_ready = False
    for attempt in range(120):
        if server_process.poll() is not None:
            print("❌ Máy chủ đã dừng bất thường!")
            print(log_server.read_text(errors="replace")[-1000:])
            break
        try:
            req_check = urllib.request.Request(
                "http://127.0.0.1:8000/api/state",
                headers={"X-Novel-Access": token_str}
            )
            with urllib.request.urlopen(req_check, timeout=2) as state_resp:
                if state_resp.status == 200:
                    server_ready = True
                    break
        except Exception:
            time.sleep(1)

    if server_ready:
        print("   ✅ Máy chủ Uvicorn đã sẵn sàng hoạt động!")
    else:
        print("   ⚠️ Hết thời gian chờ phản hồi từ 127.0.0.1:8000.")

    def _read_stream_url(proc, pattern, timeout=25):
        if proc is None or proc.stdout is None:
            return None
        line_q = queue.Queue()
        def _enqueue():
            try:
                for line in iter(proc.stdout.readline, ""):
                    if line:
                        line_q.put(line)
                    else:
                        break
            except Exception:
                pass
            finally:
                line_q.put(None)
        reader_t = threading.Thread(target=_enqueue, daemon=True)
        reader_t.start()
        start_t = time.time()
        while time.time() - start_t < timeout:
            rem = max(0.1, timeout - (time.time() - start_t))
            try:
                item = line_q.get(timeout=min(0.5, rem))
                if item is None:
                    break
                clean_item = re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\([a-zA-Z]|\x1b\][^\a\x1b]*(?:\a|\x1b\\)", "", item)
                m = re.search(pattern, clean_item)
                if m:
                    return (m.group(1) if m.groups() else m.group(0)).rstrip("/.")
            except queue.Empty:
                if proc.poll() is not None:
                    break
        return None

    pinggy_url = None
    cloudflare_url = None
    lhr_url = None
    tunnel_mode = getattr(tunnel_selector, "value", "auto") or "auto"

    if tunnel_mode in ("auto", "pinggy"):
        try:
            print("🌐 Đang kết nối Pinggy HTTPS Tunnel (Port 443)...")
            pinggy_proc = subprocess.Popen(
                [
                    "ssh", "-p", "443",
                    "-o", "StrictHostKeyChecking=no",
                    "-o", "UserKnownHostsFile=/dev/null",
                    "-o", "LogLevel=ERROR",
                    "-o", "ConnectTimeout=15",
                    "-o", "ServerAliveInterval=30",
                    "-R", "0:localhost:8000", "a.pinggy.io"
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env={**os.environ, "TERM": "dumb"}
            )
            pinggy_url = _read_stream_url(
                pinggy_proc,
                r"https://[a-zA-Z0-9.-]+\.pinggy[a-zA-Z0-9.-]*\.link",
                timeout=25
            )
            if pinggy_url:
                print(f"   ✅ Pinggy Tunnel sẵn sàng: {pinggy_url}")
            else:
                try:
                    pinggy_proc.terminate()
                except Exception:
                    pass
        except Exception as pinggy_err:
            print(f"   ⚠️ Lỗi kết nối Pinggy: {pinggy_err}")

    cf_executable = None
    if tunnel_mode in ("auto", "cloudflare"):
        cf_executable = base_dir / "cloudflared"
        if sys.platform.startswith("linux") and not cf_executable.is_file():
            try:
                cf_arch = "arm64" if "arm" in platform.machine().lower() or "aarch64" in platform.machine().lower() else "amd64"
                urllib.request.urlretrieve(
                    f"https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-{cf_arch}",
                    cf_executable
                )
                cf_executable.chmod(0o755)
            except Exception as cf_dl_err:
                print(f"   ⚠️ Không tải được cloudflared: {cf_dl_err}")

    if cf_executable is not None and cf_executable.is_file():
        print("🌐 Đang kết nối Cloudflare Tunnel (HTTP/2)...")
        cf_proc = subprocess.Popen(
            [
                str(cf_executable), "tunnel",
                "--protocol", "http2",
                "--url", "http://127.0.0.1:8000",
                "--logfile", str(log_tunnel),
                "--loglevel", "info"
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        for _ in range(35):
            if cf_proc.poll() is not None:
                break
            if log_tunnel.is_file():
                log_text = log_tunnel.read_text(errors="replace")
                cf_match = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", log_text)
                if cf_match:
                    cloudflare_url = cf_match.group(0).rstrip("/.")
                    print(f"   ✅ Cloudflare Tunnel sẵn sàng: {cloudflare_url}")
                    break
            time.sleep(1)
        if not cloudflare_url and cf_proc.poll() is None:
            try:
                cf_proc.terminate()
            except Exception:
                pass

    if (tunnel_mode == "localhost_run") or (tunnel_mode == "auto" and not pinggy_url and not cloudflare_url):
        print("🌐 Đang kết nối Localhost.run...")
        try:
            lhr_proc = subprocess.Popen(
                [
                    "ssh",
                    "-o", "StrictHostKeyChecking=no",
                    "-o", "UserKnownHostsFile=/dev/null",
                    "-o", "LogLevel=ERROR",
                    "-o", "ConnectTimeout=15",
                    "-o", "ServerAliveInterval=30",
                    "-R", "80:localhost:8000", "nokey@localhost.run"
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env={**os.environ, "TERM": "dumb"}
            )
            lhr_url = _read_stream_url(
                lhr_proc,
                r"https://[a-zA-Z0-9.-]+\.(?:lhr\.life|lhr\.pro|localhost\.run)",
                timeout=25
            )
            if lhr_url:
                print(f"   ✅ Localhost.run sẵn sàng: {lhr_url}")
            else:
                try:
                    lhr_proc.terminate()
                except Exception:
                    pass
        except Exception as lhr_err:
            print(f"   ⚠️ Lỗi kết nối Localhost.run: {lhr_err}")

    active_links = []
    if pinggy_url:
        p_clean = pinggy_url.rstrip("/")
        active_links.append(("Pinggy HTTPS (Khuyên dùng - 100% không lỗi 1033)", f"{p_clean}/?access_token={token_str}"))
    if cloudflare_url:
        cf_clean = cloudflare_url.rstrip("/")
        active_links.append(("Cloudflare Tunnel", f"{cf_clean}/?access_token={token_str}"))
    if lhr_url:
        lhr_clean = lhr_url.rstrip("/")
        active_links.append(("Localhost.run", f"{lhr_clean}/?access_token={token_str}"))

    if active_links and server_ready:
        primary_title, primary_link = active_links[0]
        print("\n🎉 NOVELREADER ĐÃ KHỞI CHẠY THÀNH CÔNG!")
        for title, link in active_links:
            print(f"🌐 {title}: {link}")
        print(f"🔑 Token: {token_str}\n")

        other_links_md = ""
        if len(active_links) > 1:
            other_lines = [f"- **{t}:** [{lnk}]({lnk})" for t, lnk in active_links]
            other_links_md = "#### 🌐 Danh sách các cổng kết nối:\n" + "\n".join(other_lines) + "\n\n*(Nếu Cloudflare báo lỗi Error 1033 do nghẽn DNS, bạn chỉ cần bấm vào link **Pinggy** phía trên để vào ngay)*\n\n"

        status_view = mo.callout(
            mo.vstack([
                mo.md("### 🎉 NovelReader Đang Hoạt Động!"),
                mo.md(
                    f"👉 **[BẤM VÀO ĐÂY ĐỂ MỞ ỨNG DỤNG ({primary_title})]({primary_link})**  \n\n"
                    f"{other_links_md}"
                    f"**🔑 Mã Access Token bảo mật:** `{token_str}`  \n"
                    f"> ⚠️ **Lưu ý:** Giữ tab trình duyệt Molab này mở trong suốt quá trình dịch truyện."
                ),
            ]),
            kind="success"
        )
    elif server_ready:
        localhost_link = f"http://127.0.0.1:8000/?access_token={token_str}"
        print(f"✅ Server đang chạy cục bộ: {localhost_link}")
        status_view = mo.callout(
            mo.vstack([
                mo.md("### ⚠️ Server đang chạy nhưng chưa tạo được Tunnel công khai"),
                mo.md(f"Bạn có thể kết nối port forwarding 8000: `{localhost_link}`"),
                mo.md(f"**🔑 Access Token:** `{token_str}`")
            ]),
            kind="warn"
        )
    else:
        status_view = mo.callout(
            mo.md("### ❌ Không thể khởi động Server. Vui lòng kiểm tra log bên dưới."),
            kind="danger"
        )

    mo.output.replace(status_view)
    return log_server, log_tunnel


@app.cell
def step6_controls_ui(mo):
    refresh_logs_btn = mo.ui.run_button(label="🔄 Làm mới nhật ký Server")
    stop_server_btn = mo.ui.run_button(label="🛑 Dừng toàn bộ Server", kind="danger")
    return refresh_logs_btn, stop_server_btn


@app.cell
def step6_logs_view(
    log_server,
    log_tunnel,
    mo,
    refresh_logs_btn,
    stop_server_btn,
    subprocess,
):
    if stop_server_btn.value:
        for cmd in [
            ["pkill", "-f", "uvicorn.*main:app"],
            ["pkill", "-f", "cloudflared"],
            ["pkill", "-f", "a.pinggy.io"],
            ["pkill", "-f", "nokey@localhost.run"],
        ]:
            subprocess.run(cmd, check=False)
        action_msg = mo.md("🛑 **Đã gửi tín hiệu dừng máy chủ thành công.**")
    else:
        action_msg = mo.md("")

    _ = refresh_logs_btn.value

    recent_logs = ""
    if log_server.is_file():
        all_lines = log_server.read_text(errors="replace").splitlines()
        recent_logs = "\n".join(all_lines[-35:])
    else:
        recent_logs = "Chưa có log ghi nhận."

    tunnel_logs = ""
    if log_tunnel.is_file():
        t_lines = log_tunnel.read_text(errors="replace").splitlines()
        tunnel_logs = "\n".join(t_lines[-15:])

    control_card = mo.vstack([
        mo.md("## 📊 Nhật ký & Điều khiển Máy chủ"),
        mo.hstack([refresh_logs_btn, stop_server_btn], gap=2),
        action_msg,
        mo.accordion({
            "📄 Nhật ký Server (Uvicorn 35 dòng gần nhất)": mo.ui.code_editor(
                value=recent_logs, language="text", min_height=200, disabled=True
            ),
            "🌐 Nhật ký Tunnel Kết nối": mo.ui.code_editor(
                value=tunnel_logs, language="text", min_height=120, disabled=True
            ),
        })
    ])
    mo.output.replace(control_card)
    return


@app.cell
def step7_backup_ui(mo):
    create_backup_btn = mo.ui.run_button(label="📦 Tạo bản sao lưu toàn bộ (ZIP)", kind="success")
    backup_ui_panel = mo.vstack([
        mo.md("## 💾 Sao lưu & Xuất dữ liệu"),
        mo.md("Dừng job dịch trước (giữ máy chủ Web đang chạy). Nút này tạo checkpoint chuẩn có audio, khôi phục được trong tab Cloud. Muốn lưu Pixeldrain hoặc bỏ audio, dùng Cài đặt → Lưu trữ Đám mây trên Web:"),
        create_backup_btn,
    ])
    mo.output.replace(backup_ui_panel)
    return (create_backup_btn,)


@app.cell
def step7_backup_process(base_dir, create_backup_btn, datetime, mo, os, shutil, urllib):
    if not create_backup_btn.value:
        backup_result_display = mo.md("")
    else:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"NovelReader_Checkpoint_{timestamp}.zip"
        backup_path = base_dir / backup_filename
        try:
            backup_request = urllib.request.Request(
                "http://127.0.0.1:8000/api/checkpoints/download",
                data=b'{"include_audio":true}', method="POST",
                headers={"Content-Type": "application/json", "X-App-Request": "novel-translator",
                         "X-Novel-Access": os.environ.get("NOVEL_WEB_ACCESS_TOKEN", "")},
            )
            with urllib.request.urlopen(backup_request, timeout=1800) as source, backup_path.open("wb") as _backup_out:
                shutil.copyfileobj(source, _backup_out, 1024 * 1024)
            size_mb = backup_path.stat().st_size / (1024 * 1024)
            backup_result_display = mo.vstack([
                mo.md(f"✅ **Checkpoint:** `{backup_filename}` ({size_mb:.1f} MB). Giữ file để khôi phục runtime mới."),
                mo.download(data=lambda: backup_path.read_bytes(), filename=backup_filename,
                            mimetype="application/zip", label="⬇️ Tải checkpoint về máy"),
            ])
        except Exception as backup_error:
            backup_path.unlink(missing_ok=True)
            backup_result_display = mo.md(f"⚠️ Chưa tạo được checkpoint: {backup_error}. Hãy dừng job nhưng giữ server chạy và thử lại.")
    mo.output.replace(backup_result_display)
    return


if __name__ == "__main__":
    app.run()
