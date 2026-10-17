import pytest
from app.glossary import parse_glossary,protect,translate_with_glossary

def test_parse():assert list(parse_glossary('林 -> Lâm\n林羽 -> Lâm Vũ'))==['林羽','林']
@pytest.mark.parametrize('bad',['no arrow','a ->',' -> b','a -> ⟦G1⟧'])
def test_invalid(bad):
    with pytest.raises(ValueError):parse_glossary(bad)
def test_longest():
    masked,mapping=protect('林羽见林。',{'林':'Lâm','林羽':'Lâm Vũ'})
    assert masked=='⟦G1⟧见⟦G2⟧。' and list(mapping.values())==['Lâm Vũ','Lâm']
def test_restore():assert translate_with_glossary(['林羽'],{'林羽':'Lâm Vũ'},lambda xs:xs)==['Lâm Vũ']
def test_lost_placeholder():
    def raw(xs):return [x.replace('⟦G1⟧','?').replace('你好','xin chào') for x in xs]
    assert translate_with_glossary(['林羽你好'],{'林羽':'Lâm Vũ'},raw)==['Lâm Vũ xin chào']
def test_duplicate_placeholder():
    assert translate_with_glossary(['林羽'],{'林羽':'Lâm Vũ'},lambda xs:['⟦G1⟧⟦G1⟧' for _ in xs])==['Lâm Vũ']
def test_count_mismatch():
    with pytest.raises(RuntimeError):translate_with_glossary(['a'],{},lambda xs:[])

def test_corrupt_suffix_falls_back():
    def raw(xs):return [x+'�' if '⟦' in x else 'Chương hai' for x in xs]
    assert translate_with_glossary(['第二章 凝气境'],{'凝气境':'Ngưng Khí Cảnh'},raw)==['Chương hai Ngưng Khí Cảnh']

def test_raw_corruption_is_not_saved():
    with pytest.raises(RuntimeError):translate_with_glossary(['a'],{},lambda xs:['a�'])
