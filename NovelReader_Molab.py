# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "marimo",
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
#     "onnxruntime-gpu>=1.23,<2",
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

__generated_with = "0.13.0"
app = marimo.App(width="full")


# ────────────────────────────────────────────────────────────────────────────
# Cell 0 — Markdown: Giới thiệu
# ────────────────────────────────────────────────────────────────────────────
@app.cell
def intro():
    import marimo as mo
    mo.md(
        r"""
        # 🚀 NovelReader v4.2 — Molab Marimo Edition

        Bản notebook tương thích **Molab Marimo** (reactive notebook).
        Chạy tuần tự từ trên xuống dưới.

        | Bước | Nội dung |
        |------|----------|
        | 1 | Tải & giải nén mã nguồn từ GitHub |
        | 2 | Cài thư viện + ORT-GPU + cuDNN |
        | 3 | Cấu hình GPU / môi trường |
        | 4 | Tải model dịch + giọng đọc, kiểm tra CUDA |
        | 5 | Khởi chạy Web + Tunnel |

        > ⚠️ **Lưu ý Marimo**: Không dùng `import *`, không khai báo trùng biến giữa các cell.
        """
    )
    return


# ────────────────────────────────────────────────────────────────────────────
# Cell 1 — Tải & giải nén mã nguồn
# ────────────────────────────────────────────────────────────────────────────
@app.cell
def step1_download():
    import os
    import sys
    import subprocess
    import zipfile
    import stat
    import urllib.request
    import hashlib
    import shutil
    from pathlib import Path

    # ------- Cấu hình đường dẫn -------
    BASE_DIR = Path.cwd()
    REPO_DIR = BASE_DIR / "NovelReader_T4_Web"
    SOURCE_URL = "https://raw.githubusercontent.com/dungbeommm/NovelReader_Translate/main/NovelReader_GPU_notebook.zip"

    # ------- Tải ZIP -------
    archive = BASE_DIR / "NovelReader_GPU_notebook.zip"
    partial = archive.with_suffix(".zip.part")

    print("📥 Đang tải mã nguồn từ GitHub...")
    print("   URL:", SOURCE_URL)
    try:
        req = urllib.request.Request(SOURCE_URL, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        })
        with urllib.request.urlopen(req, timeout=120) as src, partial.open("wb") as out:
            total = 0
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > 128 * 1024 * 1024:
                    raise RuntimeError("ZIP vượt giới hạn 128 MB.")
                out.write(chunk)
            print(f"   ✅ Tải xong: {total / (1024*1024):.1f} MB")

        if not zipfile.is_zipfile(partial):
            raise RuntimeError("GitHub không trả về ZIP hợp lệ.")
        os.replace(partial, archive)
    except Exception as exc:
        partial.unlink(missing_ok=True)
        if archive.is_file():
            print(f"   ⚠️ Tải thất bại ({exc}), dùng bản ZIP có sẵn.")
        else:
            raise

    sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    print(f"   SHA256: {sha}")

    # ------- Giải nén -------
    print("\n📦 Đang giải nén...")
    with zipfile.ZipFile(archive) as z:
        infos = z.infolist()
        if len(infos) > 5000 or sum(i.file_size for i in infos) > 512 * 1024 * 1024:
            raise RuntimeError("ZIP quá nhiều tệp hoặc quá lớn.")
        markers = [
            n for n in z.namelist()
            if n == "main.py" or (n.endswith("/main.py") and len(Path(n).parts) == 2)
        ]
        if len(markers) != 1:
            raise RuntimeError("Không xác định được thư mục dự án trong ZIP.")
        prefix = markers[0][: -len("main.py")]
        for info in infos:
            if not info.filename.startswith(prefix):
                continue
            rel = info.filename[len(prefix):]
            if not rel:
                continue
            target = (REPO_DIR / rel).resolve()
            if not target.is_relative_to(REPO_DIR.resolve()):
                raise RuntimeError("ZIP có đường dẫn không an toàn.")
            if stat.S_ISLNK(info.external_attr >> 16):
                raise RuntimeError("ZIP chứa symlink.")
            # Không ghi đè dữ liệu người dùng
            if Path(rel).parts[0] in {
                "data", "models", "output_text", "output_audio", ".git"
            } or Path(rel).name == ".env":
                continue
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as src_f, target.open("wb") as dst_f:
                    shutil.copyfileobj(src_f, dst_f)

    # ------- Thêm vào sys.path -------
    repo_str = str(REPO_DIR)
    if repo_str not in sys.path:
        sys.path.insert(0, repo_str)
    os.chdir(REPO_DIR)

    # ------- Tạo thư mục cần thiết -------
    for name in (
        "data/logs", "models/translation", "models/voices",
        "output_text", "output_audio"
    ):
        (REPO_DIR / name).mkdir(parents=True, exist_ok=True)

    # ------- Kiểm tra GPU -------
    gpu_result = subprocess.run(
        ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
        capture_output=True, text=True, timeout=10
    )
    if gpu_result.returncode == 0 and gpu_result.stdout.strip():
        parts = [p.strip() for p in gpu_result.stdout.strip().split(",", 1)]
        gpu_name = parts[0]
        vram_gb = float(parts[1]) / 1024.0 if len(parts) > 1 else 0
        print(f"\n✅ GPU: {gpu_name} ({vram_gb:.1f} GB VRAM)")
    else:
        print("\n⚠️ Không phát hiện GPU NVIDIA.")

    print(f"✅ Mã nguồn sẵn sàng: {REPO_DIR}")
    return BASE_DIR, REPO_DIR


