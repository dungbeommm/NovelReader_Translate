"""Dependency resolver regression tests: no actual pip or native wheel operations."""
import importlib.util
from pathlib import Path
import subprocess
import pytest

spec = importlib.util.spec_from_file_location('tts_deps_test', Path(__file__).parents[1]/'scripts/tts_dependencies.py')
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)


def test_logged_broken_torchvision_removed_only(monkeypatch):
    calls = []
    monkeypatch.setattr(d, 'version', lambda n: '0.26.0+cu130')
    monkeypatch.setattr(d, 'probe', lambda code: (False, '', 'RuntimeError: operator torchvision::nms does not exist'))
    monkeypatch.setattr(d, 'pip', lambda *args: calls.append(args))
    assert d.repair_optional_vision()
    assert calls == [('uninstall', '-y', 'torchvision')]


@pytest.mark.parametrize('installed', [None, '0.23.0+cu128', '0.26.0+cu130'])
def test_healthy_or_missing_vision_untouched(monkeypatch, installed):
    monkeypatch.setattr(d, 'version', lambda n: installed)
    monkeypatch.setattr(d, 'probe', lambda code: (True, '', ''))
    monkeypatch.setattr(d, 'pip', lambda *args: pytest.fail('healthy optional package changed'))
    assert not d.repair_optional_vision()


def test_existing_repair_no_sdk_or_native_install(monkeypatch):
    order = []
    monkeypatch.setattr(d, 'torch_state', lambda device: order.append(('torch', device)))
    monkeypatch.setattr(d, 'repair_optional_vision', lambda: order.append('vision'))
    monkeypatch.setattr(d, 'check_imports', lambda device: order.append(('check', device)))
    d.repair_existing('cuda')
    assert order == [('torch','cuda'), 'vision', ('check','cuda')]


def test_cuda_probe_actually_executes_operation(monkeypatch):
    codes = []
    monkeypatch.setattr(d, 'probe', lambda code: (codes.append(code) or True, '2.11.0+cu130\n2.0', ''))
    assert d.torch_state('cuda') == '2.11.0+cu130'
    assert 'x.cuda()' in codes[0] and '(x+x).cpu().item()' in codes[0]


def test_bad_torch_fails_before_pip(monkeypatch):
    monkeypatch.setattr(d, 'version', lambda n: '2.8.0+cu128')
    monkeypatch.setattr(d, 'probe', lambda code: (False, '', 'CUDA broken'))
    monkeypatch.setattr(d, 'pip', lambda *args: pytest.fail('native stack mutated'))
    with pytest.raises(RuntimeError, match='CUDA broken'):
        d.install_vieneu('cuda')


def test_matching_audio_does_not_reinstall(monkeypatch):
    monkeypatch.setattr(d, 'version', lambda n: '2.11.0+cu130')
    monkeypatch.setattr(d, 'probe', lambda code: (True, '', ''))
    monkeypatch.setattr(d, 'pip', lambda *args: pytest.fail('healthy audio changed'))
    d.ensure_audio('2.11.0+cu130')


def test_audio_uses_same_channel_no_cuda_dependencies(monkeypatch):
    calls = []
    monkeypatch.setattr(d, 'version', lambda n: '2.11.0+cu130')
    monkeypatch.setattr(d, 'probe', lambda code: (True, '', ''))
    monkeypatch.setattr(d, 'pip', lambda *args: calls.append(args))
    d.ensure_audio('2.8.0+cu128')
    assert calls == [('install','--force-reinstall','--no-deps','torchaudio==2.8.0+cu128',
                      '--index-url','https://download.pytorch.org/whl/cu128')]


def test_unusual_torch_build_not_guessed(monkeypatch):
    monkeypatch.setattr(d, 'version', lambda n: None)
    with pytest.raises(RuntimeError, match='build'):
        d.ensure_audio('2.8.0+vendor')


