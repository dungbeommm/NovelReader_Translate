"""Split Chinese source text into translation chunks."""

from __future__ import annotations

import re

SENTENCE_END = re.compile(r"(?<=[。！？!?；;…])")
PARAGRAPH_BREAK = re.compile(r"\n\s*\n+")


def split_chunks(text: str, mode: str = "sentence") -> list[str]:
    """Split *text* into non-empty chunks for independent translation."""
    text = text.strip()
    if not text:
        return []

    if mode == "paragraph":
        parts = PARAGRAPH_BREAK.split(text)
    else:
        parts: list[str] = []
        for paragraph in text.splitlines():
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            parts.extend(SENTENCE_END.split(paragraph))

    return [chunk.strip() for chunk in parts if chunk.strip()]