# ────────────────────────────────────────────────────────────────────────────
# Cell 2 — Cài thư viện + ORT GPU + cuDNN
# ────────────────────────────────────────────────────────────────────────────
@app.cell
def step2_install(REPO_DIR):
    import sys
    import subprocess

    print("=" * 65)
    print("📦 BƯỚC 2: CÀI THƯ VIỆN + ONNXRUNTIME-GPU")
    print("=" * 65)

    pip = [sys.executable, "-m", "pip"]

    # 2a. Cài requirements.txt (bỏ qua onnxruntime vì sẽ cài bản GPU riêng)
    print("\n📦 2a. Cài requirements.txt...")
    r1 = subprocess.run(
        pip + ["install", "-q", "-r", str(REPO_DIR / "requirements.txt"),
               "nvidia-cublas-cu12>=12,<13",
               "nvidia-cudnn-cu12",
               "nvidia-cuda-runtime-cu12>=12,<13"],
        capture_output=True, text=True, timeout=600
    )
    if r1.returncode != 0:
        print("❌ Lỗi cài requirements:", r1.stderr[-1000:])
    else:
        print("   ✅ Cài requirements thành công.")

    # 2b. Gỡ cả hai bản onnxruntime (CPU + GPU cũ nếu có)
    print("\n📦 2b. Gỡ onnxruntime cũ...")
    subprocess.run(
        pip + ["uninstall", "-y", "onnxruntime", "onnxruntime-gpu"],
        capture_output=True, text=True
    )

    # 2c. Cài onnxruntime-gpu (có CUDAExecutionProvider)
    print("📦 2c. Cài onnxruntime-gpu...")
    r3 = subprocess.run(
        pip + ["install", "-q", "onnxruntime-gpu"],
        capture_output=True, text=True, timeout=600
    )
    if r3.returncode != 0:
        print("❌ Lỗi cài ORT-GPU:", r3.stderr[-1000:])
    else:
        print("   ✅ Cài onnxruntime-gpu thành công.")

    # 2d. Cài espeak-ng (cần cho Piper TTS)
    print("\n📦 2d. Cài espeak-ng + ffmpeg...")
    r4 = subprocess.run(
        ["apt-get", "install", "-y", "-qq", "ffmpeg", "espeak-ng"],
        capture_output=True, text=True, timeout=120
    )
    if r4.returncode != 0:
        # Thử apt-get update trước
        subprocess.run(["apt-get", "update", "-qq"], capture_output=True, text=True)
        subprocess.run(
            ["apt-get", "install", "-y", "-qq", "ffmpeg", "espeak-ng"],
            capture_output=True, text=True
        )
    print("   ✅ espeak-ng + ffmpeg sẵn sàng.")

    # 2e. Kiểm tra kết quả
    print("\n" + "=" * 65)
    print("🔍 KIỂM TRA CÀI ĐẶT")
    print("=" * 65)

    import importlib.metadata
    packages = {
        "onnxruntime-gpu": None,
        "ctranslate2": None,
        "piper-tts": None,
        "nvidia-cudnn-cu12": None,
        "nvidia-cublas-cu12": None,
        "fastapi": None,
        "torch": None,
    }
    for pkg in packages:
        try:
            packages[pkg] = importlib.metadata.version(pkg)
            print(f"   ✅ {pkg}=={packages[pkg]}")
        except importlib.metadata.PackageNotFoundError:
            print(f"   ❌ {pkg} CHƯA CÀI!")

    print("\n✅ Bước 2 hoàn tất. Chuyển sang bước 3.")
    install_ok = True
    return (install_ok,)


