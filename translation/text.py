"""Pure parsing/alignment helpers. Never silently truncate source text."""
import re

CHAPTER = re.compile(r'^\s*(?:第[零〇一二三四五六七八九十百千万两兩億亿0-9]+[章节節回卷].*|Chapter\s+\d+\b.*)$', re.I | re.M)

def normalize(text):
    text = text.replace('\r\n', '\n').replace('\r', '\n').replace('\ufeff', '')
    text = text.translate(str.maketrans({'“': '"', '”': '"', '\u3000': ' '}))
    return '\n'.join(line.strip() for line in text.splitlines() if line.strip())

def paragraphs(text):
    return normalize(text).splitlines()

TOC_KEYWORDS = re.compile(r'^(?:目录|目錄|mục\s*lục|table\s*of\s*contents|contents|toc)$', re.I)

def is_table_of_contents(title: str, text: str) -> bool:
    """Kiểm tra xem một đoạn hoặc chương có phải là danh sách mục lục không."""
    clean_title = re.sub(r'^[第\s\d0-9章节節回卷]+', '', title).strip().lower()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return False

    if TOC_KEYWORDS.search(clean_title) or 'mục lục' in clean_title or '目录' in clean_title or '目錄' in clean_title:
        return True

    chapter_like_lines = sum(1 for line in lines if CHAPTER.search(line) or re.match(r'^(?:第[0-9一二三四五六七八九十]+|Chapter\s+\d+|Chương\s+\d+|\d+\.)', line, re.I))
    if len(lines) >= 3 and chapter_like_lines / len(lines) >= 0.4:
        return True

    if title == 'Lời mở đầu' and chapter_like_lines / len(lines) >= 0.25:
        return True

    return False

def split_chapters(text, limit=3000, auto_remove_toc=True):
    text = normalize(text)
    if not text: raise ValueError('Tệp không có nội dung đọc được.')
    matches = list(CHAPTER.finditer(text))
    chapters = []
    if matches:
        pre = text[:matches[0].start()].strip()
        if pre:
            if not (auto_remove_toc and is_table_of_contents('Lời mở đầu', pre)):
                chapters.append(('Lời mở đầu', pre))
        for i, m in enumerate(matches):
            body = text[m.end():matches[i+1].start() if i+1 < len(matches) else len(text)].strip()
            title = m.group().strip()
            if auto_remove_toc and is_table_of_contents(title, body):
                continue
            chapters.append((title, body))
    else:
        while text:
            cut = min(limit, len(text))
            if cut < len(text):
                nl = text.rfind('\n', 0, cut)
                if nl > limit//2: cut = nl
            chapters.append((f'Phần {len(chapters)+1}', text[:cut].strip()))
            text = text[cut:].lstrip('\n')
    return chapters

def segment_text(text, limit=200, terms=()):
    """Punctuation-aware, no character loss; avoid breaking known glossary terms."""
    out = []
    while text:
        cut = min(limit, len(text))
        if cut < len(text):
            points = [m.end() for m in re.finditer(r'[。！？；!?;]', text[:cut])]
            if points: cut = points[-1]
            for term in sorted(terms, key=len, reverse=True):
                pos = text.rfind(term, max(0, cut-len(term)+1), min(len(text), cut+len(term)))
                if pos < cut < pos+len(term): cut = pos if pos else pos+len(term)
        out.append(text[:cut]); text = text[cut:]
    return out

def make_plan(title, paras, terms=(), chunk_mode='sentence'):
    # The Hachimi core owns token-aware splitting. Persist logical source lines
    # here so that long paragraphs are never split by an unrelated char limit.
    return ([(-1, title)] if title.strip() else []) + [
        (i, paragraph) for i, paragraph in enumerate(paras) if paragraph.strip()
    ]


def assemble(plan, values, count):
    translated = [''] * count; title = ''
    for (paragraph, _), value in zip(plan, values):
        if value is None: continue
        if paragraph == -1: title = ' '.join((title, value)).strip()
        else: translated[paragraph] = ' '.join((translated[paragraph], value)).strip()
    return title, translated

def postprocess(text):
    text = text.translate(str.maketrans({'。': '.', '，': ',', '！': '!', '？': '?', '；': ';', '：': ':'}))
    text = re.sub(r'\s+([,.!?;:])', r'\1', text)
    text = re.sub(r'([.!?])\s+([a-zà-ỹ])', lambda m:m[1]+' '+m[2].upper(), text)
    return text[:1].upper()+text[1:] if text else text
