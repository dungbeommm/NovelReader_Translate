"""Novel Tab UI and Translation Engine integration for HachimiMT."""
from __future__ import annotations

import html
import json
import logging
import time
from pathlib import Path
from typing import Generator

import gradio as gr

from translation.core.novel_service import novel_service

log = logging.getLogger(__name__)

NOVEL_CSS = """
/* ── Novel Suite Styles (Phong cách giấy cũ / thư phòng) ─────────────── */
.novel-info-card {
    background: var(--card) !important;
    border: 1px solid var(--border) !important;
    border-radius: 8px !important;
    padding: 12px 18px !important;
    margin: 8px 0 !important;
}
.novel-reader-box {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 22px 26px;
    box-shadow: 0 4px 18px var(--shadow);
    margin-top: 10px;
}
.novel-chapter-header {
    border-bottom: 2px solid var(--border);
    padding-bottom: 12px;
    margin-bottom: 16px;
    text-align: center;
}
.novel-chap-badge {
    font-size: 11px;
    font-family: monospace;
    letter-spacing: 1.5px;
    color: var(--accent);
    font-weight: 600;
}
.novel-chap-title-vi {
    font-size: 22px;
    font-family: 'Fraunces', serif;
    color: var(--ink);
    margin: 4px 0 2px;
}
.novel-chap-title-zh {
    font-size: 13px;
    color: var(--muted);
    font-style: italic;
}
.novel-paragraphs-container {
    display: flex;
    flex-direction: column;
    gap: 12px;
    max-height: 600px;
    overflow-y: auto;
    padding-right: 6px;
}
.novel-para-row {
    display: flex;
    gap: 16px;
    padding: 8px 12px;
    border-radius: 6px;
    border-bottom: 1px solid var(--border-soft);
    transition: background 0.15s;
}
.novel-para-row:hover {
    background: var(--card-soft);
}
.novel-col-zh, .novel-col-vi {
    flex: 1;
    min-width: 0;
}
.novel-col-zh p {
    font-family: 'Noto Serif SC', serif;
    color: var(--ink-soft);
    margin: 0;
    line-height: 1.7;
}
.novel-col-vi p {
    font-family: 'Literata', serif;
    color: var(--ink);
    margin: 0;
    line-height: 1.75;
}
.para-num {
    font-size: 10px;
    font-family: monospace;
    color: var(--muted);
    float: left;
    margin-right: 8px;
    opacity: 0.6;
}
.novel-waiting {
    color: var(--muted);
    font-style: italic;
}
.novel-reader-box.mode-target .novel-col-zh { display: none !important; }
.novel-reader-box.mode-target .novel-col-vi { flex: 100% !important; }
.novel-reader-box.mode-source .novel-col-vi { display: none !important; }
.novel-reader-box.mode-source .novel-col-zh { flex: 100% !important; }
.novel-empty-reader {
    text-align: center;
    padding: 30px;
    color: var(--muted);
}
"""

def render_book_summary() -> str:
    book = novel_service.get_book()
    if not book:
        return "*(Chưa nạp truyện. Hãy tải lên file `.txt` / `.epub` hoặc nhập đường dẫn để bắt đầu.)*"
    chapters = novel_service.get_chapters()
    done = sum(c["status"] == "done" for c in chapters)
    pct = round(done / max(len(chapters), 1) * 100, 1)
    return (
        f"📖 **Tiểu thuyết:** `{book['title']}` · **Tệp:** `{book['filename']}` ({book['encoding']}) · "
        f"**Tiến độ:** **{done} / {len(chapters)}** chương ({pct}%)"
    )

def render_chapter_choices() -> list[tuple[str, int]]:
    chapters = novel_service.get_chapters()
    if not chapters:
        return [("Chưa có chương nào", 0)]
    return [(f"#{c['position']} {c['translated_title'] or c['title']}", c["id"]) for c in chapters]

def render_toc_table_data(query: str = "") -> list[list]:
    return novel_service.get_toc_data(query)