# ────────────────────────────────────────────────────────────────────────────
# Cell 3 — Cấu hình GPU / môi trường
# ────────────────────────────────────────────────────────────────────────────
@app.cell
def step3_config(REPO_DIR, install_ok):
    import os
    import site
    from pathlib import Path

    print("=" * 65)
    print("⚙️ BƯỚC 3: CẤU HÌNH GPU & MÔI TRƯỜNG")
    print("=" * 65)

    os.environ.update({
        # Batch & CT2
        "HACHIMIMT_WEB_BATCH_SIZE": "96",
        "HACHIMIMT_BATCH_SIZE": "96",
        "HACHIMIMT_CT2_BATCH_TYPE": "tokens",
        "HACHIMIMT_CT2_WINDOW_MULTIPLIER": "16",
        "HACHIMIMT_INTER_THREADS": "1",
        "HACHIMIMT_COMPUTE_TYPE": "int8_float16",
        "HACHIMIMT_FORCE_CT2_CUDA": "1",
        "HACHIMIMT_GPU_INDICES": "0",
        "HACHIMIMT_AUTO_ALL_GPUS": "0",
        "HACHIMIMT_TOKENIZE_WORKERS": str(min(os.cpu_count() or 2, 4)),
        # Piper CUDA bắt buộc
        "PIPER_DEVICE": "cuda",
        "PIPER_REQUIRE_CUDA": "1",
        "PIPER_CUDNN_ALGO": "DEFAULT",
        # Server
        "ALLOWED_HOSTS": "*",
        "ALLOW_TUNNEL": "1",
        "COLAB_GPU": "1",
        # Đường dẫn
        "NOVEL_DATA": str(REPO_DIR / "data"),
        "NOVEL_MODELS": str(REPO_DIR / "models/translation"),
        "TTS_VOICE_DIR": str(REPO_DIR / "models/voices"),
        "NOVEL_OUTPUT_TEXT": str(REPO_DIR / "output_text"),
        "NOVEL_OUTPUT_AUDIO": str(REPO_DIR / "output_audio"),
        "PYTHONUNBUFFERED": "1",
        # Drive (Molab không dùng Colab mount)
        "NOVEL_DRIVE_BACKEND": "api",
        "NOVEL_COLAB_DRIVE_BRIDGE": "0",
        "NOVEL_DRIVE_CREDENTIAL_DIR": "/tmp/novelreader-drive",
    })

    # Export thư viện NVIDIA vào LD_LIBRARY_PATH (quan trọng cho cuDNN/cuBLAS)
    libdirs = []
    for base in site.getsitepackages():
        nvidia_dir = Path(base) / "nvidia"
        if nvidia_dir.is_dir():
            libdirs.extend(
                str(p) for p in nvidia_dir.glob("*/lib") if p.is_dir()
            )
    existing = os.environ.get("LD_LIBRARY_PATH", "")
    os.environ["LD_LIBRARY_PATH"] = ":".join(libdirs + [existing])

    print(f"   BATCH_SIZE: 96")
    print(f"   COMPUTE_TYPE: int8_float16")
    print(f"   PIPER_DEVICE: cuda")
    print(f"   LD_LIBRARY_PATH: {len(libdirs)} NVIDIA lib dirs added")
    print(f"\n✅ Cấu hình hoàn tất. Chuyển sang bước 4.")
    config_ok = True
    return (config_ok,)


