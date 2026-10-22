"""Novel Translation Service: Chapter parsing, SQLite persistence, and translation engine integration."""
from __future__ import annotations

import html
import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Generator

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA = Path(os.getenv("NOVEL_DATA", str(ROOT / "data")))
DATA.mkdir(parents=True, exist_ok=True)
EXPORTS_DIR = DATA / "exports"
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

from translation.core.novel_store import Store
from translation.core.novel_files import parse_file, export_txt, export_epub, MAX_FILE

log = logging.getLogger(__name__)

class NovelService:
    def __init__(self, db_path: Path | None = None):
        self.store = Store(db_path or (DATA / "novel.sqlite3"))
        self.is_running = False
        self.is_paused = False
        self.stop_requested = False
        self.current_chapter_id: int | None = None

    def get_book(self) -> dict | None:
        return self.store.book()

    def get_chapters(self) -> list[dict]:
        return self.store.list()

    def get_chapter(self, chapter_id: int) -> dict | None:
        return self.store.get(chapter_id)

    def load_novel(self, file_path_or_obj, manual_path: str = "") -> tuple[bool, str]:
        """Loads and parses a novel from uploaded file or local path."""
        data: bytes | None = None
        filename: str = ""

        if file_path_or_obj:
            p = Path(file_path_or_obj)
            filename = p.name
            data = p.read_bytes()
        elif manual_path.strip():
            p = Path(manual_path.strip()).expanduser()
            if not p.exists() or not p.is_file():
                return False, f"Không tìm thấy tệp: {manual_path}"
            filename = p.name
            data = p.read_bytes()
        else:
            return False, "Vui lòng chọn tệp truyện hoặc nhập đường dẫn."

        if len(data) > MAX_FILE:
            return False, "Kích thước tệp vượt quá giới hạn 50 MB."

        try:
            chapters, encoding = parse_file(filename, data)
            self.store.replace(filename, encoding, chapters)
            return True, f"✓ Đã nạp thành công '{filename}' ({len(chapters)} chương, {encoding})."
        except Exception as exc:
            log.exception("Lỗi khi nạp truyện")
            return False, f"Lỗi nạp tệp: {exc}"

    def delete_book(self) -> str:
        """Clears all novel data from the database."""
        self.stop_requested = True
        self.store.clear()
        return "✓ Đã xóa sạch dữ liệu truyện khỏi thư viện."

    def reset_chapters(self, chapter_ids: list[int]) -> str:
        """Resets translation status and outputs for selected chapters."""
        if not chapter_ids:
            return "Chưa chọn chương nào để đặt lại."
        self.store.reset_chapters(chapter_ids)
        return f"✓ Đã xóa bản dịch của {len(chapter_ids)} chương."

    def delete_chapters(self, chapter_ids: list[int]) -> str:
        """Deletes selected chapters completely from the novel."""
        if not chapter_ids:
            return "Chưa chọn chương nào để xóa."
        self.store.delete_chapters(chapter_ids)
        return f"✓ Đã xóa {len(chapter_ids)} chương khỏi truyện."

    def translate_chapter(
        self,
        chapter_id: int,
        translator,
        *,
        beam_size: int = 2,
        chunk_mode: str = "sentence",
        normalize_mode: str = "auto",
        honorific_kinship: bool = True,
        honorific_pronouns: bool = True,
        pronoun_harmonizer_v9: bool = True,
        glossary_rows = None,
    ) -> tuple[str, list[str]]:
        from translation.core.text_preprocess import normalize_chinese_text
        from translation.core.glossary import compile_glossary, protect_glossary_text, restore_glossary_rows, apply_glossary_rows

        apply_postprocess_rows = None
        for mod_key in ("hachimi_app", "app"):
            mod = sys.modules.get(mod_key)
            if mod and hasattr(mod, "apply_postprocess_rows"):
                apply_postprocess_rows = getattr(mod, "apply_postprocess_rows")
                break

        if apply_postprocess_rows is None:
            from translation.core.honorific_normalize import normalize_honorifics
            from translation.core.postprocess_policy import classify_genre, v9_route_for_decision
            from translation.core.pronoun_harmonizer_v9 import harmonize_pronouns_v9
            from translation.core.text_preprocess import NORMALIZE_T2S

            def fallback_postprocess(
                rows,
                *,
                honorific_kinship=True,
                honorific_pronouns=True,
                pronoun_harmonizer_v9=True,
                raw_full_text=None,
                source_text="",
                chunk_mode="sentence",
            ):
                genre_decision = classify_genre(rows) if rows else None
                is_classical = genre_decision and genre_decision.is_classical
                if (honorific_kinship or (honorific_pronouns and is_classical)) and rows:
                    rows = [
                        (i, zh, normalize_honorifics(zh, vi, apply_kinship=honorific_kinship, apply_pronouns=bool(honorific_pronouns and is_classical), classical_context=is_classical))
                        for i, zh, vi in rows
                    ]
                if pronoun_harmonizer_v9 and rows:
                    policy_rows = [(i, normalize_chinese_text(zh, NORMALIZE_T2S), vi) for i, zh, vi in rows]
                    v9_rows, _ = harmonize_pronouns_v9(policy_rows, route=v9_route_for_decision(genre_decision) if genre_decision else "unknown_copy_guard")
                    rows = [(i, zh, fixed_vi) for (i, zh, _), (_, _, fixed_vi) in zip(rows, v9_rows)]
                full_text = "\n".join(vi for _, _, vi in rows)
                return rows, full_text, {}

            apply_postprocess_rows = fallback_postprocess

        chapter = self.store.get(chapter_id)
        if not chapter:
            raise ValueError(f"Không tìm thấy chương {chapter_id}")

        title_zh = chapter["title"] or ""
        source_paras = chapter["source"] or []
        full_source = title_zh + ("\n\n" + "\n\n".join(source_paras) if source_paras else "")

        norm_source = normalize_chinese_text(full_source, normalize_mode)
        glossary_entries = []
        glossary_protection = None
        model_source = norm_source

        if glossary_rows:
            try:
                glossary_entries, _ = compile_glossary(glossary_rows)
                if glossary_entries:
                    model_source, glossary_protection = protect_glossary_text(norm_source, glossary_entries)
            except Exception as exc:
                log.warning("Lỗi compile/protect glossary: %s", exc)

        rows, raw_full_text = translator.translate_text(
            model_source,
            chunk_mode=chunk_mode,
            beam_size=int(beam_size),
        )

        if glossary_protection and glossary_protection.protected_occurrences:
            try:
                rows, _ = restore_glossary_rows(rows, glossary_protection)
            except Exception as exc:
                log.warning("Lỗi restore glossary: %s", exc)

        try:
            rows, fixed_full_text, _ = apply_postprocess_rows(
                rows,
                honorific_kinship=honorific_kinship,
                honorific_pronouns=honorific_pronouns,
                pronoun_harmonizer_v9=pronoun_harmonizer_v9,
                raw_full_text=raw_full_text,
                source_text=norm_source,
                chunk_mode=chunk_mode,
            )
        except Exception as exc:
            log.warning("Lỗi postprocess: %s", exc)
            fixed_full_text = raw_full_text

        if glossary_entries:
            try:
                rows, _ = apply_glossary_rows(rows, glossary_entries)
                fixed_full_text = "\n\n".join(r[2] for r in rows if r[2].strip())
            except Exception as exc:
                log.warning("Lỗi apply glossary alias: %s", exc)

        parts = [p.strip() for p in fixed_full_text.split("\n\n") if p.strip()]
        if parts:
            trans_title = parts[0]
            trans_paras = parts[1:]
        else:
            trans_title = title_zh
            trans_paras = []

        if len(trans_paras) < len(source_paras):
            while len(trans_paras) < len(source_paras):
                trans_paras.append("")

        self.store.update(
            chapter_id,
            status="done",
            outputs=[r[2] for r in rows],
            translated_title=trans_title,
            translated=trans_paras,
            error="",
        )
        return trans_title, trans_paras

    def pause(self):
        self.is_paused = True

    def resume(self):
        self.is_paused = False

    def stop(self):
        self.stop_requested = True
        self.is_paused = False

    def export_txt(self) -> Path | None:
        book = self.store.book()
        if not book:
            return None
        with self.store.connect() as c:
            rows = c.execute("SELECT * FROM chapter ORDER BY position").fetchall()
        chapters = []
        for r in rows:
            d = dict(r)
            d["translated"] = json.loads(d["translated"])
            chapters.append(d)
        content = export_txt(book, chapters)
        out_path = EXPORTS_DIR / f"{book['title']}_dich.txt"
        out_path.write_bytes(content)
        return out_path

    def export_epub(self) -> Path | None:
        book = self.store.book()
        if not book:
            return None
        with self.store.connect() as c:
            rows = c.execute("SELECT * FROM chapter ORDER BY position").fetchall()
        chapters = []
        for r in rows:
            d = dict(r)
            d["translated"] = json.loads(d["translated"])
            chapters.append(d)
        content = export_epub(book, chapters)
        out_path = EXPORTS_DIR / f"{book['title']}_dich.epub"
        out_path.write_bytes(content)
        return out_path


    def get_toc_data(self, search_query: str = "") -> list[list]:
        chapters = self.store.list()
        q = search_query.strip().lower()
        rows = []
        icons = {
            "pending": "◷ Chưa dịch",
            "translating": "⟳ Đang dịch...",
            "done": "✓ Đã dịch",
            "error": "⚠ Lỗi",
        }
        for c in chapters:
            haystack = f"{c['position']} {c['title']} {c['translated_title']}".lower()
            if q and q not in haystack:
                continue
            rows.append([
                c["id"],
                f"#{c['position']}",
                c["title"],
                c["translated_title"] or "(chưa dịch)",
                icons.get(c["status"], c["status"]),
                False,
            ])
        return rows

    def render_reader_html(self, chapter_id: int | None, view_mode: str = "parallel", font_size: str = "17px") -> str:
        if not chapter_id:
            chapters = self.store.list()
            if chapters:
                chapter_id = chapters[0]["id"]
            else:
                return (
                    '<div class="novel-empty-reader">'
                    '<h3>Chưa có chương nào được chọn</h3>'
                    '<p>Vui lòng nạp truyện ở trên để bắt đầu đọc và dịch.</p>'
                    '</div>'
                )

        chapter = self.store.get(chapter_id)
        if not chapter:
            return '<div class="novel-empty-reader"><p>Không tìm thấy chương.</p></div>'

        title_zh = html.escape(chapter.get("title") or "")
        title_vi = html.escape(chapter.get("translated_title") or title_zh)
        source_paras = chapter.get("source") or []
        trans_paras = chapter.get("translated") or []

        mode_class = "mode-parallel"
        if "bản dịch" in view_mode.lower():
            mode_class = "mode-target"
        elif "nguyên tác" in view_mode.lower():
            mode_class = "mode-source"

        lines = [
            f'<div class="novel-reader-box {mode_class}" style="font-size: {font_size};">',
            '  <div class="novel-chapter-header">',
            f'    <div class="novel-chap-badge">CHƯƠNG #{chapter["position"]}</div>',
            f'    <h3 class="novel-chap-title-vi">{title_vi}</h3>',
            f'    <div class="novel-chap-title-zh">{title_zh}</div>',
            '  </div>',
            '  <div class="novel-paragraphs-container">',
        ]

        max_len = max(len(source_paras), len(trans_paras), 1)
        for i in range(max_len):
            zh = html.escape(source_paras[i]) if i < len(source_paras) else ""
            vi = html.escape(trans_paras[i]) if i < len(trans_paras) else ""
            if not vi:
                vi_html = '<span class="novel-waiting">（Bản dịch sẽ xuất hiện tại đây...）</span>'
            else:
                vi_html = vi

            lines.append(f'    <div class="novel-para-row" id="row-{i+1}">')
            lines.append(f'      <div class="novel-col-zh"><span class="para-num">{i+1}</span><p>{zh or "—"}</p></div>')
            lines.append(f'      <div class="novel-col-vi"><p>{vi_html}</p></div>')
            lines.append('    </div>')

        lines.append('  </div>')
        lines.append('</div>')
        return "\n".join(lines)


novel_service = NovelService()
