import re
from collections import Counter
import logging

log = logging.getLogger(__name__)
TOKEN = re.compile(r'⟦G\d+⟧')

def parse_glossary(text):
    result = {}
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith('#'): continue
        if '->' in line:
            source, target = [x.strip() for x in line.split('->', 1)]
        elif '\t' in line:
            source, target = [x.strip() for x in line.split('\t', 1)]
        else:
            raise ValueError(f'Từ điển dòng {n}: cần dạng 原文 -> Bản dịch')
        if not source or not target or '⟦' in source+target or '⟧' in source+target:
            raise ValueError(f'Từ điển dòng {n} không hợp lệ.')
        if len(source)>200: raise ValueError('Thuật ngữ tối đa 200 ký tự.')
        result[source] = target
    return dict(sorted(result.items(), key=lambda pair:len(pair[0]), reverse=True))

def protect(text, glossary):
    if not glossary: return text, {}
    pattern = re.compile('|'.join(re.escape(t) for t in sorted(glossary, key=len, reverse=True)))
    mapping = {}
    def replace(m):
        token = f'⟦G{len(mapping)+1}⟧'; mapping[token] = glossary[m[0]]; return token
    return pattern.sub(replace, text), mapping

def translate_with_glossary(texts, glossary, raw):
    """Exact placeholder validation. Lost/duplicated tokens trigger source-span fallback.

    Translating gaps separately guarantees target terms rather than guessing their
    translated aliases. This trades some sentence context for deterministic names.
    """
    protected = [protect(text, glossary) for text in texts]
    outputs = raw([p[0] for p in protected])
    if len(outputs)!=len(texts): raise RuntimeError('Engine trả sai số segment.')
    result = []
    for source, (masked, mapping), output in zip(texts, protected, outputs):
        if not isinstance(output, str) or (source.strip() and not output.strip()):
            raise RuntimeError('Engine trả bản dịch rỗng hoặc không hợp lệ.')
        residue = TOKEN.sub('', output)
        damaged = ('�' in output or '⟦' in residue or '⟧' in residue)
        if mapping and (damaged or Counter(TOKEN.findall(masked)) != Counter(TOKEN.findall(output))):
            log.warning('Placeholder bị thay đổi; dùng source-span glossary fallback')
            parts = re.split(r'(⟦G\d+⟧)', masked)
            indices = [i for i,p in enumerate(parts) if p.strip() and p not in mapping]
            gaps = raw([parts[i] for i in indices]) if indices else []
            if len(gaps)!=len(indices) or any(not g.strip() for g in gaps):
                raise RuntimeError('Glossary fallback trả bản dịch không hợp lệ.')
            for i, gap in zip(indices,gaps): parts[i] = gap
            output = ' '.join(mapping.get(p,p) for p in parts if p.strip())
        else:
            output = TOKEN.sub(lambda m:mapping.get(m[0],m[0]), output)
        # Best-effort direct replacement if engine retained raw Chinese terms.
        if '�' in output:
            raise RuntimeError('Model sinh ký tự Unicode lỗi; thử lại chương hoặc đổi engine.')
        if glossary:
            pat = re.compile('|'.join(re.escape(t) for t in sorted(glossary,key=len,reverse=True)))
            output = pat.sub(lambda m:glossary[m[0]],output)
        result.append(output.strip())
    return result
