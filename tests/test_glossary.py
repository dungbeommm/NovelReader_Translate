import pytest

from translation.glossary import parse_glossary, translate_with_glossary


def test_parse():
    assert list(parse_glossary('林 -> Lâm\n林羽 -> Lâm Vũ')) == ['林羽', '林']


@pytest.mark.parametrize('bad', ['no arrow', 'a ->', ' -> b'])
def test_invalid(bad):
    with pytest.raises(ValueError):
        parse_glossary(bad)


def test_conflicting_duplicate_rejected():
    with pytest.raises(ValueError):
        parse_glossary('林 -> Lâm\n林 -> Lin')


def test_identical_duplicate_merged():
    assert parse_glossary('林 -> Lâm\n林 -> Lâm') == {'林': 'Lâm'}


def test_longest_match_wins():
    seen = []

    def raw(xs):
        seen.extend(xs)
        return xs

    out = translate_with_glossary(['林羽见林。'], {'林': 'Lâm', '林羽': 'Lâm Vũ'}, raw)
    assert out == ['Lâm Vũ见Lâm。']
    assert '林' not in seen[0]


def test_restore():
    assert translate_with_glossary(['林羽'], {'林羽': 'Lâm Vũ'}, lambda xs: xs) == ['Lâm Vũ']


def test_lost_placeholder():
    def raw(xs):
        return [x.replace('QX7', '?').replace('你好', 'xin chào') for x in xs]

    assert translate_with_glossary(['林羽你好'], {'林羽': 'Lâm Vũ'}, raw) == ['Lâm Vũ xin chào']


def test_duplicate_placeholder():
    out = translate_with_glossary(['林羽'], {'林羽': 'Lâm Vũ'}, lambda xs: ['QX7 QX7' for _ in xs])
    assert out == ['Lâm Vũ']


def test_count_mismatch():
    with pytest.raises(RuntimeError):
        translate_with_glossary(['a'], {}, lambda xs: [])


def test_corrupt_suffix_falls_back():
    def raw(xs):
        return [x + '�' if 'QX7' in x else 'Chương hai' for x in xs]

    out = translate_with_glossary(['第二章 凝气境'], {'凝气境': 'Ngưng Khí Cảnh'}, raw)
    assert out == ['Chương hai Ngưng Khí Cảnh']


def test_raw_corruption_is_not_saved():
    with pytest.raises(RuntimeError):
        translate_with_glossary(['a'], {}, lambda xs: ['a�'])
