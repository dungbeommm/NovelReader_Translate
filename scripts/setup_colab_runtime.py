"""Install Colab dependencies without leaving two ONNX Runtime distributions.

Run before importing onnxruntime/piper/ctranslate2 in the notebook kernel. If
those modules were imported earlier, restart the kernel after this script.
"""
import subprocess
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    pip = [sys.executable, '-m', 'pip']
    subprocess.run(pip + ['install', '-q', '-r', str(ROOT / 'requirements.txt'),
                         'ctranslate2==4.6.0',
                         'nvidia-cublas-cu12>=12,<13', os.getenv('NOVEL_CUDNN_SPEC', 'nvidia-cudnn-cu12==9.10.2.21'),
                         'nvidia-cuda-runtime-cu12>=12,<13'], check=True)
    # piper-tts itself may require the CPU distribution. Remove both AFTER all
    # normal dependency resolution; the GPU wheel provides the same ort module.
    subprocess.run(pip + ['uninstall', '-y', 'onnxruntime', 'onnxruntime-gpu'], check=True)
    subprocess.run(pip + ['install', '-q', 'onnxruntime-gpu==1.23.2'], check=True)
    print('Đã cài ORT GPU. Không chạy pip -r requirements.txt sau bước này; nếu cần, chạy lại script này.')


if __name__ == '__main__':
    main()
