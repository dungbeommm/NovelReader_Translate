"""NovelReader WebUI launcher shared by MoLab (Marimo) and Google Colab.

The notebook is deliberately just an installer, server/tunnel launcher and log viewer.
All translation, audio, HF file management and job controls live in the WebUI.
"""
from __future__ import annotations

import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import secrets
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request

URL_LOCAL = "http://127.0.0.1:8000/"
ZROK_INSTALL = Path("/tmp/novelreader-zrok/zrok2")
NEEDED = (
    "fastapi", "uvicorn", "websockets", "python-multipart", "pydantic",
    "ebooklib", "beautifulsoup4", "charset-normalizer", "huggingface-hub",
    "ctranslate2", "sentencepiece", "gradio-client",
    "opencc-python-reimplemented", "piper-tts", "psutil",
)


def _say(message):
    print(message, flush=True)


def tail(path, lines=55):
    path = Path(path)
    if not path.is_file():
        return "(chưa có log)"
    try:
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-max(1, lines):])
    except OSError as exc:
        return f"(không đọc được log: {exc})"


def _run(command, **kwargs):
    return subprocess.run(command, text=True, capture_output=True, **kwargs)


def _gpu():
    try:
        result = _run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            timeout=10)
        if result.returncode == 0 and result.stdout.strip():
            first = result.stdout.splitlines()[0].split(",", 1)
            return first[0].strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return ""


def prepare_environment(repo_dir):
    repo_dir = Path(repo_dir).resolve()
    folders = {
        "NOVEL_DATA": "data",
        "NOVEL_MODELS": "models/translation",
        "HACHIMIMT_MODELS_DIR": "models/translation",
        "TTS_VOICE_DIR": "models/voices",
        "NOVEL_OUTPUT_TEXT": "output_text",
        "NOVEL_OUTPUT_AUDIO": "output_audio",
        "VIENEU_MODEL_DIR": "models/vieneu",
    }
    for key, relative in folders.items():
        absolute = repo_dir / relative
        absolute.mkdir(parents=True, exist_ok=True)
        os.environ[key] = str(absolute)
    os.environ["ALLOWED_HOSTS"] = "127.0.0.1,localhost"
    os.environ["ALLOW_TUNNEL"] = "1"
    os.environ.setdefault("PIPER_DEVICE", "auto")
    os.environ.setdefault("NOVEL_TTS_ENGINE", "piper")
    os.environ.setdefault("NOVEL_TTS_VOICE", "ngochuyennew")
    os.environ["PYTHONUNBUFFERED"] = "1"
    gpu = _gpu()
    if gpu:
        os.environ["COLAB_GPU"] = "1"
        os.environ.setdefault("AUDIO_WORKERS", "2")
        _say("GPU NVIDIA: " + gpu)
    else:
        os.environ.pop("COLAB_GPU", None)
        os.environ.setdefault("AUDIO_WORKERS", "1")
        _say("GPU: chưa có (chế độ CPU).")
    return gpu


def ensure_dependencies(repo_dir):
    missing = []
    for name in NEEDED:
        try:
            importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            missing.append(name)
    if missing:
        _say("Cài đặt requirements.txt (thiếu: " + ", ".join(missing) + ")")
        result = _run(
            [sys.executable, "-m", "pip", "install", "-r", str(Path(repo_dir) / "requirements.txt")],
            timeout=1500)
        if result.returncode:
            _say((result.stdout + "\n" + result.stderr)[-6000:])
            raise RuntimeError("Cài requirements.txt thất bại.")
        _say("Đã cài đặt các thư viện Python.")
    else:
        _say("Thư viện Python đã có.")
    if sys.platform.startswith("linux") and os.geteuid() == 0:
        absent = [x for x in ("ffmpeg", "espeak-ng") if not shutil.which(x)]
        if absent and shutil.which("apt-get"):
            _say("Bổ sung công cụ hệ thống: " + ", ".join(absent))
            result = _run(["apt-get", "update", "-qq"], timeout=150)
            if result.returncode == 0:
                result = _run(["apt-get", "install", "-y", "-qq", *absent], timeout=300)
            if result.returncode:
                _say("Cảnh báo: apt-get không hoàn tất; TTS có thể thiếu phụ thuộc.")


