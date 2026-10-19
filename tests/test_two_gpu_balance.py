import ast
import json
import struct
import threading
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest
from translation.gpu_balance import BalancedTranslator, balanced_indices, choose_two_devices, selected_devices


@pytest.mark.parametrize('count, expected', [(0, []), (1, [0]), (2, [0, 1]), (8, [0, 1])])
def test_choose_up_to_two_devices(count, expected):
    assert choose_two_devices(count) == expected


@pytest.mark.parametrize('size', [0, 1, 2, 3, 95, 96, 97, 256])
def test_balanced_count_coverage_and_order(size):
    weights = [1 + (i * 71) % 160 for i in range(size)]
    groups = balanced_indices(weights, 2)
    assert sorted(i for group in groups for i in group) == list(range(size))
    assert abs(len(groups[0])-len(groups[1])) <= 1
    assert all(group == sorted(group) for group in groups)
    if size == 96:
        assert [len(group) for group in groups] == [48,48]
        assert abs(sum(weights[i] for i in groups[0])-sum(weights[i] for i in groups[1])) < max(weights)*2


def test_invalid_device_request_does_not_mask_to_gpu_zero(monkeypatch):
    monkeypatch.setenv('HACHIMIMT_GPU_INDICES', '0,1')
    with pytest.raises(ValueError):
        selected_devices(1)
    monkeypatch.setenv('HACHIMIMT_GPU_INDICES', '1,0,1')
    assert selected_devices(2) == [1,0]
    monkeypatch.setenv('PIPER_GPU_INDICES','2')
    with pytest.raises(ValueError):
        selected_devices(2, 'PIPER_GPU_INDICES')


def test_ct2_both_replicas_run_concurrently_and_restore_order():
    barrier = threading.Barrier(2)
    calls = []
    def factory(path, **kwargs):
        device = kwargs['device_index']
        assert kwargs['device'] == 'cuda'
        assert kwargs['inter_threads'] == 1
        def translate(source, **opts):
            calls.append((device, len(source), opts['max_batch_size']))
            barrier.wait(timeout=5)
            return [item[0] for item in source]
        return SimpleNamespace(translate_batch=translate)
    model = BalancedTranslator('model', factory, device_index=[0,1], device='cuda', inter_threads=7)
    source = [[str(i)]*(i%20+1) for i in range(96)]
    assert model.translate_batch(source, max_batch_size=96) == [str(i) for i in range(96)]
    assert sorted(calls) == [(0,48,48), (1,48,48)]


def test_ct2_errors_are_propagated_and_no_worker_left_running():
    done = threading.Event()
    barrier = threading.Barrier(2)
    def factory(path, **kwargs):
        def translate(source, **opts):
            barrier.wait(timeout=5)
            if kwargs['device_index'] == 0:
                raise RuntimeError('CUDA out of memory')
            done.set()
            return source
        return SimpleNamespace(translate_batch=translate)
    model = BalancedTranslator('model', factory, device_index=[0,1])
    with pytest.raises(RuntimeError, match='out of memory'):
        model.translate_batch([['one'],['two']])
    assert done.is_set()


def test_ct2_does_not_silently_shrink_selected_gpu_set(monkeypatch):
    monkeypatch.setenv('NOVEL_BALANCE_GPUS','1')
    from translation.core.translator import _ct2_gpu_index_attempts
    assert _ct2_gpu_index_attempts([0,1]) == [[0,1]]


def test_piper_provider_targets_second_gpu(monkeypatch):
    from tts.cuda_session import configure_cuda_session
    monkeypatch.setenv('PIPER_REQUIRE_CUDA', '1')
    calls = []
    session = SimpleNamespace(set_providers=calls.append, disable_fallback=lambda:None,
                              get_providers=lambda:['CUDAExecutionProvider'])
    configure_cuda_session(session, device_id=1)
    assert calls[0][0][1]['device_id'] == '1'


