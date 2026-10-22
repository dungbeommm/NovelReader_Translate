"""User glossary parsing, placeholder protection, restore, and alias fallback.

Enabled glossary entries are protected before Marian decoding with a small
model-tested placeholder pool.  Exact placeholders are restored to the
canonical Vietnamese target before the existing post-processing pipeline.
Alias canonicalization remains as a compatibility fallback.
"""

from __future__ import annotations

import csv
import json
import re
import unicodedata
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

GLOSSARY_HEADERS = ("source_zh", "target_vi", "type", "aliases_vi", "enabled")
MAX_GLOSSARY_BYTES = 2_000_000
MAX_GLOSSARY_ROWS = 5_000
GLOSSARY_PLACEHOLDERS = ("QX7", "KX7", "RX7", "ZX9", "ZQ1", "VX1")
PLACEHOLDER_SCOPE_LINE = "line"
PLACEHOLDER_SCOPE_DOCUMENT = "document"
PLACEHOLDER_SCOPES = {PLACEHOLDER_SCOPE_LINE, PLACEHOLDER_SCOPE_DOCUMENT}


class GlossaryValidationError(ValueError):
    """Raised when active glossary rows are ambiguous or incomplete."""


@dataclass(frozen=True, slots=True)
class GlossaryEntry:
    source_zh: str
    target_vi: str
    entry_type: str = ""
    aliases_vi: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GlossaryReport:
    entries: int
    source_hits: int
    replacements: int
    satisfied: int
    unresolved: int
    changed_rows: int
    unresolved_terms: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GlossaryPlaceholderBinding:
    marker: str
    entry: GlossaryEntry
    occurrences: int


@dataclass(frozen=True, slots=True)
class GlossaryProtectedRow:
    index: int
    original_source: str
    protected_source: str
    bindings: tuple[GlossaryPlaceholderBinding, ...]


@dataclass(frozen=True, slots=True)
class GlossaryProtection:
    text: str
    rows: tuple[GlossaryProtectedRow, ...]
    scope: str
    markers: tuple[str, ...]
    source_hits: int
    protected_occurrences: int
    skipped_occurrences: int


@dataclass(frozen=True, slots=True)
class GlossaryRestoreReport:
    protected_occurrences: int
    restored_occurrences: int
    skipped_occurrences: int
    failed_rows: int
    overcopy_rows: int
    failed_indices: tuple[int, ...] = ()


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if value != value:
            return ""
    except (TypeError, ValueError):
        pass
    return unicodedata.normalize("NFC", str(value).strip())


def _aliases_cell(value: Any) -> str:
    if isinstance(value, (list, tuple, set)):
        return "|".join(_clean_text(item) for item in value if _clean_text(item))
    return _clean_text(value)


def _parse_enabled(value: Any) -> bool:
    if value is None or _clean_text(value) == "":
        return True
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    normalized = _clean_text(value).lower()
    if normalized in {"1", "true", "yes", "y", "on", "x", "✓", "bật"}:
        return True
    if normalized in {"0", "false", "no", "n", "off", "✗", "tắt"}:
        return False
    raise GlossaryValidationError(
        f"Giá trị enabled không hợp lệ: {value!r}; dùng true/false hoặc 1/0."
    )


def glossary_table_rows(value: Any) -> list[list[Any]]:
    """Coerce Gradio/pandas/JSON values to the five-column UI table shape."""
    if value is None:
        return []
    if hasattr(value, "values") and hasattr(value.values, "tolist"):
        value = value.values.tolist()
    elif hasattr(value, "tolist") and not isinstance(value, (str, bytes, dict)):
        value = value.tolist()
    if isinstance(value, dict) and "data" in value:
        value = value["data"]
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise GlossaryValidationError("Glossary phải là một bảng hoặc danh sách các dòng.")

    rows: list[list[Any]] = []
    for row_index, raw_row in enumerate(value, start=1):
        if isinstance(raw_row, dict):
            row = [
                raw_row.get("source_zh", raw_row.get("source", "")),
                raw_row.get("target_vi", raw_row.get("target", "")),
                raw_row.get("type", raw_row.get("entry_type", "")),
                raw_row.get("aliases_vi", raw_row.get("aliases", "")),
                raw_row.get("enabled", True),
            ]
        elif isinstance(raw_row, Sequence) and not isinstance(raw_row, (str, bytes)):
            row = list(raw_row[: len(GLOSSARY_HEADERS)])
            row.extend([""] * (len(GLOSSARY_HEADERS) - len(row)))
            if len(raw_row) < len(GLOSSARY_HEADERS):
                row[-1] = True
        else:
            raise GlossaryValidationError(f"Dòng glossary {row_index} không phải một hàng dữ liệu.")

        source = _clean_text(row[0])
        target = _clean_text(row[1])
        entry_type = _clean_text(row[2])
        aliases = _aliases_cell(row[3])
        if not any((source, target, entry_type, aliases)):
            continue
        rows.append([source, target, entry_type, aliases, _parse_enabled(row[4])])
        if len(rows) > MAX_GLOSSARY_ROWS:
            raise GlossaryValidationError(
                f"Glossary vượt giới hạn {MAX_GLOSSARY_ROWS:,} dòng."
            )
    return rows


