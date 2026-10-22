"""Auto-detect CPU/GPU and recommend CT2 batch + thread settings."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass

from translation.core.ct2_safe_import import import_ctranslate2

PHYSICAL_NVIDIA_GPU = False
PHYSICAL_GPU_NAME: str | None = None
PHYSICAL_GPU_VRAM_GB: float | None = None
DRIVER_CUDA_VERSION: str | None = None
CT2_IMPORT_ALLOW_TORCH = False
CT2_CUDA_DISABLED_REASON: str | None = None


def _detect_nvidia_gpu() -> None:
    """Chạy nvidia-smi để biết có GPU NVIDIA + CUDA version tối đa của driver."""
    global PHYSICAL_NVIDIA_GPU, PHYSICAL_GPU_NAME, PHYSICAL_GPU_VRAM_GB, DRIVER_CUDA_VERSION
    if shutil.which("nvidia-smi") is None:
        return
    try:
        header = subprocess.run(
            ["nvidia-smi"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        gpu_info = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return
    if gpu_info.returncode == 0 and gpu_info.stdout.strip():
        PHYSICAL_NVIDIA_GPU = True
        first_line = gpu_info.stdout.strip().splitlines()[0]
        parts = [part.strip() for part in first_line.split(",", 1)]
        PHYSICAL_GPU_NAME = parts[0] or None
        if len(parts) > 1:
            try:
                PHYSICAL_GPU_VRAM_GB = float(parts[1]) / 1024.0
            except ValueError:
                PHYSICAL_GPU_VRAM_GB = None
    if header.returncode == 0:
        match = re.search(r"CUDA Version:\s*([0-9]+\.[0-9]+)", header.stdout)
        if match:
            DRIVER_CUDA_VERSION = match.group(1)


def _cuda_visible_devices_allows_cuda(value: str | None) -> bool:
    if value is None:
        return True
    stripped = value.strip()
    return bool(stripped) and stripped != "-1"


def _torch_cuda_usable(timeout_s: float = 8.0) -> bool:
    """Probe torch CUDA in a child process so a bad torch import cannot hang UI."""
    code = (
        "import sys;"
        "import torch;"
        "sys.exit(0 if torch.cuda.is_available() else 2)"
    )
    env = dict(os.environ)
    env.pop("CUDA_VISIBLE_DEVICES", None)
    try:
        result = subprocess.run(
            [sys.executable, "-c", code],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout_s,
            env=env,
        )
    except Exception:
        return False
    return result.returncode == 0


def _guard_ct2_cuda_before_import() -> None:
    """Chặn CTranslate2 dò CUDA khi máy có GPU NVIDIA nhưng KHÔNG có torch-CUDA.

    CTranslate2 (wheel pip) tự phát hiện CUDA độc lập với torch. Nếu máy có GPU
    NVIDIA, nó sẽ cố nạp cuBLAS lúc translate_batch — nhưng cuBLAS DLL thường do
    bản torch-CUDA cung cấp. Engine mặc định của app KHÔNG cài torch, nên nhóm
    "có GPU + không torch-CUDA" sẽ crash 'cublas64_12.dll not found'.

    CTranslate2 đọc CUDA_VISIBLE_DEVICES MỘT LẦN lúc init, nên phải set TRƯỚC khi
    `import ctranslate2`. Chỉ ép CPU khi không có torch-CUDA khả dụng; người dùng
    torch-CUDA giữ nguyên GPU (cuBLAS của họ do torch cấp).
    """
    global CT2_IMPORT_ALLOW_TORCH, CT2_CUDA_DISABLED_REASON
    cuda_visible_devices = os.environ.get("CUDA_VISIBLE_DEVICES")
    if cuda_visible_devices is not None:
        CT2_IMPORT_ALLOW_TORCH = _cuda_visible_devices_allows_cuda(cuda_visible_devices)
        return
    if os.environ.get("HACHIMIMT_FORCE_CT2_CUDA", "").strip() == "1":
        CT2_IMPORT_ALLOW_TORCH = True
        return
    if not PHYSICAL_NVIDIA_GPU:
        os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
        CT2_CUDA_DISABLED_REASON = "no_nvidia_gpu"
        CT2_IMPORT_ALLOW_TORCH = False
        return
    if _torch_cuda_usable():
        CT2_IMPORT_ALLOW_TORCH = True
        return

    os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
    CT2_CUDA_DISABLED_REASON = "torch_cuda_unusable"
    CT2_IMPORT_ALLOW_TORCH = False


_detect_nvidia_gpu()
_guard_ct2_cuda_before_import()

ctranslate2 = import_ctranslate2(block_torch=not CT2_IMPORT_ALLOW_TORCH)

BATCH_MIN = 4
BATCH_MAX = 128
THREAD_MIN = 1
THREAD_MAX = 16
TOKENIZE_WORKERS_MAX = 16
TOKENIZE_WORKERS_MIN = 1


@dataclass(frozen=True)
class HardwareProfile:
    cpu_logical: int
    has_cuda: bool
    gpu_name: str | None
    vram_gb: float | None
    batch_size: int
    ct2_threads: int
    tokenize_workers: int

    @property
    def summary(self) -> str:
        cpu_part = f"CPU {self.cpu_logical} luồng"
        if self.has_cuda and self.gpu_name:
            vram = f"{self.vram_gb:.1f} GB" if self.vram_gb else "?"
            device_part = f"GPU {self.gpu_name} ({vram})"
        else:
            device_part = "GPU không có — chạy CPU"
        return (
            f"{cpu_part} · {device_part} · "
            f"batch={self.batch_size} · threads={self.ct2_threads} · "
            f"tokenize_workers={self.tokenize_workers}"
        )


def _env_int(name: str) -> int | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        return max(1, int(raw))
    except ValueError:
        return None


def _clamp_batch(value: int) -> int:
    return max(BATCH_MIN, min(BATCH_MAX, int(value)))


def _clamp_threads(value: int) -> int:
    return max(THREAD_MIN, min(THREAD_MAX, int(value)))


def _clamp_tokenize_workers(value: int) -> int:
    return max(TOKENIZE_WORKERS_MIN, min(TOKENIZE_WORKERS_MAX, int(value)))


def _round_batch(value: int) -> int:
    """Làm tròn batch về bội số 4 để ổn định hơn trên GPU."""
    rounded = max(BATCH_MIN, round(value / 4) * 4)
    return _clamp_batch(rounded)


def recommend_tokenize_workers(cpu_logical: int) -> int:
    return max(4, min(cpu_logical, TOKENIZE_WORKERS_MAX))


def recommend_batch_size(cpu_logical: int, *, has_cuda: bool, vram_gb: float | None) -> int:
    if has_cuda:
        if vram_gb is None:
            return 64
        if vram_gb >= 10:
            return 128
        if vram_gb >= 8:
            return 96
        if vram_gb >= 6:
            return 72
        return 48

    return _round_batch(max(4, cpu_logical))


def auto_all_gpus_by_default() -> bool:
    """Auto all GPUs only in cloud notebooks unless the user explicitly opts in."""
    raw = os.environ.get("HACHIMIMT_AUTO_ALL_GPUS", "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return bool(
        os.environ.get("KAGGLE_KERNEL_RUN_TYPE")
        or os.environ.get("KAGGLE_URL_BASE")
        or os.environ.get("COLAB_GPU")
    )


def resolve_gpu_indices(
    cuda_device_count: int,
    env_value: str | None,
    *,
    auto_all: bool = True,
) -> list[int]:
    """Quyết định CT2 dùng GPU nào (multi-GPU). Trả list device index (đã áp
    CUDA_VISIBLE_DEVICES — index 0..count-1).

    - 0 GPU → [] (CPU; _load_ct2 chỉ dùng list này khi device=cuda).
    - env vắng/rỗng → AUTO: dùng HẾT GPU khi auto_all=True, ngược lại dùng GPU 0.
    - env ĐÃ set → dùng đúng list (ép 1 GPU: "0"; chọn GPU 1: "1"; loại trùng,
      giữ thứ tự). env SAI (rác/ngoài-range) → RAISE ValueError (KHÔNG che giấu
      lỗi config — user cố set thì phải đúng, đừng âm thầm fallback rồi rớt CPU).
    """
    if cuda_device_count <= 0:
        return []
    if env_value is None or not env_value.strip():
        return list(range(cuda_device_count)) if auto_all else [0]
    try:
        requested = [int(p.strip()) for p in env_value.split(",") if p.strip()]
    except ValueError as exc:
        raise ValueError(f"HACHIMIMT_GPU_INDICES không hợp lệ: {env_value!r}") from exc
    if not requested:
        raise ValueError("HACHIMIMT_GPU_INDICES không được để trống.")
    invalid = [i for i in requested if i < 0 or i >= cuda_device_count]
    if invalid:
        raise ValueError(
            f"GPU index không hợp lệ: {invalid}; chỉ có 0..{cuda_device_count - 1}"
        )
    return list(dict.fromkeys(requested))


def recommend_ct2_threads(cpu_logical: int, *, has_cuda: bool) -> int:
    if has_cuda:
        return _clamp_threads(min(cpu_logical, 12))

    return _clamp_threads(cpu_logical)


def _ct2_has_cuda() -> bool:
    try:
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def detect_hardware_profile() -> HardwareProfile:
    cpu_logical = os.cpu_count() or 4
    has_cuda = _ct2_has_cuda()
    gpu_name: str | None = None
    vram_gb: float | None = None

    if has_cuda:
        gpu_name = PHYSICAL_GPU_NAME or "CUDA GPU"
        vram_gb = PHYSICAL_GPU_VRAM_GB

    env_batch = _env_int("HACHIMIMT_BATCH_SIZE")
    env_threads = _env_int("HACHIMIMT_THREADS")
    env_tokenize_workers = _env_int("HACHIMIMT_TOKENIZE_WORKERS")

    batch_size = (
        _clamp_batch(env_batch)
        if env_batch is not None
        else recommend_batch_size(cpu_logical, has_cuda=has_cuda, vram_gb=vram_gb)
    )
    ct2_threads = (
        _clamp_threads(env_threads)
        if env_threads is not None
        else recommend_ct2_threads(cpu_logical, has_cuda=has_cuda)
    )
    tokenize_workers = (
        _clamp_tokenize_workers(env_tokenize_workers)
        if env_tokenize_workers is not None
        else recommend_tokenize_workers(cpu_logical)
    )

    return HardwareProfile(
        cpu_logical=cpu_logical,
        has_cuda=has_cuda,
        gpu_name=gpu_name,
        vram_gb=vram_gb,
        batch_size=batch_size,
        ct2_threads=ct2_threads,
        tokenize_workers=tokenize_workers,
    )
