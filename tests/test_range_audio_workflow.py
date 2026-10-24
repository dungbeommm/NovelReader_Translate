"""Regression tests for scoped translation + audio and fixed-size grouping."""
import wave
from pathlib import Path
import pytest
from audio import audio_service, merge_service
from workflows.jobs import Job
from storage.store import Store


class FakeEngine:
    def load(self):
        pass

    def translate(self, texts, glossary, **kwargs):
        return ['Ban dich ' + text for text in texts]


def make_store(tmp_path, count=8):
    store = Store(tmp_path / 'db.sqlite', text_dir=tmp_path / 'text', audio_dir=tmp_path / 'audio')
    store.replace('test.txt', 'utf8', [(f'Chapter {i}', f'Noi dung {i}') for i in range(1, count + 1)])
    return store


def add_audio(store, positions):
    for chapter in store.list():
        if chapter['position'] in positions:
            (store.audio_dir / f"chuong_{chapter['position']:04d}.wav").write_bytes(b'audio')


@pytest.fixture
def fake_merge(monkeypatch):
    calls = []
    def merge(files, target, **kwargs):
        calls.append(([p.name for p in files], kwargs))
        target.write_bytes(b'merged')
        return target
    monkeypatch.setattr(merge_service, 'merge_audio_files', merge)
    return calls


def test_range_only_translates_and_generates_audio(tmp_path, monkeypatch):
    store = make_store(tmp_path)
    outside = [c for c in store.list() if c['position'] > 5]
    for c in outside:
        store.update(c['id'], status='done', translated=['giu nguyen'], audio_status='done')
    add_audio(store, [6, 7, 8])
    before = {c['id']: store.get(c['id']) for c in outside}
    audio_before = {p.name: p.read_bytes() for p in store.audio_dir.iterdir()}
    calls = []
    monkeypatch.setattr('workflows.jobs.create_engine', lambda _: FakeEngine())
    def generate(cid, pos, title, paras, directory, **kwargs):
        calls.append(pos)
        p = directory / f'chuong_{pos:04d}.wav'
        p.write_bytes(b'new audio')
        return p
    monkeypatch.setattr(audio_service, 'generate_chapter_audio', generate)
    job = Job(store)
    job.start({'engine': 'local', 'glossary': '', 'batch_size': 8,
               'start_pos': 1, 'end_pos': 5, 'generate_audio': True,
               'force_retranslate': True})
    job.thread.join(10)
    assert not job.thread.is_alive()
    assert calls == [1, 2, 3, 4, 5]
    assert all(c['status'] == 'done' for c in store.list())
    assert {cid: store.get(cid) for cid in before} == before
    assert all((store.audio_dir / name).read_bytes() == data for name, data in audio_before.items())
    assert job.summary()['total'] == 5


def test_generate_audio_false_skips_audio(tmp_path, monkeypatch):
    store = make_store(tmp_path, 5)
    monkeypatch.setattr('workflows.jobs.create_engine', lambda _: FakeEngine())
    calls = []
    def generate(cid, pos, title, paras, directory, **kwargs):
        calls.append(pos)
        return directory / f'chuong_{pos:04d}.wav'
    monkeypatch.setattr(audio_service, 'generate_chapter_audio', generate)
    job = Job(store)
    job.start({'engine': 'local', 'glossary': '', 'batch_size': 8,
               'start_pos': 1, 'end_pos': 5, 'generate_audio': False})
    job.thread.join(10)
    assert not job.thread.is_alive()
    assert calls == []


@pytest.mark.parametrize('scope', [
    {'chapter_ids': []},
    {'start_pos': 5, 'end_pos': 1}, {'start_pos': 50, 'end_pos': 60},
    {'start_pos': 1, 'end_pos': 5, 'chapter_ids': [1]},
    {'chapter_ids': [99999]},
])
def test_invalid_scope_never_starts_all_chapters(tmp_path, scope):
    store = make_store(tmp_path)
    before = store.list()
    job = Job(store)
    with pytest.raises(ValueError):
        job.start({'glossary': '', **scope})
    assert store.list() == before
    assert job.thread is None


