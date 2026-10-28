import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium", auto_download=["html"])


@app.cell(hide_code=True)
def WEB_DASHBOARD(json, mo, os, re, repo_dir, time, urllib):
    def _novelreader_dashboard():
        _token = ""
        _pid = ""
        for _entry in os.listdir("/proc"):
            if not _entry.isdigit():
                continue
            try:
                _cmd = open("/proc/" + _entry + "/cmdline", "rb").read().replace(bytes([0]), b" ").decode("utf-8", "replace")
            except OSError:
                continue
            if "uvicorn" in _cmd and "main:app" in _cmd:
                _pid = _entry
                try:
                    for _item in open("/proc/" + _entry + "/environ", "rb").read().split(bytes([0])):
                        if _item.startswith(b"NOVEL_WEB_ACCESS_TOKEN="):
                            _token = _item.split(b"=", 1)[1].decode("utf-8", "replace")
                except OSError:
                    pass
                break

        _zrok_host = ""
        _zrok_log = repo_dir / "data/logs/zrok_share.log"
        if _zrok_log.exists():
            from server.tunnel.zrok import extract_share_host
            _zrok_host = extract_share_host(_zrok_log.read_text(errors="replace"))
        _link = ("https://" + _zrok_host + "/?access_token=" + _token) if (_zrok_host and _token) else ""

        _models = []
        if _token:
            try:
                _req = urllib.request.Request("http://127.0.0.1:8000/api/models", headers={"X-Novel-Access": _token})
                with urllib.request.urlopen(_req, timeout=3) as _resp:
                    _models = json.loads(_resp.read())
            except Exception:
                _models = []
        _local_models = [m for m in _models if not str(m.get("id", "")).startswith("space")]
        _ready_models = [m for m in _local_models if m.get("downloaded")]

        _voices_dir = repo_dir / "models/voices"
        _voices = len(list(_voices_dir.rglob("*.onnx"))) if _voices_dir.exists() else 0

        _web = "chưa chạy"
        try:
            with urllib.request.urlopen("http://127.0.0.1:8000/", timeout=2) as _resp:
                _web = "HTTP " + str(_resp.status)
        except Exception:
            _web = "chưa chạy"

        _stamp = time.strftime("%H:%M:%S")
        _status = [
            "- Web server: **" + _web + "**",
            "- Model dịch local: **" + (str(len(_ready_models)) + "/" + str(len(_local_models)) if _local_models else "chưa rõ") + "**",
            "- Giọng đọc: **" + str(_voices) + "** file ONNX",
            "- zrok: `" + (_zrok_host or "chưa có share") + "`",
            "- Cập nhật lúc: " + _stamp,
        ]
        _blocks = [mo.md("### Bảng điều khiển NovelReader")]
        if _link:
            _blocks.append(mo.callout(mo.md("[Mở NovelReader](" + _link + ")"), kind="success"))
            _blocks.append(mo.md("**Link đầy đủ**\n\n```\n" + _link + "\n```\n\n**Mã truy cập:** `" + _token + "`"))
        else:
            _blocks.append(mo.callout(mo.md("💡 Web server hoặc zrok chưa bật. Vui lòng chạy ô **ZROK_ENABLE_AND_SHARE** ở cuối notebook để kích hoạt giao diện web."), kind="info"))
        _blocks.append(mo.md("\n".join(_status)))
        _blocks.append(mo.md("_Link chỉ sống khi sandbox molab còn chạy. Mở link lần đầu để tự đăng nhập._"))
        return mo.vstack(_blocks)

    _novelreader_dashboard()
    return


@app.cell
def _():
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

    # ============================================================
    # CAU HINH TOKEN TRUC TIEP (chinh sua trong ban notebook RIENG)
    # Khong commit token that len GitHub public. Token cu da lo can thu hoi.
    # ============================================================
    HF_TOKEN_INLINE = ""  # Dan HF token MOI cua ban vao giua cap dau ngoac kep
    ZROK_ACCOUNT_TOKEN_INLINE = ""  # Dan zrok token MOI cua ban tai day

    # Uu tien gia tri nhung truc tiep; neu de trong, dung bien moi truong.
    if HF_TOKEN_INLINE.strip():
        os.environ["HF_TOKEN"] = HF_TOKEN_INLINE.strip()
    if os.environ.get("HF_TOKEN", "").strip():
        os.environ["HUGGING_FACE_HUB_TOKEN"] = os.environ["HF_TOKEN"].strip()
    if ZROK_ACCOUNT_TOKEN_INLINE.strip():
        os.environ["ZROK_ACCOUNT_TOKEN"] = ZROK_ACCOUNT_TOKEN_INLINE.strip()
    return (
        Path,
        datetime,
        importlib,
        json,
        mo,
        os,
        re,
        shutil,
        site,
        subprocess,
        sys,
        tempfile,
        time,
        urllib,
        zipfile,
    )


