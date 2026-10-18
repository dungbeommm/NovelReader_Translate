"""Tự động kiểm tra, tải và cài đặt PyTorch CUDA cho GPU (Colab T4 / Máy cục bộ)."""
import os
import sys
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from translation.core.gpu_setup import (
    choose_cuda_channel,
    torch_install_command,
    verify_torch_cuda,
    verify_ct2_cuda,
    install_torch_cuda,
    _TORCH_CUDA_CHANNELS,
)


def get_driver_cuda() -> tuple[bool, str | None, str | None, float | None]:
    """Lấy thông tin GPU NVIDIA và CUDA version từ nvidia-smi."""
    if shutil.which("nvidia-smi") is None:
        return False, None, None, None
    try:
        header = subprocess.run(["nvidia-smi"], capture_output=True, text=True, timeout=10)
        gpu_info = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return False, None, None, None

    gpu_name = None
    vram_gb = None
    cuda_ver = None

    if gpu_info.returncode == 0 and gpu_info.stdout.strip():
        first_line = gpu_info.stdout.strip().splitlines()[0]
        parts = [p.strip() for p in first_line.split(",", 1)]
        gpu_name = parts[0]
        if len(parts) > 1:
            try:
                vram_gb = float(parts[1]) / 1024.0
            except ValueError:
                pass

    if header.returncode == 0:
        import re
        m = re.search(r"CUDA Version:\s*([0-9]+\.[0-9]+)", header.stdout)
        if m:
            cuda_ver = m.group(1)

    return True, gpu_name, cuda_ver, vram_gb


def setup_ld_library_path():
    """Liên kết thư viện CUDA của PyTorch (libcublas, libcudart) cho CTranslate2 trên Linux."""
    try:
        import torch
        torch_lib = os.path.join(os.path.dirname(torch.__file__), "lib")
        if os.path.isdir(torch_lib):
            cur = os.environ.get("LD_LIBRARY_PATH", "")
            if torch_lib not in cur:
                os.environ["LD_LIBRARY_PATH"] = f"{torch_lib}:{cur}"
                print(f"🔗 Đã liên kết thư viện CUDA: {torch_lib}")
    except Exception:
        pass


def main():
    print("=" * 65)
    print("🚀 NOVELREADER — TRÌNH KIỂM TRA & KÍCH HOẠT GPU T4 / CUDA")
    print("=" * 65)

    has_gpu, gpu_name, driver_cuda, vram_gb = get_driver_cuda()
    if not has_gpu:
        print("❌ Không tìm thấy GPU NVIDIA vật lý qua nvidia-smi.")
        print("   Nếu đang chạy trên Google Colab:")
        print("   Vào menu: Thời gian chạy -> Thay đổi loại thời gian chạy -> T4 GPU -> Lưu.")
        sys.exit(1)

    vram_str = f"{vram_gb:.1f} GB" if vram_gb else "không xác định"
    print(f"✅ Phát hiện GPU: {gpu_name} (VRAM: {vram_str})")
    print(f"📌 CUDA Driver Version: {driver_cuda or 'N/A'}")

    # Kiểm tra PyTorch CUDA hiện tại
    torch_ok, msg = verify_torch_cuda()
    channel = choose_cuda_channel(driver_cuda)

    if torch_ok:
        print(f"✅ PyTorch đã nhận GPU thành công: {msg}")
    else:
        print(f"\n⚠️ PyTorch hiện tại chưa hỗ trợ GPU: {msg}")
        print(f"📦 Đang tự động tải và cài đặt PyTorch CUDA tương thích (kênh {channel})...")
        success, res_msg = install_torch_cuda(driver_cuda, on_log=print)
        if not success:
            print(f"❌ Cài đặt PyTorch CUDA thất bại: {res_msg}")
            sys.exit(2)
        print(f"✅ {res_msg}")

    # Cấu hình LD_LIBRARY_PATH cho CTranslate2
    setup_ld_library_path()

    # Kiểm tra CTranslate2 CUDA
    ct2_ok, ct2_msg = verify_ct2_cuda()
    if ct2_ok:
        print(f"✅ CTranslate2 CUDA: {ct2_msg}")
    else:
        print(f"⚠️ CTranslate2 chưa nhận CUDA: {ct2_msg}")
        print("   Đang thử thiết lập cờ HACHIMIMT_FORCE_CT2_CUDA=1...")
        os.environ["HACHIMIMT_FORCE_CT2_CUDA"] = "1"

    # Đánh thức GPU và kiểm tra tensor
    try:
        import torch
        if torch.cuda.is_available():
            x = torch.zeros((2048, 2048), device="cuda") @ torch.zeros((2048, 2048), device="cuda")
            allocated = torch.cuda.memory_allocated(0) / (1024**2)
            reserved = torch.cuda.memory_reserved(0) / (1024**2)
            del x
            torch.cuda.empty_cache()
            print(f"🔥 Kích hoạt GPU Tensor thành công! (Allocated: {allocated:.1f}MB, Reserved: {reserved:.1f}MB)")
            print("\n🎉 GPU T4 / CUDA ĐÃ SẴN SÀNG VỚI ĐẦY ĐỦ TÀI NGUYÊN!")
    except Exception as exc:
        print(f"⚠️ Lỗi khởi động tensor GPU: {exc}")


if __name__ == "__main__":
    main()