# ────────────────────────────────────────────────────────────────────────────
# Cell 4 — Tải model + kiểm tra CUDA
# ────────────────────────────────────────────────────────────────────────────
@app.cell
def step4_check_gpu(REPO_DIR, config_ok):
    import sys
    import os
    import subprocess

    print("=" * 65)
    print("🔍 BƯỚC 4: TẢI MODEL & KIỂM TRA GPU CUDA")
    print("=" * 65)

    env = dict(os.environ)
    env.pop("CUDA_VISIBLE_DEVICES", None)

    # 4a. Kiểm tra ORT providers
    print("\n🔍 4a. Kiểm tra ONNX Runtime providers...")
    ort_check = subprocess.run(
        [sys.executable, "-c", (
            "import onnxruntime as ort; "
            "providers = ort.get_available_providers(); "
            "print('ORT_VERSION=' + ort.__version__); "
            "print('PROVIDERS=' + ','.join(providers)); "
            "print('CUDA_OK=' + str('CUDAExecutionProvider' in providers))"
        )],
        capture_output=True, text=True, timeout=60, env=env
    )
    print("   " + ort_check.stdout.strip().replace("\n", "\n   "))
    if "CUDA_OK=True" not in ort_check.stdout:
        print("   ❌ CUDAExecutionProvider CHƯA SẴN SÀNG!")
        print("   STDERR:", ort_check.stderr[-500:])
    else:
        print("   ✅ CUDAExecutionProvider sẵn sàng!")

    # 4b. Kiểm tra PyTorch CUDA
    print("\n🔍 4b. Kiểm tra PyTorch CUDA...")
    torch_check = subprocess.run(
        [sys.executable, "-c", (
            "import torch; "
            "print('TORCH=' + torch.__version__); "
            "print('CUDA=' + str(torch.cuda.is_available())); "
            "print('GPU=' + (torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'N/A')); "
            "print('VRAM=' + (f'{torch.cuda.get_device_properties(0).total_mem/(1024**3):.1f}GB' if torch.cuda.is_available() else 'N/A'))"
        )],
        capture_output=True, text=True, timeout=60, env=env
    )
    print("   " + torch_check.stdout.strip().replace("\n", "\n   "))

    # 4c. Kiểm tra CTranslate2 CUDA
    print("\n🔍 4c. Kiểm tra CTranslate2 CUDA...")
    ct2_check = subprocess.run(
        [sys.executable, "-c", (
            "import torch; import ctranslate2; "
            "count = ctranslate2.get_cuda_device_count(); "
            "print('CT2=' + ctranslate2.__version__); "
            "print('CUDA_DEVICES=' + str(count)); "
            "types = ctranslate2.get_supported_compute_types('cuda') if count > 0 else set(); "
            "print('COMPUTE_TYPES=' + ','.join(sorted(types)))"
        )],
        capture_output=True, text=True, timeout=60, env=env
    )
    print("   " + ct2_check.stdout.strip().replace("\n", "\n   "))
    if ct2_check.stderr.strip():
        print("   STDERR:", ct2_check.stderr[-300:])

    # 4d. Tải model dịch + giọng đọc + smoke test GPU
    print("\n🚀 4d. Smoke test: dịch + TTS trên GPU...")
    smoke = subprocess.run(
        [sys.executable, "scripts/check_gpu.py",
         "--model", "HachimiMT-60-QT", "--voice", "ngochuyennew"],
        capture_output=True, text=True, timeout=600, env=env,
        cwd=str(REPO_DIR)
    )
    print(smoke.stdout)
    if smoke.returncode != 0:
        print("⚠️ Smoke test thất bại:")
        print(smoke.stderr[-2000:])
        print("\nThử tiếp bước 5 — server có thể vẫn hoạt động ở chế độ fallback.")
    else:
        print("✅ GPU smoke test THÀNH CÔNG!")

    print(f"\n✅ Bước 4 hoàn tất. Chuyển sang bước 5.")
    gpu_ok = True
    return (gpu_ok,)


