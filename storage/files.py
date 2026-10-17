from pathlib import Path
from io import BytesIO
import zipfile
import tempfile
import html
from charset_normalizer import from_bytes
from bs4 import BeautifulSoup
from ebooklib import epub, ITEM_DOCUMENT
from translation.text import split_chapters, normalize, CHAPTER

MAX_FILE = 50 * 1024 * 1024

def decode_text(data):
    for encoding in ('utf-8-sig',):
        try: return data.decode(encoding), encoding
        except UnicodeDecodeError: pass
    guess=from_bytes(data, cp_isolation=['utf_8','gb18030','gbk','big5','utf_16','utf_16_le','utf_16_be']).best()
    if guess is None: raise ValueError('Không nhận diện được encoding. Hãy chuyển file sang UTF-8.')
    return str(guess), guess.encoding

def parse_file(name,data):
    if len(data)>MAX_FILE: raise ValueError('File tối đa 50 MB.')
    ext=Path(name).suffix.lower()
    if ext=='.txt':
        text,encoding=decode_text(data)
        return split_chapters(text),encoding
    if ext!='.epub': raise ValueError('Chỉ hỗ trợ .txt và .epub.')
    # Guard compressed bombs, path traversal and encrypted archives before ebooklib.
    with zipfile.ZipFile(BytesIO(data)) as z:
        infos=z.infolist()
        if len(infos)>20000 or sum(i.file_size for i in infos)>200*1024*1024:
            raise ValueError('EPUB giải nén quá lớn (giới hạn 200 MB / 20.000 mục).')
        if any(i.flag_bits & 1 or '..' in Path(i.filename).parts or i.filename.startswith(('/', '\\')) for i in infos):
            raise ValueError('EPUB mã hóa hoặc có đường dẫn không an toàn.')
    with tempfile.TemporaryDirectory() as d:
        p=Path(d)/'input.epub';p.write_bytes(data)
        book=epub.read_epub(str(p),options={'ignore_ncx':True})
        chapters=[]
        for idref,linear in book.spine:
            if linear=='no': continue
            item=book.get_item_with_id(idref)
            if item is None or item.get_type()!=ITEM_DOCUMENT: continue
            if 'nav' in getattr(item,'properties',[]) or any(k in (item.get_name() or '').lower() for k in ('toc', 'mulu', 'contents')): continue
            soup=BeautifulSoup(item.get_content(),'html.parser')
            for node in soup(['script','style','nav']): node.decompose()
            body=soup.body or soup
            text=normalize(body.get_text('\n',strip=True))
            if not text: continue
            if len(split_chapters(text))>1 or CHAPTER.search(text):
                chapters.extend(split_chapters(text));continue
            heading=body.find(['h1','h2','h3'])
            title=heading.get_text(' ',strip=True) if heading else f'Phần {len(chapters)+1}'
            if heading: heading.decompose()
            text=normalize(body.get_text('\n',strip=True))
            from translation.text import is_table_of_contents
            if is_table_of_contents(title, text): continue
            chapters.append((title,text))
        if not chapters: raise ValueError('Không tìm thấy nội dung trong EPUB spine.')
        return chapters,'EPUB / UTF-8'

def export_txt(book,chapters):
    done=sum(c['status']=='done' for c in chapters)
    output=[book['title'],f'Đã dịch {done}/{len(chapters)} chương.',
            'Chỉ các chương hoàn tất có nội dung; chương khác được ghi chú.']
    for c in chapters:
        if c['status']=='done': output.extend([c['translated_title'] or c['title'],'\n\n'.join(c['translated'])])
        else: output.append(f"[Chưa dịch hoàn tất] {c['title']} ({c['status']})")
    return '\n\n'.join(output).encode('utf-8-sig')

def export_epub(book,chapters):
    b=epub.EpubBook();b.set_identifier('ai-novel-'+str(book['id']))
    b.set_title(book['title']);b.set_language('vi');b.add_author('AI Novel Translator')
    css=epub.EpubItem(uid='style',file_name='style/reader.css',media_type='text/css',content=b'body{font-family:serif;line-height:1.8;margin:5%;}p{text-indent:1em;}h1{line-height:1.4;} .note{font-style:italic;}')
    b.add_item(css); toc=[]
    for i,c in enumerate(chapters):
        title=(c['translated_title'] or c['title']) if c['status']=='done' else c['title']
        item=epub.EpubHtml(title=title,file_name=f'chapter_{i+1}.xhtml',lang='vi')
        body=''.join('<p>'+html.escape(p)+'</p>' for p in c['translated']) if c['status']=='done' else '<p class="note">Chương chưa dịch hoàn tất; không xuất bản dịch dở.</p>'
        item.content='<h1>'+html.escape(title)+'</h1>'+body;item.add_item(css);b.add_item(item);toc.append(item)
    b.toc=tuple(toc);b.add_item(epub.EpubNcx());b.add_item(epub.EpubNav());b.spine=['nav']+toc
    with tempfile.TemporaryDirectory() as d:
        path=Path(d)/'translated.epub';epub.write_epub(str(path),b);return path.read_bytes()
