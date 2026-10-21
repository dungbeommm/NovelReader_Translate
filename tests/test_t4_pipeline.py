"""CPU-safe regression tests. Engines/voice are stubbed; FFmpeg is tested elsewhere."""
import threading
import time
from types import SimpleNamespace
from pathlib import Path
import pytest
from storage.store import Store
from workflows.jobs import Job
from workflows.audio_queue import AudioQueue
from audio import audio_service, merge_service
from translation.engines import LocalEngine
from web.schemas import Config


class FakeEngine:
    def load(self):
        pass

    def translate(self, texts, glossary, **kwargs):
        return ['Bản dịch ' + t for t in texts]


def setup(tmp_path, monkeypatch, count=4, engine=None):
    store = Store(tmp_path/'db.sqlite', tmp_path/'text', tmp_path/'audio')
    store.replace('sample.txt', 'utf8', [(f'第{i}章', f'内容{i}') for i in range(1, count+1)])
    monkeypatch.setattr('workflows.jobs.create_engine', lambda *a, **k: engine or FakeEngine())
    return store, Job(store)


def config(**kw):
    return {'glossary': '', 'engine': 'local', 'backend': 'ct2', 'batch_size': 64,
            'generate_audio': True, 'audio_pipeline': True, 'honorific_mode': 'off',
            'pronoun_harmonizer': False, **kw}


def write_audio(cid, pos, title, paras, directory, **kwargs):
    path = directory/f'chuong_{pos:04d}.wav'
    path.write_bytes(b'audio')
    return path


def finish(job):
    job.thread.join(8)
    assert not job.active, 'job/consumer must not deadlock'


def test_pipeline_overlaps_translation_but_waits_for_encoding(tmp_path, monkeypatch):
    entered, release, second_translated = (threading.Event() for _ in range(3))
    class Engine(FakeEngine):
        def translate(self, texts, glossary, **kwargs):
            if any('内容2' in t for t in texts):
                second_translated.set()
            return super().translate(texts, glossary, **kwargs)
    store, job = setup(tmp_path, monkeypatch, count=2, engine=Engine())
    def generate(*args, **kwargs):
        if args[1] == 1:
            entered.set()
            assert release.wait(5)
        return write_audio(*args, **kwargs)
    monkeypatch.setattr(audio_service, 'generate_chapter_audio', generate)
    job.start(config())
    try:
        assert entered.wait(3)
        assert second_translated.wait(3), 'translation should advance while audio is blocked'
        assert job.active, 'library remains protected until audio/encoding finishes'
        with pytest.raises(ValueError):
            job.start(config())
    finally:
        release.set()
        finish(job)
    assert job.status == 'ready'
    assert all(c['audio_status'] == 'done' for c in store.list())


def test_sequential_switch_disables_overlap(tmp_path, monkeypatch):
    entered, release, second = (threading.Event() for _ in range(3))
    class Engine(FakeEngine):
        def translate(self, texts, glossary, **kwargs):
            if any('内容2' in t for t in texts):
                second.set()
            return super().translate(texts, glossary, **kwargs)
    store, job = setup(tmp_path, monkeypatch, count=2, engine=Engine())
    def generate(*args, **kwargs):
        if args[1] == 1:
            entered.set()
            assert release.wait(5)
        return write_audio(*args, **kwargs)
    monkeypatch.setattr(audio_service, 'generate_chapter_audio', generate)
    job.start(config(audio_pipeline=False))
    try:
        assert entered.wait(3)
        assert not second.wait(.15)
    finally:
        release.set()
        finish(job)
    assert second.is_set()


