"""Khôi phục xuống dòng cho chế độ dịch "Theo đoạn".

Khi gom nhiều dòng gốc thành 1 chunk để model có thêm ngữ cảnh, Marian/CT2
nuốt ký tự xuống dòng → output thành một khối liền. Module này phân bổ lại bản
dịch về ĐÚNG số dòng gốc theo tỉ lệ (số câu / số ký tự), giữ nguyên bố cục dòng.

Thuật toán port từ Space đã chạy thật `DanVP/MoxhiMT-30-demo` (chế độ "Per chunk"):
chain heading-aware → sentence-proportional → char-proportional (fallback), mỗi
bước trả về đúng `len(source_lines)` dòng để ghép 1:1 với dòng gốc.
"""

from __future__ import annotations

import re

# Câu tiếng Việt: nuốt tới dấu kết câu (kèm dấu đóng ngoặc kép) hoặc hết chuỗi.
VI_SENTENCE_RE = re.compile(r".+?(?:[.!?…]+[”’\"']*|$)", re.S)
# Ký tự được coi là ranh giới ngắt hợp lệ khi canh theo ký tự.
VI_BREAK_CHARS = set(".!?…。！？;；,:，、”’\"'")
# Dòng tiêu đề chương: "第N章/节/回/卷/部/篇".
HEADING_RE = re.compile(r"^第[0-9零〇一二三四五六七八九十百千万两]+[章节回卷部篇]")