def _http_state(token, timeout=3):
    headers = {"X-Novel-Access": token} if token else {}
    req = urllib.request.Request(URL_LOCAL + "api/state", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except (OSError, ValueError, urllib.error.URLError):
        return 0, None


def _commandline(pid):
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
    except OSError:
        return ""


def _server_process():
    proc = Path("/proc")
    if not proc.is_dir():
        return None, None
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        command = _commandline(entry.name)
        if "uvicorn" not in command or "main:app" not in command or "8000" not in command:
            continue
        token = ""
        try:
            for part in (entry / "environ").read_bytes().split(b"\0"):
                if part.startswith(b"NOVEL_WEB_ACCESS_TOKEN="):
                    token = part.partition(b"=")[2].decode("utf-8", "replace")
                    break
        except OSError:
            pass
        return int(entry.name), token
    return None, None


def _token_file(repo_dir):
    return Path(repo_dir) / "data/private/web_access_token"


def _save_access_token(repo_dir, value):
    path = _token_file(repo_dir)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(value, encoding="utf-8")
    if os.name != "nt":
        path.chmod(0o600)


def ensure_webui(repo_dir):
    repo_dir = Path(repo_dir)
    pid, running_token = _server_process()
    desired = os.getenv("NOVEL_WEB_ACCESS_TOKEN", "").strip()
    if pid and running_token:
        desired = running_token
    if not desired:
        try:
            desired = _token_file(repo_dir).read_text(encoding="utf-8").strip()
        except OSError:
            pass
    if not desired:
        desired = secrets.token_urlsafe(18)
    os.environ["NOVEL_WEB_ACCESS_TOKEN"] = desired
    _save_access_token(repo_dir, desired)

    status, _ = _http_state(desired)
    if status == 200:
        _say("FastAPI đang chạy, giữ nguyên job và dữ liệu hiện tại.")
        return desired
    if status:
        # Never kill an existing WebUI just to replace its credentials.
        raise RuntimeError(
            f"Cổng 8000 đang có server HTTP {status} nhưng mã không khớp. "
            "Không khởi động thêm server hoặc dừng job đang chạy.")
    if pid:
        raise RuntimeError("Tiến trình Uvicorn tồn tại nhưng chưa phản hồi; xem log trước khi khởi động thêm.")

    log_file = repo_dir / "data/logs/webui.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("a", encoding="utf-8") as output:
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1",
             "--port", "8000", "--workers", "1"],
            cwd=str(repo_dir), env=dict(os.environ), stdin=subprocess.DEVNULL,
            stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
    (log_file.parent / "webui.pid").write_text(str(process.pid), encoding="ascii")
    for _ in range(60):
        status, _ = _http_state(desired, timeout=2)
        if status == 200:
            _say("FastAPI: HTTP 200 (sẵn sàng).")
            return desired
        if process.poll() is not None:
            break
        time.sleep(1)
    raise RuntimeError("FastAPI chưa khởi động: \n" + tail(log_file, 60))


def _zrok_binary():
    if ZROK_INSTALL.is_file():
        return str(ZROK_INSTALL)
    if not sys.platform.startswith("linux"):
        raise RuntimeError("Trình tự cài zrok tự động hiện hỗ trợ Linux (MoLab/Colab).")
    arch = platform.machine().lower()
    arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(arch, arch)
    with urllib.request.urlopen(
        "https://api.github.com/repos/openziti/zrok/releases/latest", timeout=25
    ) as response:
        release = json.load(response)
    assets = [
        a for a in release.get("assets", [])
        if a["name"].endswith("_linux_" + arch + ".tar.gz")
    ]
    if not assets:
        raise RuntimeError("Không có zrok2 Linux " + arch + " trong bản phát hành.")
    ZROK_INSTALL.parent.mkdir(parents=True, exist_ok=True)
    archive = ZROK_INSTALL.parent / "zrok.tar.gz"
    with urllib.request.urlopen(assets[0]["browser_download_url"], timeout=90) as response:
        with archive.open("wb") as out:
            shutil.copyfileobj(response, out)
    with tarfile.open(archive, "r:gz") as package:
        member = next(
            (m for m in package.getmembers()
             if Path(m.name).name in ("zrok2", "zrok") and m.isfile()), None)
        if member is None:
            raise RuntimeError("Không tìm thấy zrok2 trong tar.gz.")
        with package.extractfile(member) as stream, ZROK_INSTALL.open("wb") as out:
            shutil.copyfileobj(stream, out)
    ZROK_INSTALL.chmod(0o700)
    archive.unlink(missing_ok=True)
    return str(ZROK_INSTALL)


