import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from storage import huggingface_service as hf, checkpoints, cloud_settings
from storage.store import Store
from huggingface_hub import BucketFile, BucketFolder

H = {'X-App-Request': 'novel-translator'}


def bucket_file(path, size=0, uploaded_at=None):
    return BucketFile(type='file', path=path, size=size, xetHash='hash', uploadedAt=uploaded_at)


def bucket_folder(path):
    return BucketFolder(type='directory', path=path, uploadedAt=None)


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
def test_text_exports_have_unique_paths_and_fixed_bucket(book, api, kind):
    first, second = hf.export_book(book, kind), hf.export_book(book, kind)
    assert first['id'] != second['id']
    assert first['url'].startswith(hf.BASE_URL + '/tree/main/exports/')
    assert api.batch_bucket_files.call_args.args[0] == 'uri410/novelreader-storage'
    payload, path = api.batch_bucket_files.call_args.kwargs['add'][0]
    assert path.startswith('exports/') and path.endswith(f'.{kind}')
    assert isinstance(payload, bytes)
    assert first['size_bytes'] == len(payload)


def test_audio_exports_snapshot_finished_files_without_zip(book, api):
    (book.audio_dir / 'good.mp3').write_bytes(b'audio')
    nested = book.audio_dir / 'audio_gop'
    nested.mkdir()
    (nested / 'merged.m4b').write_bytes(b'merged')
    hidden = book.audio_dir / '.partial'
    hidden.mkdir()
    (hidden / 'temp.wav').write_bytes(b'partial')
    (book.audio_dir / 'secret.json').write_text('secret')
    uploaded = {}
    def upload(bucket_id, *, add):
        for source, destination in add:
            uploaded[destination] = Path(source).read_bytes()
    api.batch_bucket_files.side_effect = upload
    result = hf.export_book(book, 'audio')
    assert result['total_files'] == 2 and result['size_bytes'] == 11
    assert any(path.endswith('/audio_gop/merged.m4b') and data == b'merged'
               for path, data in uploaded.items())
    assert any(path.endswith('/good.mp3') and data == b'audio' for path, data in uploaded.items())
    assert '/tree/main/audio/' in result['url']


def test_single_audio_rejects_traversal_and_unknown_extensions(book, api):
    (book.audio_dir / 'secret.json').write_text('secret')
    for name in ['../secret.json', '..\\secret.json', 'secret.json', 'missing.mp3']:
        with pytest.raises(ValueError):
            hf.export_audio_file(book, name)
    api.batch_bucket_files.assert_not_called()


def test_single_audio_snapshot(book, api):
    (book.audio_dir / 'good.mp3').write_bytes(b'audio')
    def upload(bucket_id, *, add):
        assert Path(add[0][0]).read_bytes() == b'audio'
    api.batch_bucket_files.side_effect = upload
    assert hf.export_audio_file(book, 'good.mp3')['size_bytes'] == 5


@pytest.mark.parametrize('value', [
    '../secret.zip', '/checkpoints/test.zip', 'checkpoints/../secret.zip',
    'checkpoints//test.zip', 'checkpoints/a.exe', 'checkpoints/a\\x.zip',
    'https://evil.example/checkpoints/a.zip',
    'https://huggingface.co/datasets/uri410/novelreader-storage/blob/main/checkpoints/a.zip',
    'https://huggingface.co/buckets/other/repo/resolve/checkpoints/a.zip',
    hf.BASE_URL + '/tree/main/checkpoints/%2e%2e/secret.zip',
    hf.BASE_URL + '/tree/main/checkpoints/a.zip?download=1',
])
def test_checkpoint_path_is_confined(value):
    with pytest.raises(ValueError):
        hf.checkpoint_path(value)


@pytest.mark.parametrize('url', [
    hf.BASE_URL + '/tree/main/checkpoints/test/file.zip',
    hf.BASE_URL + '/resolve/checkpoints/test/file.zip',
])
def test_checkpoint_path_accepts_bucket_links(url):
    assert hf.checkpoint_path(url) == 'checkpoints/test/file.zip'


def test_checkpoint_upload_and_restore_download(book, api, tmp_path):
    uploaded = checkpoints.upload_checkpoint(book)
    assert uploaded['id'].startswith('checkpoints/')
    assert json.loads((cloud_settings.key_path().parents[1] / 'cloud_checkpoint_last.json').read_text('utf-8'))['id'] == uploaded['id']
    api.get_bucket_paths_info.return_value = [bucket_file(uploaded['id'], size=7)]
    def download(bucket_id, files, **kwargs):
        Path(files[0][1]).write_bytes(b'archive')
    api.download_bucket_files.side_effect = download
    target = checkpoints.download_checkpoint(uploaded['url'], tmp_path / 'out.zip')
    assert target.read_bytes() == b'archive'
    assert api.download_bucket_files.call_args.args[0] == hf.REPO_ID
    api.get_bucket_paths_info.return_value = [bucket_file(uploaded['id'], size=checkpoints.MAX_ARCHIVE + 1)]
    with pytest.raises(ValueError):
        checkpoints.download_checkpoint(uploaded['id'], target)
    assert api.download_bucket_files.call_count == 1


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
        api.batch_bucket_files.side_effect = RuntimeError('test-private-token')
        failed = client.post('/api/export/huggingface/txt', json={}, headers=H)
        assert failed.status_code == 502 and 'test-private-token' not in failed.text
        api.batch_bucket_files.reset_mock()
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