def test_single_bound_scope_translates_to_limit(tmp_path, monkeypatch):
    store = make_store(tmp_path, 8)
    monkeypatch.setattr('workflows.jobs.create_engine', lambda _: FakeEngine())
    calls = []
    def generate(cid, pos, title, paras, directory, **kwargs):
        calls.append(pos)
        p = directory / f'chuong_{pos:04d}.wav'
        p.write_bytes(b'new audio')
        return p
    monkeypatch.setattr(audio_service, 'generate_chapter_audio', generate)

    job = Job(store)
    job.start({'engine': 'local', 'glossary': '', 'batch_size': 8,
               'start_pos': 5, 'generate_audio': True})
    job.thread.join(10)
    assert not job.thread.is_alive()
    assert calls == [5, 6, 7, 8]


def test_groups_of_50_with_remainder(tmp_path, fake_merge):
    store = make_store(tmp_path, 120)
    add_audio(store, range(1, 121))
    groups = merge_service.group_and_merge_chapters(store, 50)
    assert [(g['start_pos'], g['end_pos'], g['chapter_count']) for g in groups] == [
        (1, 50, 50), (51, 100, 50), (101, 120, 20)
    ]
    assert len(fake_merge) == 3
    assert fake_merge[0][0][0] == 'chuong_0001.wav'
    assert fake_merge[0][0][-1] == 'chuong_0050.wav'
    assert fake_merge[2][0][0] == 'chuong_0101.wav'
    assert fake_merge[2][0][-1] == 'chuong_0120.wav'


def test_scoped_merge_smaller_than_group(tmp_path, fake_merge):
    store = make_store(tmp_path, 50)
    add_audio(store, range(1, 6))
    ids = [c['id'] for c in store.list() if 1 <= c['position'] <= 5]
    groups = merge_service.group_and_merge_chapters(store, 50, chapter_ids=ids)
    assert [(g['start_pos'], g['end_pos'], g['chapter_count']) for g in groups] == [(1, 5, 5)]
    assert len(fake_merge) == 1
    assert fake_merge[0][0] == [f'chuong_{i:04d}.wav' for i in range(1, 6)]


def test_missing_audio_never_shifts_boundaries(tmp_path, fake_merge):
    store = make_store(tmp_path, 100)
    add_audio(store, set(range(1, 101)) - {25})
    groups = merge_service.group_and_merge_chapters(store, 50)
    assert [(g['start_pos'], g['end_pos']) for g in groups] == [(51, 100)]
    assert len(fake_merge) == 1


def test_scoped_groups_leave_outside_audio_untouched(tmp_path, fake_merge):
    store = make_store(tmp_path, 100)
    add_audio(store, range(1, 101))
    ids = [c['id'] for c in store.list() if c['position'] <= 50]
    groups = merge_service.group_and_merge_chapters(store, 50, chapter_ids=ids)
    assert [(g['start_pos'], g['end_pos']) for g in groups] == [(1, 50)]
    assert merge_service.group_and_merge_chapters(store, 50, chapter_ids=[]) == []
    assert len(fake_merge) == 1


def test_cached_groups_and_changed_sources(tmp_path, fake_merge):
    store = make_store(tmp_path, 4)
    add_audio(store, range(1, 5))
    merge_service.group_and_merge_chapters(store, 2, bitrate='128k')
    merge_service.group_and_merge_chapters(store, 2, bitrate='128k')
    assert len(fake_merge) == 2
    (store.audio_dir / 'chuong_0001.wav').write_bytes(b'updated audio')
    merge_service.group_and_merge_chapters(store, 2, bitrate='128k')
    assert len(fake_merge) == 3
    assert fake_merge[-1][1]['bitrate'] == '128k'


