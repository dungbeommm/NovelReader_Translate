"""Runtime V9 pronoun stabilizer for HachimiMT UI rows.

This is a self-contained port of the promoted vp-mt-train V9 runtime layer.
It targets modern relation pronoun stability (teacher/student, mother/child,
peer, inner monologue guards) and leaves xianxia/cổ trang text untouched by
default through a copy-guard route.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from translation.core.postprocess_policy import classify_genre, v9_route_for_decision

ROUTES = ("auto", "modern_school", "xianxia_copy_guard", "unknown_copy_guard")
POLICY_MODES = ("stability_first",)

WORD_CHARS = r"\wÀ-ỹ"
ALLOWED_PREVIOUS_TA = {"người", "anh", "chị", "cô", "ông", "bà", "hắn", "cậu", "chúng", "trường"}
ALLOWED_PREVIOUS_TOI = {"chúng", "tụi", "bọn", "mẹ", "bố", "cha"}

SCHOOL_EXCLUSIVE_SOURCE_TERMS = ("本校", "我校", "学校", "校方", "校长", "招生", "入学", "全校")
SCHOOL_CONTEXT_SOURCE_TERMS = ("老师", "教师", "班主任", "同学", "学生", "课堂", "上课", "课程")
TEACHER_SOURCE_TERMS = ("老师", "教师", "班主任")
TEACHER_DIRECT_ADDRESS_TERMS = (
    "老师，", "老师,", "老师：", "老师:",
    "教师，", "教师,", "教师：", "教师:",
    "班主任，", "班主任,", "班主任：", "班主任:",
)
TEACHER_STUDENT_SOURCE_TERMS = (
    "卷子", "办公室", "高一", "高二", "高三", "月考", "示范班", "学生", "基础",
)
MOTHER_SOURCE_TERMS = ("母亲", "妈妈", "老妈", "妈")
TEACHER_SPEAKER_SOURCE_TERMS = ("王海", "体育老师")
NON_TEACHER_SPEAKER_SOURCE_TERMS = ("白真真", "周天翊", "少年", "少女")
INNER_MONOLOGUE_SOURCE_TERMS = ("心中", "心道", "暗道", "心想")
TEACHER_WINDOW_TAGS = {"teacher_student_window", "student_teacher_window"}
FORMAL_DEBT_SOURCE_TERMS = ("借款", "逾期", "平台", "贷款", "财务公司", "家属")
TEACHER_SURNAME_TITLES = (
    ("张老师", "Trương", "Thầy Trương"),
    ("王老师", "Vương", "Thầy Vương"),
    ("李老师", "Lý", "Thầy Lý"),
    ("林老师", "Lâm", "Thầy Lâm"),
    ("陈老师", "Trần", "Thầy Trần"),
    ("刘老师", "Lưu", "Thầy Lưu"),
    ("赵老师", "Triệu", "Thầy Triệu"),
    ("黄老师", "Hoàng", "Thầy Hoàng"),
    ("周老师", "Chu", "Thầy Chu"),
    ("吴老师", "Ngô", "Thầy Ngô"),
)
EMBEDDED_CLASSICAL_MEDIA_TERMS = (
    "古装剧", "历史剧", "宫斗剧", "电视剧", "电视里", "屏幕里", "剧中", "戏里",
)
IMPERIAL_DIALOGUE_TERMS = (
    "皇上", "陛下", "臣妾", "本宫", "朕", "妃子", "娘娘", "奴婢", "奴才", "爱卿",
)
INSTITUTION_WE_SOURCE_TERMS = (
    "我们的学校", "我们学校", "我校", "我们为", "我们推出", "我们了解到", "我们平台",
    "我们公司", "我们知道", "我们这", "我们补习班", "我们在饮用水",
    "我们指定",
)
INSTITUTION_APPLICANT_SOURCE_TERMS = ("面试官", "报考")
PEER_CLASSMATE_SOURCE_TERMS = ("白真真", "帮我还了债")
SCHOOL_APPLICATION_SOURCE_TERMS = ("我能报考", "我可以报考", "我能报名", "我可以报名")
CHILD_TO_MOTHER_SOURCE_TERMS = ("妈，", "妈,", "妈妈，", "妈妈,")
DIRECT_MOTHER_SPEAKER_MARKERS = ("母亲：", "母亲:", "妈妈：", "妈妈:", "妈：", "妈:")
MOTHER_MESSAGE_CONTEXT_TERMS = ("母亲发来的消息", "母亲发来")
APPLICANT_CONTEXT_SOURCE_TERMS = (
    "面试", "面试官", "考生", "报考", "入学", "招生", "学费", "学校", "高中",
    "录取率", "入学标准", "推荐生", "贫困生", "特长生", "补习班",
)
APPLICANT_SELF_SOURCE_TERMS = ("张羽", "考生", "同学")
GENERIC_MODERN_DIALOGUE_GUARD_TERMS = (
    "老者", "少年", "师尊", "师父", "师兄", "师弟", "师姐", "师妹", "前辈",
    "天庭", "传功", "功力", "法力贷", "本尊",
)
OLDER_BROTHER_SOURCE_TERMS = ("哥哥", "你哥", "哥")
YOUNGER_SISTER_SOURCE_TERMS = ("妹妹", "妹")
SIBLING_CONTEXT_SOURCE_TERMS = (
    "哥哥", "妹妹", "弟弟", "姐姐", "兄妹", "姐妹", "姐弟", "兄弟",
    "你哥", "你哥哥", "你姐", "你姐姐", "你弟", "你妹妹",
)
STABILITY_GENERIC_FLAG_PREFIXES = (
    "forbidden:modern_you:",
    "forbidden:modern_self:",
    "watch:inclusive_we:",
)
ACTIONABLE_POLICY_TAGS = {
    "teacher_student",
    "student_teacher",
    "family_mother_child",
    "formal_debt_call",
    "family_brother_to_sister",
    "family_sister_to_brother_context",
    "family_child_to_mother",
    "spouse_husband_to_wife",
    "spouse_wife_to_husband",
    "romance_male_to_female",
    "romance_female_to_male",
    "school_application_self",
    "institution_we_exclusive",
    "institution_applicant",
    "applicant_self",
    "generic_modern_dialogue",
    "sibling_older_brother_to_younger",
    "sibling_younger_to_older_brother",
}
SUPERNATURAL_GUARD_TERMS = (
    "布娃娃", "苍老", "神识", "戒指", "因果", "请神", "仪式", "愿望", "反噬", "魂飞魄散",
)
SUPERNATURAL_CONTEXT_TERMS = (
    "布娃娃", "邪神", "苍老", "神识", "戒指", "因果", "请神", "仪式", "愿望", "反噬", "魂飞魄散",
)
WUXIA_ROUTE_TERMS = (
    "修士", "修真", "修仙", "元婴", "金丹", "筑基", "真君", "法宝", "丹药", "灵气",
    "仙人", "仙子", "剑修", "渡劫", "结丹", "化神", "真人", "道君", "宗门", "灵根",
    "本座", "贫道", "道友", "天劫", "神识", "真元", "灵石", "符箓", "阵法", "飞剑",
    "师兄", "师弟", "师姐", "师妹", "师叔", "师伯", "师祖", "徒儿",
)
MODERN_ROUTE_TERMS = (
    "学校", "老师", "班主任", "同学", "学生", "高一", "高二", "高三", "公司", "电话",
    "手机", "电脑", "网络", "老板", "经理", "项目", "咖啡", "银行", "贷款", "财务公司",
    "母亲", "妈妈", "老妈", "妈", "哥哥", "妹妹", "姐姐", "弟弟", "总裁", "董事长", "办公室",
)
MODERN_BOOK_HINT_TERMS = ("没钱修什么仙",)
SPEAKER_VERBS = ("说", "说道", "道", "问", "答", "喊", "叫", "开口", "嘀咕", "叹", "笑")
SIBLING_FALSE_FRIEND_TERMS = ("小姐", "空姐")


def cap_like(source: str, replacement: str) -> str:
    return replacement[:1].upper() + replacement[1:] if source and source[0].isupper() else replacement


def replace_word(text: str, source: str, replacement: str) -> tuple[str, int]:
    pattern = re.compile(rf"(?<![{WORD_CHARS}]){re.escape(source)}(?![{WORD_CHARS}])", re.IGNORECASE)
    count = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return cap_like(match.group(0), replacement)

    return pattern.sub(repl, text), count


def apply_replacement(text: str, source: str, replacement: str, applied: Counter[str], rule_name: str) -> str:
    new_text, count = replace_word(text, source, replacement)
    if count:
        applied[rule_name] += count
    return new_text


def contains_source_any(source: str, terms: tuple[str, ...]) -> bool:
    return any(term in source for term in terms)


def source_has_all(source: str, terms: tuple[str, ...]) -> bool:
    return all(term in source for term in terms)


def has_speech_marker(source: str) -> bool:
    return "“" in source or "”" in source or '"' in source or "：" in source or ":" in source


def dialogue_prefix(source: str) -> str:
    positions = [source.find(marker) for marker in ("“", '"', "：", ":") if source.find(marker) >= 0]
    return source[: min(positions)] if positions else source


def dialogue_suffix(source: str) -> str:
    positions = [source.rfind(marker) for marker in ("”", '"') if source.rfind(marker) >= 0]
    return source[max(positions) + 1 :] if positions else ""


def dialogue_context(source: str) -> str:
    return dialogue_prefix(source) + dialogue_suffix(source)


def contains_dialogue_context_any(source: str, terms: tuple[str, ...]) -> bool:
    if not has_speech_marker(source):
        return False
    return contains_source_any(dialogue_context(source), terms)


def has_separate_female_pronoun(source: str) -> bool:
    return "她" in source


def is_embedded_classical_dialogue_source(source: str) -> bool:
    return contains_source_any(source, EMBEDDED_CLASSICAL_MEDIA_TERMS) and contains_source_any(source, IMPERIAL_DIALOGUE_TERMS)


def has_speaker_signal(source: str, speaker_terms: tuple[str, ...]) -> bool:
    if not has_speech_marker(source):
        return False
    if any(f"{term}：" in source or f"{term}:" in source for term in speaker_terms):
        return True
    context = dialogue_context(source)
    if not contains_source_any(context, speaker_terms):
        return False
    return contains_source_any(context, SPEAKER_VERBS) or "：" in context or ":" in context


def is_scene_break_source(source: str) -> bool:
    stripped = source.strip()
    if not stripped:
        return True
    if stripped in {"***", "---", "——", "……"}:
        return True
    if stripped.startswith(("Chapter ", "CHAPTER ")):
        return True
    return bool(re.match(r"^第[零〇一二三四五六七八九十百千万0-9]+[章节卷回]", stripped))


def prefix_has_non_teacher_speaker(prefix: str) -> bool:
    return contains_source_any(prefix, NON_TEACHER_SPEAKER_SOURCE_TERMS)


def is_clear_non_teacher_speaker_source(source: str) -> bool:
    if not has_speech_marker(source):
        return False
    prefix = dialogue_prefix(source)
    if not prefix_has_non_teacher_speaker(prefix):
        return False
    return contains_source_any(prefix, ("道", "说", "问", "开口", "哀叹", "凑到", "嘀咕"))


def is_inner_monologue_source(source: str) -> bool:
    return contains_source_any(dialogue_prefix(source), INNER_MONOLOGUE_SOURCE_TERMS)


def is_teacher_speaker_source(source: str) -> bool:
    if "你" not in source:
        return False
    if not has_speech_marker(source):
        return False
    prefix = dialogue_prefix(source)
    if prefix_has_non_teacher_speaker(prefix):
        return False
    return has_speaker_signal(source, (*TEACHER_SOURCE_TERMS, *TEACHER_SPEAKER_SOURCE_TERMS))


def is_student_addressing_teacher_source(source: str) -> bool:
    if "我" not in source or not has_speech_marker(source):
        return False
    if contains_source_any(source, TEACHER_DIRECT_ADDRESS_TERMS):
        return True
    return bool(
        re.search(
            r"(?:对|向|跟|和)[^“”\"：:]{0,12}(?:老师|教师|班主任)"
            r"[^“”\"：:]{0,12}(?:说|问|答|回答|道)",
            source,
        )
    )


def standalone_pronoun_matches(text: str, term: str, excluded_previous: set[str]) -> list[re.Match[str]]:
    matches: list[re.Match[str]] = []
    pattern = re.compile(rf"(?<![{WORD_CHARS}]){re.escape(term)}(?![{WORD_CHARS}])", re.IGNORECASE)
    for match in pattern.finditer(text):
        before = text[: match.start()].rstrip()
        previous = before.rsplit(" ", 1)[-1].casefold() if before else ""
        if previous in excluded_previous:
            continue
        matches.append(match)
    return matches


def standalone_ta_matches(text: str) -> list[re.Match[str]]:
    return standalone_pronoun_matches(text, "ta", ALLOWED_PREVIOUS_TA)


def contains_word(text: str, term: str) -> bool:
    if term == "ta":
        return bool(standalone_ta_matches(text))
    pattern = re.compile(rf"(?<![{WORD_CHARS}]){re.escape(term)}(?![{WORD_CHARS}])", re.IGNORECASE)
    return bool(pattern.search(text))


def school_we_is_exclusive(source: str, text: str) -> bool:
    lowered = text.casefold()
    if "trường ta" in lowered or "trường chúng ta" in lowered:
        return True
    return contains_word(text, "chúng ta") and contains_source_any(source, SCHOOL_EXCLUSIVE_SOURCE_TERMS)


def detect_flags(source: str, text: str) -> list[str]:
    flags: list[str] = []
    if contains_word(text, "ngươi"):
        flags.append("forbidden:modern_you:ngươi")
    if contains_word(text, "ta"):
        flags.append("forbidden:modern_self:ta")
    if school_we_is_exclusive(source, text):
        lowered = text.casefold()
        if "trường ta" in lowered:
            flags.append("forbidden:school_we_exclusive:trường ta")
        if "trường chúng ta" in lowered:
            flags.append("forbidden:school_we_exclusive:trường chúng ta")
        if contains_word(text, "chúng ta"):
            flags.append("forbidden:school_we_exclusive:chúng ta")
    elif contains_word(text, "chúng ta"):
        flags.append("watch:inclusive_we:chúng ta")
    if contains_source_any(source, MOTHER_SOURCE_TERMS):
        if not has_separate_female_pronoun(source):
            for phrase in ("nàng", "cô ấy", "cô ta"):
                if contains_word(text, phrase):
                    flags.append(f"forbidden:mother_third_person_modern:{phrase}")
    elif contains_word(text, "nàng"):
        flags.append("forbidden:female_third_person_modern:nàng")
    return flags


def forbidden_flags(flags: list[str]) -> list[str]:
    return [flag for flag in flags if flag.startswith("forbidden:")]


def actionable_flags(flags: list[str]) -> list[str]:
    return [
        flag
        for flag in flags
        if not any(flag.startswith(prefix) for prefix in STABILITY_GENERIC_FLAG_PREFIXES)
    ]


def has_actionable_policy_tags(policy_tags: list[str]) -> bool:
    return bool(set(policy_tags) & ACTIONABLE_POLICY_TAGS)


def is_teacher_peer_source(source: str) -> bool:
    return "老师" in source and source.count("老师") >= 2


def is_teacher_to_student_source(source: str) -> bool:
    if is_teacher_peer_source(source):
        return False
    if "你" not in source and "你们" not in source:
        return False
    if not has_speech_marker(source):
        return False
    prefix = dialogue_prefix(source)
    if prefix_has_non_teacher_speaker(prefix):
        return False
    if has_speaker_signal(source, (*TEACHER_SOURCE_TERMS, *TEACHER_SPEAKER_SOURCE_TERMS)):
        return True
    if contains_source_any(prefix, TEACHER_SOURCE_TERMS) and contains_source_any(source, TEACHER_STUDENT_SOURCE_TERMS):
        return True
    if "大学同学" in source:
        return False
    return False


def has_teacher_reference_without_direct_address(source: str) -> bool:
    if not contains_source_any(source, TEACHER_SOURCE_TERMS):
        return False
    if is_student_addressing_teacher_source(source):
        return False
    if is_teacher_peer_source(source) or is_teacher_to_student_source(source):
        return False
    return True


def is_mother_to_child_source(source: str) -> bool:
    if "你" not in source:
        return False
    if "妈，" in source or "妈," in source or "您" in source:
        return False
    if is_direct_mother_speaker(source):
        return True
    return has_speaker_signal(source, MOTHER_SOURCE_TERMS)


def is_formal_debt_source(source: str) -> bool:
    if ("您" in source or "先生" in source) and contains_source_any(source, FORMAL_DEBT_SOURCE_TERMS):
        return True
    return (
        source_has_all(source, ("财务公司", "贷款"))
        or source_has_all(source, ("家属", "贷款"))
        or (contains_source_any(source, ("借款", "逾期")) and contains_source_any(source, ("母亲", "电话", "儿子")))
    )


def is_husband_to_wife_source(source: str) -> bool:
    if not has_speech_marker(source) or ("我" not in source and "你" not in source):
        return False
    return "老婆" in source and contains_source_any(source, ("对妻子说", "对老婆说"))


def is_wife_to_husband_source(source: str) -> bool:
    if not has_speech_marker(source) or ("我" not in source and "你" not in source):
        return False
    return "老公" in source and contains_source_any(source, ("对丈夫说", "对老公说"))


def is_romance_male_to_female_source(source: str) -> bool:
    if not has_speech_marker(source) or "男孩" not in source or "女孩" not in source:
        return False
    prefix = dialogue_prefix(source)
    return "男孩" in prefix and "女孩" in prefix and contains_source_any(prefix, SPEAKER_VERBS)


def is_romance_female_to_male_source(source: str) -> bool:
    if not has_speech_marker(source) or "女孩" not in source or "你" not in source:
        return False
    prefix = dialogue_prefix(source)
    suffix = dialogue_suffix(source)
    if "女孩" in prefix and contains_source_any(prefix, SPEAKER_VERBS):
        return True
    return "女孩" in suffix and ("他" in suffix or "男孩" in source)


def romance_reply_tag_from_source(source: str) -> str | None:
    if is_romance_male_to_female_source(source):
        return "romance_male_to_female"
    if is_romance_female_to_male_source(source):
        return "romance_female_to_male"
    return None


def is_direct_mother_speaker(source: str) -> bool:
    return contains_source_any(source, DIRECT_MOTHER_SPEAKER_MARKERS)


def is_child_to_mother_source(source: str) -> bool:
    return contains_source_any(source, CHILD_TO_MOTHER_SOURCE_TERMS)


def has_sibling_context_source(source: str) -> bool:
    return contains_source_any(source, SIBLING_CONTEXT_SOURCE_TERMS)


def dialogue_suffix_has(source: str, terms: tuple[str, ...]) -> bool:
    return contains_source_any(dialogue_suffix(source), terms)


def is_older_brother_to_younger_source(source: str) -> bool:
    prefix = dialogue_prefix(source)
    if ("我是你哥" in source) or ("我是你哥哥" in source):
        return True
    if contains_source_any(prefix, OLDER_BROTHER_SOURCE_TERMS) and contains_source_any(source, YOUNGER_SISTER_SOURCE_TERMS):
        return True
    return False


def is_younger_to_older_brother_source(source: str) -> bool:
    prefix = dialogue_prefix(source)
    if contains_source_any(prefix, YOUNGER_SISTER_SOURCE_TERMS) and contains_source_any(source, OLDER_BROTHER_SOURCE_TERMS):
        return True
    return False


def sibling_reply_tag_from_source(source: str, fallback: str | None = None) -> str | None:
    if is_older_brother_to_younger_source(source):
        return "sibling_older_brother_to_younger"
    if is_younger_to_older_brother_source(source):
        return "sibling_younger_to_older_brother"
    if fallback:
        if dialogue_suffix_has(source, ("她", "妹妹")):
            return "sibling_younger_to_older_brother"
        if dialogue_suffix_has(source, ("他", "哥哥")):
            return "sibling_older_brother_to_younger"
    return fallback


def is_brother_to_sister_source(source: str, text: str) -> bool:
    if contains_source_any(source, SIBLING_FALSE_FRIEND_TERMS):
        return False
    return is_older_brother_to_younger_source(source) or is_younger_to_older_brother_source(source)


def is_peer_classmate_source(source: str) -> bool:
    return contains_source_any(source, PEER_CLASSMATE_SOURCE_TERMS)


def is_school_application_source(source: str) -> bool:
    return contains_source_any(source, SCHOOL_APPLICATION_SOURCE_TERMS)


def is_exclusive_institution_we_source(source: str) -> bool:
    return contains_source_any(source, INSTITUTION_WE_SOURCE_TERMS)


def is_institution_applicant_source(source: str) -> bool:
    return "你" in source and contains_source_any(source, INSTITUTION_APPLICANT_SOURCE_TERMS)


def is_institution_applicant_context_source(source: str) -> bool:
    if is_institution_applicant_source(source):
        return True
    if source_has_all(source, ("张羽同学", "学费")):
        return True
    if source_has_all(source, ("同学", "适合", "高中")):
        return True
    return contains_source_any(source, APPLICANT_CONTEXT_SOURCE_TERMS) and has_speech_marker(source)


def is_applicant_self_source(source: str) -> bool:
    if "我" not in source:
        return False
    prefix = dialogue_prefix(source)
    if contains_source_any(prefix, ("面试官", "老师", "主任", "母亲", "妈妈", "老者")):
        return False
    if contains_source_any(prefix, APPLICANT_SELF_SOURCE_TERMS):
        return True
    return contains_source_any(source, ("我想考上", "我会努力", "我已经自学", "我一定会"))


def is_generic_modern_dialogue_source(source: str) -> bool:
    if not has_speech_marker(source) or is_inner_monologue_source(source):
        return False
    if is_embedded_classical_dialogue_source(source):
        return False
    if contains_source_any(source, (*SUPERNATURAL_GUARD_TERMS, *GENERIC_MODERN_DIALOGUE_GUARD_TERMS)):
        return False
    prefix = dialogue_prefix(source)
    if not prefix.strip():
        return False
    if contains_source_any(source, (*MODERN_ROUTE_TERMS, *MODERN_BOOK_HINT_TERMS, *APPLICANT_CONTEXT_SOURCE_TERMS)):
        return True
    return contains_source_any(prefix, ("说", "道", "问", "答", "笑", "叹", "喊", "叫", "面试官", "张羽"))


def is_likely_mother_message_source(source: str) -> bool:
    stripped = source.lstrip()
    if not (stripped.startswith("“") or stripped.startswith('"')):
        return False
    if contains_source_any(source, (*SUPERNATURAL_GUARD_TERMS, *GENERIC_MODERN_DIALOGUE_GUARD_TERMS)):
        return False
    if contains_source_any(source, ("面试官", "老师", "张羽", "老者", "少年")):
        return False
    return "你" in source or "我" in source


def infer_policy_tags(source: str, text: str, flags: list[str]) -> tuple[list[str], list[str]]:
    tags: list[str] = []
    guard_reasons: list[str] = []
    forbidden = forbidden_flags(flags)
    spouse_husband_to_wife = is_husband_to_wife_source(source)
    spouse_wife_to_husband = is_wife_to_husband_source(source)
    romance_tag = romance_reply_tag_from_source(source)
    has_context_signal = bool(
        forbidden
        or contains_word(text, "cậu")
        or contains_word(text, "chúng ta")
        or school_we_is_exclusive(source, text)
        or is_school_application_source(source)
        or is_exclusive_institution_we_source(source)
        or is_institution_applicant_source(source)
        or is_peer_classmate_source(source)
        or is_teacher_to_student_source(source)
        or is_child_to_mother_source(source)
        or spouse_husband_to_wife
        or spouse_wife_to_husband
        or romance_tag
    )
    if not has_context_signal:
        return tags, guard_reasons

    if forbidden and is_embedded_classical_dialogue_source(source):
        return tags, ["embedded_classical_dialogue"]
    if forbidden and contains_source_any(source, SUPERNATURAL_GUARD_TERMS):
        return ["supernatural_entity"], ["supernatural_or_entity_context"]

    if spouse_husband_to_wife:
        tags.append("spouse_husband_to_wife")
    elif spouse_wife_to_husband:
        tags.append("spouse_wife_to_husband")
    if romance_tag:
        tags.append(romance_tag)

    peer_classmate = is_peer_classmate_source(source)
    if peer_classmate:
        tags.append("peer_classmate")

    sibling_tag = sibling_reply_tag_from_source(source)
    if sibling_tag:
        tags.append(sibling_tag)

    if is_teacher_peer_source(source):
        tags.append("teacher_peer")
    elif not peer_classmate and not sibling_tag and is_teacher_to_student_source(source):
        tags.append("teacher_student")

    source_has_school_context = (
        contains_dialogue_context_any(source, SCHOOL_CONTEXT_SOURCE_TERMS)
        and "大学同学" not in source
    )
    if (
        is_student_addressing_teacher_source(source)
        and contains_word(text, "ta")
        and "teacher_student" not in tags
    ):
        tags.append("student_teacher")
    elif (
        source_has_school_context
        and any("modern_you" in flag for flag in forbidden)
        and "teacher_student" not in tags
        and "teacher_peer" not in tags
        and "peer_classmate" not in tags
        and not sibling_tag
    ):
        tags.append("teacher_student")

    if is_mother_to_child_source(source):
        tags.append("family_mother_child")
    if is_child_to_mother_source(source):
        tags.append("family_child_to_mother")
    if is_formal_debt_source(source):
        tags.append("formal_debt_call")
    if is_brother_to_sister_source(source, text):
        tags.append("family_brother_to_sister")
    if is_school_application_source(source):
        tags.append("school_application_self")
    if is_exclusive_institution_we_source(source):
        tags.append("institution_we_exclusive")
    if is_institution_applicant_source(source):
        tags.append("institution_applicant")
    if is_applicant_self_source(source) and contains_source_any(source, APPLICANT_CONTEXT_SOURCE_TERMS):
        tags.append("applicant_self")
    return tags, guard_reasons


def replace_pronoun_matches(
    text: str,
    matches: list[re.Match[str]],
    replacement: str,
    applied: Counter[str],
    rule_name: str,
) -> str:
    if not matches:
        return text
    out = text
    for match in reversed(matches):
        out = out[: match.start()] + cap_like(match.group(0), replacement) + out[match.end() :]
    applied[rule_name] += len(matches)
    return out


def add_ta_replacement(text: str, replacement: str, applied: Counter[str], rule_name: str) -> str:
    return replace_pronoun_matches(text, standalone_ta_matches(text), replacement, applied, rule_name)


def add_toi_replacement(text: str, replacement: str, applied: Counter[str], rule_name: str) -> str:
    matches = standalone_pronoun_matches(text, "tôi", ALLOWED_PREVIOUS_TOI)
    return replace_pronoun_matches(text, matches, replacement, applied, rule_name)


def apply_many_words(text: str, sources: tuple[str, ...], replacement: str, applied: Counter[str], rule_name: str) -> str:
    for source in sources:
        text = apply_replacement(text, source, replacement, applied, rule_name)
    return text


def apply_teacher_student_con_phrases(text: str, applied: Counter[str]) -> str:
    for source, replacement in (
        ("con chuẩn bị", "em chuẩn bị"),
        ("con đã", "em đã"),
        ("con cung kính", "em cung kính"),
        ("con là", "em là"),
        ("tin con", "tin em"),
        ("với con", "với em"),
        ("cho con", "cho em"),
        ("của con", "của em"),
    ):
        text = apply_replacement(text, source, replacement, applied, "teacher_student_con_as_em")
    return text


def apply_teacher_surname_titles(source: str, text: str, applied: Counter[str]) -> str:
    for source_term, vi_surname, replacement in TEACHER_SURNAME_TITLES:
        if source_term not in source:
            continue
        text = apply_replacement(text, f"{vi_surname} lão sư", replacement, applied, "teacher_surname_title")
        text = apply_replacement(text, f"{vi_surname} giáo viên", replacement, applied, "teacher_surname_title")
    return text


def apply_third_person_flags(text: str, flags_before: list[str], applied: Counter[str]) -> str:
    if any("mother_third_person_modern" in flag for flag in flags_before):
        return apply_replacement(text, "nàng", "bà", applied, "mother_third_person")
    if any("female_third_person_modern" in flag for flag in flags_before):
        return apply_replacement(text, "nàng", "cô ấy", applied, "female_third_person")
    return text


def harmonize_stability_row(
    *,
    source: str,
    input_vi: str,
    flags_before: list[str],
    policy_tags: list[str],
    guard_reasons: list[str],
) -> tuple[str, dict[str, int]]:
    text = input_vi
    applied: Counter[str] = Counter()
    tags = set(policy_tags)

    if "route:xianxia_copy_guard" in guard_reasons or "route:unknown_copy_guard" in guard_reasons:
        return text, {}

    guarded = bool(guard_reasons)
    if not guarded:
        if "mother_narration_context" in tags and any("female_third_person_modern" in flag for flag in flags_before):
            text = apply_replacement(text, "nàng", "bà", applied, "mother_third_person")
        else:
            text = apply_third_person_flags(text, flags_before, applied)

    if "school_application_self" in tags:
        text = apply_replacement(text, "trường chúng tôi", "trường tôi", applied, "school_application_self_school")
        text = apply_replacement(text, "trường ta", "trường tôi", applied, "school_application_self_school")
        text = add_ta_replacement(text, "tôi", applied, "school_application_self")

    if "institution_we_exclusive" in tags:
        text = apply_replacement(text, "trường chúng ta", "trường chúng tôi", applied, "institution_school_we")
        text = apply_replacement(text, "trường ta", "trường chúng tôi", applied, "institution_school_we")
        text = apply_replacement(text, "chúng ta", "chúng tôi", applied, "institution_we_exclusive")
        if not tags & {"teacher_student", "family_mother_child", "family_sister_to_brother_context", "family_child_to_mother"}:
            text = add_ta_replacement(text, "tôi", applied, "institution_self_as_toi")

    if "formal_debt_call" in tags:
        text = apply_many_words(text, ("các ngươi", "các cậu"), "các anh", applied, "formal_debt_you")
        text = apply_many_words(text, ("ngươi", "cậu"), "ngài", applied, "formal_debt_you")
        text = apply_replacement(text, "chúng ta", "chúng tôi", applied, "formal_debt_we")
        text = add_ta_replacement(text, "tôi", applied, "formal_debt_self")
        text = add_toi_replacement(text, "tôi", applied, "formal_debt_self")
        return text, dict(applied)

    if guarded:
        return text, dict(applied)

    if "sibling_older_brother_to_younger" in tags:
        text = apply_many_words(text, ("các ngươi", "các cậu"), "các em", applied, "older_brother_you_as_em")
        text = apply_many_words(text, ("ngươi", "cậu"), "em", applied, "older_brother_you_as_em")
        text = add_ta_replacement(text, "anh", applied, "older_brother_self_as_anh")
        text = add_toi_replacement(text, "anh", applied, "older_brother_self_as_anh")
        return text, dict(applied)

    if "sibling_younger_to_older_brother" in tags:
        text = apply_many_words(text, ("các ngươi", "các cậu"), "các anh", applied, "younger_sibling_you_as_anh")
        text = apply_many_words(text, ("ngươi", "cậu"), "anh", applied, "younger_sibling_you_as_anh")
        text = add_ta_replacement(text, "em", applied, "younger_sibling_self_as_em")
        text = add_toi_replacement(text, "em", applied, "younger_sibling_self_as_em")
        return text, dict(applied)

    if "peer_classmate" in tags:
        text = apply_many_words(text, ("các ngươi", "các cậu"), "các cậu", applied, "peer_you_as_cau")
        text = apply_many_words(text, ("ngươi", "cậu"), "cậu", applied, "peer_you_as_cau")
        text = add_ta_replacement(text, "tớ", applied, "peer_self_as_to")
        if "我欠二十多万的人" in source:
            text = apply_replacement(text, "người ta nợ hơn hai mươi vạn", "người như tớ nợ hơn hai mươi vạn", applied, "peer_debt_self_phrase")
            text = apply_replacement(text, "tớ nợ hơn hai mươi vạn người", "người như tớ nợ hơn hai mươi vạn", applied, "peer_debt_self_phrase")
        return text, dict(applied)

    if "family_mother_child" in tags:
        text = apply_many_words(text, ("các ngươi", "các cậu"), "các con", applied, "mother_you_as_con")
        text = apply_many_words(text, ("ngươi", "cậu"), "con", applied, "mother_you_as_con")
        text = add_ta_replacement(text, "mẹ", applied, "mother_self_as_me")
        text = add_toi_replacement(text, "mẹ", applied, "mother_self_as_me")
        return text, dict(applied)

    if "family_child_to_mother" in tags:
        text = apply_many_words(text, ("Mẹ, em yên tâm", "Mẹ, ngươi yên tâm", "Mẹ, cậu yên tâm"), "Mẹ, mẹ yên tâm", applied, "child_you_as_mother")
        text = apply_many_words(text, ("ngươi", "cậu", "ngài"), "mẹ", applied, "child_you_as_mother")
        text = apply_many_words(text, ("chúng ta", "chúng tôi"), "chúng con", applied, "child_we_as_chung_con")
        if "你" not in source or "Mẹ, mẹ yên tâm" in text:
            text = apply_replacement(text, "em", "con", applied, "child_self_as_con")
        text = add_ta_replacement(text, "con", applied, "child_self_as_con")
        text = add_toi_replacement(text, "con", applied, "child_self_as_con")
        return text, dict(applied)

    if "applicant_self" in tags:
        text = add_ta_replacement(text, "em", applied, "applicant_self_as_em")
        text = add_toi_replacement(text, "em", applied, "applicant_self_as_em")

    if "institution_applicant" in tags and "teacher_student" not in tags:
        text = apply_many_words(text, ("các ngươi", "các cậu"), "các em", applied, "institution_applicant_you")
        text = apply_many_words(text, ("ngươi", "cậu"), "em", applied, "institution_applicant_you")
        return text, dict(applied)

    if "applicant_self" in tags and "teacher_student" not in tags:
        return text, dict(applied)

    if "family_brother_to_sister" in tags:
        text = add_ta_replacement(text, "em", applied, "brother_self_as_em")
        text = add_toi_replacement(text, "em", applied, "brother_self_as_em")
        return text, dict(applied)

    if "family_sister_to_brother_context" in tags:
        text = apply_many_words(text, ("các ngươi", "các cậu"), "các em", applied, "sister_you_as_em")
        text = apply_many_words(text, ("ngươi", "cậu"), "em", applied, "sister_you_as_em")
        text = add_ta_replacement(text, "chị", applied, "sister_self_as_chi")
        text = add_toi_replacement(text, "chị", applied, "sister_self_as_chi")
        return text, dict(applied)

    if "teacher_student" in tags:
        text = apply_many_words(text, ("các ngươi", "các cậu"), "các em", applied, "teacher_you_as_student")
        text = apply_many_words(text, ("ngươi", "cậu"), "em", applied, "teacher_you_as_student")
        text = apply_teacher_student_con_phrases(text, applied)
        text = apply_teacher_surname_titles(source, text, applied)
        text = add_ta_replacement(text, "thầy", applied, "teacher_self_as_thay")
        text = add_toi_replacement(text, "thầy", applied, "teacher_self_as_thay")
        if "我相信你" in source:
            text = apply_replacement(text, "anh tin em", "thầy tin em", applied, "teacher_self_as_thay")
        if "我的肩膀" in source:
            text = apply_replacement(text, "vỗ vai thầy", "vỗ vai em", applied, "teacher_student_shoulder")
        text = apply_replacement(text, "lão sư", "giáo viên", applied, "teacher_context_lao_su")
        return text, dict(applied)

    if "student_teacher" in tags:
        text = apply_teacher_student_con_phrases(text, applied)
        text = add_ta_replacement(text, "em", applied, "student_self_as_em")
        text = add_toi_replacement(text, "em", applied, "student_self_as_em")
        text = apply_many_words(text, ("ngươi", "cậu"), "thầy", applied, "student_you_as_teacher")
        text = apply_replacement(text, "lão sư", "thầy", applied, "student_teacher_lao_su")
        return text, dict(applied)

    if "spouse_husband_to_wife" in tags:
        text = apply_many_words(text, ("các ngươi", "các cậu"), "các em", applied, "husband_you_as_em")
        text = apply_many_words(text, ("ngươi", "cậu"), "em", applied, "husband_you_as_em")
        text = add_ta_replacement(text, "anh", applied, "husband_self_as_anh")
        text = add_toi_replacement(text, "anh", applied, "husband_self_as_anh")
        return text, dict(applied)

    if "spouse_wife_to_husband" in tags:
        text = apply_many_words(text, ("các ngươi", "các cậu"), "các anh", applied, "wife_you_as_anh")
        text = apply_many_words(text, ("ngươi", "cậu"), "anh", applied, "wife_you_as_anh")
        text = add_ta_replacement(text, "em", applied, "wife_self_as_em")
        text = add_toi_replacement(text, "em", applied, "wife_self_as_em")
        return text, dict(applied)

    if "romance_male_to_female" in tags:
        text = apply_many_words(text, ("các ngươi", "các cậu"), "các em", applied, "romance_male_you_as_em")
        text = apply_many_words(text, ("ngươi", "cậu"), "em", applied, "romance_male_you_as_em")
        text = add_ta_replacement(text, "anh", applied, "romance_male_self_as_anh")
        text = add_toi_replacement(text, "anh", applied, "romance_male_self_as_anh")
        return text, dict(applied)

    if "romance_female_to_male" in tags:
        text = apply_many_words(text, ("các ngươi", "các cậu"), "các anh", applied, "romance_female_you_as_anh")
        text = apply_many_words(text, ("ngươi", "cậu"), "anh", applied, "romance_female_you_as_anh")
        text = add_ta_replacement(text, "em", applied, "romance_female_self_as_em")
        text = add_toi_replacement(text, "em", applied, "romance_female_self_as_em")
        return text, dict(applied)

    if "generic_modern_dialogue" in tags:
        text = apply_many_words(text, ("các ngươi", "các cậu"), "các cậu", applied, "generic_modern_you")
        text = apply_many_words(text, ("ngươi", "cậu"), "cậu", applied, "generic_modern_you")
        text = add_ta_replacement(text, "tôi", applied, "generic_modern_self")
        return text, dict(applied)

    return text, dict(applied)


def apply_runtime_row(
    chapter: str,
    system: str,
    row: dict[str, Any],
    route: str,
    route_reason: str,
    context_guard_reasons: list[str] | None = None,
    context_policy_tags: list[str] | None = None,
) -> dict[str, Any]:
    source = str(row["source_zh"])
    input_vi = str(row["input_vi"])
    flags_before = detect_flags(source, input_vi)
    policy_tags, guard_reasons = infer_policy_tags(source, input_vi, flags_before)
    if context_policy_tags:
        policy_tags = [*policy_tags, *context_policy_tags]
    teacher_window_active = any(tag in TEACHER_WINDOW_TAGS for tag in policy_tags)
    policy_tags = [tag for tag in policy_tags if tag not in TEACHER_WINDOW_TAGS]
    if is_inner_monologue_source(source):
        policy_tags = [tag for tag in policy_tags if tag != "peer_classmate"]
    sibling_policy_tags = {"sibling_older_brother_to_younger", "sibling_younger_to_older_brother"}
    if set(policy_tags) & sibling_policy_tags:
        policy_tags = [
            tag for tag in policy_tags
            if tag not in {"teacher_student", "student_teacher", "teacher_peer", "peer_classmate"}
        ]
    if "teacher_student" in policy_tags and (
        "peer_classmate" not in policy_tags or teacher_window_active or is_teacher_speaker_source(source)
    ):
        policy_tags = [tag for tag in policy_tags if tag not in {"peer_classmate", "student_teacher"}]
    elif "peer_classmate" in policy_tags:
        policy_tags = [tag for tag in policy_tags if tag not in {"teacher_student", "student_teacher"}]
    if "family_sister_to_brother_context" in policy_tags and not is_direct_mother_speaker(source):
        policy_tags = [tag for tag in policy_tags if tag != "family_mother_child"]
    policy_tags = list(dict.fromkeys(policy_tags))

    if context_guard_reasons and forbidden_flags(flags_before):
        guard_reasons = [*guard_reasons, *context_guard_reasons]
    if route.endswith("_copy_guard") and flags_before:
        guard_reasons = [*guard_reasons, f"route:{route}"]
    if (
        route == "modern_school"
        and not policy_tags
        and not guard_reasons
        and forbidden_flags(flags_before)
        and is_generic_modern_dialogue_source(source)
        and not has_teacher_reference_without_direct_address(source)
    ):
        policy_tags.append("generic_modern_dialogue")

    if route.endswith("_copy_guard"):
        prediction = input_vi
        applied: dict[str, int] = {}
    else:
        prediction, applied = harmonize_stability_row(
            source=source,
            input_vi=input_vi,
            flags_before=flags_before,
            policy_tags=policy_tags,
            guard_reasons=guard_reasons,
        )

    flags_after = detect_flags(source, prediction)
    actionable_before = actionable_flags(flags_before)
    actionable_after = actionable_flags(flags_after)
    changed = prediction != input_vi
    actionable_policy_tags = not route.endswith("_copy_guard") and has_actionable_policy_tags(policy_tags)
    return {
        "id": f"{chapter}:{system}:{int(row['row_index']):04d}",
        "chapter": chapter,
        "system": system,
        "route": route,
        "route_reason": route_reason,
        "row_index": row["row_index"],
        "source_zh": source,
        "input_vi": input_vi,
        "prediction_vi": prediction,
        "changed": changed,
        "flags_before": flags_before,
        "flags_after": flags_after,
        "actionable_flags_before": actionable_before,
        "actionable_flags_after": actionable_after,
        "policy_tags": policy_tags,
        "guard_reasons": guard_reasons,
        "applied_rules": applied,
        "needs_review": bool(changed or actionable_before or actionable_after or guard_reasons or actionable_policy_tags),
    }


def apply_runtime_spec_rows(
    chapter: str,
    system: str,
    rows: list[dict[str, Any]],
    route: str,
    route_reason: str,
) -> tuple[list[dict[str, Any]], int]:
    predictions: list[dict[str, Any]] = []
    missing_inputs = 0
    context_guard_remaining = 0
    sister_to_brother_remaining = 0
    child_to_mother_remaining = 0
    mother_narration_remaining = 0
    peer_classmate_remaining = 0
    teacher_to_student_remaining = 0
    inner_monologue_remaining = 0
    institution_applicant_remaining = 0
    sibling_dialogue_remaining = 0
    romance_dialogue_remaining = 0
    sibling_next_policy_tag: str | None = None
    romance_next_policy_tag: str | None = None
    pre_context_policy_tags: list[list[str]] = [[] for _ in rows]

    for row_pos, row in enumerate(rows):
        source_text = str(row["source_zh"])
        if route != "modern_school" or not contains_source_any(source_text, MOTHER_MESSAGE_CONTEXT_TERMS):
            continue
        for previous_pos in range(max(0, row_pos - 4), row_pos):
            previous_source = str(rows[previous_pos]["source_zh"])
            if is_likely_mother_message_source(previous_source):
                pre_context_policy_tags[previous_pos].append("family_mother_child")

    for row_pos, row in enumerate(rows):
        source_text = str(row["source_zh"])
        if is_scene_break_source(source_text):
            context_guard_remaining = 0
            sister_to_brother_remaining = 0
            child_to_mother_remaining = 0
            mother_narration_remaining = 0
            peer_classmate_remaining = 0
            teacher_to_student_remaining = 0
            inner_monologue_remaining = 0
            institution_applicant_remaining = 0
            sibling_dialogue_remaining = 0
            romance_dialogue_remaining = 0
            sibling_next_policy_tag = None
            romance_next_policy_tag = None
        if not str(row["input_vi"]).strip():
            missing_inputs += 1
        context_guard_reasons: list[str] = []
        context_policy_tags: list[str] = [*pre_context_policy_tags[row_pos]]
        explicit_sibling_tag = sibling_reply_tag_from_source(source_text)
        explicit_romance_tag = romance_reply_tag_from_source(source_text)
        if route == "modern_school" and explicit_sibling_tag:
            context_policy_tags.append(explicit_sibling_tag)
        elif (
            route == "modern_school"
            and sibling_dialogue_remaining > 0
            and sibling_next_policy_tag
            and has_speech_marker(source_text)
            and ("你" in source_text or "我" in source_text)
        ):
            context_policy_tags.append(sibling_reply_tag_from_source(source_text, sibling_next_policy_tag) or sibling_next_policy_tag)
            sibling_dialogue_remaining -= 1
        if route == "modern_school" and explicit_romance_tag:
            context_policy_tags.append(explicit_romance_tag)
        elif (
            route == "modern_school"
            and romance_dialogue_remaining > 0
            and romance_next_policy_tag
            and has_speech_marker(source_text)
            and ("你" in source_text or "我" in source_text)
        ):
            context_policy_tags.append(romance_next_policy_tag)
            romance_dialogue_remaining -= 1
        if route == "modern_school" and (
            is_child_to_mother_source(source_text)
            or is_teacher_speaker_source(source_text)
            or is_clear_non_teacher_speaker_source(source_text)
        ):
            inner_monologue_remaining = 0
        if route == "modern_school" and institution_applicant_remaining > 0:
            if "你" in source_text or "你们" in source_text:
                context_policy_tags.append("institution_applicant")
            if has_speech_marker(source_text) and is_applicant_self_source(source_text):
                context_policy_tags.append("applicant_self")
            institution_applicant_remaining -= 1
        if route == "modern_school" and context_guard_remaining > 0:
            context_guard_reasons.append("context:supernatural_entity_window")
            context_guard_remaining -= 1
        if route == "modern_school" and inner_monologue_remaining > 0:
            if has_speech_marker(source_text):
                context_guard_reasons.append("context:inner_monologue_window")
            inner_monologue_remaining -= 1
        if route == "modern_school" and sister_to_brother_remaining > 0:
            if "你" in source_text or "我" in source_text:
                context_policy_tags.append("family_sister_to_brother_context")
            sister_to_brother_remaining -= 1
        if route == "modern_school" and child_to_mother_remaining > 0:
            if "你" in source_text or "我" in source_text:
                context_policy_tags.append("family_child_to_mother")
            child_to_mother_remaining -= 1
        if route == "modern_school" and mother_narration_remaining > 0:
            if "她" in source_text:
                context_policy_tags.append("mother_narration_context")
            mother_narration_remaining -= 1
        if route == "modern_school" and peer_classmate_remaining > 0:
            if ("你" in source_text or "我" in source_text) and has_speech_marker(source_text):
                context_policy_tags.append("peer_classmate")
            peer_classmate_remaining -= 1
        if route == "modern_school" and teacher_to_student_remaining > 0:
            if is_clear_non_teacher_speaker_source(source_text):
                teacher_to_student_remaining = 0
            else:
                if has_speech_marker(source_text):
                    if "你" in source_text:
                        context_policy_tags.extend(["teacher_student", "teacher_student_window"])
                    elif "我" in source_text:
                        context_policy_tags.extend(["student_teacher", "student_teacher_window"])
                teacher_to_student_remaining -= 1

        predictions.append(
            apply_runtime_row(
                chapter,
                system,
                row,
                route,
                route_reason,
                context_guard_reasons,
                context_policy_tags,
            )
        )

        if route == "modern_school" and contains_source_any(source_text, SUPERNATURAL_CONTEXT_TERMS):
            context_guard_remaining = max(context_guard_remaining, 2)
        if route == "modern_school" and is_inner_monologue_source(source_text):
            inner_monologue_remaining = max(inner_monologue_remaining, 2)
        if (
            route == "modern_school"
            and explicit_sibling_tag
            and not contains_source_any(source_text, SIBLING_FALSE_FRIEND_TERMS)
        ):
            sister_to_brother_remaining = max(sister_to_brother_remaining, 4)
        if route == "modern_school" and is_child_to_mother_source(source_text):
            child_to_mother_remaining = max(child_to_mother_remaining, 4)
        if route == "modern_school" and is_mother_to_child_source(source_text):
            mother_narration_remaining = max(mother_narration_remaining, 18)
        if route == "modern_school" and is_teacher_speaker_source(source_text):
            teacher_to_student_remaining = max(teacher_to_student_remaining, 12)
        if route == "modern_school" and is_peer_classmate_source(source_text) and has_speech_marker(source_text):
            peer_classmate_remaining = max(peer_classmate_remaining, 10)
        if route == "modern_school" and is_institution_applicant_context_source(source_text):
            institution_applicant_remaining = max(institution_applicant_remaining, 12)
        if route == "modern_school":
            row_policy_tags = set(predictions[-1].get("policy_tags") or [])
            if "sibling_older_brother_to_younger" in row_policy_tags:
                sibling_next_policy_tag = "sibling_younger_to_older_brother"
                sibling_dialogue_remaining = max(sibling_dialogue_remaining, 4)
            elif "sibling_younger_to_older_brother" in row_policy_tags:
                sibling_next_policy_tag = "sibling_older_brother_to_younger"
                sibling_dialogue_remaining = max(sibling_dialogue_remaining, 4)
            if "romance_male_to_female" in row_policy_tags:
                romance_next_policy_tag = "romance_female_to_male"
                romance_dialogue_remaining = max(romance_dialogue_remaining, 4)
            elif "romance_female_to_male" in row_policy_tags:
                romance_next_policy_tag = "romance_male_to_female"
                romance_dialogue_remaining = max(romance_dialogue_remaining, 4)
    return predictions, missing_inputs


def is_romance_dialogue_rows(rows: list[tuple[int, str, str]]) -> bool:
    joined = "\n".join(source for _, source, _ in rows)
    if "男孩" not in joined or "女孩" not in joined or not has_speech_marker(joined):
        return False
    if contains_source_any(joined, (*WUXIA_ROUTE_TERMS, *SUPERNATURAL_GUARD_TERMS, *IMPERIAL_DIALOGUE_TERMS)):
        return False
    return True


def classify_route_for_rows(rows: list[tuple[int, str, str]], forced_route: str = "auto") -> tuple[str, str]:
    if forced_route != "auto":
        if forced_route not in ROUTES:
            raise ValueError(f"unknown route: {forced_route}")
        return forced_route, f"forced:{forced_route}"
    decision = classify_genre(rows)
    if decision.route == "unknown_guard" and is_romance_dialogue_rows(rows):
        return "modern_school", "auto:romance_signal"
    return v9_route_for_decision(decision), f"auto:{decision.reason}"


def summarize_predictions(predictions: list[dict[str, Any]], missing_input_rows: int) -> dict[str, Any]:
    route_counts = Counter(str(row.get("route") or "") for row in predictions)
    applied = Counter()
    policy_tags = Counter()
    guard_reasons = Counter()
    for row in predictions:
        applied.update(row.get("applied_rules") or {})
        policy_tags.update(row.get("policy_tags") or [])
        guard_reasons.update(row.get("guard_reasons") or [])
    return {
        "candidate_id": "pronoun-harmonizer-runtime-v9",
        "rows": len(predictions),
        "missing_input_rows": missing_input_rows,
        "changed_rows": sum(1 for row in predictions if row.get("changed")),
        "needs_review_rows": sum(1 for row in predictions if row.get("needs_review")),
        "guarded_rows": sum(1 for row in predictions if row.get("guard_reasons")),
        "actionable_after_rows": sum(1 for row in predictions if row.get("actionable_flags_after")),
        "route_counts": dict(route_counts),
        "applied_rule_counts": dict(applied),
        "policy_tag_counts": dict(policy_tags),
        "guard_counts": dict(guard_reasons),
    }


def harmonize_pronouns_v9(
    rows: list[tuple[int, str, str]],
    *,
    route: str = "auto",
) -> tuple[list[tuple[int, str, str]], dict[str, Any]]:
    """Apply V9 to UI translation rows.

    Input/output row shape is `(index, source_zh, translation_vi)`.
    """
    if not rows:
        return rows, summarize_predictions([], 0)
    selected_route, route_reason = classify_route_for_rows(rows, route)
    runtime_rows = [
        {"id": f"qt2_{index:04d}", "row_index": index, "source_zh": source, "input_vi": vi}
        for index, source, vi in rows
    ]
    predictions, missing = apply_runtime_spec_rows(
        "qt2",
        "ui",
        runtime_rows,
        selected_route,
        route_reason,
    )
    if len(predictions) != len(rows):
        raise RuntimeError(f"V9 row count mismatch: expected {len(rows)}, got {len(predictions)}")
    for (index, _source, _vi), prediction in zip(rows, predictions):
        if prediction.get("row_index") != index:
            raise RuntimeError(f"V9 row index mismatch: {index} != {prediction.get('row_index')}")
    out_rows = [
        (index, source, str(prediction.get("prediction_vi") or vi))
        for (index, source, vi), prediction in zip(rows, predictions)
    ]
    report = summarize_predictions(predictions, missing)
    report.update({"enabled": True, "route": selected_route, "route_reason": route_reason})
    return out_rows, report
