# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "marimo>=0.23.3",
#     "fastapi>=0.115,<1",
#     "uvicorn>=0.30,<1",
#     "websockets>=13,<16",
#     "python-multipart>=0.0.18,<1",
#     "pydantic>=2.9,<3",
#     "ebooklib>=0.19,<1",
#     "beautifulsoup4>=4.12,<5",
#     "charset-normalizer>=3.4,<4",
#     "huggingface-hub>=0.34,<3",
#     "ctranslate2>=4.5,<5",
#     "sentencepiece>=0.2,<1",
#     "gradio-client>=1.10,<3",
#     "opencc-python-reimplemented>=0.1.7,<1",
#     "piper-tts>=1.3,<2",
#     "onnxruntime-gpu>=1.20,<2",
#     "transformers>=4.40.0",
#     "sacremoses>=0.1.1",
#     "safetensors>=0.4.0",
#     "google-api-python-client>=2.150,<3",
#     "google-auth-oauthlib>=1.2,<2",
#     "google-auth-httplib2>=0.2,<1",
#     "nvidia-cublas-cu12>=12,<13",
#     "nvidia-cudnn-cu12",
#     "nvidia-cuda-runtime-cu12>=12,<13",
#     "pathvalidate>=3.3,<4",
# ]
# ///

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
        re,
        secrets,
        shutil,
        site,
        sqlite3,
        subprocess,
        sys,
        tempfile,
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
            "ngochuyennew (Nữ miền Bắc - Ngọc Huyền mới)": "ngochuyennew",
            "phuongtrang (Nữ miền Nam - Phương Trang)": "phuongtrang",
            "bacnam (Nam miền Bắc)": "bacnam",
        },
        value="ngochuyennew (Nữ miền Bắc - Ngọc Huyền mới)",
        label="Giọng đọc TTS",
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
        # 🚀 NovelReader AI — Molab Marimo Edition v4.3

        Bản notebook tối ưu hóa riêng cho **Molab Marimo** (reactive environment), tương thích 100% với Google Colab / Kaggle.
        Tự động cấu hình **CTranslate2 CUDA + Piper TTS ORT-GPU cuDNN 12** và hệ thống kết nối **Tunnel HTTP/2 đa tầng**.

        ### 📋 Các bước chạy tự động:
        1. 📥 **Bước 1:** Khởi tạo môi trường & Mã nguồn NovelReader
        2. 📦 **Bước 2:** Cài đặt thư viện + ONNX Runtime GPU + NVIDIA cuDNN 12
        3. ⚙️ **Bước 3:** Cấu hình tham số GPU tối ưu (Batch 96, int8_float16)
        4. 🔍 **Bước 4:** Tải giọng đọc Ngọc Huyền + Kiểm tra CUDA thật
        5. 🌐 **Bước 5:** Khởi chạy máy chủ Web + Link truy cập bảo mật
        6. 📦 **Bước 6:** Xem log trực tiếp & Sao lưu kết quả dịch ra file ZIP
        """
    )

    settings_panel = mo.vstack([
        mo.md("### ⚙️ Tuỳ chọn cấu hình khởi động:"),
        mo.hstack([model_selector, voice_selector, tunnel_selector], justify="start", gap=2),
    ])

    intro_view = mo.vstack([intro_markdown, settings_panel])
    return model_selector, tunnel_selector, voice_selector


@app.cell
def step1_source_setup(Path, os, shutil, subprocess, sys, urllib, zipfile):
    print("=" * 65)
    print("📥 BƯỚC 1: KHỞI TẠO MÔI TRƯỜNG & MÃ NGUỒN NOVELREADER")
    print("=" * 65)

    base_dir = Path.cwd().resolve()

    # Nhận diện nếu notebook đang chạy ngay trong thư mục repository
    if (base_dir / "main.py").is_file() and (base_dir / "translation").is_dir():
        repo_dir = base_dir
        print(f"✅ Đang chạy trực tiếp trong thư mục dự án: {repo_dir}")
    elif (base_dir / "NovelReader_T4_Web" / "main.py").is_file():
        repo_dir = base_dir / "NovelReader_T4_Web"
        print(f"✅ Đã tìm thấy thư mục NovelReader_T4_Web: {repo_dir}")
    else:
        repo_dir = base_dir / "NovelReader_T4_Web"
        archive_path = base_dir / "NovelReader_GPU_notebook.zip"
        source_url = "https://raw.githubusercontent.com/dungbeommm/NovelReader_Translate/main/NovelReader_GPU_notebook.zip"

        if not archive_path.is_file():
            print("📥 Đang tải mã nguồn từ GitHub...")
            print(f"   URL: {source_url}")
            part_path = archive_path.with_suffix(".zip.part")
            try:
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                download_req = urllib.request.Request(source_url, headers=headers)
                with urllib.request.urlopen(download_req, timeout=120) as resp, open(part_path, "wb") as out_file:
                    shutil.copyfileobj(resp, out_file)
                if not zipfile.is_zipfile(part_path):
                    raise RuntimeError("File tải về không phải định dạng ZIP hợp lệ.")
                os.replace(part_path, archive_path)
                print(f"   ✅ Đã tải xong: {archive_path.stat().st_size / (1024 * 1024):.1f} MB")
            except Exception as exc:
                if part_path.exists():
                    part_path.unlink(missing_ok=True)
                raise RuntimeError(f"Lỗi khi tải mã nguồn: {exc}")

        print(f"📦 Đang giải nén mã nguồn vào: {repo_dir}...")
        with zipfile.ZipFile(archive_path) as _zf:
            _zf.extractall(base_dir)
        print("   ✅ Giải nén mã nguồn thành công.")

    # Đưa repo vào sys.path và chuyển thư mục làm việc
    repo_path_str = str(repo_dir)
    if repo_path_str not in sys.path:
        sys.path.insert(0, repo_path_str)
    os.chdir(repo_dir)

    # Đảm bảo các thư mục dữ liệu cần thiết tồn tại
    for folder_name in (
        "data/logs", "models/translation", "models/voices",
        "output_text", "output_audio"
    ):
        (repo_dir / folder_name).mkdir(parents=True, exist_ok=True)

    # Kiểm tra GPU phần cứng với nvidia-smi
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

    step1_ready = True
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

    # Kiểm tra các thư viện bắt buộc
    needed_packages = ["fastapi", "uvicorn", "ctranslate2", "piper-tts"]
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
            # Gỡ bỏ triệt để onnxruntime CPU và đảm bảo bản GPU + cuDNN 12 chuẩn xác
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

    # Cài đặt espeak-ng và ffmpeg (bắt buộc cho Piper TTS và mã hóa audio)
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
    return


@app.cell
def step3_configure_env(Path, gpu_detected, os, repo_dir, site):
    print("=" * 65)
    print("⚙️ BƯỚC 3: THIẾT LẬP BIẾN MÔI TRƯỜNG & LIÊN KẾT CUDA")
    print("=" * 65)

    env_map = {
        # Batch & CTranslate2 tối ưu hóa
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
        # Piper TTS CUDA
        "PIPER_DEVICE": "cuda" if gpu_detected else "cpu",
        "PIPER_REQUIRE_CUDA": "1" if gpu_detected else "0",
        "PIPER_CUDNN_ALGO": "DEFAULT",
        # Server & Tunnel
        "ALLOWED_HOSTS": "*",
        "ALLOW_TUNNEL": "1",
        "COLAB_GPU": "1" if gpu_detected else "0",
        # Đường dẫn thư mục
        "NOVEL_DATA": str(repo_dir / "data"),
        "NOVEL_MODELS": str(repo_dir / "models/translation"),
        "TTS_VOICE_DIR": str(repo_dir / "models/voices"),
        "NOVEL_OUTPUT_TEXT": str(repo_dir / "output_text"),
        "NOVEL_OUTPUT_AUDIO": str(repo_dir / "output_audio"),
        "PYTHONUNBUFFERED": "1",
        # Google Drive API
        "NOVEL_DRIVE_BACKEND": "api",
        "NOVEL_COLAB_DRIVE_BRIDGE": "0",
        "NOVEL_DRIVE_CREDENTIAL_DIR": "/tmp/novelreader-drive",
    }
    os.environ.update(env_map)

    # Thêm toàn bộ các thư mục thư viện nvidia cuDNN / cuBLAS vào LD_LIBRARY_PATH
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
    return


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
):
    print("=" * 65)
    print("🔍 BƯỚC 4: TẢI MODEL GIỌNG ĐỌC & KIỂM TRA GPU CUDA")
    print("=" * 65)

    chosen_voice = voice_selector.value or "ngochuyennew"
    voices_dir = repo_dir / "models/voices"
    voices_dir.mkdir(parents=True, exist_ok=True)
    voice_onnx = voices_dir / f"{chosen_voice}.onnx"
    voice_json = voices_dir / f"{chosen_voice}.onnx.json"

    # 4a. Tải giọng đọc nếu chưa có trên ổ đĩa
    if not (voice_onnx.is_file() and voice_onnx.stat().st_size > 10 * 1024 * 1024 and voice_json.is_file()):
        print(f"⬇️ Đang tải trước giọng đọc '{chosen_voice}'...")
        web_headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

        def _fetch_file(url_list, target_file, min_bytes=100):
            if target_file.is_file() and target_file.stat().st_size >= min_bytes:
                return True
            temp_path = target_file.with_suffix(".dl_tmp")
            for url in url_list:
                try:
                    r = urllib.request.Request(url, headers=web_headers)
                    with urllib.request.urlopen(r, timeout=60) as resp, open(temp_path, "wb") as f_out:
                        shutil.copyfileobj(resp, f_out)
                    if temp_path.stat().st_size >= min_bytes:
                        os.replace(temp_path, target_file)
                        return True
                except Exception:
                    pass
                finally:
                    if temp_path.exists():
                        temp_path.unlink(missing_ok=True)
            return False

        json_sources = [
            f"https://cdn.ainovelreader.com/tts_model/{chosen_voice}.onnx.json",
            f"https://raw.githubusercontent.com/dungbeommm/NovelReader_voices/main/voices/low/low-{chosen_voice}/{chosen_voice}.onnx.json",
        ]
        onnx_sources = [
            f"https://cdn.ainovelreader.com/tts_model/{chosen_voice}.onnx",
            f"https://raw.githubusercontent.com/dungbeommm/NovelReader_voices/main/voices/low/low-{chosen_voice}/{chosen_voice}.onnx",
        ]

        _fetch_file(json_sources, voice_json, min_bytes=50)
        _fetch_file(onnx_sources, voice_onnx, min_bytes=10 * 1024 * 1024)

        if voice_onnx.is_file() and voice_onnx.stat().st_size > 10 * 1024 * 1024:
            print(f"   ✅ Đã tải xong giọng {chosen_voice}: {voice_onnx.stat().st_size / (1024 * 1024):.1f} MB")
        else:
            print(f"   ⚠️ Giọng đọc sẽ được tự động tải bổ sung khi ứng dụng chạy.")
    else:
        print(f"   ✅ Model giọng '{chosen_voice}' đã có sẵn ({voice_onnx.stat().st_size / (1024 * 1024):.1f} MB).")

    # 4b. Kiểm tra ORT Execution Providers
    cuda_provider_confirmed = False
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
                cuda_provider_confirmed = True
                print("🎉 XÁC NHẬN: Piper TTS đã có CUDAExecutionProvider!")
            else:
                print("⚠️ CUDAExecutionProvider chưa xuất hiện trong phiên kiểm tra.")
        except Exception as ort_err:
            print(f"⚠️ Kiểm tra ORT: {ort_err}")

        # 4c. Chạy GPU Smoke-test thực tế
        chosen_model = model_selector.value or "HachimiMT-60-QT"
        print(f"🚀 Chạy GPU smoke-test với model '{chosen_model}'...")
        try:
            smoke_test = subprocess.run(
                [
                    sys.executable, "scripts/check_gpu.py",
                    "--model", chosen_model,
                    "--voice", chosen_voice
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
    return


@app.cell
def step5_launch_server(
    base_dir,
    mo,
    os,
    re,
    repo_dir,
    secrets,
    subprocess,
    sys,
    time,
    tunnel_selector,
    urllib,
):
    print("=" * 65)
    print("🌐 BƯỚC 5: KHỞI CHẠY MÁY CHỦ WEB & HỆ THỐNG TUNNEL ĐA TẦNG")
    print("=" * 65)

    # 1. Dọn dẹp tiến trình cũ nếu chạy lại cell
    subprocess.run(["pkill", "-f", "uvicorn.*main:app"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["pkill", "-f", "cloudflared"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.5)

    # 2. Sinh mã token truy cập bảo mật
    token_str = secrets.token_urlsafe(32)
    session_str = secrets.token_hex(16)
    os.environ["NOVEL_WEB_ACCESS_TOKEN"] = token_str
    os.environ["NOVEL_EXPORT_SESSION_ID"] = session_str

    log_server = repo_dir / "data/logs/colab-server.log"
    log_tunnel = repo_dir / "data/logs/colab-tunnel.log"

    # Mở file log bền vững (không đóng theo with block để tránh lỗi broken pipe gây crash tiến trình nền)
    server_out = open(str(log_server), "a", buffering=1, encoding="utf-8", errors="replace")

    # 3. Khởi động Uvicorn Server ở chế độ nền
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

    # 4. Chờ máy chủ phản hồi trạng thái sẵn sàng
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

    # 5. Khởi tạo Tunnel đa tầng (Pinggy HTTPS + Cloudflare HTTP/2)
    pinggy_url = None
    cloudflare_url = None
    lhr_url = None

    # 5a. Pinggy HTTPS Tunnel (SSH Port 443 - Tuyệt đối không bị lỗi Cloudflare 1033)
    try:
        print("🌐 Đang kết nối Pinggy HTTPS Tunnel (Port 443)...")
        pinggy_proc = subprocess.Popen(
            [
                "ssh", "-p", "443", "-o", "StrictHostKeyChecking=no",
                "-o", "ServerAliveInterval=30",
                "-R", "0:localhost:8000", "a.pinggy.io"
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env={**os.environ, "TERM": "dumb"}
        )
        p_start = time.time()
        while time.time() - p_start < 25:
            p_line = pinggy_proc.stdout.readline()
            if not p_line:
                break
            p_match = re.search(r"(https://[a-zA-Z0-9.-]+\.pinggy[a-zA-Z0-9.-]*\.link)", p_line)
            if p_match:
                pinggy_url = p_match.group(1)
                print(f"   ✅ Pinggy Tunnel sẵn sàng: {pinggy_url}")
                break
    except Exception as pinggy_err:
        print(f"   ⚠️ Lỗi kết nối Pinggy: {pinggy_err}")

    # 5b. Cloudflare Tunnel (HTTP/2 - Port 443)
    cf_executable = base_dir / "cloudflared"
    if sys.platform.startswith("linux") and not cf_executable.is_file():
        try:
            urllib.request.urlretrieve(
                "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
                cf_executable
            )
            cf_executable.chmod(0o755)
        except Exception as cf_dl_err:
            print(f"   ⚠️ Không tải được cloudflared: {cf_dl_err}")

    if cf_executable.is_file():
        print("🌐 Đang kết nối Cloudflare Tunnel (HTTP/2)...")
        # Sử dụng cờ --logfile độc lập để cloudflared ghi log trực tiếp, tránh đóng luồng gây Error 1033
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
                    cloudflare_url = cf_match.group(0)
                    print(f"   ✅ Cloudflare Tunnel sẵn sàng: {cloudflare_url}")
                    break
            time.sleep(1)

    # 5c. Localhost.run (Dự phòng nếu hai cổng trên đều không mở được)
    if not pinggy_url and not cloudflare_url:
        print("🌐 Đang kết nối Localhost.run...")
        try:
            lhr_proc = subprocess.Popen(
                [
                    "ssh", "-o", "StrictHostKeyChecking=no",
                    "-o", "ServerAliveInterval=30",
                    "-R", "80:localhost:8000", "nokey@localhost.run"
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env={**os.environ, "TERM": "dumb"}
            )
            l_start = time.time()
            while time.time() - l_start < 25:
                l_line = lhr_proc.stdout.readline()
                if not l_line:
                    break
                l_match = re.search(r"(https://[a-zA-Z0-9.-]+\.lhr\.life)", l_line)
                if l_match:
                    lhr_url = l_match.group(1)
                    print(f"   ✅ Localhost.run sẵn sàng: {lhr_url}")
                    break
        except Exception as lhr_err:
            print(f"   ⚠️ Lỗi kết nối Localhost.run: {lhr_err}")

    # 6. Hiển thị bảng điều khiển kết quả
    active_links = []
    if pinggy_url:
        active_links.append(("Pinggy HTTPS (Khuyên dùng - 100% không lỗi 1033)", f"{pinggy_url}/?access_token={token_str}"))
    if cloudflare_url:
        active_links.append(("Cloudflare Tunnel", f"{cloudflare_url}/?access_token={token_str}"))
    if lhr_url:
        active_links.append(("Localhost.run", f"{lhr_url}/?access_token={token_str}"))

    if active_links and server_ready:
        primary_title, primary_link = active_links[0]
        print(f"\n🎉 NOVELREADER ĐÃ KHỞI CHẠY THÀNH CÔNG!")
        for title, link in active_links:
            print(f"🌐 {title}: {link}")
        print(f"🔑 Token: {token_str}\n")

        other_links_md = ""
        if len(active_links) > 1:
            other_lines = [f"- **{t}:** [{lnk}]({lnk})" for t, lnk in active_links]
            other_links_md = "#### 🌐 Danh sách các cổng kết nối:\n" + "\n".join(other_lines) + "\n\n*(Nếu Cloudflare báo lỗi Error 1033 do nghẽn DNS, bạn chỉ cần bấm vào link **Pinggy** phía trên để vào ngay)*\n\n"

        status_view = mo.callout(
            mo.vstack([
                mo.md(f"### 🎉 NovelReader Đang Hoạt Động!"),
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

    server_active = True
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
        subprocess.run(["pkill", "-f", "uvicorn.*main:app"], check=False)
        subprocess.run(["pkill", "-f", "cloudflared"], check=False)
        action_msg = mo.md("🛑 **Đã gửi tín hiệu dừng máy chủ thành công.**")
    else:
        action_msg = mo.md("")

    # Nhấn refresh_logs_btn sẽ tự động kích hoạt cell này chạy lại để nạp log mới nhất
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
    return


@app.cell
def step7_backup_ui(mo):
    create_backup_btn = mo.ui.run_button(label="📦 Tạo bản sao lưu toàn bộ (ZIP)", kind="success")
    backup_ui_panel = mo.vstack([
        mo.md("## 💾 Sao lưu & Xuất dữ liệu"),
        mo.md("Bấm nút bên dưới để đóng gói toàn bộ bản dịch (output_text), file âm thanh (output_audio) và cơ sở dữ liệu truyện:"),
        create_backup_btn,
    ])
    return (create_backup_btn,)


@app.cell
def step7_backup_process(
    Path,
    base_dir,
    create_backup_btn,
    datetime,
    mo,
    repo_dir,
    sqlite3,
    tempfile,
    zipfile,
):
    if not create_backup_btn.value:
        backup_result_display = mo.md("")
    else:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"NovelReader_Backup_{timestamp}.zip"
        backup_path = base_dir / backup_filename

        print(f"📦 Đang tạo bản sao lưu: {backup_filename}...")
        with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as _backup_zf:
            # Nén output_text và output_audio
            for folder in ("output_text", "output_audio"):
                f_path = repo_dir / folder
                if f_path.is_dir():
                    for item in f_path.rglob("*"):
                        if item.is_file() and not any(part.startswith(".") for part in item.relative_to(repo_dir).parts):
                            _backup_zf.write(item, item.relative_to(repo_dir))

            # Snapshot database an toàn
            db_path = repo_dir / "data/novel.sqlite3"
            if db_path.exists():
                with tempfile.TemporaryDirectory() as temp_dir:
                    snap_path = Path(temp_dir) / "novel.sqlite3"
                    with sqlite3.connect(db_path) as s_conn, sqlite3.connect(snap_path) as d_conn:
                        s_conn.backup(d_conn)
                    _backup_zf.write(snap_path, "data/novel.sqlite3")

        size_mb = backup_path.stat().st_size / (1024 * 1024)
        backup_data = backup_path.read_bytes()

        backup_result_display = mo.vstack([
            mo.md(f"✅ **Đã tạo xong bản sao lưu:** `{backup_filename}` ({size_mb:.1f} MB)"),
            mo.download(
                data=backup_data,
                filename=backup_filename,
                label=f"⬇️ Bấm vào đây để tải {backup_filename} về máy tính"
            )
        ])
    return


if __name__ == "__main__":
    app.run()
