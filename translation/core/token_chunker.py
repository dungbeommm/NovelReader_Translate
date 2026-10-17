"""Token-aware chunking for Marian models (ported from HachimiMT HF Space)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from transformers import PreTrainedTokenizerBase

# Câu nguồn: nuốt tới cụm dấu kết (gồm 。！？!?；; và … ……) kèm ngoặc đóng theo
# sau (」』）》】 và ”’ " '), hoặc hết chuỗi. Giữ ngoặc đóng Ở LẠI câu vừa kết,
# không đẩy sang câu sau (trước đây 」 sau 。 rơi nhầm vào câu kế tiếp).
SENTENCE_RE = re.compile(
    r".+?(?:[。！？!?；;…]+[」』）》】”’\"']*|$)",
    re.S,
)
HEADING_RE = re.compile(r"^第[0-9零〇一二三四五六七八九十百千万两]+[章节回卷部篇]")
METADATA_RE = re.compile(r"^(?:书名|作者|简介|内容简介|作品简介)\s*[:：]")


def is_hard_boundary_line(line: str) -> bool:
    """Lines that must stay standalone even in paragraph chunk mode."""
    stripped = (line or "").strip()
    if not stripped or "\n" in stripped:
        return False
    if METADATA_RE.match(stripped):
        return True
    if len(stripped) > 32:
        return False
    if re.search(r"[。！？!?；;，,：:\"“”]", stripped):
        return False
    return bool(HEADING_RE.match(stripped))


def source_token_ids(
    tokenizer: PreTrainedTokenizerBase,
    text: str,
    *,
    max_length: int,
    truncation: bool,
) -> list[int]:
    token_ids = tokenizer(
        text,
        truncation=truncation,
        max_length=max_length,
    )["input_ids"]
    if tokenizer.pad_token_id is not None:
        token_ids = [tid for tid in token_ids if tid != tokenizer.pad_token_id]
    return token_ids


def source_token_count(
    tokenizer: PreTrainedTokenizerBase,
    text: str,
    *,
    max_length: int,
) -> int:
    return len(source_token_ids(tokenizer, text, max_length=max_length, truncation=False))


def char_chunks(
    tokenizer: PreTrainedTokenizerBase,
    text: str,
    *,
    max_tokens: int,
) -> list[str]:
    chunks: list[str] = []
    remaining = text
    while remaining:
        if source_token_count(tokenizer, remaining, max_length=max_tokens) <= max_tokens:
            chunks.append(remaining)
            break

        low, high = 1, len(remaining)
        best = 1
        while low <= high:
            middle = (low + high) // 2
            candidate = remaining[:middle]
            if source_token_count(tokenizer, candidate, max_length=max_tokens) <= max_tokens:
                best = middle
                low = middle + 1
            else:
                high = middle - 1

        chunks.append(remaining[:best])
        remaining = remaining[best:]
    return chunks


def sentence_chunks(
    tokenizer: PreTrainedTokenizerBase,
    line: str,
    *,
    max_tokens: int,
) -> list[str]:
    if source_token_count(tokenizer, line, max_length=max_tokens) <= max_tokens:
        return [line]

    pieces = [match.group(0) for match in SENTENCE_RE.finditer(line)]
    if not pieces:
        return char_chunks(tokenizer, line, max_tokens=max_tokens)

    chunks: list[str] = []
    current = ""
    for piece in pieces:
        if source_token_count(tokenizer, piece, max_length=max_tokens) > max_tokens:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(char_chunks(tokenizer, piece, max_tokens=max_tokens))
            continue

        candidate = current + piece
        if current and source_token_count(tokenizer, candidate, max_length=max_tokens) > max_tokens:
            chunks.append(current)
            current = piece
        else:
            current = candidate

    if current:
        chunks.append(current)
    return chunks


def _layout_lines(text: str) -> list[str]:
    """Tách dòng GIỮ dòng rỗng đầu/cuối, chuẩn hóa newline (cho plan-based)."""
    return (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")


def split_sentence_lines_with_plan(
    tokenizer: PreTrainedTokenizerBase,
    text: str,
    *,
    max_tokens: int,
) -> tuple[list[str], list[list[int] | None]]:
    """Chia "Theo câu" KÈM plan ánh xạ dòng-nguồn → chunk-index.

    Trả `(chunks, plan)` với `plan` theo TỪNG dòng nguồn (giữ cả dòng trống):
    `None` nếu dòng trống, hoặc danh sách index các chunk thuộc dòng đó (một dòng
    dài vượt cap có thể tách thành nhiều chunk → nhiều index). Cho phép ghép lại
    output theo đúng bố cục dòng nguồn (giữ dòng trống), điều mà `split_for_
    translation` thường (trả phẳng list[str]) không làm được.
    """
    chunks: list[str] = []
    plan: list[list[int] | None] = []
    for line in _layout_lines(text):
        stripped = line.strip()
        if not stripped:
            plan.append(None)
            continue
        line_chunks = sentence_chunks(tokenizer, stripped, max_tokens=max_tokens)
        indices = list(range(len(chunks), len(chunks) + len(line_chunks)))
        chunks.extend(line_chunks)
        plan.append(indices)
    return chunks, plan


def split_paragraphs_with_plan(
    tokenizer: PreTrainedTokenizerBase,
    text: str,
    *,
    max_tokens: int,
) -> tuple[list[str], list[tuple[int, ...]]]:
    """Chia "Theo đoạn" thật, kèm map chunk -> line-index tuyệt đối.

    Khác "Theo câu": các dòng liên tiếp trong cùng đoạn được pack vào một chunk
    tới sát cap để giảm số chunk và giữ context. Khác bản cũ: mỗi chunk giữ danh
    sách line-index nguồn, cho phép restore/fallback theo từng chunk thay vì đoán
    toàn tài liệu.
    """
    chunks: list[str] = []
    plan: list[tuple[int, ...]] = []
    buffered_lines: list[str] = []
    buffered_indices: list[int] = []

    def flush_buffer() -> None:
        if not buffered_lines:
            return
        chunks.append("\n".join(buffered_lines))
        plan.append(tuple(buffered_indices))
        buffered_lines.clear()
        buffered_indices.clear()

    def add_line_chunk(line_index: int, line: str) -> None:
        for piece in sentence_chunks(tokenizer, line, max_tokens=max_tokens):
            chunks.append(piece)
            plan.append((line_index,))

    for line_index, line in enumerate(_layout_lines(text)):
        stripped = line.strip()
        if not stripped:
            flush_buffer()
            continue

        if is_hard_boundary_line(stripped):
            flush_buffer()
            add_line_chunk(line_index, stripped)
            continue

        if source_token_count(tokenizer, stripped, max_length=max_tokens) > max_tokens:
            flush_buffer()
            add_line_chunk(line_index, stripped)
            continue

        candidate_lines = [*buffered_lines, stripped]
        candidate = "\n".join(candidate_lines)
        if buffered_lines and source_token_count(tokenizer, candidate, max_length=max_tokens) > max_tokens:
            flush_buffer()
        buffered_lines.append(stripped)
        buffered_indices.append(line_index)

    flush_buffer()
    return chunks, plan


def split_for_translation(
    tokenizer: PreTrainedTokenizerBase,
    text: str,
    *,
    max_tokens: int,
    chunk_mode: str = "sentence",
) -> list[str]:
    """Split *text* into chunks that fit within *max_tokens*."""
    text = text.strip()
    if not text:
        return []

    if chunk_mode == "paragraph":
        chunks, _plan = split_paragraphs_with_plan(
            tokenizer,
            text,
            max_tokens=max_tokens,
        )
        return chunks

    chunks = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        chunks.extend(sentence_chunks(tokenizer, line, max_tokens=max_tokens))
    return chunks
