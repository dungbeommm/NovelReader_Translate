import io
import json
import os
import threading
import wave
import zipfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from storage.store import Store
from storage import checkpoints
from web.schemas import Config


@pytest.fixture
def book(tmp_path, monkeypatch):
    monkeypatch.setenv('NOVEL_DATA', str(tmp_path / 'data'))
    store = Store(tmp_path / 'book.sqlite3')
    store.replace('sample.txt', 'utf-8', [('第一章', '你好'), ('第二章', '世界')])
    store.configure(Config(batch_size=1024, audio_workers=3).model_dump())
    cid = store.list()[0]['id']
    store.update(cid, status='done', translated_title='Chương 1', translated=['Xin chào'], outputs=['Chương 1', 'Xin chào'], audio_status='done')
    store.export_chapter_text(cid, 'Chương 1', ['Xin chào'], 1)
    (store.audio_dir / 'chuong_0001.mp3').write_bytes(b'fake mp3')
    return store


def test_snapshot_restore_text_and_draft(book, tmp_path):
    checkpoints.save_draft({'batch_size': 512, 'audio_workers': 4, 'api_key': 'never include'})
    private = tmp_path / 'data/private'
    private.mkdir(parents=True)
    (private / 'hf_token.txt').write_text('secret-not-in-backup', encoding='utf-8')
    archive = checkpoints.create_checkpoint(book, tmp_path / 'checkpoint.zip')
    with zipfile.ZipFile(archive) as z:
        assert not any('private' in n or 'audio/' in n for n in z.namelist())
        assert b'never include' not in z.read('workspace_draft.json')
        assert b'secret-not-in-backup' not in b''.join(z.read(n) for n in z.namelist())
    previous_output = book.text_dir
    book.replace('other.txt', 'utf-8', [('Other', 'abc')])
    result = checkpoints.restore_checkpoint(book, archive)
    assert result['chapters'] == 2
    assert book.get(book.list()[0]['id'])['translated'] == ['Xin chào']
    assert book.list()[0]['audio_status'] == 'none'
    assert checkpoints.load_draft()['audio_workers'] == 4
    assert previous_output.exists()
    assert book.text_dir != previous_output


def test_snapshot_with_audio_and_recovery_states(book, tmp_path):
    book.update(book.list()[1]['id'], status='translating', audio_status='generating', outputs=['partial'])
    archive = checkpoints.create_checkpoint(book, tmp_path / 'full.zip', include_audio=True)
    checkpoints.restore_checkpoint(book, archive)
    rows = book.list()
    assert rows[0]['audio_status'] == 'done'
    assert (book.audio_dir / 'chuong_0001.mp3').read_bytes() == b'fake mp3'
    assert rows[1]['audio_status'] == 'none' and rows[1]['status'] == 'pending'
    assert book.get(rows[1]['id'])['outputs'] == ['partial']


def test_reject_tamper_traversal_and_arbitrary_urls(book, tmp_path):
    archive = checkpoints.create_checkpoint(book, tmp_path / 'bad.zip')
    original = book.book()
    with zipfile.ZipFile(archive, 'a') as z:
        z.writestr('../../escape.txt', 'bad')
    with pytest.raises(ValueError):
        checkpoints.restore_checkpoint(book, archive)
    assert book.book() == original


def test_reject_checksum_damage_before_db_mutation(book, tmp_path):
    archive = checkpoints.create_checkpoint(book, tmp_path / 'good.zip')
    bad = tmp_path / 'tampered.zip'
    with zipfile.ZipFile(archive) as z, zipfile.ZipFile(bad, 'w') as out:
        for name in z.namelist():
            out.writestr(name, b'broken' if name == 'data/novel.sqlite3' else z.read(name))
    title = book.book()['title']
    with pytest.raises(ValueError, match='SHA256'):
        checkpoints.restore_checkpoint(book, bad)
    assert book.book()['title'] == title


@pytest.mark.parametrize('workers', [1, 2, 4, 8])
def test_worker_and_queue_config_bounds(workers):
    assert Config(audio_workers=workers, audio_queue_size=32).audio_workers == workers
    with pytest.raises(ValueError): Config(audio_workers=9)
    with pytest.raises(ValueError): Config(audio_queue_size=33)