def test_piper_balances_chunks_concurrently_and_concatenates_in_order(tmp_path, monkeypatch):
    from audio import audio_service
    import tts.synthesis
    from tts.replicas import VoiceReplicas
    barrier = threading.Barrier(2)
    voices = [SimpleNamespace(session=object(), gpu=i) for i in range(2)]
    voice = VoiceReplicas(voices, [0,1])
    calls = []
    chunks = ['a'*5, 'b'*15, 'c'*10, 'd'*20]
    monkeypatch.setattr(audio_service,'split_text_for_tts',lambda *a,**kw:chunks)
    def synth(replica, text, out, **kwargs):
        if not any(gpu == replica.gpu for gpu, _ in calls):
            barrier.wait(timeout=5)
        calls.append((replica.gpu, text))
        out.setnchannels(1);out.setsampwidth(2);out.setframerate(22050)
        out.writeframes(struct.pack('<h', ord(text[0])))
    monkeypatch.setattr(tts.synthesis,'synthesize_wav',synth)
    result = tmp_path/'result.wav'
    audio_service.synth_text_to_wav(voice, 'long enough text', result, tmp_path)
    assert sorted(sum(len(text) for gpu,text in calls if gpu==i) for i in (0,1)) == [25,25]
    assert [sum(gpu==i for gpu,_ in calls) for i in (0,1)] == [2,2]
    with wave.open(str(result),'rb') as out:
        assert struct.unpack('<4h',out.readframes(4)) == tuple(map(ord,'abcd'))


def test_piper_loads_two_devices_and_caches_pool(tmp_path,monkeypatch):
    from audio import audio_service
    import sys
    from translation import ct2_safe_import
    for ext in ('.onnx','.onnx.json'):
        (tmp_path/('test'+ext)).write_text('stub')
    monkeypatch.setattr(audio_service,'VOICE_DIR',tmp_path)
    monkeypatch.setattr(audio_service,'_voice_instances',{})
    monkeypatch.setattr(audio_service,'is_cuda_available_for_piper',lambda:True)
    monkeypatch.setenv('NOVEL_BALANCE_GPUS','1')
    monkeypatch.setenv('PIPER_GPU_INDICES','0,1')
    monkeypatch.setenv('PIPER_DEVICE','cuda')
    monkeypatch.setattr(ct2_safe_import,'import_ctranslate2',lambda:SimpleNamespace(get_cuda_device_count=lambda:2))
    sessions = []
    def load(*a, **kw):
        class Session:
            def set_providers(self, providers): self.providers=providers
            def get_providers(self): return ['CUDAExecutionProvider']
            def disable_fallback(self):pass
        session=Session();sessions.append(session)
        return SimpleNamespace(session=session)
    monkeypatch.setitem(sys.modules,'piper',SimpleNamespace(PiperVoice=SimpleNamespace(load=load)))
    voice=audio_service.get_voice('test')
    assert voice.device_indices == [0,1]
    assert [s.providers[0][1]['device_id'] for s in sessions] == ['0','1']
    assert audio_service.get_voice('test') is voice
    assert len(sessions) == 2


def test_piper_second_device_error_does_not_cache_partial_pool(tmp_path,monkeypatch):
    from audio import audio_service
    import sys
    from translation import ct2_safe_import
    for ext in ('.onnx','.onnx.json'):
        (tmp_path/('test'+ext)).write_text('stub')
    monkeypatch.setattr(audio_service,'VOICE_DIR',tmp_path)
    monkeypatch.setattr(audio_service,'_voice_instances',{})
    monkeypatch.setattr(audio_service,'is_cuda_available_for_piper',lambda:True)
    monkeypatch.setenv('NOVEL_BALANCE_GPUS','1')
    monkeypatch.setenv('PIPER_GPU_INDICES','0,1')
    monkeypatch.setenv('PIPER_DEVICE','cuda')
    monkeypatch.setattr(ct2_safe_import,'import_ctranslate2',lambda:SimpleNamespace(get_cuda_device_count=lambda:2))
    calls=[]
    def load(*a,**kw):
        calls.append(kw)
        if len(calls)==2: raise RuntimeError('GPU 1 failed')
        return SimpleNamespace(session=SimpleNamespace(set_providers=lambda p:None,get_providers=lambda:['CUDAExecutionProvider'],disable_fallback=lambda:None))
    monkeypatch.setitem(sys.modules,'piper',SimpleNamespace(PiperVoice=SimpleNamespace(load=load)))
    with pytest.raises(RuntimeError,match='khởi tạo CUDA thất bại'):
        audio_service.get_voice('test')
    assert len(calls)==2
    assert not audio_service._voice_instances


def test_notebook_does_not_pin_gpu_zero_and_prints_recovery_code():
    x=json.loads((Path(__file__).resolve().parents[1]/'NovelReader_Colab.ipynb').read_text())
    for c in x['cells']:
        if c['cell_type']=='code': ast.parse(''.join(c['source']))
    config=''.join(x['cells'][6]['source'])
    assert "'HACHIMIMT_GPU_INDICES': '0'" not in config
    assert "os.environ['NOVEL_BALANCE_GPUS'] = '1'" in config
    assert 'choose_two_devices(cuda_count)' in config
    assert "os.environ['PIPER_GPU_INDICES']" in config
    assert 'Mã truy cập (dán vào trang đăng nhập nếu cần)' in ''.join(x['cells'][10]['source'])


