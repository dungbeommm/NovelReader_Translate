"""Notebook bootstrap: JSON voices + selected TTS runtime, fail loudly on errors."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from scripts.tts_dependencies import install_vieneu, repair_existing


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--engine', choices=['piper','vieneu'], default='piper')
    p.add_argument('--voice', default=None)
    p.add_argument('--device', choices=['auto','cpu','cuda'], default='auto')
    p.add_argument('--install', action='store_true')
    p.add_argument('--repair-only', action='store_true', help='Gỡ TorchVision lỗi và kiểm tra import; không tải model/cài Torch')
    p.add_argument('--preload', action='store_true')
    p.add_argument('--refs-only', action='store_true')
    p.add_argument('--all', action='store_true')
    args = p.parse_args(argv)
    os.environ['VIENEU_DEVICE'] = args.device
    if args.engine == 'piper':
        cmd = [sys.executable, str(ROOT/'scripts/download_voices.py'), '--all' if args.all else '--catalog-only']
        subprocess.run(cmd, check=True)
        if not args.all:
            subprocess.run([sys.executable, str(ROOT/'scripts/download_voices.py'), '--voice', args.voice or 'ngochuyennew'], check=True)
        return 0
    if args.install or args.repair_only:
        device = args.device
        if device == 'auto':
            # Choose hardware without importing CPU torch before replacing its wheel.
            gpu = subprocess.run(['nvidia-smi','--query-gpu=name','--format=csv,noheader'], capture_output=True, text=True) if __import__('shutil').which('nvidia-smi') else None
            device = 'cuda' if gpu and gpu.returncode == 0 and gpu.stdout.strip() else 'cpu'
        os.environ["VIENEU_DEVICE"] = device
        if args.repair_only:
            repair_existing(device)
            return 0
        install_vieneu(device)
    from audio.vieneu_service import ensure_references, get_runtime, runtime_status
    data = ensure_references()
    print(f"Đã nhập đủ {len(data['voices'])} giọng từ gói Vbook (không chạy backbone GGUF).", flush=True)
    if args.preload and not args.refs_only:
        print('Tải/nạp backbone ONNX/PyTorch và codec chính thức. Dữ liệu này lớn hơn gói giọng 188 MB.', flush=True)
        get_runtime()
    print(json.dumps(runtime_status(), ensure_ascii=False), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
