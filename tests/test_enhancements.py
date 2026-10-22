import importlib
import pytest
from fastapi.testclient import TestClient
from translation.glossary import parse_glossary
from translation.engines import invert_opener_spacing, list_available_models
from workflows.jobs import apply_postprocess

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('NOVEL_DATA', str(tmp_path))
    import main
    importlib.reload(main)
    with TestClient(main.app) as c:
        yield c

def test_api_models(client):
    r = client.get('/api/models')
    assert r.status_code == 200
    models = r.json()
    assert len(models) >= 4
    ids = [m['id'] for m in models]
    assert 'HachimiMT-60-QT' in ids
    assert 'HachimiMT-60' in ids
    assert 'space' in ids

def test_api_hardware(client):
    r = client.get('/api/hardware')
    assert r.status_code == 200
    hw = r.json()
    assert 'cpu_count' in hw
    assert 'intra_threads' in hw
    assert hw['cpu_count'] >= 1

def test_glossary_tab_format():
    text = "林羽\tLâm Vũ\n玄剑宗 -> Huyền Kiếm Tông"
    g = parse_glossary(text)
    assert g['林羽'] == 'Lâm Vũ'
    assert g['玄剑宗'] == 'Huyền Kiếm Tông'

def test_invert_opener_spacing():
    assert invert_opener_spacing('“ Khấu Hồng”') == '“Khấu Hồng”'
    assert invert_opener_spacing('“Khấu Hồng”') == '“Khấu Hồng”'
    assert invert_opener_spacing('“ 123”') == '“ 123”'

def test_postprocess_honorifics():
    cfg = {'honorific_mode': 'safe', 'pronoun_harmonizer': True}
    title, paras = apply_postprocess(
        title='Chương một Sư ca',
        paras=['Sư ca, chúng ta đi gặp sư phụ.'],
        source_title='第一章 师兄',
        source_paras=['师兄，我们去见师父。'],
        config=cfg
    )
    assert 'Sư huynh' in title or 'Sư huynh' in paras[0]

def test_triplet_options_validation(client):
    H = {'X-App-Request': 'novel-translator'}
    r = client.post('/api/translate/start', json={
        'engine': 'HachimiMT-60-QT',
        'beam_size': 3,
        'chunk_mode': 'paragraph',
        'normalize_mode': 't2s'
    }, headers=H)
    assert r.status_code == 409 and 'Hãy nạp truyện trước' in r.text

    r_bad = client.post('/api/translate/start', json={
        'beam_size': 10
    }, headers=H)
    assert r_bad.status_code == 422


