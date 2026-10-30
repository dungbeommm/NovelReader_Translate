from types import SimpleNamespace

import pytest

from translation.core.translator import _select_torch_device


def runtime(cuda=False, xpu=True):
    return SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: cuda),
                           xpu=SimpleNamespace(is_available=lambda: xpu))


def test_xpu_is_explicit_and_auto_preserves_existing_selection(monkeypatch):
    monkeypatch.delenv('HACHIMIMT_TORCH_DEVICE', raising=False)
    assert _select_torch_device(runtime()) == 'cpu'
    assert _select_torch_device(runtime(cuda=True)) == 'cuda'
    monkeypatch.setenv('HACHIMIMT_TORCH_DEVICE', 'xpu')
    assert _select_torch_device(runtime(cuda=True)) == 'xpu'


def test_explicit_xpu_must_not_silently_run_on_cpu(monkeypatch):
    monkeypatch.setenv('HACHIMIMT_TORCH_DEVICE', 'xpu')
    with pytest.raises(RuntimeError, match='không chuyển sang CPU'):
        _select_torch_device(runtime(xpu=False))
    with pytest.raises(RuntimeError):
        _select_torch_device(SimpleNamespace(cuda=runtime().cuda))


def test_xpu_load_failure_does_not_switch_to_ct2(monkeypatch):
    from translation.core import translator
    from translation.engines import LocalEngine

    monkeypatch.setenv('HACHIMIMT_TORCH_DEVICE', 'xpu')
    def fail(self, *args):
        raise RuntimeError('XPU model failure')
    monkeypatch.setattr(translator.HachimiTranslator, 'load', fail)
    with pytest.raises(RuntimeError, match='không chuyển sang CT2/CPU'):
        LocalEngine(backend='transformers').load()


def test_openvino_rejects_cpu_execution(monkeypatch):
    import sys
    from tts.openvino_session import OpenVINOSession

    compiled = SimpleNamespace(get_property=lambda _: ['CPU'])
    monkeypatch.setitem(sys.modules, 'openvino', SimpleNamespace(Core=lambda: SimpleNamespace(compile_model=lambda *a: compiled)))
    with pytest.raises(RuntimeError, match='không chạy GPU'):
        OpenVINOSession('voice.onnx')


def test_piper_openvino_failure_must_not_fall_back_to_cpu(monkeypatch, tmp_path):
    import sys
    from audio import audio_service
    from tts import openvino_session

    (tmp_path / 'test.onnx').write_bytes(b'stub')
    (tmp_path / 'test.onnx.json').write_text('{}')
    monkeypatch.setattr(audio_service, 'VOICE_DIR', tmp_path)
    monkeypatch.setattr(audio_service, '_voice_instances', {})
    monkeypatch.setenv('PIPER_DEVICE', 'openvino')
    monkeypatch.setenv('PIPER_REQUIRE_CUDA', '0')
    def fail(*args):
        raise RuntimeError('Intel GPU unavailable')
    monkeypatch.setattr(openvino_session, 'OpenVINOSession', fail)
    monkeypatch.setitem(sys.modules, 'piper', SimpleNamespace(PiperVoice=SimpleNamespace(load=lambda *a, **k: pytest.fail('CPU fallback'))))
    monkeypatch.setitem(sys.modules, 'piper.config', SimpleNamespace(PiperConfig=SimpleNamespace(from_dict=lambda value: value)))
    with pytest.raises(RuntimeError, match='Intel GPU unavailable'):
        audio_service.get_voice('test')


def test_piper_openvino_conflicts_with_strict_cuda(monkeypatch, tmp_path):
    from audio import audio_service

    (tmp_path / 'test.onnx').write_bytes(b'stub')
    (tmp_path / 'test.onnx.json').write_text('{}')
    monkeypatch.setattr(audio_service, 'VOICE_DIR', tmp_path)
    monkeypatch.setattr(audio_service, '_voice_instances', {})
    monkeypatch.setenv('PIPER_DEVICE', 'openvino')
    monkeypatch.setenv('PIPER_REQUIRE_CUDA', '1')
    with pytest.raises(ValueError, match='xung đột'):
        audio_service.get_voice('test')