@pytest.mark.parametrize('size', [0, 1, -1, 501, 2.5, True])
def test_bad_group_size(tmp_path, size):
    with pytest.raises(ValueError):
        merge_service.group_and_merge_chapters(make_store(tmp_path), size)


def test_real_ffmpeg_merge(tmp_path):
    store = make_store(tmp_path, 2)
    for pos in (1, 2):
        with wave.open(str(store.audio_dir / f'chuong_{pos:04d}.wav'), 'wb') as f:
            f.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
            f.writeframes(b'\0\0' * 1600)
    groups = merge_service.group_and_merge_chapters(store, 2, 'wav')
    with wave.open(groups[0]['file_path'], 'rb') as f:
        assert f.getnframes() == 3200
        assert f.getframerate() == 16000


def test_auto_job_never_merges_unrelated_groups(tmp_path, monkeypatch, fake_merge):
    store = make_store(tmp_path, 8)
    add_audio(store, range(1, 9))
    monkeypatch.setattr('workflows.jobs.create_engine', lambda _: FakeEngine())
    def generate(cid, pos, title, paras, directory, **kwargs):
        p = directory / f'chuong_{pos:04d}.wav'
        p.write_bytes(b'new audio')
        return p
    monkeypatch.setattr(audio_service, 'generate_chapter_audio', generate)
    job = Job(store)
    job.start({'glossary': '', 'engine': 'local', 'start_pos': 1, 'end_pos': 4,
               'auto_group_audio': True, 'group_size': 2, 'audio_format': 'wav', 'force_retranslate': True})
    job.thread.join(10)
    assert not job.thread.is_alive()
    assert len(fake_merge) == 2
    assert all('0005' not in name for call, _ in fake_merge for name in call)
    assert sorted(p.name for p in (store.audio_dir / 'audio_gop').glob('*.wav')) == ['chuong_0001_0002.wav', 'chuong_0003_0004.wav']


def test_audio_failure_is_reported_without_touching_other_chapters(tmp_path, monkeypatch):
    store = make_store(tmp_path)
    monkeypatch.setattr('workflows.jobs.create_engine', lambda _: FakeEngine())
    def fail(*args, **kwargs):
        raise RuntimeError('missing voice model')
    monkeypatch.setattr(audio_service, 'generate_chapter_audio', fail)
    job = Job(store)
    job.start({'glossary': '', 'start_pos': 1, 'end_pos': 1})
    job.thread.join(10)
    assert job.status == 'error'
    assert store.list()[0]['audio_status'] == 'error'
    assert all(c['status'] == 'pending' for c in store.list()[1:])


def test_real_ffmpeg_mp3_merge(tmp_path):
    import json
    import subprocess
    store = make_store(tmp_path, 2)
    for pos in (1, 2):
        with wave.open(str(store.audio_dir / f'chuong_{pos:04d}.wav'), 'wb') as f:
            f.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
            f.writeframes(b'\0\0' * 8000)
    group = merge_service.group_and_merge_chapters(store, 2, 'mp3')[0]
    probe = subprocess.run(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json',
                            group['file_path']], check=True, capture_output=True, text=True)
    info = json.loads(probe.stdout)
    assert info['streams'][0]['codec_name'] == 'mp3'
    assert 0.95 <= float(info['format']['duration']) <= 1.2


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    import importlib
    from fastapi.testclient import TestClient
    monkeypatch.setenv('NOVEL_DATA', str(tmp_path / 'data'))
    import main
    importlib.reload(main)
    store = make_store(tmp_path)
    monkeypatch.setattr(main.runtime, 'store', store)
    monkeypatch.setattr(main.runtime, 'job', Job(store))
    with TestClient(main.app) as client:
        yield client, store


@pytest.mark.parametrize('scope', [
    {'chapter_ids': []},
    {'start_pos': 5, 'end_pos': 1}, {'start_pos': 1, 'end_pos': 5, 'chapter_ids': [1]},
])
def test_api_rejects_invalid_scopes(api_client, scope):
    client, store = api_client
    response = client.post('/api/translate/start', json=scope, headers={'X-App-Request': 'novel-translator'})
    assert response.status_code == 422
    assert all(c['status'] == 'pending' for c in store.list())


