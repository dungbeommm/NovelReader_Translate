from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


GENRE_MODERN = "modern"
GENRE_CLASSICAL = "classical"
GENRE_MIXED_GUARD = "mixed_guard"
GENRE_UNKNOWN_GUARD = "unknown_guard"


@dataclass(frozen=True)
class GenreDecision:
    route: str
    classical_score: int
    modern_score: int
    evidence: tuple[str, ...]
    reason: str

    @property
    def is_modern(self) -> bool:
        return self.route == GENRE_MODERN

    @property
    def is_classical(self) -> bool:
        return self.route == GENRE_CLASSICAL


BOOK_MODERN_HINTS = ("没钱修什么仙",)

HARD_CLASSICAL_SIGNALS = (
    "修士", "修真", "修仙", "元婴", "金丹", "筑基", "真君", "法宝", "丹药", "灵气",
    "仙人", "仙子", "剑修", "渡劫", "结丹", "化神", "真人", "道君", "宗门", "灵根",
    "本座", "贫道", "道友", "天劫", "神识", "真元", "灵石", "符箓", "阵法", "飞剑",
    "皇帝", "王爷", "陛下", "皇后", "太后", "公主", "太子", "侯爷", "世子",
    "江湖", "武林", "内力", "剑客", "掌门", "少侠", "师尊", "师父", "前辈",
    "师兄", "师弟", "师姐", "师妹", "师叔", "师伯", "师祖", "徒儿", "道友",
)

HARD_MODERN_SIGNALS = (
    "公司", "大学", "高中", "初中", "小学", "学校", "老师", "班主任", "同学", "学生",
    "课堂", "上课", "课程", "高一", "高二", "高三", "面试", "招生", "学费", "补习班",
    "电话", "手机", "电脑", "网络", "汽车", "地铁", "飞机", "酒店", "警察", "医院",
    "护士", "短信", "微信", "视频", "直播", "电视", "银行", "信用卡", "互联网",
    "程序", "软件", "老板", "经理", "项目", "咖啡", "贷款", "借款", "逾期",
    "财务公司", "平台", "总裁", "董事长", "办公室",
)


def _joined_sources(rows_or_text: Iterable[tuple[int, str, str]] | str) -> str:
    if isinstance(rows_or_text, str):
        return rows_or_text
    return "\n".join(str(source) for _, source, _ in rows_or_text)


def _hits(text: str, terms: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(term for term in terms if term in text)


def classify_genre(rows_or_text: Iterable[tuple[int, str, str]] | str) -> GenreDecision:
    text = _joined_sources(rows_or_text)
    book_hits = _hits(text, BOOK_MODERN_HINTS)
    if book_hits:
        return GenreDecision(
            route=GENRE_MODERN,
            classical_score=0,
            modern_score=len(book_hits),
            evidence=book_hits,
            reason="book_modern_hint",
        )

    classical_hits = _hits(text, HARD_CLASSICAL_SIGNALS)
    modern_hits = _hits(text, HARD_MODERN_SIGNALS)
    classical_score = len(classical_hits)
    modern_score = len(modern_hits)
    evidence = (*classical_hits[:8], *modern_hits[:8])

    if classical_score and not modern_score:
        return GenreDecision(GENRE_CLASSICAL, classical_score, modern_score, evidence, "classical_signal")
    if modern_score and not classical_score:
        return GenreDecision(GENRE_MODERN, classical_score, modern_score, evidence, "modern_signal")
    if classical_score and modern_score:
        return GenreDecision(GENRE_MIXED_GUARD, classical_score, modern_score, evidence, "mixed_signal")
    return GenreDecision(GENRE_UNKNOWN_GUARD, classical_score, modern_score, evidence, "no_signal")


def v9_route_for_decision(decision: GenreDecision) -> str:
    if decision.route == GENRE_MODERN:
        return "modern_school"
    if decision.route == GENRE_UNKNOWN_GUARD:
        return "unknown_copy_guard"
    return "xianxia_copy_guard"
