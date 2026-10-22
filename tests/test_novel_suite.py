import os
import sys
import tempfile
from pathlib import Path

from translation.core.novel_text import split_chapters, paragraphs, make_plan, assemble
from translation.core.novel_store import Store
from translation.core.novel_files import parse_file, export_txt, export_epub
from translation.core.novel_service import NovelService


SAMPLE_TXT = """第1章 Mở đầu
Đoạn văn thứ nhất.
Đoạn văn thứ hai.

第2章 Biến cố
Nội dung chương hai.
Trận chiến bắt đầu.
"""


def test_novel_text_splitting():
    chapters = split_chapters(SAMPLE_TXT)
    assert len(chapters) == 2
    assert "第1章" in chapters[0][0]
    assert "第2章" in chapters[1][0]
    paras = paragraphs(chapters[0][1])
    assert len(paras) == 2


def test_novel_store_operations():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_novel.sqlite3"
        store = Store(db_path)

        chapters = [
            ("Chương 1", "Đoạn 1\n\nĐoạn 2"),
            ("Chương 2", "Đoạn 3\n\nĐoạn 4"),
            ("Chương 3", "Đoạn 5\n\nĐoạn 6"),
        ]
        store.replace("tac_pham_mau.txt", "UTF-8", chapters)

        current = store.book()
        assert current is not None
        assert current["title"] == "tac_pham_mau"

        ch_list = store.list()
        assert len(ch_list) == 3
        assert ch_list[0]["status"] == "pending"

        store.update(
            ch_list[0]["id"],
            translated=["Bản dịch 1", "Bản dịch 2"],
            status="done"
        )
        ch0 = store.get(ch_list[0]["id"])
        assert ch0["status"] == "done"
        assert len(ch0["translated"]) == 2

        store.reset_chapters([ch_list[0]["id"]])
        ch0_reset = store.get(ch_list[0]["id"])
        assert ch0_reset["status"] == "pending"
        assert ch0_reset["translated"] == []

        store.delete_chapters([ch_list[2]["id"]])
        assert len(store.list()) == 2

        store.clear()
        assert store.book() is None
        assert store.list() == []


def test_novel_files_and_export():
    chapters, encoding = parse_file("test_novel.txt", SAMPLE_TXT.encode("utf-8"))
    assert len(chapters) == 2
    assert "utf-8" in encoding.lower()

    book = {"title": "test_novel"}
    ch_objs = [
        {"position": 1, "title": chapters[0][0], "translated_title": "Chương 1", "source": ["Đoạn 1"], "translated": ["Dịch đoạn 1"], "status": "done"},
        {"position": 2, "title": chapters[1][0], "translated_title": "Chương 2", "source": ["Đoạn 2"], "translated": [], "status": "pending"},
    ]

    txt_data = export_txt(book, ch_objs)
    assert b"test_novel" in txt_data
    assert "Dịch đoạn 1".encode("utf-8") in txt_data

    epub_data = export_epub(book, ch_objs)
    assert epub_data.startswith(b"PK")


def test_novel_service():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_svc.sqlite3"
        svc = NovelService(db_path=db_path)

        book_path = Path(tmpdir) / "sample.txt"
        book_path.write_text(SAMPLE_TXT, encoding="utf-8")

        ok, summary = svc.load_novel(str(book_path))
        assert ok is True
        assert "sample.txt" in summary
        assert "2 chương" in summary

        toc = svc.get_toc_data()
        assert len(toc) == 2
        assert toc[0][2] == "第1章 Mở đầu"
        assert "◷" in toc[0][4]

        html = svc.render_reader_html(toc[0][0], view_mode="Song song (Đối chiếu)")
        assert "第1章" in html
        assert "novel-reader-box" in html

        del_msg = svc.delete_chapters([toc[0][0]])
        assert "1 chương" in del_msg
        assert len(svc.get_toc_data()) == 1

        reset_msg = svc.reset_chapters([toc[1][0]])
        assert "1 chương" in reset_msg
