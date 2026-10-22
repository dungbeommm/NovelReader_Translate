"""Chuẩn hóa xưng hô Hán-Việt cho bản dịch (hậu kỳ, neo nguồn ZH).

Người đọc muốn xưng hô nhất quán Hán-Việt (tỷ/muội/ca ca/sư huynh/hắn/nàng/ta),
không nhảy "chị em" ↔ "tỷ muội" trong một chương.

Nguyên lý: CHỈ đổi khi NGUỒN tiếng Trung có từ xưng hô tường minh (neo nguồn ZH).
Chỗ nguồn không có từ → không đụng. KHÔNG suy luận quan hệ. Thuần hậu kỳ, không
cần model. Áp per-row (mỗi câu/đoạn có cặp zh-vi riêng → neo chính xác).

API (khớp phong cách text_preprocess.py):
  normalize_honorifics(zh, vi, mode="off", kinship_mode="always") -> str
  honorific_message(mode) -> str
  HONORIFIC_MODES = {off, safe, xianxia_strict}

Port từ MT-zhvi-medium-train/scripts/pronoun/honorific_normalizer.py (qua TDD,
68 test). Đại từ chỉ bật ở mode xianxia_strict + gate cổ trang (tránh phá văn
hiện đại); thân tộc đơn (哥/姐 1 ký tự) TẮT vì hay trùng tên riêng/loanword.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter

from translation.core.text_preprocess import NORMALIZE_T2S, normalize_chinese_text

HONORIFIC_OFF = "off"
HONORIFIC_SAFE = "safe"
HONORIFIC_STRICT = "xianxia_strict"
HONORIFIC_MODES = {HONORIFIC_OFF, HONORIFIC_SAFE, HONORIFIC_STRICT}
KINSHIP_MODES = {"always", "classical_only"}
_BOUNDARY_CHARS = r"\wÀ-ỹ"

_RAW = {
    "哥们": {"hv": None}, "哥们儿": {"hv": None}, "哥儿们": {"hv": None},
    "大哥大": {"hv": None}, "弟媳": {"hv": None}, "弟妹": {"hv": None},
    "小姐": {"hv": None}, "大嫂": {"hv": None}, "嫂子": {"hv": None}, "嫂": {"hv": None},
    "我们": {"hv": None}, "咱们": {"hv": None}, "你们": {"hv": None},
    "他们": {"hv": None}, "她们": {"hv": None},
    "我校": {"hv": None}, "我司": {"hv": None}, "我国": {"hv": None},
    "我方": {"hv": None}, "我院": {"hv": None},
    "师兄": {"hv": "sư huynh", "drift": ["sư ca", "sư anh"], "tier": "kinship"},
    "师弟": {"hv": "sư đệ", "drift": ["sư em"], "tier": "kinship"},
    "师姐": {"hv": "sư tỷ", "drift": ["sư chị"], "tier": "kinship"},
    "师妹": {"hv": "sư muội", "drift": ["sư em"], "tier": "kinship"},
    "师叔": {"hv": "sư thúc", "drift": [], "tier": "kinship"},
    "师伯": {"hv": "sư bá", "drift": [], "tier": "kinship"},
    "师祖": {"hv": "sư tổ", "drift": [], "tier": "kinship"},
    "徒儿": {"hv": "đồ nhi", "drift": [], "tier": "kinship"},
    "姐妹": {"hv": "tỷ muội", "drift": ["chị em"], "tier": "kinship"},
    "兄弟": {"hv": "huynh đệ", "drift": ["anh em"], "tier": "kinship"},
    "兄妹": {"hv": "huynh muội", "drift": ["anh em"], "tier": "kinship"},
    "姐弟": {"hv": "tỷ đệ", "drift": ["chị em"], "tier": "kinship"},
    "师徒": {"hv": "sư đồ", "drift": [], "tier": "kinship"},
    "姐姐": {"hv": "tỷ tỷ", "drift": ["chị gái", "chị"], "tier": "kinship"},
    "妹妹": {"hv": "muội muội", "drift": ["em gái"], "tier": "kinship"},
    "哥哥": {"hv": "ca ca", "drift": ["anh trai", "anh"], "tier": "kinship"},
    "弟弟": {"hv": "đệ đệ", "drift": ["em trai"], "tier": "kinship"},
    "大哥": {"hv": "đại ca", "drift": ["anh cả", "anh lớn", "anh hai"], "tier": "kinship"},
    "公子": {"hv": "công tử", "drift": [], "tier": "kinship"},
    "姑娘": {"hv": "cô nương", "drift": [], "tier": "kinship"},
    "师尊": {"hv": "sư tôn", "drift": [], "tier": "kinship"},
    "师父": {"hv": "sư phụ", "drift": [], "tier": "kinship"},
    "前辈": {"hv": "tiền bối", "drift": [], "tier": "kinship"},
    "晚辈": {"hv": "vãn bối", "drift": [], "tier": "kinship"},
    "本座": {"hv": "bản tọa", "drift": [], "tier": "kinship"},
    "姐": {"hv": "tỷ", "drift": ["chị"], "tier": "kinship_single"},
    "妹": {"hv": "muội", "drift": [], "tier": "kinship_single"},
    "哥": {"hv": "ca", "drift": ["anh"], "tier": "kinship_single"},
    "弟": {"hv": "đệ", "drift": [], "tier": "kinship_single"},
    "你": {"hv": "ngươi", "drift": ["cậu", "bạn", "mày"], "tier": "pronoun"},
    "您": {"hv": "ngài", "drift": ["ông", "bác"], "tier": "pronoun"},
    "他": {"hv": "hắn", "drift": ["anh ấy", "anh ta", "cậu ấy", "cậu ta", "gã"], "tier": "pronoun"},
    "她": {"hv": "nàng", "drift": ["cô ấy", "cô ta", "ả"], "tier": "pronoun"},
    "我": {"hv": "ta", "drift": ["tôi", "tớ"], "tier": "pronoun"},
}

HONORIFIC_MAP: dict[str, dict] = {}
for _k, _v in _RAW.items():
    _e = dict(_v)
    if _e.get("drift"):
        _e["drift"] = sorted(_e["drift"], key=len, reverse=True)
    HONORIFIC_MAP[_k] = _e

_TERMS_BY_LEN = sorted(HONORIFIC_MAP.keys(), key=len, reverse=True)
_TARGET_LONG_PHRASES = tuple(
    sorted(
        {
            drift
            for entry in HONORIFIC_MAP.values()
            for drift in entry.get("drift", [])
            if " " in drift
        },
        key=len,
        reverse=True,
    )
)
_RECOGNIZE_ONLY_TARGET_PHRASES = (
    "anh ấy", "anh ta", "chị ấy", "chị ta", "em ấy", "em ta",
    "các anh", "các chị", "các em",
)
_PROTECTED_TARGET_PHRASES = tuple(
    sorted(set(_TARGET_LONG_PHRASES) | set(_RECOGNIZE_ONLY_TARGET_PHRASES), key=len, reverse=True)
)
_GENERIC_KINSHIP_SINGLE_DRIFTS = {"anh", "chị", "em"}

WUXIA_SIGNALS = [
    "修士", "修真", "修仙", "元婴", "金丹", "筑基", "真君", "法宝", "丹药", "灵气",
    "仙人", "仙子", "剑修", "渡劫", "结丹", "化神", "真人", "道君", "宗门", "灵根",
    "本座", "贫道", "道友", "天劫", "神识", "真元", "灵石", "符箓", "阵法", "飞剑",
]
MODERN_SIGNALS = [
    "公司", "大学", "电话", "手机", "电脑", "网络", "汽车", "老板", "经理", "项目",
    "咖啡", "地铁", "飞机", "酒店", "警察", "医院", "护士", "短信", "微信", "视频",
    "直播", "电视", "银行", "信用卡", "互联网", "程序", "软件", "总裁", "董事长",
]


def genre_score(zh: str) -> tuple[int, int]:
    c = sum(1 for s in WUXIA_SIGNALS if s in zh)
    m = sum(1 for s in MODERN_SIGNALS if s in zh)
    return c, m


def is_classical(zh: str) -> bool:
    """Có signal cổ trang VÀ không lẫn hiện đại → coi là cổ trang (bảo thủ).
    Nếu có signal hiện đại thì cần cổ trang áp đảo (chặn 'hiện đại tu tiên')."""
    c, m = genre_score(zh)
    if m == 0:
        return c >= 1
    return c >= 2 and c > m


def longest_match_mentions(zh: str) -> list[str]:
    """Quét nguồn trái→phải, tại mỗi vị trí chọn term dài nhất.

    Cách này giữ đúng thứ tự mention trong nguồn và vẫn chặn term ngắn lọt vào
    span term dài (哥哥 chặn 哥; 我们 chặn 我).
    """
    mentions: list[str] = []
    i = 0
    while i < len(zh):
        matched = ""
        for term in _TERMS_BY_LEN:
            if zh.startswith(term, i):
                matched = term
                break
        if matched:
            mentions.append(matched)
            i += len(matched)
        else:
            i += 1
    return mentions


def longest_match_terms(zh: str) -> dict[str, int]:
    return dict(Counter(longest_match_mentions(zh)))


def _match_case(new: str, old: str) -> str:
    return new[:1].upper() + new[1:] if old[:1].isupper() else new


def _target_spans(text: str, phrase: str) -> list[tuple[int, int]]:
    pat = rf"(?<![{_BOUNDARY_CHARS}])" + re.escape(phrase) + rf"(?![{_BOUNDARY_CHARS}])"
    return [(m.start(), m.end()) for m in re.finditer(pat, text, flags=re.IGNORECASE)]


def _inside_any_span(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
    return any(span_start <= start and end <= span_end for span_start, span_end in spans)


def _protected_target_spans(vi: str, current_variant: str) -> list[tuple[int, int]]:
    """Các phrase dài không được để drift một từ ăn vào giữa."""
    spans: list[tuple[int, int]] = []
    for phrase in _PROTECTED_TARGET_PHRASES:
        if phrase == current_variant:
            continue
        if f" {current_variant.casefold()}" not in f" {phrase.casefold()}":
            continue
        spans.extend(_target_spans(vi, phrase))
    return spans


def _has_pronoun_competition(variant: str, source_mentions: list[str]) -> bool:
    variant = variant.casefold()
    if variant == "anh":
        return "他" in source_mentions
    if variant == "chị":
        return "她" in source_mentions
    if variant == "em":
        return "你" in source_mentions
    return False


def _remaining_rewrite_budgets(source_mentions: list[str], vi: str) -> Counter[str]:
    """Số mention nguồn còn được rewrite sau khi target đã có canonical.

    Nếu `哥哥` đã được dịch thành `ca ca`, mention đó đã được tiêu thụ và không
    được tiếp tục lấy một `anh` khác trong cùng câu để đổi thêm.
    """
    budgets: Counter[str] = Counter()
    for term, source_count in Counter(source_mentions).items():
        entry = HONORIFIC_MAP.get(term) or {}
        hv = entry.get("hv")
        if not hv:
            continue
        budgets[term] = max(0, source_count - len(_target_spans(vi, hv)))
    return budgets


def _normalize_kinship_mode(kinship_mode: str | None) -> str:
    mode = (kinship_mode or "always").strip().lower()
    return mode if mode in KINSHIP_MODES else "classical_only"


def _replace_one_drift(
    vi: str,
    variants: list[str],
    target: str,
    *,
    tier: str,
    source_mentions: list[str],
) -> tuple[str, int]:
    """Thay một mention theo thứ tự nguồn.

    Nếu chỉ còn drift một từ mơ hồ (`anh/chị/em`) trong dòng có đại từ nguồn
    cạnh tranh, bỏ qua để tránh kiểu `Anh ấy` → `Ca ca ấy`.
    """
    done = 0
    for v in variants:
        if tier.startswith("kinship") and v.casefold() in _GENERIC_KINSHIP_SINGLE_DRIFTS:
            if _has_pronoun_competition(v, source_mentions):
                continue
        pat = rf"(?<![{_BOUNDARY_CHARS}])(" + re.escape(v) + rf")(?![{_BOUNDARY_CHARS}])"
        protected_spans = _protected_target_spans(vi, v)

        def repl(m):
            nonlocal done
            if done >= 1 or _inside_any_span(m.start(), m.end(), protected_spans):
                return m.group(0)
            done += 1
            return _match_case(target, m.group(0))

        vi = re.sub(pat, repl, vi, flags=re.IGNORECASE)
        if done:
            break
    return vi, done


def _skip(tier: str, classical: bool, apply_kinship: bool, apply_pronouns: bool,
          kinship_mode: str, enable_single: bool) -> bool:
    """True = bỏ qua term. 2 cờ độc lập: apply_kinship (thân tộc/cặp/title) +
    apply_pronouns (đại từ). Đại từ luôn còn gate cổ trang."""
    if tier == "pronoun":
        return (not apply_pronouns) or (not classical)
    if tier == "kinship_single":
        if not apply_kinship or not enable_single:
            return True
        return kinship_mode == "classical_only" and not classical
    if tier == "kinship":
        if not apply_kinship:
            return True
        return kinship_mode == "classical_only" and not classical
    return False


def honorific_mode(mode: str | None) -> str:
    mode = (mode or HONORIFIC_OFF).strip().lower()
    return mode if mode in HONORIFIC_MODES else HONORIFIC_OFF


def _mode_to_flags(mode: str) -> tuple[bool, bool]:
    """map mode lũy tiến (tương thích ngược) → (apply_kinship, apply_pronouns)."""
    mode = honorific_mode(mode)
    if mode == HONORIFIC_SAFE:
        return True, False
    if mode == HONORIFIC_STRICT:
        return True, True
    return False, False


def normalize_honorifics(zh: str, vi: str, mode: str | None = None,
                         *, apply_kinship: bool | None = None,
                         apply_pronouns: bool | None = None,
                         kinship_mode: str = "always",
                         enable_single: bool = False,
                         classical_context: bool | None = None) -> str:
    """Chuẩn hóa xưng hô VI theo neo nguồn ZH.

    2 cờ ĐỘC LẬP (ưu tiên nếu truyền): apply_kinship (thân tộc tỷ/muội/ca ca...) +
    apply_pronouns (đại từ ngươi/hắn/nàng/ta, vẫn gate cổ trang). Cho phép mọi tổ hợp,
    gồm 'chỉ đại từ'. `mode` (off/safe/xianxia_strict) = tương thích ngược, map sang
    2 cờ khi 2 cờ không được truyền."""
    if apply_kinship is None and apply_pronouns is None:
        apply_kinship, apply_pronouns = _mode_to_flags(mode)
    else:
        apply_kinship = bool(apply_kinship)
        apply_pronouns = bool(apply_pronouns)

    if (not apply_kinship and not apply_pronouns) or not vi or not zh:
        return vi
    kinship_mode = _normalize_kinship_mode(kinship_mode)
    vi = unicodedata.normalize("NFC", vi)
    zh = unicodedata.normalize("NFC", normalize_chinese_text(zh, NORMALIZE_T2S))
    mentions = longest_match_mentions(zh)
    if not mentions:
        return vi
    classical = bool(classical_context) if classical_context is not None else is_classical(zh)
    rewrite_budgets = _remaining_rewrite_budgets(mentions, vi)
    for term in mentions:
        if rewrite_budgets[term] <= 0:
            continue
        entry = HONORIFIC_MAP[term]
        hv = entry.get("hv")
        if hv is None:
            continue
        if _skip(entry["tier"], classical, apply_kinship, apply_pronouns,
                 kinship_mode, enable_single):
            continue
        drift = entry.get("drift", [])
        if not drift:
            continue
        vi, changed = _replace_one_drift(
            vi,
            drift,
            hv,
            tier=entry["tier"],
            source_mentions=mentions,
        )
        rewrite_budgets[term] -= changed
    return vi


normalize = normalize_honorifics


def honorific_message(mode: str | None) -> str:
    mode = honorific_mode(mode)
    if mode == HONORIFIC_OFF:
        return "Giữ nguyên xưng hô theo bản dịch."
    if mode == HONORIFIC_SAFE:
        return "Đã chuẩn hóa xưng hô thân tộc sang Hán-Việt (tỷ/muội/ca ca...)."
    return "Đã chuẩn hóa xưng hô Hán-Việt gồm cả đại từ (ngươi/hắn/nàng/ta)."
