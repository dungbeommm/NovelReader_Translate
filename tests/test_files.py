import zipfile
from io import BytesIO
from ebooklib import epub
from storage.files import parse_file,export_txt,export_epub,decode_text

def test_gb18030():
    s='第一章 少年\n林羽来到山门前。'*30
    assert decode_text(s.encode('gb18030'))[0]==s

def test_epub_spine(tmp_path):
    b=epub.EpubBook();b.set_identifier('test');b.set_title('Test');b.set_language('zh')
    a=epub.EpubHtml(title='B',file_name='b.xhtml');a.content='<h1>第二章 B</h1><p>乙</p>'
    c=epub.EpubHtml(title='A',file_name='a.xhtml');c.content='<h1>第一章 A</h1><p>甲</p>'
    b.add_item(a);b.add_item(c);b.add_item(epub.EpubNcx());b.add_item(epub.EpubNav());b.spine=['nav',c,a];b.toc=[c,a]
    p=tmp_path/'a.epub';epub.write_epub(str(p),b)
    chapters,enc=parse_file('a.epub',p.read_bytes())
    assert [c[0] for c in chapters]==['第一章 A','第二章 B']

def test_export_omits_partial(tmp_path):
    book={'id':1,'title':'Test'};chapters=[{'status':'done','title':'甲','translated_title':'A','translated':['Xin chào']},
    {'status':'error','title':'乙','translated_title':'','translated':['DO NOT EXPORT']}]
    txt=export_txt(book,chapters).decode('utf-8-sig');assert 'Xin chào' in txt and 'DO NOT EXPORT' not in txt and 'Chưa dịch' in txt
    data=export_epub(book,chapters)
    with zipfile.ZipFile(BytesIO(data)) as z:
        assert z.namelist()[0]=='mimetype'
        content=''.join(z.read(n).decode() for n in z.namelist() if n.endswith('.xhtml'))
        assert 'Xin chào' in content and 'DO NOT EXPORT' not in content

def test_reject_path_traversal():
    import pytest
    f=BytesIO()
    with zipfile.ZipFile(f,'w') as z:z.writestr('../evil','x')
    with pytest.raises(ValueError):parse_file('x.epub',f.getvalue())