def simulate_install(monkeypatch, cpu_present=True, ort='1.31.0', changed=False):
    calls = []
    protected = {'torch':'2.11.0+cu130', 'torchaudio':'2.11.0+cu130', 'nvidia-cudnn-cu12':'9.27.0.42'}
    monkeypatch.setattr(d, 'bootstrap_missing_torch', lambda device: None)
    monkeypatch.setattr(d, 'torch_state', lambda device: protected['torch'])
    monkeypatch.setattr(d, 'repair_optional_vision', lambda: False)
    monkeypatch.setattr(d, 'ensure_audio', lambda v: None)
    monkeypatch.setattr(d, 'protected_versions', lambda: protected)
    monkeypatch.setattr(d, 'version', lambda n: (ort if n=='onnxruntime-gpu' else '1.31.0' if n=='onnxruntime' and cpu_present
                                                else 'changed' if changed and n=='torch' else protected.get(n)))
    monkeypatch.setattr(d, 'probe', lambda c: (True, "['CUDAExecutionProvider']", ''))
    monkeypatch.setattr(d, 'check_imports', lambda device: None)
    def pip(*args):
        if '-c' in args:
            text = Path(args[args.index('-c')+1]).read_text()
            assert 'torch==2.11.0+cu130' in text
            assert 'nvidia-cudnn-cu12==9.27.0.42' in text
        calls.append(args)
    monkeypatch.setattr(d, 'pip', pip)
    return calls


def test_install_preserves_new_torch_cuda_and_exact_ort(monkeypatch):
    calls = simulate_install(monkeypatch)
    d.install_vieneu('cuda')
    assert calls[1] == ('uninstall', '-y', 'onnxruntime')
    assert calls[2] == ('install','--force-reinstall','--no-deps','onnxruntime-gpu==1.31.0')
    assert not any('torch==2.8.0' in c for c in calls)


def test_gpu_ort_not_reinstalled_if_no_overlap(monkeypatch):
    calls = simulate_install(monkeypatch, cpu_present=False)
    d.install_vieneu('cuda')
    assert len(calls) == 1


def test_unexpected_native_mutation_detected(monkeypatch):
    simulate_install(monkeypatch, changed=True)
    with pytest.raises(RuntimeError, match='ngoài dự kiến'):
        d.install_vieneu('cuda')


def test_child_probe_timeout_and_capture(monkeypatch):
    def run(cmd, **kwargs):
        assert cmd[:2] == [d.sys.executable, '-c']
        assert kwargs == dict(capture_output=True, text=True, timeout=120)
        return subprocess.CompletedProcess(cmd, 1, '', 'native error')
    monkeypatch.setattr(d.subprocess, 'run', run)
    assert d.probe('import torchvision') == (False, '', 'native error')


def test_pip_error_not_suppressed(monkeypatch):
    def run(cmd, **kwargs):
        assert kwargs['check'] is True
        raise subprocess.CalledProcessError(1, cmd)
    monkeypatch.setattr(d.subprocess, 'run', run)
    with pytest.raises(subprocess.CalledProcessError):
        d.pip('install','example')


@pytest.mark.parametrize('tv', ['2.8.0+cu128', '2.11.0+cu130'])
def test_bootstrap_never_replaces_existing_torch(monkeypatch, tv):
    monkeypatch.setattr(d, 'version', lambda n: tv)
    monkeypatch.setattr(d, 'pip', lambda *args: pytest.fail('existing torch changed'))
    d.bootstrap_missing_torch('cuda')


@pytest.mark.parametrize('device,driver,channel', [('cpu','', 'cpu'), ('cuda','12.6','cu126'), ('cuda','13.2','cu128')])
def test_absent_torch_bootstrap(monkeypatch, device, driver, channel):
    calls = []
    monkeypatch.setattr(d, 'version', lambda n: None)
    monkeypatch.setattr(d.subprocess, 'run', lambda *a, **kw: subprocess.CompletedProcess(a, 0, 'CUDA Version: '+driver, ''))
    monkeypatch.setattr(d, 'pip', lambda *args: calls.append(args))
    d.bootstrap_missing_torch(device)
    assert calls == [('install', 'torch==2.8.0', 'torchaudio==2.8.0', '--index-url', 'https://download.pytorch.org/whl/'+channel)]


def test_absent_torch_unknown_driver_fails_safely(monkeypatch):
    monkeypatch.setattr(d, 'version', lambda n: None)
    monkeypatch.setattr(d.subprocess, 'run', lambda *a, **kw: subprocess.CompletedProcess(a, 0, '', ''))
    monkeypatch.setattr(d, 'pip', lambda *args: pytest.fail('guessed driver'))
    with pytest.raises(RuntimeError, match='driver'):
        d.bootstrap_missing_torch('cuda')
