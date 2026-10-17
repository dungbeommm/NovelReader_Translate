"""Cài torch bản CUDA phù hợp để bật GPU cho CTranslate2.

Engine mặc định (CT2) cần thư viện cuBLAS/cuDNN để chạy GPU; cách đơn giản nhất
là cài bản torch CUDA (đã đóng gói sẵn các DLL đó). Module này:
  - chọn channel cu1xx cao nhất mà driver hỗ trợ,
  - chạy `pip install torch --index-url ...` vào CHÍNH python đang chạy (sys.executable),
  - stream log để UI hiển thị tiến trình.

Sau khi cài xong PHẢI khởi động lại app: torch phải có mặt TRƯỚC khi import
ctranslate2 (xem hardware._guard_ct2_cuda_before_import) thì GPU mới được bật.
"""

from __future__ import annotations

import subprocess
import os
import sys
from typing import Callable, Iterator

# Các channel CUDA mà PyTorch stable phát hành (cao → thấp). Xác minh tại
# https://pytorch.org/get-started/locally/ (hiện: cu118, cu126, cu128).
# (major, minor, "cuXXX")
_TORCH_CUDA_CHANNELS = [
    (12, 8, "cu128"),
    (12, 6, "cu126"),
    (11, 8, "cu118"),
]


def choose_cuda_channel(driver_cuda: str | None) -> str | None:
    """Chọn channel torch cao nhất mà driver còn hỗ trợ (driver_cuda dạng '13.2').

    NVIDIA backward-compatible: driver hỗ trợ tới CUDA X chạy được mọi wheel <= X.
    Trả None nếu driver quá cũ hơn cả bản thấp nhất (cu118).
    """
    if not driver_cuda:
        # Không biết driver → chọn bản phổ biến tương thích rộng nhất.
        return "cu118"
    try:
        major, minor = (int(part) for part in driver_cuda.split(".")[:2])
    except (ValueError, TypeError):
        return "cu118"
    for ch_major, ch_minor, channel in _TORCH_CUDA_CHANNELS:
        if (major, minor) >= (ch_major, ch_minor):
            return channel
    return None


def torch_install_command(channel: str) -> list[str]:
    # --upgrade --force-reinstall: BẮT BUỘC. Nếu user đã có torch-CPU (vd từ setup
    # cũ / requirements-pytorch), `pip install torch` thường báo "already satisfied"
    # và KHÔNG ghi đè → cài xong vẫn là CPU. Force-reinstall đảm bảo lấy bản CUDA.
    return [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--upgrade",
        "--force-reinstall",
        "torch",
        "--index-url",
        f"https://download.pytorch.org/whl/{channel}",
    ]


def verify_torch_cuda() -> tuple[bool, str]:
    """Sau khi cài, kiểm tra torch có thật sự thấy CUDA không (subprocess sạch).

    Chạy trong tiến trình con KHÔNG bị mask CUDA_VISIBLE_DEVICES=-1 (guard của app
    có thể đã set ở tiến trình hiện tại). Bắt trường hợp 'cài xong nhưng vẫn CPU'.
    """
    code = (
        "import torch,sys;"
        "print('TORCH_VERSION='+torch.__version__);"
        "print('CUDA_OK='+str(torch.cuda.is_available()))"
    )
    env = dict(os.environ)
    env.pop("CUDA_VISIBLE_DEVICES", None)  # bỏ mask để torch nhìn thấy GPU thật
    try:
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
    except Exception as exc:
        return False, f"Không kiểm tra được torch sau cài: {exc}"
    out = result.stdout
    version = ""
    for line in out.splitlines():
        if line.startswith("TORCH_VERSION="):
            version = line.split("=", 1)[1]
    cuda_ok = "CUDA_OK=True" in out
    if cuda_ok:
        return True, f"torch {version} đã nhận GPU."
    return False, (
        f"Đã cài torch {version or '(?)'} nhưng torch.cuda vẫn = False — "
        "có thể driver chưa phù hợp hoặc bản torch không khớp. Xem README."
    )