@pytest.mark.parametrize('path', ['../x', '/audio', 'a//b', 'a/./b', 'a/../b', 'a\\b', 'a\n.txt', 'a:', 'a/'])
def test_repository_browser_rejects_invalid_paths_before_network(api, path):
    with pytest.raises(ValueError):
        hf.list_directory(path)
    api.list_bucket_tree.assert_not_called()


def test_repository_listing_and_unique_uploads(api):
    api.list_bucket_tree.return_value = [
        bucket_file('notes.txt', 12, '2026-10-26T12:00:00Z'),
        bucket_folder('audio'),
        bucket_file('.gitkeep', 0),
    ]
    result = hf.list_directory()
    assert [item['name'] for item in result['entries']] == ['audio', 'notes.txt']
    assert result['file_bytes'] == 12
    assert result['entries'][1]['updated_at'].startswith('2026-10-26T12:00:00')
    assert api.list_bucket_tree.call_args.kwargs['recursive'] is False
    api.get_bucket_paths_info.return_value = []
    api.list_bucket_tree.return_value = []
    hf.upload_to_directory(b'data', 'notes.txt', 'books')
    assert api.batch_bucket_files.call_args.kwargs['add'] == [(b'data', 'books/notes.txt')]
    hf.upload_to_directory(b'', 'new', 'books', folder=True)
    assert api.batch_bucket_files.call_args.kwargs['add'] == [(b'', 'books/new/.gitkeep')]
    api.get_bucket_paths_info.return_value = [bucket_file('books/new')]
    with pytest.raises(FileExistsError):
        hf.upload_to_directory(b'', 'new', 'books', folder=True)
    api.get_bucket_paths_info.return_value = []
    api.list_bucket_tree.return_value = [bucket_file('books/existing/chapter.mp3')]
    with pytest.raises(FileExistsError):
        hf.upload_to_directory(b'', 'existing', 'books', folder=True)
    assert api.batch_bucket_files.call_count == 2
    with pytest.raises(ValueError):
        hf.upload_to_directory(b'data', 'nested/file.txt')


def test_repository_listing_is_bounded(api):
    api.list_bucket_tree.return_value = (bucket_file(f'{i}.txt', 1) for i in range(1000))
    result = hf.list_directory()
    assert len(result['entries']) == 500 and result['truncated']
    assert result['file_bytes'] == 500


def test_storage_file_routes_keep_credentials_private(book, api, monkeypatch, tmp_path):
    from web.application import create_app
    from web import runtime
    from web.routes import huggingface as routes
    app = create_app()
    runtime.store = runtime.job.store = book
    api.bucket_info.return_value = SimpleNamespace(private=True)
    api.whoami.return_value = {'name': 'reader', 'auth': {'accessToken': 'test-private-token'}}
    api.list_bucket_tree.return_value = [bucket_file('sample.txt', 4)]
    api.get_bucket_paths_info.return_value = []
    with TestClient(app) as client:
        connection = client.post('/api/storage/test', json={}, headers=H)
        assert connection.json()['username'] == 'reader'
        assert 'test-private-token' not in connection.text
        assert client.get('/api/storage/files').json()['entries'][0]['name'] == 'sample.txt'
        api.list_bucket_tree.return_value = []
        assert client.post('/api/storage/folders', json={'name': 'new'}).status_code == 403
        assert client.post('/api/storage/folders', json={'name': 'new'}, headers=H).status_code == 200
        assert client.post('/api/storage/upload', data={'path': 'books'},
                           files={'file': ('sample.txt', b'data')}, headers=H).status_code == 200
        monkeypatch.setattr(routes, 'MAX_FILE', 3)
        assert client.post('/api/storage/upload', files={'file': ('large.txt', b'data')}, headers=H).status_code == 413
        def download(bucket_id, files, **kwargs):
            Path(files[0][1]).write_bytes(b'data')
        api.get_bucket_paths_info.return_value = [bucket_file('sample.txt', 4)]
        api.download_bucket_files.side_effect = download
        response = client.get('/api/storage/download', params={'path': 'sample.txt'})
        assert response.content == b'data'
        api.list_bucket_tree.side_effect = RuntimeError('test-private-token')
        failure = client.get('/api/storage/files')
        assert failure.status_code == 502 and 'test-private-token' not in failure.text


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
