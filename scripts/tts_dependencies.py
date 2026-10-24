"""Conservative TTS dependency checks. Native imports always run in fresh children."""
import importlib.metadata as metadata
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def pip(*args):
    subprocess.run([sys.executable, '-m', 'pip', *args], check=True)


def version(name):
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def probe(code):
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=120)
    return result.returncode == 0, result.stdout.strip(), result.stderr.strip()


def torch_state(device):
    code = "import torch; print(torch.__version__); x=torch.ones(1)"
    if device == 'cuda':
        code += "; assert torch.cuda.is_available(), 'CUDA unavailable'; x=x.cuda(); print((x+x).cpu().item())"
    ok, out, err = probe(code)
    if not ok:
        raise RuntimeError('PyTorch chưa hoạt động trên ' + device + '. Chạy scripts/setup_gpu.py cho CUDA, '
                           'hoặc cài PyTorch phù hợp trước; không tự hạ Torch/thay CUDA.\n' + err[-3000:])
    return out.splitlines()[0]


def repair_optional_vision():
    """Keep healthy vision installations; remove only a proven broken optional one."""
    if version('torchvision') is None:
        return False
    ok, _, err = probe('import torchvision; print(torchvision.__version__)')
    if ok:
        return False
    print('TorchVision tùy chọn bị lỗi import; gỡ để không chặn Transformers/TTS. '
          'Các tác vụ xử lý ảnh cần cài lại TorchVision tương thích.\n' + err[-1500:], flush=True)
    pip('uninstall', '-y', 'torchvision')
    return True


def check_imports(device):
    torch_state(device)
    ok, _, err = probe('import torch, torchaudio; from transformers import PreTrainedModel; '
                       'print(torch.__version__, torchaudio.__version__, PreTrainedModel.__name__)')
    if not ok:
        raise RuntimeError('Kiểm tra Torch/TorchAudio/Transformers thất bại trước khi tải model:\n' + err[-4000:])


def protected_versions():
    # Prevent optional TTS packages from changing an existing native stack.
    names = {'torch', 'torchaudio', 'torchvision', 'triton'}
    result = {}
    for dist in metadata.distributions():
        name = (dist.metadata.get('Name') or '').lower().replace('_', '-')
        if name in names or name.startswith('nvidia-'):
            result[name] = dist.version
    return result


def ensure_audio(torch_version):
    installed = version('torchaudio')
    if installed == torch_version:
        ok, _, _ = probe('import torchaudio')
        if ok:
            return
    # Use the SAME torch wheel channel and no dependency resolver/native rewrites.
    base, _, channel = torch_version.partition('+')
    if channel and channel != 'cpu' and not (channel.startswith('cu') and channel[2:].isdigit()):
        raise RuntimeError('Torch build đặc biệt: hãy cài TorchAudio cùng build thủ công: ' + torch_version)
    channel = channel or 'cpu'
    pip('install', '--force-reinstall', '--no-deps', 'torchaudio==' + torch_version,
        '--index-url', 'https://download.pytorch.org/whl/' + channel)
    ok, _, err = probe('import torch, torchaudio; print(torch.__version__, torchaudio.__version__)')
    if not ok:
        raise RuntimeError('TorchAudio cùng phiên bản vẫn không import được:\n' + err[-3000:])


def bootstrap_missing_torch(device):
    """Only a genuinely absent Torch gets the SDK's matched 2.8 baseline."""
    if version('torch') is not None:
        return
    channel = 'cpu'
    if device == 'cuda':
        result = subprocess.run(['nvidia-smi'], capture_output=True, text=True, timeout=15)
        match = re.search(r'CUDA Version:\s*(\d+)\.(\d+)', result.stdout)
        driver = tuple(map(int, match.groups())) if match else (0, 0)
        if result.returncode or driver < (12, 6):
            raise RuntimeError('Chưa có Torch; không xác định được driver CUDA >=12.6. '
                               'Hãy cài PyTorch tương thích thủ công hoặc chọn CPU.')
        channel = 'cu128' if driver >= (12, 8) else 'cu126'
    print('Chưa có Torch: cài mới bộ Torch/TorchAudio 2.8 từ ' + channel, flush=True)
    pip('install', 'torch==2.8.0', 'torchaudio==2.8.0', '--index-url',
        'https://download.pytorch.org/whl/' + channel)


def install_vieneu(device):
    bootstrap_missing_torch(device)
    tv = torch_state(device)  # Fail BEFORE touching packages if CUDA is broken.
    repair_optional_vision()
    ensure_audio(tv)
    protected = protected_versions()
    previous_gpu_ort = version('onnxruntime-gpu')
    with tempfile.TemporaryDirectory(prefix='novel-tts-') as tmp:
        constraints = Path(tmp) / 'native-stack.txt'
        constraints.write_text(''.join(f'{k}=={v}\n' for k, v in sorted(protected.items())))
        pip('install', '-c', str(constraints), 'vieneu==3.8.3', 'soundfile>=0.13,<1', 'transformers==4.57.6')
    # SDK requires CPU ORT by distribution name. Both distributions share files:
    # removing CPU ORT must be followed by reinstalling the exact existing GPU build.
    if device == 'cuda' or previous_gpu_ort:
        cpu_present = version('onnxruntime') is not None
        if cpu_present:
            pip('uninstall', '-y', 'onnxruntime')
        if cpu_present or not previous_gpu_ort:
            spec = ('onnxruntime-gpu==' + previous_gpu_ort) if previous_gpu_ort else 'onnxruntime-gpu>=1.21,<2'
            pip('install', '--force-reinstall', '--no-deps', spec)
    changed = {name: (old, version(name)) for name, old in protected.items() if version(name) != old}
    if changed:
        raise RuntimeError('Native stack đã thay đổi ngoài dự kiến: ' + json.dumps(changed))
    repair_optional_vision()
    check_imports(device)
    ok, out, err = probe("import onnxruntime as o; print(o.get_available_providers())" +
                         ("; assert 'CUDAExecutionProvider' in o.get_available_providers()" if device == 'cuda' else ''))
    if not ok:
        raise RuntimeError('ONNX Runtime chưa sẵn sàng (chưa nạp model):\n' + err[-3000:])
    print('TTS dependencies OK; giữ nguyên Torch/CUDA. ORT: ' + out, flush=True)


def repair_existing(device):
    """Targeted hotfix: no SDK, torch, CUDA or model reinstall/download."""
    torch_state(device)
    repair_optional_vision()
    check_imports(device)
    print('Kiểm tra TTS OK. Không cài lại Torch/CUDA/model. Khởi động lại server/kernel cũ nếu đang chạy.', flush=True)