def test_stop_with_full_queue_does_not_leave_queued_chapters(tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    store, job = setup(tmp_path, monkeypatch, count=10)
    calls = []
    def generate(*args, **kwargs):
        calls.append(args[1])
        entered.set()
        assert release.wait(5)
        return write_audio(*args, **kwargs)
    monkeypatch.setattr(audio_service, 'generate_chapter_audio', generate)
    job.start(config(audio_queue_size=1))
    try:
        assert entered.wait(3)
        job.pause()
        job.stop()  # wakes a paused producer AND consumer
    finally:
        release.set()
        finish(job)
    assert calls == [1]
    assert not any(c['audio_status'] in ('queued', 'generating') for c in store.list())
    assert (store.text_dir/'toan_bo_truyen.txt').exists()


def test_audio_failure_is_reported_and_remaining_chapters_continue(tmp_path, monkeypatch):
    store, job = setup(tmp_path, monkeypatch, count=3)
    def generate(*args, **kwargs):
        if args[1] == 2:
            raise RuntimeError('expected Piper failure')
        return write_audio(*args, **kwargs)
    monkeypatch.setattr(audio_service, 'generate_chapter_audio', generate)
    job.start(config())
    finish(job)
    assert job.status == 'error'
    assert [c['audio_status'] for c in store.list()] == ['done', 'error', 'done']
    assert all(c['status'] == 'done' for c in store.list())


def test_resume_audio_without_retranslation(tmp_path, monkeypatch):
    class NeverTranslate(FakeEngine):
        def translate(self, *args, **kwargs):
            raise AssertionError('completed text must not be translated again')
    store, job = setup(tmp_path, monkeypatch, count=3, engine=NeverTranslate())
    for chapter in store.list():
        store.update(chapter['id'], status='done', translated_title='Chương', translated=['Đã dịch'], audio_status='error')
    monkeypatch.setattr(audio_service, 'generate_chapter_audio', write_audio)
    job.start(config())
    finish(job)
    assert job.status == 'ready'
    assert all(c['audio_status'] == 'done' for c in store.list())


def test_aggregate_and_group_run_once_after_all_audio(tmp_path, monkeypatch):
    store, job = setup(tmp_path, monkeypatch, count=5)
    monkeypatch.setattr(audio_service, 'generate_chapter_audio', write_audio)
    exports, merges = [], []
    original = store.export_full_book_text
    def export():
        exports.append(True)
        return original()
    def merge(*args, **kwargs):
        assert all(c['audio_status'] == 'done' for c in store.list())
        merges.append(kwargs)
        return []
    monkeypatch.setattr(store, 'export_full_book_text', export)
    monkeypatch.setattr(merge_service, 'group_and_merge_chapters', merge)
    job.start(config(auto_group_audio=True))
    finish(job)
    assert len(exports) == len(merges) == 1
    assert 'Bản dịch' in (store.text_dir/'toan_bo_truyen.txt').read_text()


def test_final_merge_failure_sets_job_error(tmp_path, monkeypatch):
    store, job = setup(tmp_path, monkeypatch)
    monkeypatch.setattr(audio_service, 'generate_chapter_audio', write_audio)
    def fail(*a, **k):
        raise RuntimeError('expected merge failure')
    monkeypatch.setattr(merge_service, 'group_and_merge_chapters', fail)
    job.start(config(auto_group_audio=True))
    finish(job)
    assert job.status == 'error'


def test_oom_retries_same_segments_without_loss(tmp_path, monkeypatch):
    calls = []
    class OOM(FakeEngine):
        def translate(self, texts, glossary, **kwargs):
            calls.append(len(texts))
            if len(texts) > 1:
                raise RuntimeError('CUDA out of memory')
            return super().translate(texts, glossary, **kwargs)
    store, job = setup(tmp_path, monkeypatch, count=1, engine=OOM())
    # Multiple source segments force a real smaller re-batch.
    store.replace('x.txt', 'utf8', [('第一章', '甲\n乙\n丙\n丁')])
    job.start(config(generate_audio=False))
    finish(job)
    chapter = store.get(store.list()[0]['id'])
    assert job.status == 'ready'
    assert chapter['status'] == 'done'
    assert all(x is not None for x in chapter['outputs'])
    assert max(calls) > 1 and calls[-1] == 1
    assert all(t in '\n'.join(chapter['translated']) for t in ('甲', '乙', '丙', '丁'))


def test_internal_inference_budget_reduces_to_one():
    engine = LocalEngine()
    engine.translator = SimpleNamespace(_batch_size=96)
    assert engine.reduce_batch_size()
    assert engine.translator._batch_size == 48
    engine.translator._batch_size = 1
    assert not engine.reduce_batch_size()


def test_audio_queue_bounded_and_worker_exception_does_not_deadlock():
    entered, release = threading.Event(), threading.Event()
    def consume(item):
        entered.set()
        assert release.wait(3)
        raise RuntimeError('consumer failed')
    cancelled = []
    q = AudioQueue(consume, lambda: True, cancelled.append, maxsize=1)
    q.submit(1)
    assert entered.wait(2)
    q.submit(2)
    assert q.queue.qsize() == q.queue.maxsize == 1
    release.set()
    with pytest.raises(RuntimeError, match='Audio worker failed'):
        q.close()
    assert not q.worker.is_alive()
    assert cancelled == [2]


def test_restart_recovers_interrupted_audio(tmp_path, monkeypatch):
    store, job = setup(tmp_path, monkeypatch, count=2)
    for chapter, status in zip(store.list(), ['queued', 'generating']):
        store.update(chapter['id'], status='done', audio_status=status)
    recovered = Store(store.path)
    assert all(c['audio_status'] == 'none' for c in recovered.list())


def test_gpu_schema_default_and_queue_validation(monkeypatch):
    monkeypatch.setenv('COLAB_GPU', '1')
    monkeypatch.delenv('HACHIMIMT_WEB_BATCH_SIZE', raising=False)
    assert Config().batch_size == 96
    with pytest.raises(ValueError):
        Config(audio_queue_size=0)


@pytest.mark.parametrize('mode,require', [('cuda', '0'), ('auto', '1')])
def test_strict_piper_rejects_cpu_session(tmp_path, monkeypatch, mode, require):
    import sys
    for suffix in ('.onnx', '.onnx.json'):
        (tmp_path/('test'+suffix)).write_text('stub')
    monkeypatch.setattr(audio_service, 'VOICE_DIR', tmp_path)
    monkeypatch.setattr(audio_service, '_voice_instances', {})
    monkeypatch.setenv('PIPER_DEVICE', mode)
    monkeypatch.setenv('PIPER_REQUIRE_CUDA', require)
    monkeypatch.setattr(audio_service, 'is_cuda_available_for_piper', lambda: True)
    calls = []
    def load(*args, **kwargs):
        calls.append(kwargs['use_cuda'])
        return SimpleNamespace(session=SimpleNamespace(get_providers=lambda: ['CPUExecutionProvider']))
    monkeypatch.setitem(sys.modules, 'piper', SimpleNamespace(PiperVoice=SimpleNamespace(load=load)))
    with pytest.raises(RuntimeError, match='khởi tạo CUDA thất bại'):
        audio_service.get_voice('test')
    assert calls == [True], 'strict mode must never retry CPU'
    assert not audio_service._voice_instances


def test_benchmark_cli_help_without_gradio():
    import subprocess
    import sys
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, str(root/'translation/core/benchmark_file.py'), '--help'],
                            cwd=root, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert '--beam' in result.stdout and '--backend' in result.stdout