@pytest.mark.parametrize('count', [1,2,3])
def test_core_loader_selects_up_to_two_replicas(tmp_path,monkeypatch,count):
    from translation.core import translator as core
    monkeypatch.setenv('NOVEL_BALANCE_GPUS','1')
    monkeypatch.delenv('HACHIMIMT_GPU_INDICES',raising=False)
    monkeypatch.setenv('HACHIMIMT_COMPUTE_TYPE','int8_float16')
    monkeypatch.setattr(core,'ensure_model_files',lambda *a:tmp_path)
    monkeypatch.setattr(core,'_load_ct2_tokenizer',lambda *a,**kw:object())
    calls=[]
    def factory(path,**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(device='cuda',device_index=kwargs['device_index'])
    monkeypatch.setattr(core,'ctranslate2',SimpleNamespace(get_cuda_device_count=lambda:count,Translator=factory))
    engine=SimpleNamespace(_profile=SimpleNamespace(has_cuda=True),_ct2_threads=4,_ct2_inter_threads=1)
    config=SimpleNamespace(ct2_subdir='ct2',newline_token=None)
    core.HachimiTranslator._load_ct2(engine,config)
    assert [c['device_index'] for c in calls] == choose_two_devices(count)
    assert engine._ct2_worker_count == min(count,2)
    assert isinstance(engine._ct2_model,BalancedTranslator) == (count>1)


def test_fallback_loader_uses_both_gpus_and_discards_failed_core(tmp_path,monkeypatch):
    from translation import engines,ct2_safe_import
    from translation.core import translator as core,hardware
    import sys
    monkeypatch.setenv('NOVEL_BALANCE_GPUS','1')
    monkeypatch.setenv('HACHIMIMT_GPU_INDICES','0,1')
    monkeypatch.setenv('HACHIMIMT_FORCE_CT2_CUDA','1')
    monkeypatch.setattr(engines,'translation_models',lambda:tmp_path)
    model=tmp_path/'HachimiMT-60-QT'
    for name in ['ct2-int8_float32/model.bin','ct2-int8_float32/config.json','ct2-int8_float32/shared_vocabulary.json','source.spm','target.spm']:
        path=model/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('stub')
    class BrokenCore:
        def load(self,*args): raise RuntimeError('core failed')
    monkeypatch.setattr(core,'HachimiTranslator',BrokenCore)
    monkeypatch.setitem(sys.modules,'sentencepiece',SimpleNamespace(SentencePieceProcessor=lambda **kw:object()))
    monkeypatch.setattr(hardware,'detect_hardware_profile',lambda:SimpleNamespace(has_cuda=True,ct2_threads=4))
    calls=[]
    def factory(path,**kw):
        calls.append(kw['device_index'])
        return SimpleNamespace(device='cuda')
    monkeypatch.setattr(ct2_safe_import,'import_ctranslate2',lambda:SimpleNamespace(get_cuda_device_count=lambda:2,Translator=factory))
    engine=engines.LocalEngine()
    engine.load()
    assert engine.translator is None
    assert isinstance(engine.model,BalancedTranslator)
    assert calls == [0,1]


def test_two_gpu_mode_rejects_unsupported_pytorch(monkeypatch):
    from translation.engines import LocalEngine
    monkeypatch.setenv('NOVEL_BALANCE_GPUS','1')
    monkeypatch.setenv('HACHIMIMT_GPU_INDICES','0,1')
    with pytest.raises(ValueError,match='CTranslate2'):
        LocalEngine(backend='pytorch').load()


def test_piper_rejects_cuda_on_wrong_device(monkeypatch):
    from tts.cuda_session import configure_cuda_session
    monkeypatch.setenv('PIPER_REQUIRE_CUDA','1')
    session=SimpleNamespace(set_providers=lambda p:None,disable_fallback=lambda:None,
        get_providers=lambda:['CUDAExecutionProvider'],
        get_provider_options=lambda:{'CUDAExecutionProvider':{'device_id':'0'}})
    with pytest.raises(RuntimeError,match='không dùng đúng GPU 1'):
        configure_cuda_session(session,device_id=1)