def build_novel_tab(
    translator,
    model_select,
    backend_select,
    beam_size,
    chunk_mode,
    normalize_mode,
    honorific_kinship,
    honorific_pronouns,
    pronoun_harmonizer_v9,
    auto_batch,
    manual_batch,
    glossary_table,
):
    with gr.Tab("📚 Dịch tiểu thuyết (Tách chương · EPUB / TXT · Đọc song song)"):
        gr.Markdown(
            "Dịch tiểu thuyết trọn bộ từ file `.txt` hoặc `.epub`. "
            "Tự động chia chương, lưu độc lập từng chương vào database SQLite "
            "(không mất dữ liệu khi ngắt giữa chừng), đối chiếu song song và xuất EPUB/TXT hoàn chỉnh.",
            elem_classes=["honorific-hint"],
        )

        # ── 1. Nguồn truyện ───────────────────────────────────────────
        with gr.Row():
            novel_file = gr.File(
                label="Chọn file truyện (.txt hoặc .epub)",
                file_types=[".txt", ".epub"],
                type="filepath",
                scale=3,
            )
            novel_path = gr.Textbox(
                label="Hoặc nhập đường dẫn file trên máy",
                placeholder=r"C:\Downloads\truyen.txt hoặc C:\Downloads\truyen.epub",
                scale=3,
            )
        with gr.Row():
            load_btn = gr.Button("📥 Nạp truyện & Phân tích chương", variant="primary", scale=2)
            clear_btn = gr.Button("🗑 Xóa truyện khỏi thư viện", variant="stop", scale=1)

        book_info = gr.Markdown(render_book_summary(), elem_classes=["novel-info-card"])

        # ── 2. Điều khiển dịch ─────────────────────────────────────────
        with gr.Row():
            reset_chk = gr.Checkbox(label="Dịch lại từ đầu (xóa bản dịch cũ của truyện)", value=False, scale=2)
            start_btn = gr.Button("▷ Bắt đầu dịch truyện", variant="primary", size="lg", scale=3)
            pause_btn = gr.Button("Ⅱ Tạm dừng", variant="secondary", scale=1)
            stop_btn = gr.Button("□ Dừng", variant="stop", scale=1)

        novel_progress_html = gr.HTML(
            '<div style="padding: 10px; background: var(--card); border: 1px solid var(--border); border-radius: 6px; text-align: center;">'
            '● <strong>Sẵn sàng</strong> — Chọn cấu hình và bấm "Bắt đầu dịch truyện".</div>'
        )
        status_box = gr.Markdown("")

        # ── 3. Mục lục & Quản lý chương ────────────────────────────────
        with gr.Accordion("📑 Mục lục & Quản lý chương", open=True):
            with gr.Row():
                search_input = gr.Textbox(label="Tìm chương", placeholder="Nhập tên chương hoặc số thứ tự...", scale=4)
                select_all_btn = gr.Button("Chọn tất cả", size="sm", scale=1)
                deselect_all_btn = gr.Button("Bỏ chọn", size="sm", scale=1)

            with gr.Row():
                batch_reset_btn = gr.Button("↺ Xóa bản dịch đã chọn", variant="secondary", size="sm")
                batch_delete_btn = gr.Button("🗑 Xóa chương đã chọn", variant="stop", size="sm")
                batch_msg = gr.Markdown("")

            initial_toc = render_toc_table_data()
            toc_table = gr.Dataframe(
                headers=["ID", "#", "Tên chương gốc", "Bản dịch", "Trạng thái", "Chọn"],
                datatype=["number", "str", "str", "str", "str", "bool"],
                value=initial_toc,
                interactive=True,
                max_height=320,
                label="Danh sách chương (Click vào hàng hoặc chọn menu bên dưới để đọc)",
            )

        # ── 4. Khung đọc truyện song song ──────────────────────────────
        with gr.Accordion("📖 Khung đọc truyện song song", open=True):
            chapters = novel_service.get_chapters()
            initial_cid = chapters[0]["id"] if chapters else 0
            cur_chapter_state = gr.State(initial_cid)

            with gr.Row():
                chapter_select = gr.Dropdown(
                    label="Chọn chương để đọc",
                    choices=render_chapter_choices(),
                    value=initial_cid if initial_cid else None,
                    scale=4,
                )
                prev_btn = gr.Button("← Trước", size="sm", scale=1)
                next_btn = gr.Button("Sau →", size="sm", scale=1)
                reset_cur_btn = gr.Button("↺ Xóa bản dịch chương này", size="sm", scale=1)
                delete_cur_btn = gr.Button("🗑 Xóa chương này", variant="stop", size="sm", scale=1)

            with gr.Row():
                view_mode = gr.Radio(
                    ["Song song (2 cột)", "Chỉ bản dịch", "Chỉ nguyên tác"],
                    value="Song song (2 cột)",
                    label="Chế độ xem",
                    scale=2,
                )
                font_size = gr.Radio(["15px", "17px", "19px", "21px"], value="17px", label="Cỡ chữ", scale=2)
                copy_btn = gr.Button("📋 Sao chép bản dịch chương", size="sm", scale=1)
                copy_msg = gr.Markdown("")

            reader_display = gr.HTML(
                novel_service.render_reader_html(initial_cid, "Song song (2 cột)", "17px"),
                elem_id="novel-reader-display",
            )

        # ── 5. Xuất truyện ─────────────────────────────────────────────
        with gr.Row():
            export_txt_btn = gr.Button("💾 Xuất toàn bộ truyện .txt", variant="secondary")
            export_epub_btn = gr.Button("📖 Xuất sách điện tử .epub", variant="secondary")
            download_novel = gr.File(label="Tải file sách đã xuất")

        # ── EVENTS ────────────────────────────────────────────────────
        def on_load(f_obj, p_str):
            ok, msg = novel_service.load_novel(f_obj, p_str or "")
            summary = render_book_summary()
            toc = render_toc_table_data()
            choices = render_chapter_choices()
            chaps = novel_service.get_chapters()
            cid = chaps[0]["id"] if chaps else 0
            r_html = novel_service.render_reader_html(cid, "Song song (2 cột)", "17px")
            return msg, summary, toc, gr.update(choices=choices, value=cid if cid else None), cid, r_html

        load_btn.click(
            on_load,
            inputs=[novel_file, novel_path],
            outputs=[status_box, book_info, toc_table, chapter_select, cur_chapter_state, reader_display],
        )

        def on_clear():
            msg = novel_service.delete_book()
            summary = render_book_summary()
            r_html = novel_service.render_reader_html(None)
            return msg, summary, [], gr.update(choices=[("Chưa có chương nào", 0)], value=None), 0, r_html

        clear_btn.click(
            on_clear,
            outputs=[status_box, book_info, toc_table, chapter_select, cur_chapter_state, reader_display],
        )

        def on_search(q):
            return render_toc_table_data(q)

        search_input.change(on_search, inputs=[search_input], outputs=[toc_table])

        def on_select_all(table_data):
            if not table_data:
                return table_data
            new_data = [list(row) for row in table_data]
            for row in new_data:
                if len(row) >= 6:
                    row[5] = True
            return new_data

        def on_deselect_all(table_data):
            if not table_data:
                return table_data
            new_data = [list(row) for row in table_data]
            for row in new_data:
                if len(row) >= 6:
                    row[5] = False
            return new_data

        select_all_btn.click(on_select_all, inputs=[toc_table], outputs=[toc_table])
        deselect_all_btn.click(on_deselect_all, inputs=[toc_table], outputs=[toc_table])

        def on_batch_reset(table_data, cur_cid, v_mode, f_size):
            if not table_data:
                return "Chưa có dữ liệu chương.", table_data, render_book_summary(), cur_cid, novel_service.render_reader_html(cur_cid, v_mode, f_size)
            selected_ids = [int(row[0]) for row in table_data if len(row) >= 6 and row[5]]
            if not selected_ids:
                return "Chưa chọn chương nào để đặt lại.", table_data, render_book_summary(), cur_cid, novel_service.render_reader_html(cur_cid, v_mode, f_size)
            msg = novel_service.reset_chapters(selected_ids)
            toc = render_toc_table_data()
            summary = render_book_summary()
            r_html = novel_service.render_reader_html(cur_cid, v_mode, f_size)
            return msg, toc, summary, cur_cid, r_html

        batch_reset_btn.click(
            on_batch_reset,
            inputs=[toc_table, cur_chapter_state, view_mode, font_size],
            outputs=[batch_msg, toc_table, book_info, cur_chapter_state, reader_display],
        )

        def on_batch_delete(table_data, cur_cid, v_mode, f_size):
            if not table_data:
                return "Chưa có dữ liệu chương.", table_data, render_book_summary(), cur_cid, novel_service.render_reader_html(cur_cid, v_mode, f_size), gr.update()
            selected_ids = [int(row[0]) for row in table_data if len(row) >= 6 and row[5]]
            if not selected_ids:
                return "Chưa chọn chương nào để xóa.", table_data, render_book_summary(), cur_cid, novel_service.render_reader_html(cur_cid, v_mode, f_size), gr.update()
            msg = novel_service.delete_chapters(selected_ids)
            toc = render_toc_table_data()
            summary = render_book_summary()
            choices = render_chapter_choices()
            chaps = novel_service.get_chapters()
            new_cid = chaps[0]["id"] if chaps else 0
            r_html = novel_service.render_reader_html(new_cid, v_mode, f_size)
            return msg, toc, summary, new_cid, r_html, gr.update(choices=choices, value=new_cid if new_cid else None)

        batch_delete_btn.click(
            on_batch_delete,
            inputs=[toc_table, cur_chapter_state, view_mode, font_size],
            outputs=[batch_msg, toc_table, book_info, cur_chapter_state, reader_display, chapter_select],
        )

        def on_select_chapter(cid, v_mode, f_size):
            if not cid:
                return 0, novel_service.render_reader_html(None)
            return cid, novel_service.render_reader_html(int(cid), v_mode, f_size)

        chapter_select.change(
            on_select_chapter,
            inputs=[chapter_select, view_mode, font_size],
            outputs=[cur_chapter_state, reader_display],
        )

        def on_toc_select(evt: gr.SelectData, v_mode, f_size):
            try:
                row_idx = evt.index[0]
                chaps = novel_service.get_chapters()
                if 0 <= row_idx < len(chaps):
                    cid = chaps[row_idx]["id"]
                    r_html = novel_service.render_reader_html(cid, v_mode, f_size)
                    return cid, gr.update(value=cid), r_html
            except Exception:
                pass
            return gr.update(), gr.update(), gr.update()

        toc_table.select(
            on_toc_select,
            inputs=[view_mode, font_size],
            outputs=[cur_chapter_state, chapter_select, reader_display],
        )

        def on_prev(cur_cid, v_mode, f_size):
            chaps = novel_service.get_chapters()
            if not chaps or not cur_cid:
                return cur_cid, gr.update(), gr.update()
            idx = next((i for i, c in enumerate(chaps) if c["id"] == cur_cid), 0)
            prev_idx = max(0, idx - 1)
            new_cid = chaps[prev_idx]["id"]
            return new_cid, gr.update(value=new_cid), novel_service.render_reader_html(new_cid, v_mode, f_size)

        def on_next(cur_cid, v_mode, f_size):
            chaps = novel_service.get_chapters()
            if not chaps or not cur_cid:
                return cur_cid, gr.update(), gr.update()
            idx = next((i for i, c in enumerate(chaps) if c["id"] == cur_cid), 0)
            next_idx = min(len(chaps) - 1, idx + 1)
            new_cid = chaps[next_idx]["id"]
            return new_cid, gr.update(value=new_cid), novel_service.render_reader_html(new_cid, v_mode, f_size)

        prev_btn.click(on_prev, inputs=[cur_chapter_state, view_mode, font_size], outputs=[cur_chapter_state, chapter_select, reader_display])
        next_btn.click(on_next, inputs=[cur_chapter_state, view_mode, font_size], outputs=[cur_chapter_state, chapter_select, reader_display])

        def on_reset_cur(cur_cid, v_mode, f_size):
            if not cur_cid:
                return "Chưa chọn chương.", render_toc_table_data(), render_book_summary(), novel_service.render_reader_html(None)
            msg = novel_service.reset_chapters([cur_cid])
            return msg, render_toc_table_data(), render_book_summary(), novel_service.render_reader_html(cur_cid, v_mode, f_size)

        reset_cur_btn.click(
            on_reset_cur,
            inputs=[cur_chapter_state, view_mode, font_size],
            outputs=[status_box, toc_table, book_info, reader_display],
        )

        def on_delete_cur(cur_cid, v_mode, f_size):
            if not cur_cid:
                return "Chưa chọn chương.", render_toc_table_data(), render_book_summary(), 0, gr.update(), novel_service.render_reader_html(None)
            msg = novel_service.delete_chapters([cur_cid])
            chaps = novel_service.get_chapters()
            new_cid = chaps[0]["id"] if chaps else 0
            choices = render_chapter_choices()
            return msg, render_toc_table_data(), render_book_summary(), new_cid, gr.update(choices=choices, value=new_cid if new_cid else None), novel_service.render_reader_html(new_cid, v_mode, f_size)

        delete_cur_btn.click(
            on_delete_cur,
            inputs=[cur_chapter_state, view_mode, font_size],
            outputs=[status_box, toc_table, book_info, cur_chapter_state, chapter_select, reader_display],
        )

        def on_view_change(cur_cid, v_mode, f_size):
            return novel_service.render_reader_html(cur_cid, v_mode, f_size)

        view_mode.change(on_view_change, inputs=[cur_chapter_state, view_mode, font_size], outputs=[reader_display])
        font_size.change(on_view_change, inputs=[cur_chapter_state, view_mode, font_size], outputs=[reader_display])

        def on_copy(cur_cid):
            if not cur_cid:
                return "Chưa chọn chương để sao chép."
            chap = novel_service.get_chapter(cur_cid)
            if not chap:
                return "Không tìm thấy chương."
            text = (chap.get("translated_title") or chap.get("title") or "") + "\n\n" + "\n\n".join(chap.get("translated") or [])
            # Return text for display or notification
            return f"✓ Đã đọc {len(text)} ký tự bản dịch chương #{chap.get('position')}."

        copy_btn.click(on_copy, inputs=[cur_chapter_state], outputs=[copy_msg])

        # ── 6. Dịch truyện đa luồng / streaming ─────────────────────────
        def run_novel_translation(
            reset_all: bool,
            m_select: str,
            b_select: str,
            b_size: float,
            c_mode: str,
            n_mode: str,
            h_kinship: bool,
            h_pronouns: bool,
            p_v9: bool,
            a_batch: bool,
            m_batch: float,
            g_table,
            cur_cid: int,
            v_mode: str,
            f_size: str,
        ) -> Generator[tuple, None, None]:
            book = novel_service.get_book()
            if not book:
                yield "Chưa nạp truyện.", render_book_summary(), render_toc_table_data(), cur_cid, novel_service.render_reader_html(cur_cid, v_mode, f_size), "Lỗi: Hãy nạp truyện trước."
                return

            if reset_all:
                all_ids = [c["id"] for c in novel_service.get_chapters()]
                novel_service.reset_chapters(all_ids)

            novel_service.is_running = True
            novel_service.is_paused = False
            novel_service.stop_requested = False

            # Ensure model loaded
            try:
                translator.load(m_select, b_select)
            except Exception as exc:
                yield f"Lỗi nạp model: {exc}", render_book_summary(), render_toc_table_data(), cur_cid, novel_service.render_reader_html(cur_cid, v_mode, f_size), f"Lỗi model: {exc}"
                return

            chapters = novel_service.get_chapters()
            pending_chapters = [c for c in chapters if c["status"] != "done"]
            total = len(chapters)
            done_init = total - len(pending_chapters)

            start_time = time.perf_counter()
            done_count = done_init

            for idx, c in enumerate(pending_chapters):
                if novel_service.stop_requested:
                    break

                while novel_service.is_paused:
                    time.sleep(0.5)
                    if novel_service.stop_requested:
                        break

                cid = c["id"]
                c_pos = c["position"]
                c_title = c["title"]

                pct = round(done_count / max(total, 1) * 100, 1)
                p_html = (
                    f'<div style="padding: 10px; background: var(--card); border: 1px solid var(--border); border-radius: 6px;">'
                    f'<div style="display:flex; justify-content:space-between; margin-bottom:6px;">'
                    f'<strong>Đang dịch Chương #{c_pos}: {c_title}</strong>'
                    f'<span>{done_count} / {total} chương ({pct}%)</span>'
                    f'</div>'
                    f'<div style="background: var(--border-soft); height: 8px; border-radius: 4px; overflow: hidden;">'
                    f'<div style="background: var(--accent); width: {pct}%; height: 100%; transition: width 0.3s;"></div>'
                    f'</div></div>'
                )
                yield p_html, render_book_summary(), render_toc_table_data(), cur_cid, novel_service.render_reader_html(cur_cid, v_mode, f_size), f"Đang dịch #{c_pos}..."

                try:
                    novel_service.translate_chapter(
                        cid,
                        translator,
                        beam_size=int(b_size),
                        chunk_mode=c_mode,
                        normalize_mode=n_mode,
                        honorific_kinship=h_kinship,
                        honorific_pronouns=h_pronouns,
                        pronoun_harmonizer_v9=p_v9,
                        glossary_rows=g_table,
                    )
                    done_count += 1
                except Exception as exc:
                    log.exception("Lỗi dịch chương %s", cid)

                # Update live view if reading current translating chapter
                display_cid = cid if (not cur_cid or cur_cid == cid) else cur_cid
                pct = round(done_count / max(total, 1) * 100, 1)
                elapsed = time.perf_counter() - start_time
                rate = (done_count - done_init) / elapsed * 60 if elapsed > 0 else 0
                rate_str = f" · {rate:.1f} chương/phút" if rate > 0 else ""

                p_html = (
                    f'<div style="padding: 10px; background: var(--card); border: 1px solid var(--border); border-radius: 6px;">'
                    f'<div style="display:flex; justify-content:space-between; margin-bottom:6px;">'
                    f'<strong>Tiến độ: {done_count} / {total} chương ({pct}%)</strong>'
                    f'<span>{rate_str}</span>'
                    f'</div>'
                    f'<div style="background: var(--border-soft); height: 8px; border-radius: 4px; overflow: hidden;">'
                    f'<div style="background: var(--accent); width: {pct}%; height: 100%; transition: width 0.3s;"></div>'
                    f'</div></div>'
                )
                yield p_html, render_book_summary(), render_toc_table_data(), display_cid, novel_service.render_reader_html(display_cid, v_mode, f_size), f"✓ Hoàn tất #{c_pos}"

            novel_service.is_running = False
            final_pct = round(done_count / max(total, 1) * 100, 1)
            final_html = (
                f'<div style="padding: 10px; background: var(--card); border: 1px solid var(--border); border-radius: 6px; text-align: center;">'
                f'✓ <strong>Hoàn thành dịch</strong> — {done_count} / {total} chương ({final_pct}%)'
                f'</div>'
            )
            yield final_html, render_book_summary(), render_toc_table_data(), cur_cid, novel_service.render_reader_html(cur_cid, v_mode, f_size), "Hoàn tất."

        start_btn.click(
            run_novel_translation,
            inputs=[
                reset_chk,
                model_select,
                backend_select,
                beam_size,
                chunk_mode,
                normalize_mode,
                honorific_kinship,
                honorific_pronouns,
                pronoun_harmonizer_v9,
                auto_batch,
                manual_batch,
                glossary_table,
                cur_chapter_state,
                view_mode,
                font_size,
            ],
            outputs=[novel_progress_html, book_info, toc_table, cur_chapter_state, reader_display, status_box],
        )

        pause_btn.click(lambda: novel_service.pause(), outputs=[])
        stop_btn.click(lambda: novel_service.stop(), outputs=[])

        # ── 7. Xuất file ───────────────────────────────────────────────
        def on_export_txt():
            p = novel_service.export_txt()
            return str(p) if p else None

        def on_export_epub():
            p = novel_service.export_epub()
            return str(p) if p else None

        export_txt_btn.click(on_export_txt, outputs=[download_novel])
        export_epub_btn.click(on_export_epub, outputs=[download_novel])
