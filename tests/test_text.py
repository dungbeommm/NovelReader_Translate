import pytest
from translation.text import split_chapters, segment_text, paragraphs, make_plan, assemble, normalize,postprocess

@pytest.mark.parametrize('heading',['第一章 少年','第〇二節 出发','第102回 故事','Chapter 12 Dawn','第两百卷 风起'])
def test_chapter_forms(heading):
    result=split_chapters(heading+'\n正文\n第二章 结尾\n下文')
    assert len(result)==2 and result[0]==(heading,'正文')

def test_preamble():assert split_chapters('序言\n第一章 山\n文')[0]==('Lời mở đầu','序言')
def test_fallback():
    text='字'*9001; cs=split_chapters(text)
    assert len(cs)==4 and ''.join(c[1] for c in cs)==text
    assert max(len(c[1]) for c in cs)<=3000

def test_no_inline_heading():assert split_chapters('他说第一章很有趣。')[0][0]=='Phần 1'
def test_blank():
    with pytest.raises(ValueError):split_chapters(' \n')
def test_normalize():assert normalize('“你好”\r\n\r\n　再见 ' )=='"你好"\n再见'
def test_segment_no_loss():
    text='这是一个句子。'*90+'结尾'
    segments=segment_text(text)
    assert ''.join(segments)==text and all(len(s)<=200 for s in segments)
def test_protect_segment_boundary():
    text='一'*198+'玄剑宗'+'二'*210
    ss=segment_text(text,terms=['玄剑宗'])
    assert ''.join(ss)==text and any('玄剑宗' in s for s in ss)
def test_alignment():
    ps=['甲'*250,'乙。'];plan=make_plan('标题',ps)
    title,merged=assemble(plan,['Tựa','A','B'],2)
    assert title=='Tựa' and merged==['A','B']
def test_paragraphs():assert paragraphs('甲\n\n“乙”\n丙')==['甲','"乙"','丙']
def test_punctuation():assert postprocess('xin chào ， ngươi 。 tiếp tục ！')=='Xin chào, ngươi. Tiếp tục!'