def _parse_aliases(value: str, target_vi: str) -> tuple[str, ...]:
    aliases: list[str] = []
    seen = {target_vi}
    for raw_alias in value.split("|"):
        alias = _clean_text(raw_alias)
        if alias and alias not in seen:
            aliases.append(alias)
            seen.add(alias)
    aliases.sort(key=lambda item: (-len(item), item))
    return tuple(aliases)


def compile_glossary(
    value: Any,
    *,
    normalize_source: Callable[[str], str] | None = None,
) -> list[GlossaryEntry]:
    """Validate active rows, normalize keys, merge identical mappings."""
    normalize_source = normalize_source or (lambda text: text)
    merged: dict[str, GlossaryEntry] = {}
    first_rows: dict[str, int] = {}

    for row_index, row in enumerate(glossary_table_rows(value), start=1):
        source_zh, target_vi, entry_type, aliases_cell, enabled = row
        if not enabled:
            continue
        if not source_zh or not target_vi:
            raise GlossaryValidationError(
                f"Dòng glossary {row_index}: source_zh và target_vi là bắt buộc "
                "khi mục đang bật."
            )
        normalized_source = _clean_text(normalize_source(source_zh))
        if not normalized_source:
            raise GlossaryValidationError(
                f"Dòng glossary {row_index}: source_zh rỗng sau chuẩn hóa."
            )
        aliases = _parse_aliases(aliases_cell, target_vi)
        existing = merged.get(normalized_source)
        if existing is None:
            merged[normalized_source] = GlossaryEntry(
                source_zh=normalized_source,
                target_vi=target_vi,
                entry_type=entry_type,
                aliases_vi=aliases,
            )
            first_rows[normalized_source] = row_index
            continue
        if existing.target_vi != target_vi:
            raise GlossaryValidationError(
                f"Xung đột source_zh {normalized_source!r}: dòng "
                f"{first_rows[normalized_source]} → {existing.target_vi!r}, "
                f"dòng {row_index} → {target_vi!r}."
            )
        combined_aliases = tuple(
            sorted(
                set(existing.aliases_vi).union(aliases),
                key=lambda item: (-len(item), item),
            )
        )
        merged[normalized_source] = GlossaryEntry(
            source_zh=normalized_source,
            target_vi=target_vi,
            entry_type=existing.entry_type or entry_type,
            aliases_vi=combined_aliases,
        )

    return sorted(
        merged.values(),
        key=lambda entry: (-len(entry.source_zh), entry.source_zh, entry.target_vi),
    )


def _source_matches(
    source_text: str,
    entries: Sequence[GlossaryEntry],
) -> list[GlossaryEntry]:
    candidates: list[tuple[int, int, int, GlossaryEntry]] = []
    for entry_index, entry in enumerate(entries):
        start = source_text.find(entry.source_zh)
        while start >= 0:
            end = start + len(entry.source_zh)
            candidates.append((start, -len(entry.source_zh), entry_index, entry))
            start = source_text.find(entry.source_zh, start + 1)
    candidates.sort(key=lambda item: item[:3])

    selected: list[GlossaryEntry] = []
    occupied_until = -1
    for start, negative_length, _entry_index, entry in candidates:
        end = start - negative_length
        if start < occupied_until:
            continue
        selected.append(entry)
        occupied_until = end
    return selected