# ────────────────────────────────────────────────────────────────────────────
# Cell 5 — Khởi chạy Web Server + Tunnel
# ────────────────────────────────────────────────────────────────────────────
@app.cell
def step5_server(REPO_DIR, BASE_DIR, gpu_ok):
    import os
    import sys
    import re
    import time
    import secrets
    import subprocess
    import urllib.request
    import socket

    print("=" * 65)
    print("🌐 BƯỚC 5: KHỞI CHẠY WEB SERVER + TUNNEL")
    print("=" * 65)

    # ------- Kill tiến trình cũ nếu có -------
    subprocess.run(["pkill", "-f", "uvicorn.*main:app"], capture_output=True)
    subprocess.run(["pkill", "-f", "cloudflared"], capture_output=True)
    time.sleep(2)

    # ------- Kiểm tra port 8000 -------
    try:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 8000))
        print("   ✅ Port 8000 sẵn sàng.")
    except OSError:
        print("   ⚠️ Port 8000 đang bị chiếm, thử kill...")
        subprocess.run(["fuser", "-k", "8000/tcp"], capture_output=True)
        time.sleep(2)

    # ------- Token bảo mật -------
    access_token = secrets.token_urlsafe(32)
    session_id = secrets.token_hex(16)
    os.environ["NOVEL_WEB_ACCESS_TOKEN"] = access_token
    os.environ["NOVEL_EXPORT_SESSION_ID"] = session_id

    server_log = REPO_DIR / "data/logs/colab-server.log"
    tunnel_log = REPO_DIR / "data/logs/colab-tunnel.log"

    # ------- Khởi động Uvicorn -------
    print("\n🚀 Khởi động Uvicorn server...")
    with server_log.open("w") as sf:
        server_process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "main:app",
             "--host", "127.0.0.1", "--port", "8000",
             "--workers", "1", "--no-access-log",
             "--timeout-graceful-shutdown", "120"],
            cwd=str(REPO_DIR),
            stdout=sf,
            stderr=subprocess.STDOUT,
            env=dict(os.environ)
        )

    # Chờ server sẵn sàng
    print("   Đang chờ server khởi động...")
    server_ready = False
    for i in range(120):
        if server_process.poll() is not None:
            print("   ❌ Server đã thoát sớm!")
            print(server_log.read_text()[-3000:])
            break
        try:
            req = urllib.request.Request(
                "http://127.0.0.1:8000/api/state",
                headers={"X-Novel-Access": access_token}
            )
            with urllib.request.urlopen(req, timeout=2) as resp:
                if resp.status == 200:
                    server_ready = True
                    break
        except Exception:
            time.sleep(1)

    if server_ready:
        print("   ✅ Uvicorn server đang chạy!")
    else:
        print("   ❌ Server chưa sẵn sàng sau 120 giây.")
        print("   Log cuối:", server_log.read_text()[-2000:])

    # ------- Thiết lập Tunnel -------
    print("\n🔗 Thiết lập tunnel...")

    # Thử Cloudflare trước (cần port 7844)
    cloudflared = BASE_DIR / "cloudflared"
    public_url = None
    tunnel_type = None

    # Kiểm tra port 7844 có mở không
    port_7844_ok = False
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(5)
            result = s.connect_ex(("198.41.200.233", 7844))
            port_7844_ok = (result == 0)
    except Exception:
        pass

    if port_7844_ok:
        # Dùng Cloudflare tunnel
        print("   Dùng Cloudflare Tunnel...")
        if not cloudflared.is_file():
            urllib.request.urlretrieve(
                "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
                cloudflared
            )
            cloudflared.chmod(0o755)

        with tunnel_log.open("w") as tf:
            tunnel_process = subprocess.Popen(
                [str(cloudflared), "tunnel", "--url", "http://127.0.0.1:8000"],
                stdout=tf, stderr=subprocess.STDOUT
            )

        for _ in range(90):
            if tunnel_process.poll() is not None:
                break
            content = tunnel_log.read_text()
            match = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", content)
            if match:
                public_url = match.group(0)
                tunnel_type = "Cloudflare"
                break
            time.sleep(1)
    else:
        print("   ⚠️ Port 7844 bị chặn, Cloudflare Tunnel không khả dụng.")

    # Fallback: dùng SSH tunnel qua port 443
    if not public_url:
        print("   Chuyển sang tunnel qua SSH port 443...")
        tunnel_process = subprocess.Popen(
            ["ssh", "-o", "StrictHostKeyChecking=no",
             "-R", "0:localhost:8000", "a.]@a.]"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env={**os.environ, "TERM": "dumb"}
        )
        # Nếu SSH không khả dụng, thử dùng Python HTTP tunnel
        if tunnel_process.poll() is not None:
            print("   SSH không khả dụng, thử Pinggy tunnel...")
            tunnel_process = subprocess.Popen(
                ["ssh", "-p", "443", "-o", "StrictHostKeyChecking=no",
                 "-R", "0:localhost:8000", "a.pinggy.io"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env={**os.environ, "TERM": "dumb"}
            )

            start = time.time()
            while time.time() - start < 30:
                line = tunnel_process.stdout.readline()
                if not line:
                    break
                match = re.search(r"(https://[a-zA-Z0-9.-]+\.pinggy[a-zA-Z0-9.-]*\.link)", line)
                if match:
                    public_url = match.group(1)
                    tunnel_type = "Pinggy"
                    break

    # ------- Kết quả -------
    print("\n" + "=" * 65)
    if public_url and server_ready:
        full_url = f"{public_url}/?access_token={access_token}"
        print(f"🎉 NOVELREADER ĐÃ SẴN SÀNG!")
        print(f"\n🌐 Link truy cập ({tunnel_type}):")
        print(f"   {full_url}")
        print(f"\n🔑 Access Token:")
        print(f"   {access_token}")
        print(f"\n⚠️ Giữ link và token riêng tư. Không chia sẻ.")
    elif server_ready:
        print(f"✅ Server chạy tại http://127.0.0.1:8000")
        print(f"⚠️ Không thiết lập được tunnel. Truy cập qua localhost.")
        print(f"🔑 Token: {access_token}")
    else:
        print("❌ Server khởi động thất bại. Xem log bên trên.")
    print("=" * 65)

    return


# ────────────────────────────────────────────────────────────────────────────
# Cell 6 (tùy chọn) — Sao lưu kết quả
# ────────────────────────────────────────────────────────────────────────────
@app.cell
def step6_backup(REPO_DIR, BASE_DIR):
    import marimo as mo

    _btn = mo.ui.run_button(label="📦 Sao lưu kết quả")
    mo.md(
        f"""
        ## 6. Sao lưu kết quả

        Bấm nút bên dưới để tạo file ZIP chứa text/audio đã dịch và database.
        **Dừng server trước khi sao lưu** để đảm bảo dữ liệu nhất quán.

        {_btn}
        """
    )
    return (_btn,)


@app.cell
def do_backup(_btn, REPO_DIR, BASE_DIR):
    import zipfile
    import sqlite3
    import tempfile
    from pathlib import Path
    from datetime import datetime

    if not _btn.value:
        return

    print("📦 Đang tạo bản sao lưu...")
    backup = BASE_DIR / (
        "NovelReader_outputs_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".zip"
    )

    with zipfile.ZipFile(backup, "w", zipfile.ZIP_DEFLATED) as z:
        for folder in ("output_text", "output_audio"):
            folder_path = REPO_DIR / folder
            if folder_path.is_dir():
                for p in folder_path.rglob("*"):
                    if p.is_file() and not any(
                        part.startswith(".") for part in p.relative_to(REPO_DIR).parts
                    ):
                        z.write(p, p.relative_to(REPO_DIR))

        db = REPO_DIR / "data/novel.sqlite3"
        if db.exists():
            with tempfile.TemporaryDirectory() as temp:
                snapshot = Path(temp) / "novel.sqlite3"
                with sqlite3.connect(db) as src, sqlite3.connect(snapshot) as dst:
                    src.backup(dst)
                z.write(snapshot, "data/novel.sqlite3")

    size_mb = backup.stat().st_size / (1024 * 1024)
    print(f"✅ Bản sao lưu: {backup.name} ({size_mb:.1f} MB)")
    return


if __name__ == "__main__":
    app.run()