def verify_ct2_cuda() -> tuple[bool, str]:
    """Kiểm tra tiến trình mới có thể import torch CUDA rồi import CT2 CUDA.

    Đây là smoke test đúng đường app sau restart: torch phải được import trước để
    đăng ký thư mục DLL CUDA, rồi CTranslate2 mới dò và nạp CUDA/cuBLAS.
    """
    code = (
        "import os,sys;"
        "os.environ.pop('CUDA_VISIBLE_DEVICES', None);"
        "import torch;"
        "print('TORCH_VERSION='+torch.__version__);"
        "print('TORCH_CUDA_OK='+str(torch.cuda.is_available()));"
        "import ctranslate2;"
        "count=ctranslate2.get_cuda_device_count();"
        "print('CT2_VERSION='+ctranslate2.__version__);"
        "print('CT2_CUDA_COUNT='+str(count));"
        "types=ctranslate2.get_supported_compute_types('cuda') if count else set();"
        "print('CT2_CUDA_TYPES='+','.join(sorted(types)));"
        "sys.exit(0 if count > 0 else 2)"
    )
    env = dict(os.environ)
    env.pop("CUDA_VISIBLE_DEVICES", None)
    try:
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
    except Exception as exc:
        return False, f"Không kiểm tra được CTranslate2 CUDA: {exc}"

    stdout = result.stdout.strip()
    stderr = result.stderr.strip()
    count = ""
    version = ""
    types = ""
    for line in stdout.splitlines():
        if line.startswith("CT2_CUDA_COUNT="):
            count = line.split("=", 1)[1]
        elif line.startswith("CT2_VERSION="):
            version = line.split("=", 1)[1]
        elif line.startswith("CT2_CUDA_TYPES="):
            types = line.split("=", 1)[1]

    try:
        cuda_count = int(count)
    except ValueError:
        cuda_count = 0

    if result.returncode == 0 and cuda_count > 0:
        type_text = f", compute={types}" if types else ""
        return True, f"CTranslate2 {version or '(?)'} đã thấy {count} GPU CUDA{type_text}."

    detail = stdout or stderr or f"exit={result.returncode}"
    return False, (
        "torch đã nhận GPU nhưng CTranslate2 chưa qua smoke test CUDA. "
        f"Chi tiết: {detail}"
    )


def _stream_pip(cmd: list[str]) -> Iterator[str]:
    """Chạy pip, yield từng dòng output (cả stdout/stderr gộp)."""
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        yield line.rstrip()
    proc.wait()
    yield f"__EXIT__:{proc.returncode}"


def install_torch_cuda(
    driver_cuda: str | None,
    on_log: Callable[[str], None] | None = None,
) -> tuple[bool, str]:
    """Cài torch CUDA vào env hiện tại. Trả (thành công, thông điệp cuối).

    on_log nhận từng dòng log (để UI cập nhật). Đây là hàm blocking — gọi trong
    thread/generator của Gradio, đừng gọi thẳng trên event loop chính.
    """
    channel = choose_cuda_channel(driver_cuda)
    if channel is None:
        return False, (
            "Driver NVIDIA quá cũ so với các bản torch CUDA hiện có. "
            "Hãy cập nhật driver rồi thử lại, hoặc cài torch thủ công."
        )

    cmd = torch_install_command(channel)
    if on_log:
        on_log(f"Cài torch CUDA ({channel}) — tải ~2–3 GB, cần ~5 GB ổ trống, vui lòng đợi…")
        on_log(" ".join(cmd))

    exit_code: int | None = None
    for line in _stream_pip(cmd):
        if line.startswith("__EXIT__:"):
            exit_code = int(line.split(":", 1)[1])
            continue
        if on_log and line:
            on_log(line)

    if exit_code != 0:
        return False, (
            f"Cài torch thất bại (mã lỗi {exit_code}). "
            "Kiểm tra mạng/dung lượng đĩa, hoặc cài thủ công theo README."
        )

    # Cài xong chưa đủ — xác minh torch và CT2 THẬT SỰ thấy CUDA (bắt 'already
    # satisfied', bản không khớp driver, hoặc CT2 không nạp được CUDA/cuBLAS).
    ok, verify_msg = verify_torch_cuda()
    if not ok:
        return False, verify_msg
    ct2_ok, ct2_msg = verify_ct2_cuda()
    if not ct2_ok:
        return False, f"{verify_msg} {ct2_msg}"
    return True, (
        f"Đã cài torch CUDA ({channel}) — {verify_msg} {ct2_msg} "
        "Hãy TẮT và MỞ LẠI app (stop rồi start) để bật GPU."
    )