def test_cuda_conv_policy_and_runtime_fallback_disabled(monkeypatch):
    from tts.cuda_session import configure_cuda_session, guard_cuda_session
    monkeypatch.setenv('PIPER_DEVICE', 'cuda')
    class Session:
        disabled = 0
        def set_providers(self, providers):
            self.providers = providers
        def disable_fallback(self):
            self.disabled += 1
        def get_providers(self):
            return ['CUDAExecutionProvider', 'CPUExecutionProvider']
    session = Session()
    configure_cuda_session(session)
    assert session.providers[0][1]['cudnn_conv1d_pad_to_nc1d'] == '1'
    assert session.providers[0][1]['cudnn_conv_algo_search'] == 'DEFAULT'
    guard_cuda_session(SimpleNamespace(session=session))
    assert session.disabled == 2


def test_cuda_guard_detects_provider_lost_after_inference(monkeypatch):
    from tts.cuda_session import guard_cuda_session
    monkeypatch.setenv('PIPER_REQUIRE_CUDA', '1')
    session = SimpleNamespace(disable_fallback=lambda: None,
                              get_providers=lambda: ['CPUExecutionProvider'])
    with pytest.raises(RuntimeError, match='mất CUDA'):
        guard_cuda_session(SimpleNamespace(session=session))


@pytest.mark.parametrize('batch', [96, 128, 192, 256, 512, 1024])
def test_web_allows_larger_translation_batches(batch):
    assert Config(batch_size=batch).batch_size == batch


@pytest.mark.parametrize('batch', [0, 1025])
def test_web_rejects_batch_outside_bounds(batch):
    with pytest.raises(ValueError):
        Config(batch_size=batch)