@app.cell
def _(mo):
    model_selector = mo.ui.dropdown(
        options={
            "HachimiMT-60-QT (Khuyên dùng - Nhanh, chuẩn)": "HachimiMT-60-QT",
            "HachimiMT-40-QT (Nhẹ, cổ trang)": "HachimiMT-40-QT",
            "HachimiMT-30 (Siêu nhẹ)": "HachimiMT-30",
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

    tunnel_selector = mo.md("Giao diện notebook trực tiếp")

    intro_markdown = mo.md(
        r"""
        # 🚀 NovelReader AI — Molab Marimo Edition v4.7.1

        Bản notebook tối ưu hóa riêng cho **Molab Marimo** (reactive environment), tương thích 100% với Google Colab / Kaggle.
        Tự động cấu hình **CTranslate2 CUDA + Piper ONNX hoặc VieNeu v3 Turbo** và hệ thống kết nối **bảng điều khiển marimo**.

        ### 📋 Các bước chạy tự động:
        1. 📥 **Bước 1:** Khởi tạo môi trường & Mã nguồn NovelReader
        2. 📦 **Bước 2:** Cài đặt thư viện + ONNX Runtime GPU + NVIDIA cuDNN 12
        3. ⚙️ **Bước 3:** Cấu hình tham số GPU tối ưu (Batch 96, int8_float16)
        4. 🔍 **Bước 4:** Tải model theo bộ đọc. VieNeu: 25 giọng Vbook + backbone/codec chính thức tải riêng, không chạy GGUF.
        5. 🌐 **Bước 5:** Mở bảng điều khiển trực tiếp trong notebook
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
    mo.output.replace(mo.md("# 📚 NovelReader trên MoLab\nChạy bốn bước chuẩn bị môi trường và model, sau đó dùng **Bảng điều khiển notebook** bên dưới để nạp truyện, dịch, tạo audio và sao lưu Hugging Face."))
    return (
        model_selector,
        tts_engine_selector,
        vieneu_voice_selector,
        voice_download_mode,
        voice_selector,
    )


@app.cell
def _(Path, os, shutil, subprocess, sys, urllib, zipfile):
    print("=" * 65)
    print("📥 BƯỚC 1: KHỞI TẠO MÔI TRƯỜNG & MÃ NGUỒN NOVELREADER")
    print("=" * 65)

    base_dir = Path.cwd().resolve()

    # Nhận diện nếu notebook đang chạy ngay trong thư mục repository
    if (base_dir / "main.py").is_file() and (base_dir / "translation").is_dir():
        repo_dir = base_dir
        print(f"✅ Đang chạy trực tiếp trong thư mục dự án: {repo_dir}")
    elif (base_dir / "NovelReader_T4_Web" / "main.py").is_file() and (base_dir / "NovelReader_T4_Web" / "translation").is_dir():
        repo_dir = base_dir / "NovelReader_T4_Web"
        print(f"✅ Đã tìm thấy thư mục NovelReader_T4_Web: {repo_dir}")
    else:
        repo_dir = base_dir / "NovelReader_T4_Web"
        repo_dir.mkdir(parents=True, exist_ok=True)
        print("📦 Đang nạp mã nguồn NovelReader từ GitHub...")
        _cloned = False
        try:
            _res = subprocess.run(
                ["git", "clone", "--depth", "1", "https://github.com/dungbeommm/NovelReader_Translate.git", str(repo_dir)],
                capture_output=True, text=True, timeout=90
            )
            if _res.returncode == 0 and (repo_dir / "main.py").is_file():
                _cloned = True
                print("✅ Đã git clone mã nguồn thành công.")
            else:
                print("⚠️ git clone không thành công, thử tải qua ZIP:", _res.stderr.strip())
        except Exception as _git_err:
            print("⚠️ git clone gặp ngoại lệ, thử tải qua ZIP:", _git_err)

        if not _cloned:
            _zip_url = "https://github.com/dungbeommm/NovelReader_Translate/archive/refs/heads/main.zip"
            _zip_path = base_dir / "novelreader_source.zip"
            try:
                with urllib.request.urlopen(_zip_url, timeout=60) as _resp:
                    _zip_path.write_bytes(_resp.read())
                with zipfile.ZipFile(_zip_path) as _z:
                    for _m in _z.infolist():
                        _parts = Path(_m.filename).parts[1:]
                        if not _parts:
                            continue
                        _target = repo_dir / Path(*_parts)
                        if _m.is_dir():
                            _target.mkdir(parents=True, exist_ok=True)
                        else:
                            _target.parent.mkdir(parents=True, exist_ok=True)
                            _target.write_bytes(_z.read(_m))
                _zip_path.unlink(missing_ok=True)
                print("✅ Đã tải và giải nén mã nguồn NovelReader ZIP thành công.")
            except Exception as _zip_err:
                print("❌ Lỗi khi tải ZIP mã nguồn:", _zip_err)

    # BEGIN_RETIRED_STORAGE_CLEANUP
    for _retired in ('gdrive/__init__.py', 'gdrive/api_drive.py', 'gdrive/colab_bridge.py', 'gdrive/export_service.py', 'gdrive/gdrive_service.py', 'storage/pixeldrain_service.py', 'web/routes/gdrive.py', 'web/routes/drive_api.py', 'web/routes/drive_exports.py', 'web/routes/pixeldrain_routes.py'):
        (repo_dir / _retired).unlink(missing_ok=True)
    # END_RETIRED_STORAGE_CLEANUP

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

    # Chỉ nhận diện GPU ở bước này; CUDA thực tế được smoke-test ở bước 4.
    from notebook.gpu_manager import detect_gpu as nr_detect_gpu
    gpu_info = nr_detect_gpu()
    gpu_detected = gpu_info["detected"]
    gpu_label = gpu_info["name"]
    vram_display = gpu_info["vram"]
    print(f"✅ GPU: {gpu_label} ({vram_display})" if gpu_detected else "⚠️ Runtime chưa gắn GPU NVIDIA (CPU).")

    step1_ready = True
    return gpu_detected, repo_dir


@app.cell
def _(gpu_detected, importlib, repo_dir, subprocess, sys):
    print("=" * 65)
    print("📦 BƯỚC 2: CÀI ĐẶT THƯ VIỆN & CẤU HÌNH PIPER CUDA")
    print("=" * 65)

    pip_executable = [sys.executable, "-m", "pip"]

    # Kiểm tra các thư viện bắt buộc
    needed_packages = ["fastapi", "uvicorn", "websockets", "python-multipart", "pydantic", "ebooklib", "beautifulsoup4", "charset-normalizer", "huggingface-hub", "ctranslate2", "sentencepiece", "gradio-client", "opencc-python-reimplemented", "piper-tts", "psutil"]
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
            install_result = subprocess.run(
                pip_executable + ["install", "-q", "-r", str(req_path)],
                capture_output=True, text=True
            )
            if install_result.returncode != 0:
                print((install_result.stderr or install_result.stdout)[-5000:])
                raise RuntimeError("Cài đặt thư viện từ requirements.txt thất bại.")

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
    return (step2_ready,)


@app.cell
def _(
    Path,
    gpu_detected,
    os,
    repo_dir,
    site,
    step2_ready,
    tts_engine_selector,
    vieneu_voice_selector,
    voice_selector,
):
    assert step2_ready
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
        "NOVEL_TTS_ENGINE": tts_engine_selector.value or "piper",
        "NOVEL_TTS_VOICE": (vieneu_voice_selector.value or "truc_ly") if tts_engine_selector.value=="vieneu" else (voice_selector.value or "ngochuyennew"),
        "VIENEU_DEVICE": "cuda" if gpu_detected else "cpu",
        "VIENEU_MODEL_DIR": str(repo_dir/"models/vieneu"),
        # Piper TTS CUDA & Hi-Performance Audio
        "PIPER_DEVICE": "cuda" if gpu_detected else "cpu",
        "PIPER_REQUIRE_CUDA": "1" if gpu_detected else "0",
        "PIPER_CUDNN_ALGO": "DEFAULT",
        "AUDIO_WORKERS": "2" if gpu_detected else "1",
        "TTS_CHUNK_MAX_CHARS": "4000" if gpu_detected else "2500",
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
    }
    from notebook.bootstrap import apply_runtime_environment
    apply_runtime_environment(env_map, gpu_detected)

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
    return (step3_ready,)


@app.cell
def _(
    gpu_detected,
    model_selector,
    os,
    repo_dir,
    step3_ready,
    subprocess,
    sys,
    voice_download_mode,
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

    # Kiểm tra đúng cấu trúc CTranslate2 và tải trước cho cả CPU lẫn GPU.
    from notebook.model_loader import ensure_translation_model as nr_ensure_model
    chosen_model = model_selector.value or "HachimiMT-60-QT"
    if nr_ensure_model(repo_dir, chosen_model):
        print(f"✅ Đã tải model dịch {chosen_model}.")

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
                print("🎉 ORT có CUDAExecutionProvider (chưa chứng minh inference).")
            else:
                print("⚠️ CUDAExecutionProvider chưa xuất hiện trong phiên kiểm tra.")
        except Exception as ort_err:
            print(f"⚠️ Kiểm tra ORT: {ort_err}")

        # 4d. Chạy GPU Smoke-test thực tế
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
def _(json, mo, os, repo_dir, step4_ready, subprocess, urllib):
    # BƯỚC 5 — Backend trực tiếp trong notebook marimo
    assert step4_ready
    import importlib as nr_importlib
    from web import runtime as nr_runtime
    from web.schemas import Config as nr_Config
    from storage import checkpoints as nr_checkpoints
    from storage import huggingface_service as nr_hf
    from storage.cloud_settings import save_key as nr_save_key, save_repo_id as nr_save_repo_id, load_key as nr_load_key
    from storage.files import export_txt as nr_export_txt, export_epub as nr_export_epub
    from audio import audio_service as nr_audio
    from notebook.session_manager import BackendClient as nr_BackendClient
    nr_client = nr_BackendClient()
    # Không thay thế dữ liệu nếu tác vụ cũ còn chạy.
    try:
        _req = urllib.request.Request("http://127.0.0.1:8000/api/state", headers={"X-Novel-Access": os.environ.get("NOVEL_WEB_ACCESS_TOKEN", "")})
        with urllib.request.urlopen(_req, timeout=2) as _resp:
            _previous_state = json.loads(_resp.read())
        if _previous_state.get("progress", {}).get("active"):
            raise RuntimeError("Tác vụ cũ còn chạy: hãy dừng tác vụ trước khi chuyển backend.")
    except (OSError, ValueError):
        pass
    # Không pkill uvicorn để giữ WebUI và tunnel zrok hoạt động ổn định
    # subprocess.run(["pkill", "-f", "uvicorn.*main:app"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if nr_runtime.store is None:
        nr_runtime.initialize()
    log_server = repo_dir / "data/logs/app.log"
    log_tunnel = repo_dir / "data/logs/retired-tunnel.log"
    server_active = False
    nr_get_notice, nr_set_notice = mo.state("Sẵn sàng. Nạp truyện hoặc khôi phục checkpoint để bắt đầu.")
    mo.callout(mo.md("### ✅ Backend notebook đã sẵn sàng\nDùng bảng điều khiển NovelReader phía dưới."), kind="success")
    return (
        nr_Config,
        nr_client,
        nr_audio,
        nr_checkpoints,
        nr_export_epub,
        nr_export_txt,
        nr_get_notice,
        nr_hf,
        nr_runtime,
        nr_save_key,
        nr_save_repo_id,
        nr_load_key,
        nr_set_notice,
    )


@app.cell
def _(
    Path,
    datetime,
    json,
    mo,
    nr_Config,
    nr_client,
    model_selector,
    nr_checkpoints,
    nr_hf,
    nr_runtime,
    nr_save_key,
    nr_save_repo_id,
    nr_load_key,
    nr_set_notice,
    os,
    repo_dir,
    tempfile,
    zipfile,
):
    # NOVELREADER_NATIVE_CONTROLS
    import io as nr_io
    import threading as nr_threading
    nr_tasks = {"thread": None}
    def nr_report(text):
        nr_set_notice(str(text))
    def nr_run_task(label, fn):
        if nr_tasks["thread"] is not None and nr_tasks["thread"].is_alive():
            nr_report("Một thao tác đang xử lý. Hãy chờ hoàn tất.")
            return
        def work():
            try:
                nr_report(label + "…")
                result = fn()
                nr_report(label + ": " + (json.dumps(result, ensure_ascii=False) if isinstance(result, dict) else str(result or "Hoàn tất")))
            except Exception as exc:
                nr_report("Lỗi: " + str(getattr(exc, "detail", exc)))
        nr_tasks["thread"] = mo.Thread(target=work, daemon=True)
        nr_tasks["thread"].start()
    def nr_settings():
        return nr_Config(engine=nr_model.value, batch_size=int(nr_batch.value),
            glossary=nr_glossary.value, generate_audio=nr_make_audio.value,
            tts_engine=nr_tts.value, voice_id=nr_voice.value.strip(),
            audio_speed=float(nr_speed.value), audio_format=nr_format.value,
            audio_bitrate=nr_bitrate.value, honorific_mode=nr_honorific.value,
            start_pos=int(nr_start.value), end_pos=int(nr_end.value) if nr_end.value else None,
            auto_group_audio=nr_group.value, group_size=int(nr_group_size.value),
            cloud_checkpoint=bool(nr_cloud_auto.value), cloud_checkpoint_every=10,
            cloud_checkpoint_minutes=10).model_dump()
    def nr_import_uploaded():
        nr_runtime.ensure_idle()
        if nr_runtime.store.book() and not nr_replace.value:
            raise ValueError("Đánh dấu cho phép thay truyện hiện tại trước khi nạp.")
        if not nr_upload.value:
            raise ValueError("Chọn file TXT, EPUB hoặc ZIP trước.")
        item = nr_upload.value[0]
        name, data = item.name, item.contents
        if name.lower().endswith(".zip"):
            from storage.files import decode_text
            with zipfile.ZipFile(nr_io.BytesIO(data)) as archive:
                entries = [x for x in archive.infolist() if not x.is_dir() and x.filename.lower().endswith(".txt")]
                if not entries or len(entries) > 20000 or sum(x.file_size for x in archive.infolist()) > 50*1024*1024:
                    raise ValueError("ZIP phải có TXT, tối đa 50 MB sau giải nén và 20.000 file TXT.")
                if any(x.flag_bits & 1 for x in entries):
                    raise ValueError("ZIP có mật khẩu không được hỗ trợ.")
                data = "\n\n".join(decode_text(archive.read(x))[0] for x in sorted(entries, key=lambda x:x.filename)).encode("utf-8")
                name = Path(name).stem + ".txt"
        if nr_client.available():
            return nr_client.upload_book(name, data).get("book")
        return nr_runtime.import_book(name, data).get("book")
    def nr_start_job():
        if nr_cloud_auto.value and not nr_load_key():
            raise ValueError('Bật checkpoint tự động cần có token HF. Hãy cấu hình HF hoặc tắt tự đồng bộ.')
        if nr_client.available():
            return nr_client.start_job(nr_settings())
        nr_runtime.job.start(nr_settings(), reset=False)
        return nr_runtime.job.summary()
    def nr_control(action):
        if nr_runtime.job.thread is not None and nr_runtime.job.thread.is_alive():
            getattr(nr_runtime.job, action)()
            return nr_runtime.job.summary()
        if nr_client.available():
            return nr_client.control(action)
        getattr(nr_runtime.job, action)()
        return nr_runtime.job.summary()
    def nr_draft():
        nr_runtime.ensure_idle()
        nr_checkpoints.save_draft(nr_settings())
        return "Đã lưu cấu hình."
    def nr_hf_configure():
        nr_runtime.ensure_idle()
        repo = nr_hf_repo.value.strip()
        if len(repo.split("/")) != 2 or any(not x for x in repo.split("/")):
            raise ValueError("Kho HF phải theo dạng tài_khoản/tên_bucket.")
        nr_save_repo_id(repo)  # Shared config read by both notebook and FastAPI.
        if nr_hf_token.value.strip():
            os.environ["HF_TOKEN"] = nr_hf_token.value.strip()
            nr_save_key(nr_hf_token.value.strip())
        return nr_hf.check_connection()
    def nr_hf_create():
        nr_runtime.ensure_idle()
        if nr_hf_token.value.strip():
            os.environ["HF_TOKEN"] = nr_hf_token.value.strip()
            nr_save_key(nr_hf_token.value.strip())
        repo = nr_hf_repo.value.strip()
        if len(repo.split("/")) != 2 or any(not x for x in repo.split("/")):
            raise ValueError("Nhập bucket theo dạng tài_khoản/tên_bucket.")
        nr_hf.client().create_bucket(bucket_id=repo, private=True, exist_ok=True)
        return nr_hf_configure()
    def nr_local_backup():
        with nr_runtime.job.lock:
            nr_runtime.ensure_idle()
            folder = repo_dir / "notebook_exports"
            folder.mkdir(exist_ok=True)
            target = folder / ("NovelReader_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + ".zip")
            nr_checkpoints.create_checkpoint(nr_runtime.store, target, nr_include_audio.value)
            return "Đã tạo " + target.name + ". Tải ở tab Kết quả."
    def nr_cloud_backup():
        with nr_runtime.job.lock:
            nr_runtime.ensure_idle()
            return nr_checkpoints.upload_checkpoint(nr_runtime.store, nr_include_audio.value)
    def nr_restore():
        if not nr_restore_confirm.value:
            raise ValueError("Cần đánh dấu xác nhận khôi phục sẽ thay dữ liệu hiện tại.")
        with nr_runtime.job.lock:
            nr_runtime.ensure_idle()
            with tempfile.TemporaryDirectory() as work:
                target = Path(work) / "checkpoint.zip"
                if nr_restore_upload.value:
                    target.write_bytes(nr_restore_upload.value[0].contents)
                elif nr_restore_link.value.strip():
                    nr_checkpoints.download_checkpoint(nr_restore_link.value.strip(), target)
                else:
                    raise ValueError("Chọn ZIP checkpoint hoặc nhập đường dẫn HF.")
                result = nr_checkpoints.restore_checkpoint(nr_runtime.store, target)
                nr_runtime.job.target_chapter_ids = None
                nr_runtime.job.scope_label = ""
                nr_runtime.job.status = "ready"
                return result
    def nr_merge():
        from audio import merge_service
        with nr_runtime.job.lock:
            nr_runtime.ensure_idle()
            return {"groups": merge_service.group_and_merge_chapters(nr_runtime.store, group_size=int(nr_group_size.value), fmt=nr_format.value)}
    def nr_button(label, fn, kind="neutral"):
        return mo.ui.button(label=label, kind=kind, on_click=lambda value: (nr_run_task(label, fn), (value or 0)+1)[1], value=0)
    nr_upload = mo.ui.file(filetypes=[".txt", ".epub", ".zip"], max_size=50*1024*1024, label="Chọn truyện TXT / EPUB / ZIP")
    nr_replace = mo.ui.checkbox(label="Cho phép thay truyện hiện tại khi nạp file")
    nr_model = mo.ui.dropdown(options=["HachimiMT-60-QT", "HachimiMT-40-QT", "HachimiMT-30"], value=model_selector.value, label="Model dịch")
    nr_batch = mo.ui.number(start=1, stop=1024, value=96, label="Batch size")
    nr_start = mo.ui.number(start=1, value=1, label="Từ chương")
    nr_end = mo.ui.number(start=0, value=0, label="Đến chương (0 = hết)")
    nr_glossary = mo.ui.text_area(label="Thuật ngữ / tên riêng", full_width=True)
    nr_honorific = mo.ui.dropdown(options={"Tự nhiên, an toàn":"safe", "Tiên hiệp":"xianxia_strict", "Tắt":"off"}, value="Tự nhiên, an toàn", label="Xưng hô")
    nr_make_audio = mo.ui.checkbox(value=True, label="Tạo audio sau khi dịch")
    nr_tts = mo.ui.dropdown(options=["piper", "vieneu"], value="piper", label="Bộ đọc")
    nr_voice = mo.ui.text(value="ngochuyennew", label="Mã giọng (VieNeu: truc_ly)")
    nr_speed = mo.ui.slider(start=0.4, stop=2.5, step=0.1, value=1.0, label="Tốc độ")
    nr_format = mo.ui.dropdown(options=["mp3", "m4b", "m4a", "wav", "opus"], value="mp3", label="Định dạng")
    nr_bitrate = mo.ui.dropdown(options=["64k", "96k", "128k", "192k"], value="96k", label="Bitrate")
    nr_group = mo.ui.checkbox(label="Tự động gộp audio")
    nr_group_size = mo.ui.number(start=2, stop=500, value=50, label="Số chương / nhóm")
    nr_hf_repo = mo.ui.text(value=nr_hf.repo_id(), label="Bucket Hugging Face", full_width=True)
    nr_hf_token = mo.ui.text(kind="password", label="Token HF mới (bỏ trống để giữ token đã cấu hình)", full_width=True)
    nr_include_audio = mo.ui.checkbox(label="Kèm audio trong checkpoint")
    nr_cloud_auto = mo.ui.checkbox(value=True, label="Tự đồng bộ tiến độ lên Hugging Face")
    nr_restore_upload = mo.ui.file(filetypes=[".zip"], max_size=2*1024**3, label="Checkpoint ZIP")
    nr_restore_link = mo.ui.text(label="Hoặc đường dẫn checkpoint trên HF", full_width=True)
    nr_restore_confirm = mo.ui.checkbox(label="Tôi đồng ý thay dữ liệu hiện tại bằng checkpoint")
    nr_refresh = mo.ui.refresh(options=[2,5,10,30], default_interval=5, label="Làm mới tiến độ (giây)")
    nr_controls = mo.ui.tabs({
        "📥 Truyện": mo.vstack([mo.md("### Nạp truyện\nFile tối đa 50 MB. Nạp truyện sẽ thay truyện đang có."), nr_upload, nr_replace, nr_button("Nạp truyện", nr_import_uploaded, "success")]),
        "⚙️ Dịch & giọng": mo.vstack([mo.hstack([nr_model,nr_batch]), mo.hstack([nr_start,nr_end,nr_honorific]), nr_glossary, nr_make_audio, mo.hstack([nr_tts,nr_voice,nr_speed]), mo.hstack([nr_format,nr_bitrate]), mo.hstack([nr_group,nr_group_size]), nr_button("Lưu cấu hình",nr_draft)]),
        "☁️ Hugging Face": mo.vstack([nr_hf_repo,nr_hf_token,nr_button("Áp dụng & kiểm tra HF",nr_hf_configure),mo.md("Nếu kho chưa tồn tại, nút dưới tạo bucket riêng tư trong tài khoản có quyền ghi."),nr_button("Tạo bucket HF riêng tư",nr_hf_create),nr_cloud_auto,mo.md("Tự lưu bản dịch và SQLite sau mỗi 10 chương hoặc 10 phút, cùng một bản khi kết thúc; audio không nằm trong bản tự lưu."),nr_include_audio,mo.hstack([nr_button("Tạo checkpoint ZIP",nr_local_backup),nr_button("Sao lưu lên HF",nr_cloud_backup)]),mo.md("### Khôi phục"),nr_restore_upload,nr_restore_link,nr_restore_confirm,nr_button("Khôi phục checkpoint",nr_restore,"warn")]),
    })
    mo.vstack([mo.md("# 📚 NovelReader — Bảng điều khiển notebook"),
        mo.hstack([nr_button("▶ Bắt đầu / tiếp tục chương chưa dịch", nr_start_job,"success"), nr_button("⏸ Tạm dừng", lambda: nr_control("pause")),nr_button("▶ Tiếp tục",lambda: nr_control("resume")),nr_button("■ Hủy tác vụ",lambda: nr_control("stop"),"danger")]),
        nr_controls,mo.hstack([nr_button("Gộp audio đã có", nr_merge),nr_refresh])])
    return (
        nr_bitrate,
        nr_button,
        nr_format,
        nr_refresh,
        nr_speed,
        nr_tts,
        nr_voice,
    )


@app.cell
def _(mo, nr_client, nr_get_notice, nr_refresh, nr_runtime, repo_dir):
    # NOVELREADER_NATIVE_PROGRESS
    _ = nr_refresh.value
    try:
        _nr_summary = nr_client.state()["progress"] if nr_client.available() else nr_runtime.job.summary()
    except (OSError, ValueError):
        _nr_summary = nr_runtime.job.summary()
    _nr_book = nr_runtime.store.book()
    _nr_rows = nr_runtime.store.list() if _nr_book else []
    _nr_done = int(_nr_summary.get("done",0))
    _nr_total = int(_nr_summary.get("total",0))
    _nr_log = repo_dir / "data/logs/app.log"
    _nr_log_text = "\n".join(_nr_log.read_text(errors="replace").splitlines()[-35:]) if _nr_log.is_file() else "Chưa có nhật ký."
    _nr_notice = nr_get_notice()
    mo.vstack([mo.md("## 📊 Tiến độ"),mo.callout(mo.plain_text(_nr_notice)),
        mo.md(f"**Truyện:** {(_nr_book or {}).get('title','Chưa nạp')} · **Trạng thái:** {_nr_summary['status']} · **Hoàn tất:** {_nr_done}/{_nr_total}"),
        mo.md(_nr_summary.get("message", "")),
        mo.ui.table([{k:r.get(k) for k in ("position","title","status","audio_status")} for r in _nr_rows[:200]], selection=None, page_size=10) if _nr_rows else mo.md("Nạp truyện ở bảng điều khiển để bắt đầu."),
        mo.accordion({"Nhật ký gần nhất":mo.ui.code_editor(value=_nr_log_text,language="text",disabled=True)})])
    return


@app.cell
def _(
    mo,
    nr_bitrate,
    nr_button,
    nr_format,
    nr_runtime,
    nr_speed,
    nr_tts,
    nr_voice,
):
    # NOVELREADER_NATIVE_RESULTS_CONTROLS
    nr_chapter_no = mo.ui.number(start=1, value=1, label="Chương muốn xem / nghe")
    nr_results_refresh = mo.ui.run_button(label="Làm mới kết quả và danh sách tải")
    def nr_single_audio():
        from web.routes.audio import generate_single_audio
        from web.schemas import AudioSettingsPatch
        _chapter = next((r for r in nr_runtime.store.list() if r["position"]==int(nr_chapter_no.value)), None)
        if not _chapter:
            raise ValueError("Không tìm thấy chương.")
        return generate_single_audio(_chapter["id"], AudioSettingsPatch(tts_engine=nr_tts.value, voice_id=nr_voice.value.strip(), audio_speed=float(nr_speed.value), audio_format=nr_format.value, audio_bitrate=nr_bitrate.value))
    mo.vstack([mo.md("## 📖 Kết quả & tải xuống"), mo.hstack([nr_chapter_no,nr_results_refresh,nr_button("Tạo lại audio chương đang chọn",nr_single_audio)])])
    return nr_chapter_no, nr_results_refresh


@app.cell
def _(
    mo,
    nr_audio,
    nr_chapter_no,
    nr_export_epub,
    nr_export_txt,
    nr_results_refresh,
    nr_runtime,
    repo_dir,
):
    # NOVELREADER_NATIVE_RESULTS
    _ = nr_results_refresh.value
    _nr_position = int(nr_chapter_no.value)
    _nr_all_rows = nr_runtime.store.list()
    _nr_row = next((r for r in _nr_all_rows if r["position"]==_nr_position), None)
    _nr_result_parts = []
    if _nr_row:
        _nr_chapter = nr_runtime.store.get(_nr_row["id"])
        _nr_result_parts.append(mo.md("### " + str(_nr_chapter.get("translated_title") or _nr_chapter["title"])))
        _nr_result_parts.append(mo.ui.code_editor(value="\n\n".join(_nr_chapter.get("translated") or []), language="text",disabled=True))
        _nr_audio_path = nr_audio.get_chapter_audio_path(nr_runtime.store.audio_dir,_nr_row["id"],_nr_position)
        if _nr_audio_path and _nr_audio_path.is_file():
            _nr_result_parts.extend([mo.audio(_nr_audio_path),mo.download(data=lambda p=_nr_audio_path:p.read_bytes(), filename=_nr_audio_path.name,label="Tải audio chương")])
        else:
            _nr_result_parts.append(mo.md("Chương này chưa có audio."))
    else:
        _nr_result_parts.append(mo.md("Chưa có chương được chọn."))
    _nr_current_book=nr_runtime.store.book()
    if _nr_current_book:
        def _nr_text_download(fmt):
            _b=nr_runtime.store.book()
            _rows=[nr_runtime.store.get(r["id"]) for r in nr_runtime.store.list()]
            return (nr_export_txt if fmt=="txt" else nr_export_epub)(_b,_rows)
        _nr_result_parts.append(mo.hstack([mo.download(data=lambda:_nr_text_download("txt"),filename="translated.txt",label="Tải bản dịch TXT"),mo.download(data=lambda:_nr_text_download("epub"),filename="translated.epub",label="Tải bản dịch EPUB")]))
        _nr_audio_files=nr_audio.exportable_audio_files(nr_runtime.store.audio_dir)
        _nr_result_parts.append(mo.accordion({"Audio và nhóm đã gộp":mo.vstack([mo.download(data=lambda p=p:p.read_bytes(),filename=p.name,label=p.name) for p in _nr_audio_files[:100]]) if _nr_audio_files else mo.md("Chưa có audio.")}))
    _nr_backups=sorted((repo_dir/"notebook_exports").glob("*.zip"),reverse=True)
    if _nr_backups:
        _nr_result_parts.append(mo.accordion({"Checkpoint ZIP":mo.vstack([mo.download(data=lambda p=p:p.read_bytes(),filename=p.name,label=p.name) for p in _nr_backups[:20]])}))
    mo.vstack(_nr_result_parts)
    return


@app.cell
def _(mo):
    mo.md("""
    Nhấn **Làm mới kết quả và danh sách tải** sau khi dịch, tạo audio hoặc sao lưu. Token HF không được đưa vào checkpoint.
    """)
    return


@app.cell
def _(Path, json, subprocess, urllib):
    # ZROK_INSTALL
    import tarfile as _zr_tar
    _zr_dir=Path("/tmp/novelreader-zrok")
    _zr_dir.mkdir(exist_ok=True)
    with urllib.request.urlopen("https://api.github.com/repos/openziti/zrok/releases/latest",timeout=15) as _zr_response:
        _zr_release=json.load(_zr_response)
    _zr_asset=next(a for a in _zr_release["assets"] if a["name"].endswith("_linux_amd64.tar.gz"))
    _zr_archive=_zr_dir/"zrok.tar.gz"
    with urllib.request.urlopen(_zr_asset["browser_download_url"],timeout=30) as _zr_download:
        _zr_archive.write_bytes(_zr_download.read())
    with _zr_tar.open(_zr_archive) as _zr_package:
        _zr_member=next(m for m in _zr_package.getmembers() if Path(m.name).name in ("zrok2","zrok") and m.isfile())
        (_zr_dir/"zrok2").write_bytes(_zr_package.extractfile(_zr_member).read())
    (_zr_dir/"zrok2").chmod(0o700)
    print(subprocess.run([str(_zr_dir/"zrok2"),"version"],capture_output=True,text=True,timeout=10).stdout)
    print("zrok đã cài. Chờ đăng nhập myzrok.io để kích hoạt môi trường.")
    return


@app.cell
def _(Path, json, mo, os, repo_dir, subprocess, sys, urllib, zr_account_token):
    # ZROK_ENABLE_AND_SHARE
    import re as _zc_re
    import signal as _zc_signal
    import time as _zc_time
    import secrets as _zc_secrets
    import urllib.error as _zc_urllib_error

    zrok_url = ""
    zrok_access_code = ""
    _zc_token = str(zr_account_token).strip()
    if not _zc_token:
        mo.stop(True, mo.md("Thiếu token zrok trong ô cấu hình."))

    _zc_bin = Path("/tmp/novelreader-zrok/zrok2")
    if not _zc_bin.is_file():
        # Tự cài lại khi sandbox được relaunch và /tmp bị làm sạch.
        import json as _zc_json
        import tarfile as _zc_tarfile
        import urllib.request as _zc_request
        _zc_dir = _zc_bin.parent
        _zc_dir.mkdir(parents=True, exist_ok=True)
        try:
            with _zc_request.urlopen("https://api.github.com/repos/openziti/zrok/releases/latest", timeout=20) as _zc_response:
                _zc_release = _zc_json.load(_zc_response)
            _zc_asset = next(a for a in _zc_release["assets"] if a["name"].endswith("_linux_amd64.tar.gz"))
            _zc_archive = _zc_dir / "zrok.tar.gz"
            with _zc_request.urlopen(_zc_asset["browser_download_url"], timeout=60) as _zc_download:
                _zc_archive.write_bytes(_zc_download.read())
            with _zc_tarfile.open(_zc_archive) as _zc_package:
                _zc_member = next(m for m in _zc_package.getmembers() if Path(m.name).name in ("zrok2", "zrok") and m.isfile())
                _zc_bin.write_bytes(_zc_package.extractfile(_zc_member).read())
            _zc_bin.chmod(0o700)
            print("Đã tự cài lại zrok:", subprocess.run([str(_zc_bin), "version"], capture_output=True, text=True, timeout=10).stdout.strip())
        except Exception as _zc_install_error:
            print("Tự cài zrok thất bại:", type(_zc_install_error).__name__, str(_zc_install_error))
            mo.stop(True, mo.md("Không tải/cài được zrok; xem lỗi ở output phía trên."))

    # Khởi động WebUI nếu sandbox vừa kết nối lại và server chưa chạy.
    _zc_web_log = repo_dir / "data/logs/webui.log"
    _zc_web_log.parent.mkdir(parents=True, exist_ok=True)

    def _zc_http_status():
        try:
            with urllib.request.urlopen("http://127.0.0.1:8000/", timeout=3) as _zc_resp:
                return _zc_resp.status
        except _zc_urllib_error.HTTPError as _zc_err:
            return _zc_err.code
        except Exception:
            return 0

    zrok_access_code = os.environ.get("NOVEL_WEB_ACCESS_TOKEN", "").strip()
    if not zrok_access_code:
        zrok_access_code = _zc_secrets.token_urlsafe(9)
        os.environ["NOVEL_WEB_ACCESS_TOKEN"] = zrok_access_code


    _zc_running_pid = ""
    _zc_running_token = ""
    for _zc_pid in os.listdir("/proc"):
        if not _zc_pid.isdigit():
            continue
        try:
            with open("/proc/" + _zc_pid + "/cmdline", "rb") as _zc_f:
                _zc_cmd = _zc_f.read().replace(bytes([0]), b" ").decode("utf-8", "replace")
            if "uvicorn" not in _zc_cmd or "main:app" not in _zc_cmd or "8000" not in _zc_cmd:
                continue
            _zc_running_pid = _zc_pid
            with open("/proc/" + _zc_pid + "/environ", "rb") as _zc_f:
                for _zc_item in _zc_f.read().split(bytes([0])):
                    if _zc_item.startswith(b"NOVEL_WEB_ACCESS_TOKEN="):
                        _zc_running_token = _zc_item.split(b"=", 1)[1].decode("utf-8", "replace")
                        break
            break
        except OSError:
            continue


    _zc_status = _zc_http_status()
    _zc_web_running = bool(_zc_running_pid) and _zc_running_token == zrok_access_code and _zc_status == 200
    if _zc_running_pid and not _zc_web_running:
        # Dừng server cũ nếu nó đang dùng mã khác; không đổi mã giữa lúc xử lý truyện.
        try:
            _zc_state_req = urllib.request.Request(
                "http://127.0.0.1:8000/api/state",
                headers={"X-Novel-Access": _zc_running_token},
            )
            with urllib.request.urlopen(_zc_state_req, timeout=3) as _zc_state_resp:
                _zc_state = json.loads(_zc_state_resp.read())
            if _zc_state.get("progress", {}).get("active"):
                mo.stop(True, mo.md("Tác vụ NovelReader đang chạy; dừng tác vụ trước khi đổi mã truy cập."))
        except Exception:
            pass
        try:
            os.kill(int(_zc_running_pid), _zc_signal.SIGTERM)
        except (OSError, ValueError):
            pass
        for _zc_wait in range(20):
            _zc_status = _zc_http_status()
            if _zc_status != 200:
                break
            _zc_time.sleep(0.5)
        if _zc_status == 200:
            print("Server cũ chưa dừng được; giữ nguyên để tránh tạo server trùng.")
            mo.stop(True, mo.md("Không thể khởi động lại WebUI an toàn; hãy reconnect sandbox rồi chạy lại ô này."))
        _zc_web_running = False


    if not _zc_web_running:
        _zc_web_out = open(_zc_web_log, "w", encoding="utf-8")
        _zc_web_proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"],
            cwd=str(repo_dir),
            stdin=subprocess.DEVNULL,
            stdout=_zc_web_out,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        _zc_web_out.close()
        for _zc_try in range(45):
            _zc_status = _zc_http_status()
            if _zc_status == 200:
                break
            _zc_time.sleep(1)


    if _zc_status != 200:
        print("WebUI chưa lên được; log:")
        try:
            print(_zc_web_log.read_text(errors="replace")[-5000:])
        except OSError:
            pass
        mo.stop(True, mo.md("WebUI chưa sẵn sàng trên cổng 8000; xem log ngay phía trên."))

    print("WebUI HTTP:", _zc_status)

    # Dùng lại environment zrok hiện có; chỉ enable nếu sandbox chưa có environment.
    _zc_status_result = subprocess.run(
        [str(_zc_bin), "status"], capture_output=True, text=True, timeout=15
    )
    _zc_status_text = _zc_status_result.stdout + _zc_status_result.stderr
    _zc_env_line = next((line for line in _zc_status_text.splitlines() if "EnvZId" in line), "")
    _zc_env_enabled = "<<SET>>" in _zc_env_line

    if not _zc_env_enabled:
        _zc_enable = subprocess.run(
            [str(_zc_bin), "enable", _zc_token, "--headless"],
            capture_output=True, text=True, timeout=60
        )
        if _zc_enable.returncode != 0:
            _zc_status_result = subprocess.run(
                [str(_zc_bin), "status"], capture_output=True, text=True, timeout=15
            )
            _zc_status_text = _zc_status_result.stdout + _zc_status_result.stderr
            _zc_env_line = next((line for line in _zc_status_text.splitlines() if "EnvZId" in line), "")
            if "<<SET>>" not in _zc_env_line:
                print((_zc_enable.stdout + _zc_enable.stderr)[-3000:])
                mo.stop(True, mo.md("Không enable được zrok; xem lỗi ở output phía trên."))

    # Dừng share cũ để mỗi lần chạy bắt URL mới và không để lại tunnel lặp.
    for _zc_pid in os.listdir("/proc"):
        if not _zc_pid.isdigit():
            continue
        try:
            with open("/proc/" + _zc_pid + "/cmdline", "rb") as _zc_f:
                _zc_cmd = _zc_f.read().replace(bytes([0]), b" ").decode("utf-8", "replace")
            if "zrok2" in _zc_cmd and "share public" in _zc_cmd:
                os.kill(int(_zc_pid), _zc_signal.SIGTERM)
        except (OSError, ValueError):
            pass
    _zc_time.sleep(1)

    _zc_share_log = repo_dir / "data/logs/zrok_share.log"
    _zc_share_log.parent.mkdir(parents=True, exist_ok=True)
    _zc_share_log.write_text("", encoding="utf-8")
    _zc_share_out = open(_zc_share_log, "w", encoding="utf-8")
    _zc_share_proc = subprocess.Popen(
        [str(_zc_bin), "share", "public", "http://127.0.0.1:8000", "--headless"],
        cwd=str(repo_dir),
        stdin=subprocess.DEVNULL,
        stdout=_zc_share_out,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    _zc_share_out.close()

    _zc_host = ""
    _zc_log_text = ""
    for _zc_try in range(60):
        if _zc_share_log.exists():
            _zc_log_text = _zc_share_log.read_text(errors="replace")
            from server.tunnel.zrok import extract_share_host
            _zc_host = extract_share_host(_zc_log_text)
            if _zc_host:
                break
        if _zc_share_proc.poll() is not None:
            break
        _zc_time.sleep(1)

    if not _zc_host:
        print("zrok share chưa trả về URL; log:")
        print(_zc_log_text[-5000:])
        mo.stop(True, mo.md("Chưa lấy được URL zrok; xem log ngay phía trên."))

    zrok_url = "https://" + _zc_host + "/"

    # Lấy mã truy cập từ môi trường của WebUI đang phục vụ cổng 8000.
    zrok_access_code = os.environ.get("NOVEL_WEB_ACCESS_TOKEN", "").strip()
    if not zrok_access_code:
        for _zc_pid in os.listdir("/proc"):
            if not _zc_pid.isdigit():
                continue
            try:
                with open("/proc/" + _zc_pid + "/cmdline", "rb") as _zc_f:
                    _zc_cmd = _zc_f.read().replace(bytes([0]), b" ").decode("utf-8", "replace")
                if "uvicorn" not in _zc_cmd or "main:app" not in _zc_cmd:
                    continue
                with open("/proc/" + _zc_pid + "/environ", "rb") as _zc_f:
                    for _zc_item in _zc_f.read().split(bytes([0])):
                        if _zc_item.startswith(b"NOVEL_WEB_ACCESS_TOKEN="):
                            zrok_access_code = _zc_item.split(b"=", 1)[1].decode("utf-8", "replace")
                            break
                if zrok_access_code:
                    break
            except OSError:
                pass

    print("ZROK_URL:", zrok_url)
    if not zrok_access_code:
        print("Chưa tìm thấy mã truy cập trong môi trường WebUI.")
    return zrok_access_code, zrok_url


@app.cell
def _(json, urllib):
    # ZROK_RELEASE_CHECK
    with urllib.request.urlopen("https://api.github.com/repos/openziti/zrok/releases?per_page=10",timeout=15) as _zr_meta:
        _zr_releases=json.load(_zr_meta)
    print([(r["tag_name"],[a["name"] for a in r["assets"] if "linux_amd64" in a["name"]]) for r in _zr_releases])
    return


@app.cell
def _(os):
    # ZROK_ACCOUNT_TOKEN_INPUT: set a new token in the MoLab runtime environment.
    zr_account_token = os.environ.get("ZROK_ACCOUNT_TOKEN", "").strip()
    return (zr_account_token,)


@app.cell
def _(repo_dir, subprocess):
    # ZROK_STATUS_CHECK
    for _zs_args in [["status"],["enable","--help"],["share","public","--help"]]:
        _zs_result=subprocess.run(["/tmp/novelreader-zrok/zrok2"]+_zs_args,capture_output=True,text=True,timeout=10)
        print("COMMAND:",_zs_args,"EXIT:",_zs_result.returncode)
        print((_zs_result.stdout+_zs_result.stderr)[-7500:])
    _zr_log=repo_dir/"data/logs/zrok_share.log"
    if _zr_log.exists():
        print(_zr_log.read_text(errors="replace")[-5000:])
    else:
        print("Chưa có log share zrok. Nhập token rồi chạy ô ZROK_ENABLE_AND_SHARE.")
    return


@app.cell(hide_code=True)
def _(mo, zrok_access_code, zrok_url):
    mo.md(rf"""
    ## 🔗 Link truy cập zrok

    {('[**Mở NovelReader qua zrok**](' + zrok_url + ')') if zrok_url else 'Link zrok chưa sẵn sàng; chạy lại ô Web + zrok.'}

    **Địa chỉ:** {zrok_url or 'chưa sẵn sàng'}

    **Mã truy cập:** {zrok_access_code or 'chưa tìm thấy'}

    *Tự cập nhật mỗi lần chạy ô zrok.*
    """)
    return


if __name__ == "__main__":
    app.run()