def _source_spans(
    source_text: str,
    entries: Sequence[GlossaryEntry],
) -> list[tuple[int, int, GlossaryEntry]]:
    """Return non-overlapping source spans, preferring the longest key."""
    candidates: list[tuple[int, int, int, GlossaryEntry]] = []
    for entry_index, entry in enumerate(entries):
        start = source_text.find(entry.source_zh)
        while start >= 0:
            end = start + len(entry.source_zh)
            candidates.append((start, -len(entry.source_zh), entry_index, entry))
            start = source_text.find(entry.source_zh, start + 1)
    candidates.sort(key=lambda item: item[:3])

    selected: list[tuple[int, int, GlossaryEntry]] = []
    occupied_until = -1
    for start, negative_length, _entry_index, entry in candidates:
        end = start - negative_length
        if start < occupied_until:
            continue
        selected.append((start, end, entry))
        occupied_until = end
    return selected


def _line_body_and_ending(raw_line: str) -> tuple[str, str]:
    for ending in ("\r\n", "\n", "\r"):
        if raw_line.endswith(ending):
            return raw_line[: -len(ending)], ending
    return raw_line, ""


def _placeholder_pattern(marker: str) -> re.Pattern[str]:
    return re.compile(
        rf"(?<![A-Za-z0-9]){re.escape(marker)}(?![A-Za-z0-9])",
        re.IGNORECASE,
    )


def protect_glossary_text(
    text: str,
    entries: Sequence[GlossaryEntry],
    *,
    scope: str = PLACEHOLDER_SCOPE_LINE,
    markers: Sequence[str] = GLOSSARY_PLACEHOLDERS,
) -> GlossaryProtection:
    """Replace matched source terms with model-tested placeholders.

    ``line`` scope reuses the finite marker pool on every non-blank source line
    and is used by CT2, whose output rows preserve source-line identity.
    ``document`` scope assigns each marker to one entry for the entire input and
    is the conservative fallback for backends that return arbitrary chunks.
    """
    if scope not in PLACEHOLDER_SCOPES:
        raise ValueError(f"Placeholder scope không hợp lệ: {scope!r}.")

    marker_pool = tuple(
        dict.fromkeys(_clean_text(marker) for marker in markers if _clean_text(marker))
    )
    collision_values = [text]
    for entry in entries:
        collision_values.extend((entry.target_vi, *entry.aliases_vi))
    marker_pool = tuple(
        marker
        for marker in marker_pool
        if not any(marker.casefold() in value.casefold() for value in collision_values)
    )

    protected_parts: list[str] = []
    protected_rows: list[GlossaryProtectedRow] = []
    source_hits = 0
    protected_occurrences = 0
    row_index = 0
    document_assignments: dict[GlossaryEntry, str] = {}

    for raw_line in text.splitlines(keepends=True):
        body, ending = _line_body_and_ending(raw_line)
        if not body.strip():
            protected_parts.append(raw_line)
            continue

        row_index += 1
        spans = _source_spans(body, entries)
        source_hits += len(spans)
        if not spans or not marker_pool:
            protected_parts.append(raw_line)
            continue

        ordered_entries: list[GlossaryEntry] = []
        seen_entries: set[GlossaryEntry] = set()
        for _start, _end, entry in spans:
            if entry not in seen_entries:
                ordered_entries.append(entry)
                seen_entries.add(entry)

        if scope == PLACEHOLDER_SCOPE_DOCUMENT:
            for entry in ordered_entries:
                if entry in document_assignments:
                    continue
                if len(document_assignments) >= len(marker_pool):
                    break
                document_assignments[entry] = marker_pool[len(document_assignments)]
            assignments = document_assignments
        else:
            assignments = {
                entry: marker
                for entry, marker in zip(ordered_entries, marker_pool, strict=False)
            }

        counts: dict[GlossaryEntry, int] = {}
        protected_body = body
        for start, end, entry in reversed(spans):
            marker = assignments.get(entry)
            if marker is None:
                continue
            protected_body = protected_body[:start] + marker + protected_body[end:]
            counts[entry] = counts.get(entry, 0) + 1

        bindings = tuple(
            GlossaryPlaceholderBinding(
                marker=assignments[entry],
                entry=entry,
                occurrences=counts[entry],
            )
            for entry in ordered_entries
            if entry in counts
        )
        protected_occurrences += sum(binding.occurrences for binding in bindings)
        if bindings:
            protected_rows.append(
                GlossaryProtectedRow(
                    index=row_index,
                    original_source=body.strip(),
                    protected_source=protected_body.strip(),
                    bindings=bindings,
                )
            )
        protected_parts.append(protected_body + ending)

    return GlossaryProtection(
        text="".join(protected_parts),
        rows=tuple(protected_rows),
        scope=scope,
        markers=marker_pool,
        source_hits=source_hits,
        protected_occurrences=protected_occurrences,
        skipped_occurrences=source_hits - protected_occurrences,
    )