def test_api_accepts_single_bound_scope(api_client):
    client, store = api_client
    response = client.post('/api/translate/start', json={'start_pos': 1}, headers={'X-App-Request': 'novel-translator'})
    assert response.status_code == 200


def test_api_manual_group_does_not_translate_or_generate_audio(api_client, monkeypatch, fake_merge):
    client, store = api_client
    add_audio(store, range(1, 9))
    def forbidden(*args, **kwargs):
        raise AssertionError('Manual grouping must not translate or synthesize audio')
    monkeypatch.setattr('workflows.jobs.create_engine', forbidden)
    monkeypatch.setattr(audio_service, 'generate_chapter_audio', forbidden)
    response = client.post('/api/audio/auto-group', json={'group_size': 2, 'format': 'mp3'},
                           headers={'X-App-Request': 'novel-translator'})
    assert response.status_code == 200
    assert response.json()['count'] == 4
    assert all(c['status'] == 'pending' for c in store.list())
    listing = client.get('/api/audio/groups').json()
    assert len(listing) == 4
    assert all(item['filename'].endswith('.mp3') for item in listing)
    assert all('sources.json' not in item['filename'] for item in listing)


def test_api_manual_group_waits_for_missing_audio(api_client, fake_merge):
    client, store = api_client
    add_audio(store, [1, 3, 4, 5])
    response = client.post('/api/audio/auto-group', json={'group_size': 2},
                           headers={'X-App-Request': 'novel-translator'})
    assert response.status_code == 200
    assert [(g['start_pos'], g['end_pos']) for g in response.json()['groups']] == [(3, 4)]


def test_merge_error_does_not_change_successful_audio_status(tmp_path, monkeypatch):
    store = make_store(tmp_path, 2)
    monkeypatch.setattr('workflows.jobs.create_engine', lambda _: FakeEngine())
    def generate(cid, pos, title, paras, directory, **kwargs):
        p = directory / f'chuong_{pos:04d}.wav'
        p.write_bytes(b'new audio')
        return p
    def fail(*args, **kwargs):
        raise RuntimeError('ffmpeg unavailable')
    monkeypatch.setattr(audio_service, 'generate_chapter_audio', generate)
    monkeypatch.setattr(merge_service, 'merge_audio_files', fail)
    job = Job(store)
    job.start({'glossary': '', 'start_pos': 1, 'end_pos': 2,
               'auto_group_audio': True, 'group_size': 2})
    job.thread.join(10)
    assert job.status == 'error'
    assert all(c['audio_status'] == 'done' for c in store.list())


def test_job_scoped_range_smaller_than_group_size_auto_merges(tmp_path, monkeypatch, fake_merge):
    store = make_store(tmp_path, 20)
    monkeypatch.setattr('workflows.jobs.create_engine', lambda _: FakeEngine())
    def generate(cid, pos, title, paras, directory, **kwargs):
        p = directory / f'chuong_{pos:04d}.wav'
        p.write_bytes(b'new audio')
        return p
    monkeypatch.setattr(audio_service, 'generate_chapter_audio', generate)

    job = Job(store)
    # Translate chapters 1 to 5 with group_size=50 (5 < 50)
    job.start({'engine': 'local', 'glossary': '', 'batch_size': 8,
               'start_pos': 1, 'end_pos': 5, 'group_size': 50,
               'force_retranslate': True, 'auto_group_audio': True})
    job.thread.join(10)
    assert not job.thread.is_alive()
    assert job.status == 'ready'

    # Must automatically merge chapters 1..5 into one file even though 5 < 50
    assert len(fake_merge) >= 1
    merged_files = fake_merge[-1][0]
    assert merged_files == [f'chuong_{i:04d}.wav' for i in range(1, 6)]