def test_synthesis_really_overlaps(book, tmp_path, monkeypatch):
    from audio import audio_service
    from tts import synthesis
    barrier = threading.Barrier(2)
    errors = []
    def synth(voice, text, output, **kwargs):
        barrier.wait(timeout=3)
        output.setnchannels(1); output.setsampwidth(2); output.setframerate(22050)
        output.writeframes(b'\0\0' * 20)
    monkeypatch.setattr(synthesis, 'synthesize_wav', synth)
    monkeypatch.setattr(audio_service, 'is_cuda_available_for_piper', lambda: False)
    def run(n):
        try:
            audio_service.synth_text_to_wav(object(), 'test', tmp_path / f'{n}.wav', tmp_path)
        except Exception as exc:
            errors.append(exc)
    threads = [threading.Thread(target=run, args=(n,)) for n in range(2)]
    for t in threads: t.start()
    for t in threads: t.join(5)
    assert not errors
    assert all((tmp_path / f'{n}.wav').exists() for n in range(2))


def test_full_voice_catalog_without_models(tmp_path, monkeypatch):
    from audio import audio_service
    monkeypatch.setattr(audio_service, 'VOICE_DIR', tmp_path)
    voices = audio_service.list_available_voices()
    assert len(voices) >= 22
    assert any(v['id'] == 'ngochuyennew' for v in voices)
    assert not any(v['downloaded'] for v in voices)


def test_checkpoint_routes_and_idle_guard(book, monkeypatch):
    from web.application import create_app
    from web import runtime
    app = create_app()
    runtime.store = book
    runtime.job.store = book
    headers = {'X-App-Request': 'novel-translator'}
    with TestClient(app) as client:
        for path in ('/api/settings/pixeldrain', '/api/settings/gdrive', '/api/export/pixeldrain/status', '/api/export/drive/capabilities'):
            assert client.get(path).status_code == 404
        assert client.post('/api/checkpoints/draft', json={'batch_size': 1024, 'audio_workers': 4}, headers=headers).status_code == 200
        assert client.get('/api/checkpoints/draft').json()['config']['audio_workers'] == 4
        download = client.post('/api/checkpoints/download', json={'include_audio': True}, headers=headers)
        assert download.status_code == 200
        book.replace('different.txt', 'utf-8', [('new', 'different')])
        response = client.post('/api/checkpoints/restore', files={'file': ('test.zip', download.content)}, headers=headers)
        assert response.status_code == 200 and len(book.list()) == 2
        stop = threading.Event()
        t = threading.Thread(target=stop.wait); t.start()
        runtime.job.thread = t
        try:
            assert client.post('/api/checkpoints/download', json={}, headers=headers).status_code == 409
            assert client.post('/api/checkpoints/restore', files={'file': ('test.zip', download.content)}, headers=headers).status_code == 409
        finally:
            stop.set(); t.join()


def test_each_audio_worker_uses_its_own_voice_session(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace
    from audio import audio_service
    from workflows.audio_queue import AudioQueue
    (tmp_path / 'test.onnx').write_bytes(b'stub')
    (tmp_path / 'test.onnx.json').write_text('{}')
    monkeypatch.setattr(audio_service, 'VOICE_DIR', tmp_path)
    monkeypatch.setattr(audio_service, '_voice_instances', {})
    monkeypatch.setenv('PIPER_DEVICE', 'cpu')
    monkeypatch.setenv('PIPER_REQUIRE_CUDA', '0')
    monkeypatch.setitem(sys.modules, 'piper', SimpleNamespace(PiperVoice=SimpleNamespace(load=lambda *a, **k: SimpleNamespace(session=SimpleNamespace(get_providers=lambda: ['CPUExecutionProvider'])))))
    sessions = []
    barrier = threading.Barrier(3)
    def consume(item):
        voice = audio_service.get_voice('test')
        assert audio_service.get_voice('test') is voice
        sessions.append(id(voice))
        barrier.wait(timeout=3)
    queue = AudioQueue(consume, lambda: True, lambda _: None, workers=3)
    for item in range(3): queue.submit(item)
    queue.close()
    assert len(set(sessions)) == 3
    audio_service.release_worker_voices()
    assert not audio_service._voice_instances
