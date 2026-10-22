import logging
import re

from translation.core.glossary import (
    MAX_GLOSSARY_ROWS,
    PLACEHOLDER_SCOPE_DOCUMENT,
    GlossaryEntry,
    GlossaryValidationError,
    compile_glossary,
    protect_glossary_text,
    restore_glossary_rows,
)

log = logging.getLogger(__name__)


def parse_glossary(text):
    rows = []
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        if '->' in line:
            source, target = [x.strip() for x in line.split('->', 1)]
        elif '\t' in line:
            source, target = [x.strip() for x in line.split('\t', 1)]
        else:
            raise ValueError(f'Từ điển dòng {n}: cần dạng 原文 -> Bản dịch')
        if not source or not target:
            raise ValueError(f'Từ điển dòng {n} không hợp lệ.')
        if len(source) > 200:
            raise ValueError('Thuật ngữ tối đa 200 ký tự.')
        rows.append([source, target, '', '', True])
        if len(rows) > MAX_GLOSSARY_ROWS:
            raise ValueError(f'Từ điển vượt giới hạn {MAX_GLOSSARY_ROWS:,} dòng.')
    try:
        entries = compile_glossary(rows)
    except GlossaryValidationError as exc:
        raise ValueError(str(exc)) from exc
    return {entry.source_zh: entry.target_vi for entry in entries}


def _entries(glossary):
    ordered = sorted(glossary.items(), key=lambda pair: len(pair[0]), reverse=True)
    return [GlossaryEntry(source_zh=s, target_vi=t) for s, t in ordered]


def _direct_replace(output, glossary):
    if not glossary:
        return output
    pat = re.compile('|'.join(re.escape(t) for t in sorted(glossary, key=len, reverse=True)))
    return pat.sub(lambda m: glossary[m[0]], output)


def _span_fallback(raw, protection):
    mapping = {}
    for row in protection.rows:
        for binding in row.bindings:
            mapping[binding.marker] = binding.entry.target_vi
    splitter = re.compile('(' + '|'.join(re.escape(m) for m in protection.markers) + ')')
    parts = splitter.split(protection.text)
    indices = [i for i, p in enumerate(parts) if p.strip() and p not in mapping]
    gaps = raw([parts[i] for i in indices]) if indices else []
    if len(gaps) != len(indices) or any(not g.strip() for g in gaps):
        raise RuntimeError('Glossary fallback trả bản dịch không hợp lệ.')
    for i, gap in zip(indices, gaps):
        parts[i] = gap
    return ' '.join(mapping.get(p, p) for p in parts if p.strip())


def translate_with_glossary(texts, glossary, raw):
    entries = _entries(glossary or {})
    protections = [
        protect_glossary_text(text, entries, scope=PLACEHOLDER_SCOPE_DOCUMENT)
        for text in texts
    ]
    outputs = raw([p.text for p in protections])
    if len(outputs) != len(texts):
        raise RuntimeError('Engine trả sai số segment.')
    result = []
    for source, protection, output in zip(texts, protections, outputs):
        if not isinstance(output, str) or (source.strip() and not output.strip()):
            raise RuntimeError('Engine trả bản dịch rỗng hoặc không hợp lệ.')
        if protection.rows:
            restored, report = restore_glossary_rows([(1, protection.text, output)], protection)
            if report.failed_rows or '�' in output:
                log.warning('Placeholder bị thay đổi; dùng source-span glossary fallback')
                output = _span_fallback(raw, protection)
            else:
                output = restored[0][2]
        if '�' in output:
            raise RuntimeError('Model sinh ký tự Unicode lỗi; thử lại chương hoặc đổi engine.')
        result.append(_direct_replace(output, glossary).strip())
    return result
