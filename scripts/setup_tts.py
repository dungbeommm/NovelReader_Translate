"""Notebook bootstrap: JSON voices + selected TTS runtime, fail loudly on errors."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def install_vieneu(device):
    # Optional dependencies: do not make Piper users install the whole SDK.
    subprocess.run([sys.executable, '-m', 'pip', 'install', 'vieneu==3.8.3', 'soundfile', 'transformers==4.57.6'], check=True)
    if device == 'cuda':
        try:
            import torch
            ready = torch.__version__.split('+')[0] == '2.8.0' and torch.cuda.is_available()
        except ImportError:
            ready = False
        if not ready:
            subprocess.run([sys.executable, '-m', 'pip', 'install', 'torch==2.8.0', 'torchaudio==2.8.0', '--index-url', 'https://download.pytorch.org/whl/cu128'], check=True)
        else:
            subprocess.run([sys.executable, '-m', 'pip', 'install', 'torchaudio==2.8.0'], check=True)
        # CPU and GPU ORT distributions install the same Python module. Reinstall
        # GPU files AFTER removing CPU ORT, otherwise importing Piper can break.
        subprocess.run([sys.executable, '-m', 'pip', 'uninstall', '-y', 'onnxruntime'], check=True)
        subprocess.run([sys.executable, '-m', 'pip', 'install', '--force-reinstall', '--no-deps', 'onnxruntime-gpu>=1.21,<2'], check=True)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--engine', choices=['piper','vieneu'], default='piper')
    p.add_argument('--voice', default=None)
    p.add_argument('--device', choices=['auto','cpu','cuda'], default='auto')
    p.add_argument('--install', action='store_true')
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
    if args.install:
        device = args.device
        if device == 'auto':
            # Choose hardware without importing CPU torch before replacing its wheel.
            gpu = subprocess.run(['nvidia-smi','--query-gpu=name','--format=csv,noheader'], capture_output=True, text=True) if __import__('shutil').which('nvidia-smi') else None
            device = 'cuda' if gpu and gpu.returncode == 0 and gpu.stdout.strip() else 'cpu'
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