def restore_glossary_rows(
    rows: Iterable[tuple[int, str, str]],
    protection: GlossaryProtection,
) -> tuple[list[tuple[int, str, str]], GlossaryRestoreReport]:
    """Restore exact placeholders and fail a whole row on any count mismatch."""
    protected_by_index = {row.index: row for row in protection.rows}
    document_entries: dict[str, GlossaryEntry] = {}
    if protection.scope == PLACEHOLDER_SCOPE_DOCUMENT:
        for protected_row in protection.rows:
            for binding in protected_row.bindings:
                existing = document_entries.get(binding.marker.casefold())
                if existing is not None and existing != binding.entry:
                    raise RuntimeError(
                        f"Placeholder {binding.marker!r} ánh xạ tới nhiều glossary entry."
                    )
                document_entries[binding.marker.casefold()] = binding.entry

    output_rows: list[tuple[int, str, str]] = []
    restored_occurrences = 0
    failed_indices: list[int] = []
    overcopy_rows = 0
    seen_line_indices: set[int] = set()

    for index, source_zh, translated_vi in rows:
        if protection.scope == PLACEHOLDER_SCOPE_LINE:
            protected_row = protected_by_index.get(index)
            if protected_row is None:
                output_rows.append((index, source_zh, translated_vi))
                continue
            seen_line_indices.add(index)
            bindings = protected_row.bindings
            source_matches_row = source_zh.strip() == protected_row.protected_source
        else:
            bindings = tuple(
                GlossaryPlaceholderBinding(
                    marker=marker,
                    entry=entry,
                    occurrences=len(_placeholder_pattern(marker).findall(source_zh)),
                )
                for marker, entry in (
                    (marker, document_entries[marker.casefold()])
                    for marker in protection.markers
                    if marker.casefold() in document_entries
                )
                if _placeholder_pattern(marker).search(source_zh)
            )
            if not bindings:
                output_rows.append((index, source_zh, translated_vi))
                continue
            source_matches_row = True

        restored_source = source_zh
        expected_counts = {binding.marker.casefold(): binding.occurrences for binding in bindings}
        actual_counts = {
            marker.casefold(): len(_placeholder_pattern(marker).findall(translated_vi))
            for marker in protection.markers
        }
        count_mismatch = any(
            actual_counts.get(marker.casefold(), 0) != expected_counts.get(marker.casefold(), 0)
            for marker in protection.markers
        )
        row_overcopy = any(
            actual_counts.get(marker.casefold(), 0) > expected_counts.get(marker.casefold(), 0)
            for marker in protection.markers
        )

        for binding in bindings:
            restored_source = _placeholder_pattern(binding.marker).sub(
                lambda _match, value=binding.entry.source_zh: value,
                restored_source,
            )

        if not source_matches_row or count_mismatch:
            failed_indices.append(index)
            overcopy_rows += int(row_overcopy)
            output_rows.append((index, restored_source, translated_vi))
            continue

        restored_vi = translated_vi
        for binding in bindings:
            restored_vi = _placeholder_pattern(binding.marker).sub(
                lambda _match, value=binding.entry.target_vi: value,
                restored_vi,
            )
            restored_occurrences += binding.occurrences
        output_rows.append((index, restored_source, restored_vi))

    if protection.scope == PLACEHOLDER_SCOPE_LINE:
        failed_indices.extend(sorted(set(protected_by_index) - seen_line_indices))

    unique_failed_indices = tuple(dict.fromkeys(failed_indices))
    report = GlossaryRestoreReport(
        protected_occurrences=protection.protected_occurrences,
        restored_occurrences=restored_occurrences,
        skipped_occurrences=protection.skipped_occurrences,
        failed_rows=len(unique_failed_indices),
        overcopy_rows=overcopy_rows,
        failed_indices=unique_failed_indices,
    )
    return output_rows, report


def _literal_pattern(value: str) -> re.Pattern[str]:
    left = r"(?<!\w)" if value[0].isalnum() or value[0] == "_" else ""
    right = r"(?!\w)" if value[-1].isalnum() or value[-1] == "_" else ""
    return re.compile(f"{left}{re.escape(value)}{right}")