def split_layout_lines(text: str) -> list[str]:
    """Tách dòng nhưng giữ dòng rỗng đầu/cuối và chuẩn hóa newline."""
    return (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _nonblank_line_count(text: str) -> int:
    return sum(1 for line in split_layout_lines(text) if line.strip())


def _single_translation_layout(source_lines: list[str], target_text: str) -> str:
    translated = (target_text or "").strip()
    restored = [""] * len(source_lines)
    for index, source_line in enumerate(source_lines):
        if source_line.strip():
            restored[index] = translated
            break
    return "\n".join(restored)


def _layout_from_nonblank_translations(
    source_text: str,
    translations: list[str],
) -> str:
    translated_iter = iter(translations)
    output: list[str] = []
    for source_line in split_layout_lines(source_text):
        if source_line.strip():
            output.append(next(translated_iter, ""))
        else:
            output.append("")
    sentinel = object()
    if next(translated_iter, sentinel) is not sentinel:
        raise RuntimeError("Số dòng dịch lớn hơn số dòng nguồn không rỗng")
    return "\n".join(output)


def _rows_from_layout(source_text: str, full_text: str) -> list[tuple[int, str, str]]:
    source_lines = split_layout_lines(source_text)
    target_lines = split_layout_lines(full_text)
    if len(source_lines) != len(target_lines):
        raise RuntimeError(
            f"Layout mismatch: source={len(source_lines)}, target={len(target_lines)}"
        )

    rows: list[tuple[int, str, str]] = []
    row_index = 1
    for source_line, target_line in zip(source_lines, target_lines):
        if source_line.strip():
            rows.append((row_index, source_line.strip(), target_line.strip()))
            row_index += 1
    return rows


def is_heading_line(line: str) -> bool:
    """Dòng tiêu đề chương ngắn (giữ riêng 1 dòng, không gộp vào đoạn)."""
    stripped = (line or "").strip()
    if not stripped or "\n" in stripped:
        return False
    if len(stripped) > 24:
        return False
    if re.search(r"[。！？!?；;，,：:\"“”]", stripped):
        return False
    return bool(HEADING_RE.match(stripped))


def split_vi_sentences(text: str) -> list[str]:
    """Tách bản dịch tiếng Việt thành danh sách câu (gọn khoảng trắng)."""
    units = [
        re.sub(r"\s+", " ", m.group(0)).strip()
        for m in VI_SENTENCE_RE.finditer(text or "")
    ]
    return [u for u in units if u]


def restore_line_breaks_by_sentences(
    source_text: str, target_text: str
) -> tuple[str | None, str]:
    """Phân bổ câu bản dịch về các dòng gốc theo tỉ lệ độ dài ký tự nguồn.

    Trả (None, lý do) khi số câu đích < số dòng gốc (không đủ để chia) → caller
    rơi sang canh-theo-ký-tự.
    """
    source_lines = split_layout_lines(source_text)
    nonblank = [line.strip() for line in source_lines if line.strip()]
    if len(nonblank) <= 1:
        return _single_translation_layout(source_lines, target_text), "single-line"

    target_units = split_vi_sentences(target_text)
    if len(target_units) < len(nonblank):
        return None, "too-few-target-sentences"

    total_source_chars = max(sum(len(line) for line in nonblank), 1)
    total_target_units = len(target_units)
    remaining_lines = len(nonblank)
    source_seen = 0
    target_cursor = 0
    restored: list[str] = []

    for line in source_lines:
        stripped = line.strip()
        if not stripped:
            restored.append("")
            continue

        source_seen += len(stripped)
        remaining_lines -= 1
        ideal_end = round(source_seen / total_source_chars * total_target_units)
        min_end = target_cursor + 1
        max_end = total_target_units - remaining_lines
        end = min(max(ideal_end, min_end), max_end)
        restored.append(" ".join(target_units[target_cursor:end]).strip())
        target_cursor = end

    if target_cursor < total_target_units:
        for i in range(len(restored) - 1, -1, -1):
            if restored[i].strip():
                restored[i] = (
                    restored[i] + " " + " ".join(target_units[target_cursor:])
                ).strip()
                break
    return "\n".join(restored), "sentence-proportional"


def restore_line_breaks_by_dp(
    source_text: str, target_text: str
) -> tuple[str | None, str]:
    """Chia câu đích về dòng nguồn bằng monotonic DP theo tỉ lệ độ dài.

    Mỗi dòng nguồn không-rỗng nhận ít nhất một câu đích. Nếu model gộp quá mạnh
    khiến số câu đích ít hơn số dòng nguồn, caller phải fallback line-by-line
    hoặc char-proportional tùy ngữ cảnh.
    """
    source_lines = split_layout_lines(source_text)
    nonblank = [line.strip() for line in source_lines if line.strip()]
    if len(nonblank) <= 1:
        return _single_translation_layout(source_lines, target_text), "single-line"

    target_units = split_vi_sentences(target_text)
    if len(target_units) < len(nonblank):
        return None, "too-few-target-sentences"

    n = len(nonblank)
    m = len(target_units)
    # DP là O(n·m²) — chỉ rẻ ở quy mô chunk (CT2 plan-path: n ≤ ~12). Đường
    # legacy (plan=None, backend PyTorch) có thể đưa cả tài liệu vào đây:
    # 400 dòng/1200 câu đo được ~26s, 2000 dòng ~50 phút. Vượt ngân sách →
    # trả None để caller dùng sentence-proportional (tuyến tính).
    if n * m * m > 100_000_000:
        return None, "dp-too-large"
    source_chars = [max(len(line), 1) for line in nonblank]
    target_chars = [max(len(unit), 1) for unit in target_units]
    total_source = max(sum(source_chars), 1)
    total_target = max(sum(target_chars), 1)

    prefix = [0]
    for count in target_chars:
        prefix.append(prefix[-1] + count)

    inf = float("inf")
    dp = [[inf] * (m + 1) for _ in range(n + 1)]
    prev = [[-1] * (m + 1) for _ in range(n + 1)]
    dp[0][0] = 0.0

    for i in range(1, n + 1):
        min_j = i
        max_j = m - (n - i)
        for j in range(min_j, max_j + 1):
            for k in range(i - 1, j):
                if dp[i - 1][k] == inf:
                    continue
                group_chars = prefix[j] - prefix[k]
                src_ratio = source_chars[i - 1] / total_source
                tgt_ratio = group_chars / total_target
                group_size = j - k
                cost = (src_ratio - tgt_ratio) ** 2
                if group_size > 1:
                    cost += 0.002 * (group_size - 1)
                if dp[i - 1][k] + cost < dp[i][j]:
                    dp[i][j] = dp[i - 1][k] + cost
                    prev[i][j] = k

    if prev[n][m] < 0:
        return None, "dp-no-path"

    groups: list[tuple[int, int]] = []
    i, j = n, m
    while i > 0:
        k = prev[i][j]
        groups.append((k, j))
        i, j = i - 1, k
    groups.reverse()

    restored: list[str] = []
    group_cursor = 0
    for line in source_lines:
        if not line.strip():
            restored.append("")
            continue
        start, end = groups[group_cursor]
        restored.append(" ".join(target_units[start:end]).strip())
        group_cursor += 1
    return "\n".join(restored), "sentence-dp"


def find_nearest_break(text: str, desired: int, min_pos: int, max_pos: int) -> int:
    """Tìm vị trí ngắt gần `desired` nhất rơi vào ranh giới câu/khoảng trắng."""
    desired = min(max(desired, min_pos), max_pos)
    window_start = max(min_pos, desired - 80)
    window_end = min(max_pos, desired + 80)
    best_idx, best_score = desired, float("inf")

    for idx in range(window_start, window_end + 1):
        prev = text[idx - 1] if idx > 0 else ""
        cur = text[idx] if idx < len(text) else ""
        if prev in VI_BREAK_CHARS or cur.isspace():
            score = abs(idx - desired)
            if prev in ".!?…。！？":
                score -= 8
            if score < best_score:
                best_idx, best_score = idx, score
    return best_idx


def restore_line_breaks_by_chars(
    source_text: str, target_text: str
) -> tuple[str, str]:
    """Fallback: chia bản dịch theo tỉ lệ ký tự, ngắt tại ranh giới gần nhất."""
    source_lines = split_layout_lines(source_text)
    nonblank = [line.strip() for line in source_lines if line.strip()]
    if len(nonblank) <= 1:
        return _single_translation_layout(source_lines, target_text), "single-line"

    compact_target = re.sub(r"\s+", " ", target_text or "").strip()
    if not compact_target:
        return _layout_from_nonblank_translations(source_text, [""] * len(nonblank)), "char-proportional"
    total_source_chars = max(sum(len(line) for line in nonblank), 1)
    target_len = len(compact_target)
    source_seen = 0
    last_pos = 0
    parts: list[str] = []

    for line in nonblank[:-1]:
        source_seen += len(line)
        desired = round(source_seen / total_source_chars * target_len)
        remaining_parts = len(nonblank) - len(parts) - 1
        min_pos = min(last_pos + 1, target_len)
        max_pos = min(target_len, max(min_pos, target_len - remaining_parts))
        pos = find_nearest_break(compact_target, desired, min_pos, max_pos)
        parts.append(compact_target[last_pos:pos].strip())
        last_pos = pos
    parts.append(compact_target[last_pos:].strip())

    restored: list[str] = []
    part_cursor = 0
    for line in source_lines:
        if line.strip():
            restored.append(parts[part_cursor] if part_cursor < len(parts) else "")
            part_cursor += 1
        else:
            restored.append("")
    return "\n".join(restored), "char-proportional"


FRAGMENT_END_RE = re.compile(
    r"\b(?:mùng|ngày|tháng|năm|vào|ở|tại|trong|ngoài|với|và|của|là|một|"
    r"các|những|đến|từ|sau|trước|bằng|cho|cùng|đang|đã|sẽ|vừa|rồi)$",
    re.I,
)


def _starts_lower_or_digit(text: str) -> bool:
    stripped = (text or "").lstrip()
    if not stripped:
        return False
    first = stripped[0]
    return first.isdigit() or first.islower()


def _looks_fragmented(lines: list[str]) -> bool:
    for current, nxt in zip(lines, lines[1:]):
        stripped = current.strip()
        if not stripped:
            return True
        comparable = stripped.rstrip(" .!?…;:，,")
        if FRAGMENT_END_RE.search(comparable) and _starts_lower_or_digit(nxt):
            return True
        if not re.search(r"[.!?…;:。！？；”’\"']$", stripped) and _starts_lower_or_digit(nxt):
            return True
    return False


def _restore_chunk_lines(
    source_lines: list[str],
    target_text: str,
) -> tuple[list[str], str, bool]:
    source_text = "\n".join(source_lines)
    if len(source_lines) <= 1:
        return [(target_text or "").strip()], "single-line", True

    # Model có marker xuống dòng (ModelConfig.newline_token) tự trả về "\n" trong
    # bản dịch của chunk nhiều dòng. Khớp ĐÚNG số dòng nguồn → dùng thẳng, không
    # đoán theo tỉ lệ. Lệch số dòng → bỏ "\n" của model rồi đi đường restore cũ.
    # Model khác không bao giờ sinh "\n" nên nhánh này không chạm tới chúng.
    if "\n" in (target_text or ""):
        native_lines = [line.strip() for line in target_text.split("\n") if line.strip()]
        if len(native_lines) == len(source_lines):
            return native_lines, "native-newlines", True
        target_text = " ".join(native_lines)

    restored, mode = restore_line_breaks_by_dp(source_text, target_text)
    confident = restored is not None
    if restored is None:
        restored, mode = restore_line_breaks_by_chars(source_text, target_text)

    restored_lines = [
        line.strip()
        for line in split_layout_lines(restored)
        if line.strip() or len(source_lines) == 1
    ]
    if len(restored_lines) != len(source_lines):
        restored_lines = (restored_lines + [""] * len(source_lines))[: len(source_lines)]
        confident = False
    if _looks_fragmented(restored_lines):
        confident = False
    return restored_lines, mode, confident


def native_chunk_lines(target_text: str, expected_lines: int) -> list[str] | None:
    """Exact native layout; blank/extra/missing lines are never inferred away."""
    if not target_text or "<NL>" in target_text:
        return None
    lines = [line.strip() for line in split_layout_lines(target_text)]
    if len(lines) != expected_lines or not all(lines):
        return None
    return lines


def paragraph_chunk_fallback_indices(
    source_text: str,
    chunks: list[str],
    translations: list[str],
    plan: list[tuple[int, ...]],
    *,
    require_native_newlines: bool = False,
) -> list[int]:
    """Các chunk nhiều dòng nên dịch lại từng dòng vì restore thiếu tin cậy."""
    if len(chunks) != len(translations) or len(chunks) != len(plan):
        raise RuntimeError(
            f"Chunk/translation/plan lệch số lượng: {len(chunks)} != "
            f"{len(translations)} != {len(plan)}"
        )
    source_lines = split_layout_lines(source_text)
    fallback: list[int] = []
    for chunk_index, (line_indices, translated_chunk) in enumerate(zip(plan, translations)):
        if require_native_newlines:
            if native_chunk_lines(translated_chunk, len(line_indices)) is None:
                fallback.append(chunk_index)
            continue
        if len(line_indices) <= 1:
            continue
        chunk_source_lines = [source_lines[i].strip() for i in line_indices]
        _lines, _mode, confident = _restore_chunk_lines(
            chunk_source_lines,
            translated_chunk or "",
        )
        if not confident:
            fallback.append(chunk_index)
    return fallback


def _restore_chunks_by_layout(
    source_text: str,
    chunks: list[str],
    translations: list[str],
) -> str | None:
    """Restore từng chunk rồi đặt lại theo layout toàn nguồn nếu map dòng còn rõ.

    Không có ChunkPlan nên ta chỉ dùng đường này khi tổng số dòng non-blank trong
    chunks khớp với nguồn. Nếu một dòng dài bị char-split thành nhiều chunk, tổng
    này sẽ vượt nguồn và caller fallback về thuật toán toàn tài liệu cũ.
    """
    source_nonblank_count = _nonblank_line_count(source_text)
    chunk_line_counts = [_nonblank_line_count(chunk) for chunk in chunks]
    if sum(chunk_line_counts) != source_nonblank_count:
        return None

    translated_lines: list[str] = []
    for source_chunk, translated_chunk in zip(chunks, translations):
        source_lines = split_layout_lines(source_chunk)
        restored_chunk, _mode = restore_line_breaks(source_chunk, translated_chunk or "")
        target_lines = split_layout_lines(restored_chunk)
        if len(source_lines) != len(target_lines):
            return None
        for source_line, target_line in zip(source_lines, target_lines):
            if source_line.strip():
                translated_lines.append(target_line.strip())

    if len(translated_lines) != source_nonblank_count:
        return None
    return _layout_from_nonblank_translations(source_text, translated_lines)


def assemble_paragraph_output(
    source_text: str,
    chunks: list[str],
    translations: list[str],
    plan: list[tuple[int, ...]] | None = None,
    fallback_line_translations: dict[int, str] | None = None,
    *,
    require_native_newlines: bool = False,
) -> tuple[list[tuple[int, str, str]], str]:
    """Ghép kết quả chế độ "Theo đoạn" rồi khôi phục bố cục dòng.

    Trả `(rows, full_text)` trong đó `full_text` có ĐÚNG số dòng (kể cả dòng
    trống) như văn bản nguồn, và `rows` ghép 1:1 từng dòng-gốc-không-rỗng với
    dòng-dịch tương ứng (để bảng đối chiếu khớp với bản tải về).

    Quy trình khớp Space `translate_per_chunk`: nối các chunk dịch (tiêu đề chèn
    \\n để tách riêng), gọn khoảng trắng, rồi `restore_line_breaks`.
    """
    if len(chunks) != len(translations):
        raise RuntimeError(
            f"Chunk/translation lệch số lượng: {len(chunks)} != {len(translations)}"
        )
    if plan is not None:
        if len(plan) != len(chunks):
            raise RuntimeError(
                f"Chunk/plan lệch số lượng: {len(chunks)} != {len(plan)}"
            )
        source_lines = split_layout_lines(source_text)
        line_parts: list[list[str]] = [[] for _ in source_lines]
        fallback_line_translations = fallback_line_translations or {}
        fallback_used: set[int] = set()

        for chunk_index, (line_indices, translated_chunk) in enumerate(zip(plan, translations)):
            del chunk_index
            native_lines = native_chunk_lines(translated_chunk, len(line_indices)) if require_native_newlines else None
            translated_chunk = (translated_chunk or "").strip()
            if not line_indices:
                continue

            # Invariant với translator: fallback được chọn theo NGUYÊN CHUNK
            # (paragraph_chunk_fallback_indices trả chunk-index, mọi line của
            # chunk đó đều được dịch lại) nên all() ở đây nhận trọn chunk hoặc
            # không gì cả. Nếu đổi sang fallback theo dòng lẻ, phải chuyển sang
            # xử lý per-line, không thì các dòng partial bị bỏ qua âm thầm.
            if all(line_index in fallback_line_translations for line_index in line_indices):
                for line_index in line_indices:
                    # A long source line can own several one-line chunks. A
                    # retry translates that entire line once, replacing ALL
                    # its chunks; do not append the same result repeatedly.
                    if line_index in fallback_used:
                        continue
                    fallback = fallback_line_translations[line_index].strip()
                    if require_native_newlines and native_chunk_lines(fallback, 1) is None:
                        raise RuntimeError("Dịch lại từng dòng chưa trả về bản dịch đầy đủ")
                    line_parts[line_index].append(fallback)
                    fallback_used.add(line_index)
                continue

            if require_native_newlines:
                if native_lines is None:
                    raise RuntimeError("Chunk sai số dòng chưa được dịch lại từng dòng")
                for line_index, native_line in zip(line_indices, native_lines):
                    line_parts[line_index].append(native_line)
                continue

            if len(line_indices) == 1:
                line_parts[line_indices[0]].append(translated_chunk)
                continue

            chunk_source_lines = [source_lines[i].strip() for i in line_indices]
            restored_lines, _mode, _confident = _restore_chunk_lines(
                chunk_source_lines,
                translated_chunk,
            )
            for line_index, restored_line in zip(line_indices, restored_lines):
                line_parts[line_index].append(restored_line.strip())

        out_lines: list[str] = []
        for source_line, parts in zip(source_lines, line_parts):
            if source_line.strip():
                out_lines.append(" ".join(part for part in parts if part).strip())
            else:
                out_lines.append("")
        full_text = "\n".join(out_lines)
        return _rows_from_layout(source_text, full_text), full_text

    full_text = _restore_chunks_by_layout(source_text, chunks, translations)
    if full_text is None:
        parts: list[str] = []
        for source_chunk, translated_chunk in zip(chunks, translations):
            translated_chunk = (translated_chunk or "").strip()
            if is_heading_line(source_chunk):
                parts.append(f"\n{translated_chunk}\n")
            else:
                parts.append(translated_chunk)
        raw_output = " ".join(parts)
        raw_output = re.sub(r"[ \t]+", " ", raw_output)
        raw_output = re.sub(r" *\n *", "\n", raw_output)

        full_text, _mode = restore_line_breaks(source_text, raw_output)

    return _rows_from_layout(source_text, full_text), full_text


def assemble_sentence_output(
    source_text: str,
    chunks: list[str],
    translations: list[str],
    plan: list[list[int] | None],
) -> tuple[list[tuple[int, str, str]], str]:
    """Ghép kết quả chế độ "Theo câu" GIỮ bố cục dòng (kể cả dòng trống).

    `plan` (từ split_sentence_lines_with_plan) ánh xạ từng dòng nguồn → chunk-index
    (None nếu dòng trống). Vì "Theo câu" KHÔNG gom dòng (mỗi chunk nằm gọn trong 1
    dòng nguồn), việc ghép là DETERMINISTIC: nối các chunk dịch cùng dòng bằng
    " " → 1 dòng output; dòng trống → "" → GIỮ bố cục. Không phỏng đoán tỉ lệ như
    "Theo đoạn". Trả `(rows, full_text)`: full_text đúng layout nguồn, rows 1 dòng
    non-blank/1 row (ghép multi-chunk), để bảng đối chiếu khớp bản tải về.
    """
    if len(chunks) != len(translations):
        raise RuntimeError(
            f"Chunk/translation lệch số lượng: {len(chunks)} != {len(translations)}"
        )
    source_lines = split_layout_lines(source_text)
    out_lines: list[str] = []
    for source_line, indices in zip(source_lines, plan):
        if indices is None:
            out_lines.append("")
        else:
            out_lines.append(
                " ".join((translations[i] or "").strip() for i in indices).strip()
            )
    full_text = "\n".join(out_lines)
    return _rows_from_layout(source_text, full_text), full_text


def restore_line_breaks(source_text: str, target_text: str) -> tuple[str, str]:
    """Khôi phục bố cục dòng của bản dịch khớp với văn bản nguồn.

    Orchestrator: nếu dòng đầu là tiêu đề chương thì tách riêng nó rồi xử lý phần
    thân; còn lại thử canh-theo-câu trước, không được thì canh-theo-ký-tự. Luôn
    trả về chuỗi có đúng bố cục dòng (kể cả dòng trống) của nguồn.
    """
    source_lines = split_layout_lines(source_text)
    first_nonblank = next(
        (i for i, line in enumerate(source_lines) if line.strip()), None
    )
    target_lines = [line.strip() for line in split_layout_lines(target_text)]
    target_lines = [line for line in target_lines if line]

    if (
        first_nonblank is not None
        and len(target_lines) > 1
        and is_heading_line(source_lines[first_nonblank])
    ):
        body_start = first_nonblank + 1
        blank_after_heading = 0
        while body_start < len(source_lines) and not source_lines[body_start].strip():
            blank_after_heading += 1
            body_start += 1
        body_source = "\n".join(source_lines[body_start:])
        body_target = "\n".join(target_lines[1:])
        restored_body, body_mode = restore_line_breaks(body_source, body_target)
        restored = [""] * first_nonblank
        restored.append(target_lines[0])
        restored.extend([""] * blank_after_heading)
        if restored_body:
            restored.append(restored_body)
        return "\n".join(restored), f"heading+{body_mode}"

    restored, mode = restore_line_breaks_by_dp(source_text, target_text)
    if restored is not None:
        return restored, mode
    restored, mode = restore_line_breaks_by_sentences(source_text, target_text)
    if restored is not None:
        return restored, mode
    return restore_line_breaks_by_chars(source_text, target_text)
