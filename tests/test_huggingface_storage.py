import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from storage import huggingface_service as hf, checkpoints, cloud_settings
from storage.store import Store

H = {'X-App-Request': 'novel-translator'}


@pytest.fixture
def book(tmp_path, monkeypatch):
    monkeypatch.setenv('NOVEL_DATA', str(tmp_path / 'data'))
    monkeypatch.setenv('HF_TOKEN', 'test-private-token')
    store = Store(tmp_path / 'book.sqlite3')
    store.replace('sample.txt', 'utf-8', [('第一章', '你好')])
    return store


@pytest.fixture
def api(monkeypatch):
    api = Mock()
    monkeypatch.setattr(hf, 'client', lambda: api)
    return api


@pytest.mark.parametrize('kind', ['txt', 'epub'])
def test_text_exports_have_unique_paths_and_fixed_repository(book, api, kind):
    first, second = hf.export_book(book, kind), hf.export_book(book, kind)
    assert first['id'] != second['id']
    assert first['url'].startswith(hf.BASE_URL + '/blob/main/exports/')
    args = api.upload_file.call_args.kwargs
    assert args['repo_id'] == 'uri410/novelreader-storage'
    assert args['repo_type'] == 'dataset'
    assert isinstance(args['path_or_fileobj'], bytes)
    assert first['size_bytes'] == len(args['path_or_fileobj'])


def test_audio_exports_snapshot_finished_files_without_zip(book, api):
    (book.audio_dir / 'good.mp3').write_bytes(b'audio')
    nested = book.audio_dir / 'audio_gop'
    nested.mkdir()
    (nested / 'merged.m4b').write_bytes(b'merged')
    hidden = book.audio_dir / '.partial'
    hidden.mkdir()
    (hidden / 'temp.wav').write_bytes(b'partial')
    (book.audio_dir / 'secret.json').write_text('secret')
    def upload(**kwargs):
        root = Path(kwargs['folder_path'])
        assert sorted(p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()) == ['audio_gop/merged.m4b', 'good.mp3']
        assert kwargs['repo_id'] == hf.REPO_ID
    api.upload_folder.side_effect = upload
    result = hf.export_book(book, 'audio')
    assert result['total_files'] == 2 and result['size_bytes'] == 11
    assert '/tree/main/audio/' in result['url']
    api.upload_file.assert_not_called()


def test_single_audio_rejects_traversal_and_unknown_extensions(book, api):
    (book.audio_dir / 'secret.json').write_text('secret')
    for name in ['../secret.json', '..\\secret.json', 'secret.json', 'missing.mp3']:
        with pytest.raises(ValueError):
            hf.export_audio_file(book, name)
    api.upload_file.assert_not_called()


def test_single_audio_snapshot(book, api):
    (book.audio_dir / 'good.mp3').write_bytes(b'audio')
    def upload(**kwargs):
        assert Path(kwargs['path_or_fileobj']).read_bytes() == b'audio'
    api.upload_file.side_effect = upload
    assert hf.export_audio_file(book, 'good.mp3')['size_bytes'] == 5


@pytest.mark.parametrize('value', [
    '../secret.zip', '/checkpoints/test.zip', 'checkpoints/../secret.zip',
    'checkpoints//test.zip', 'checkpoints/a.exe', 'checkpoints/a\\x.zip',
    'https://evil.example/checkpoints/a.zip',
    'https://huggingface.co/datasets/other/repo/blob/main/checkpoints/a.zip',
    hf.BASE_URL + '/blob/main/checkpoints/%2e%2e/secret.zip',
    hf.BASE_URL + '/blob/main/checkpoints/a.zip?download=1',
])
def test_checkpoint_path_is_confined(value):
    with pytest.raises(ValueError):
        hf.checkpoint_path(value)


def test_checkpoint_upload_and_restore_download(book, api, tmp_path, monkeypatch):
    uploaded = checkpoints.upload_checkpoint(book)
    assert uploaded['id'].startswith('checkpoints/')
    assert json.loads((cloud_settings.key_path().parents[1] / 'cloud_checkpoint_last.json').read_text('utf-8'))['id'] == uploaded['id']
    cached = tmp_path / 'cached.zip'
    cached.write_bytes(b'archive')
    api.repo_info.return_value = SimpleNamespace(sha='pinned-commit')
    api.get_paths_info.return_value = [SimpleNamespace(size=7)]
    download = Mock(return_value=str(cached))
    monkeypatch.setattr(hf, 'hf_hub_download', download)
    target = checkpoints.download_checkpoint(uploaded['url'], tmp_path / 'out.zip')
    assert target.read_bytes() == b'archive'
    assert download.call_args.kwargs['revision'] == 'pinned-commit'
    assert download.call_args.kwargs['repo_id'] == hf.REPO_ID
    api.get_paths_info.return_value = [SimpleNamespace(size=checkpoints.MAX_ARCHIVE + 1)]
    with pytest.raises(ValueError):
        checkpoints.download_checkpoint(uploaded['id'], target)
    assert download.call_count == 1


def test_routes_defaults_old_cloud_removed_and_errors_redacted(book, api):
    from web.application import create_app
    from web import runtime
    app = create_app()
    runtime.store = runtime.job.store = book
    with TestClient(app) as client:
        status = client.get('/api/storage/status')
        assert status.json()['default_destination'] == 'huggingface'
        assert 'test-private-token' not in status.text
        assert client.post('/api/export/huggingface/txt', json={}, headers=H).status_code == 200
        assert client.post('/api/export/huggingface/txt', json={}).status_code == 403
        for path in ['/api/export/pixeldrain/status', '/api/settings/gdrive', '/api/drive-api/status', '/api/export/drive/capabilities']:
            assert client.get(path).status_code == 404
        api.upload_file.side_effect = RuntimeError('test-private-token')
        failed = client.post('/api/export/huggingface/txt', json={}, headers=H)
        assert failed.status_code == 502 and 'test-private-token' not in failed.text
        api.upload_file.reset_mock()
        monkey_thread = SimpleNamespace(is_alive=lambda: True)
        previous = runtime.job.thread
        runtime.job.thread = monkey_thread
        try:
            assert client.post('/api/export/huggingface/audio', json={}, headers=H).status_code == 409
        finally:
            runtime.job.thread = previous


def test_missing_token_fails_before_network(tmp_path, monkeypatch):
    monkeypatch.setenv('NOVEL_DATA', str(tmp_path))
    monkeypatch.delenv('HF_TOKEN', raising=False)
    with pytest.raises(ValueError, match='HF_TOKEN'):
        hf.client()


def test_notebook_bundle_excludes_runtime_data_and_retired_backends():
    import io
    import zipfile
    from scripts.package_notebooks import source_archive, RETIRED
    with zipfile.ZipFile(io.BytesIO(source_archive())) as archive:
        names = archive.namelist()
        assert 'storage/huggingface_service.py' in names
        assert not set(names).intersection(RETIRED)
        assert not any(n.startswith(('data/', 'models/', 'output_text/', 'output_audio/')) or n == '.env' for n in names)
        assert b'private-token-from-user' not in archive.read('storage/huggingface_service.py')