def _replace_entry_aliases(text: str, entry: GlossaryEntry) -> tuple[str, int, int]:
    marker_index = 0
    marker = "\ue000HACHIMI_GLOSSARY\ue001"
    while marker in text or marker in entry.target_vi or marker in entry.aliases_vi:
        marker_index += 1
        marker = f"\ue000HACHIMI_GLOSSARY_{marker_index}\ue001"

    protected, canonical_count = _literal_pattern(entry.target_vi).subn(marker, text)
    replacements = 0
    for alias in entry.aliases_vi:
        protected, count = _literal_pattern(alias).subn(marker, protected)
        replacements += count
    return protected.replace(marker, entry.target_vi), replacements, canonical_count


def apply_glossary_rows(
    rows: Iterable[tuple[int, str, str]],
    entries: Sequence[GlossaryEntry],
) -> tuple[list[tuple[int, str, str]], GlossaryReport]:
    """Apply aliases only in rows whose source contains the mapped Chinese term."""
    output_rows: list[tuple[int, str, str]] = []
    source_hits = 0
    replacements = 0
    satisfied = 0
    unresolved = 0
    changed_rows = 0
    unresolved_terms: set[str] = set()

    for index, source_zh, translated_vi in rows:
        matches = _source_matches(source_zh, entries)
        source_hits += len(matches)
        unique_matches = list(dict.fromkeys(matches))
        fixed_vi = translated_vi
        row_changed = False
        for entry in unique_matches:
            fixed_vi, replaced_count, canonical_count = _replace_entry_aliases(fixed_vi, entry)
            if replaced_count:
                replacements += replaced_count
                row_changed = True
            elif canonical_count:
                satisfied += 1
            else:
                unresolved += 1
                unresolved_terms.add(entry.source_zh)
        if row_changed:
            changed_rows += 1
        output_rows.append((index, source_zh, fixed_vi))

    report = GlossaryReport(
        entries=len(entries),
        source_hits=source_hits,
        replacements=replacements,
        satisfied=satisfied,
        unresolved=unresolved,
        changed_rows=changed_rows,
        unresolved_terms=tuple(sorted(unresolved_terms)),
    )
    return output_rows, report


def read_glossary_file(path: Path) -> list[list[Any]]:
    path = Path(path)
    if path.suffix.lower() not in {".tsv", ".json"}:
        raise GlossaryValidationError("Chỉ hỗ trợ glossary .tsv hoặc .json.")
    if path.stat().st_size > MAX_GLOSSARY_BYTES:
        raise GlossaryValidationError(
            f"File glossary vượt giới hạn {MAX_GLOSSARY_BYTES // 1_000_000} MB."
        )

    if path.suffix.lower() == ".json":
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GlossaryValidationError(f"Không đọc được JSON glossary: {exc}") from exc
        if isinstance(payload, dict) and "entries" in payload:
            payload = payload["entries"]
        return glossary_table_rows(payload)

    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            raw_rows = list(csv.reader(handle, delimiter="\t"))
    except UnicodeDecodeError as exc:
        raise GlossaryValidationError("TSV glossary phải dùng UTF-8.") from exc
    if not raw_rows:
        return []

    normalized_header = [_clean_text(item).lower() for item in raw_rows[0]]
    if {"source_zh", "target_vi"}.issubset(normalized_header):
        positions = {name: normalized_header.index(name) for name in GLOSSARY_HEADERS if name in normalized_header}
        data_rows = []
        for raw_row in raw_rows[1:]:
            data_rows.append(
                [
                    raw_row[positions[name]] if name in positions and positions[name] < len(raw_row)
                    else (True if name == "enabled" else "")
                    for name in GLOSSARY_HEADERS
                ]
            )
    else:
        data_rows = raw_rows
    return glossary_table_rows(data_rows)


def write_glossary_file(path: Path, value: Any, *, file_format: str = "tsv") -> Path:
    rows = glossary_table_rows(value)
    path = Path(path)
    file_format = _clean_text(file_format).lower()
    if file_format == "json":
        payload = [
            dict(zip(GLOSSARY_HEADERS, row, strict=True))
            for row in rows
        ]
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return path
    if file_format != "tsv":
        raise GlossaryValidationError("Định dạng xuất glossary phải là tsv hoặc json.")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(GLOSSARY_HEADERS)
        writer.writerows(rows)
    return path