def _zrok_process(repo_dir):
    log_dir = Path(repo_dir) / "data/logs"
    pid_file = log_dir / "zrok_share.pid"
    try:
        pid = int(pid_file.read_text().strip())
        if "share public" in _commandline(pid) and "zrok" in _commandline(pid):
            return pid
    except (OSError, ValueError):
        pass
    # Adopt a share created by an older notebook in the same sandbox.
    if Path("/proc").is_dir():
        for entry in Path("/proc").iterdir():
            if entry.name.isdigit():
                command = _commandline(entry.name)
                if "zrok" in command and "share public" in command:
                    return int(entry.name)
    return None


def ensure_zrok(repo_dir, token):
    from server.tunnel.zrok import extract_share_host, public_share_command

    if not token:
        _say("Chưa có ZROK_ACCOUNT_TOKEN: chỉ khởi động WebUI cục bộ.")
        return "", "Thiếu token zrok; điền ZROK_ACCOUNT_TOKEN_INLINE hoặc biến môi trường."
    executable = _zrok_binary()
    checked = _run([executable, "status"], timeout=20)
    message = checked.stdout + "\n" + checked.stderr
    enabled = any("EnvZId" in line and "<<SET>>" in line for line in message.splitlines())
    if not enabled:
        _say("Kích hoạt tài khoản zrok...")
        cmd = _run([executable, "enable", token, "--headless"], timeout=90)
        if cmd.returncode:
            checked = _run([executable, "status"], timeout=20)
            if not any("EnvZId" in line and "<<SET>>" in line for line in checked.stdout.splitlines()):
                return "", "Kích hoạt zrok thất bại: " + (cmd.stderr + "\n" + cmd.stdout)[-800:]

    logs = Path(repo_dir) / "data/logs"
    log = logs / "zrok_share.log"
    existing_pid = _zrok_process(repo_dir)
    if existing_pid:
        host = extract_share_host(tail(log, 200))
        if host:
            _say("Giữ nguyên tunnel zrok đang chạy.")
            return "https://" + host + "/", ""
        # Do not start a second share or kill an existing one.
        return "", "Tunnel zrok đang chạy nhưng chưa nhận được URL; xem log bên dưới."

    with log.open("w", encoding="utf-8") as output:
        process = subprocess.Popen(
            public_share_command(executable),
            cwd=str(repo_dir), env=dict(os.environ), stdin=subprocess.DEVNULL,
            stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
    (logs / "zrok_share.pid").write_text(str(process.pid), encoding="ascii")
    for _ in range(60):
        host = extract_share_host(tail(log, 200))
        if host:
            return "https://" + host + "/", ""
        if process.poll() is not None:
            break
        time.sleep(1)
    return "", "zrok không trả về URL: \n" + tail(log, 60)


def _localtunnel_command():
    if not shutil.which("node") or not shutil.which("npm"):
        if not (sys.platform.startswith("linux") and os.geteuid() == 0
                and shutil.which("apt-get")):
            raise RuntimeError("Cần cài Node.js và npm để chạy LocalTunnel.")
        _say("Cài Node.js và npm cho LocalTunnel...")
        for command in (["apt-get", "update", "-qq"],
                        ["apt-get", "install", "-y", "-qq", "nodejs", "npm"]):
            installed = _run(command, timeout=300)
            if installed.returncode:
                raise RuntimeError("Cài Node.js/npm thất bại: " + installed.stderr[-1500:])
    prefix = Path("/tmp/novelreader-localtunnel")
    client = prefix / "node_modules/localtunnel/bin/lt.js"
    if not client.is_file():
        _say("Cài LocalTunnel 2.0.2...")
        installed = _run(
            [shutil.which("npm"), "install", "--prefix", str(prefix),
             "--no-audit", "--no-fund", "localtunnel@2.0.2"], timeout=300)
        if installed.returncode:
            raise RuntimeError("Cài LocalTunnel thất bại: " + installed.stderr[-1500:])
    return [shutil.which("node"), str(client), "--port", "8000",
            "--local-host", "127.0.0.1"]


def ensure_localtunnel(repo_dir):
    logs = Path(repo_dir) / "data/logs"
    logs.mkdir(parents=True, exist_ok=True)
    log = logs / "localtunnel.log"
    pid_file = logs / "localtunnel.pid"
    pattern = re.compile(r"https://[a-z0-9-]+\.loca\.lt\b", re.I)
    existing = False
    try:
        command = _commandline(int(pid_file.read_text().strip()))
        existing = "localtunnel/bin/lt.js" in command and "--port 8000" in command
    except (OSError, ValueError):
        pass
    process = None
    if existing:
        _say("Giữ nguyên LocalTunnel đang chạy.")
    else:
        command = _localtunnel_command()
        with log.open("w", encoding="utf-8") as output:
            process = subprocess.Popen(
                command, cwd=str(repo_dir), env=dict(os.environ),
                stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                start_new_session=True)
        pid_file.write_text(str(process.pid), encoding="ascii")
    for _ in range(60):
        if process is not None and process.poll() is not None:
            break
        matches = pattern.findall(tail(log, 200))
        if matches:
            return matches[-1] + "/", ""
        time.sleep(1)
    return "", "LocalTunnel chưa trả URL; xem data/logs/localtunnel.log:\n" + tail(log, 60)


def _localtunnel_password():
    try:
        with urllib.request.urlopen("https://loca.lt/mytunnelpassword", timeout=15) as response:
            value = response.read(256).decode("utf-8").strip()
        # The public server expects the tunnel machine's public IP, not a WebUI token.
        import ipaddress
        return str(ipaddress.ip_address(value))
    except (OSError, ValueError):
        return ""


def launch(repo_dir, *, hf_token="", zrok_token="", tunnel="zrok"):
    if tunnel not in ("zrok", "localtunnel"):
        raise ValueError("Tunnel phải là zrok hoặc localtunnel.")
    repo_dir = Path(repo_dir).resolve()
    if not (repo_dir / "main.py").is_file():
        raise RuntimeError("Không thấy main.py trong repo NovelReader.")
    if hf_token.strip():
        os.environ["HF_TOKEN"] = hf_token.strip()
        os.environ["HUGGING_FACE_HUB_TOKEN"] = hf_token.strip()
    if zrok_token.strip():
        os.environ["ZROK_ACCOUNT_TOKEN"] = zrok_token.strip()
    _say("NovelReader — Chế độ chỉ khởi chạy và xem log (không có bảng điều khiển notebook).")
    gpu = prepare_environment(repo_dir)
    ensure_dependencies(repo_dir)
    access_code = ensure_webui(repo_dir)
    try:
        if tunnel == "localtunnel":
            url, tunnel_error = ensure_localtunnel(repo_dir)
        else:
            url, tunnel_error = ensure_zrok(repo_dir, os.getenv("ZROK_ACCOUNT_TOKEN", "").strip())
    except Exception as exc:
        url, tunnel_error = "", f"{type(exc).__name__}: {exc}"
    result = {
        "url": url,
        "local_url": URL_LOCAL,
        "access_code": access_code,
        "gpu": gpu or "CPU",
        "tunnel_error": tunnel_error,
        "repo_dir": str(repo_dir),
        "tunnel": tunnel,
        "tunnel_password": _localtunnel_password() if tunnel == "localtunnel" and url else "",
    }
    print_result(result)
    return result


def print_result(result):
    _say("\n" + "=" * 66)
    _say("  NOVELREADER — THÔNG TIN TRUY CẬP")
    _say("=" * 66)
    _say("WEBUI_URL: " + (result.get("url") or "CHƯA CÓ LINK PUBLIC"))
    _say("MA_TRUY_CAP: " + result.get("access_code", ""))
    _say("LOCAL_URL: " + result.get("local_url", URL_LOCAL))
    _say("TAI_NGUYEN: " + result.get("gpu", "CPU"))
    if result.get("tunnel") == "localtunnel":
        _say("TUNNEL_PASSWORD: " + (result.get("tunnel_password") or "Không lấy được; mở https://loca.lt/mytunnelpassword từ MoLab để kiểm tra."))
        _say("Nếu loca.lt hỏi Tunnel Password, nhập TUNNEL_PASSWORD; sau đó đăng nhập WebUI bằng MA_TRUY_CAP.")
    if result.get("tunnel_error"):
        _say("CANH_BAO_TUNNEL: " + result["tunnel_error"])
    _say("Mở WEBUI_URL và nhập MA_TRUY_CAP ở trang đăng nhập.")
    _say("=" * 66)


def print_logs(result, lines=45):
    root = Path(result["repo_dir"]) / "data/logs"
    for name, filename in (
        ("WEBUI / Uvicorn", "webui.log"),
        (("LOCALTUNNEL / Tunnel", "localtunnel.log") if result.get("tunnel") == "localtunnel"
         else ("ZROK / Tunnel", "zrok_share.log")),
        ("ỨNG DỤNG / JOB", "app.log"),
    ):
        _say("\n" + "-" * 16 + " LOGCAT " + name + " " + "-" * 16)
        _say(tail(root / filename, lines))
    _say("\nLog trực tiếp: tail -f " + str(root / "webui.log"))
