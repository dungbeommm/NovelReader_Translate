"""Pure parsing/alignment helpers. Never silently truncate source text."""
import re

CHAPTER = re.compile(r'^\s*(?:第[零〇一二三四五六七八九十百千万两兩億亿0-9]+[章节節回卷].*|Chapter\s+\d+\b.*)$', re.I | re.M)

def normalize(text):
    text = text.replace('\r\n', '\n').replace('\r', '\n').replace('\ufeff', '')
    text = text.translate(str.maketrans({'“': '"', '”': '"', '\u3000': ' '}))
    return '\n'.join(line.strip() for line in text.splitlines() if line.strip())

def paragraphs(text):
    return normalize(text).splitlines()

def split_chapters(text, limit=3000):
    text = normalize(text)
    if not text: raise ValueError('Tệp không có nội dung đọc được.')
    matches = list(CHAPTER.finditer(text))
    chapters = []
    if matches:
        pre = text[:matches[0].start()].strip()
        if pre: chapters.append(('Lời mở đầu', pre))
        for i, m in enumerate(matches):
            body = text[m.end():matches[i+1].start() if i+1 < len(matches) else len(text)].strip()
            chapters.append((m.group().strip(), body))
    else:
        # Prefer line boundaries, but bound even a single 100k-character line.
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
    if chunk_mode == 'paragraph':
        plan = [(-1, seg) for seg in segment_text(title, limit=200, terms=terms)]
        for i, p in enumerate(paras):
            if len(p) <= 400:
                plan.append((i, p))
            else:
                for seg in segment_text(p, limit=350, terms=terms):
                    plan.append((i, seg))
        return plan
    return [(-1, seg) for seg in segment_text(title, terms=terms)] + [
        (i, seg) for i, p in enumerate(paras) for seg in segment_text(p, terms=terms)]


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
