"""Typed adapter from application text batches to the Hachimi public API."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from translation.core.text_preprocess import normalize_chinese_text


@dataclass(frozen=True)
class TranslationRequest:
    texts: tuple[str, ...]
    model: str
    backend: str = "ct2"
    beam_size: int = 2
    chunk_mode: str = "sentence"
    normalize_mode: str = "auto"


@dataclass(frozen=True)
class TranslationResult:
    texts: tuple[str, ...]
    source_fingerprint: str
    model_revision: str
    profile: dict[str, Any]


def translate_batch(translator, request: TranslationRequest) -> TranslationResult:
    """Translate lines as one document for batched inference and layout restore."""
    normalized = tuple(
        normalize_chinese_text(text, request.normalize_mode) if text.strip() else ""
        for text in request.texts
    )
    active = [(index, text) for index, text in enumerate(normalized) if text.strip()]
    outputs = [""] * len(normalized)
    if active:
        source = "\n".join(text for _, text in active)
        _, translated = translator.translate_text(
            source, chunk_mode=request.chunk_mode, beam_size=request.beam_size
        )
        lines = translated.splitlines()
        if len(lines) != len(active):
            raise RuntimeError(
                f"Core trả {len(lines)} dòng cho {len(active)} đoạn nguồn."
            )
        for (index, _), value in zip(active, lines):
            outputs[index] = value.strip()

    revision = f"{request.model}:{request.backend}"
    core_revision = getattr(translator, "_model_key", None)
    if core_revision:
        revision = f"{core_revision}:{getattr(translator, '_backend', request.backend)}"
    fingerprint = hashlib.sha256("\n".join(normalized).encode("utf-8")).hexdigest()
    return TranslationResult(
        texts=tuple(outputs),
        source_fingerprint=fingerprint,
        model_revision=revision,
        profile=dict(getattr(translator, "last_profile", {}) or {}),
    )
