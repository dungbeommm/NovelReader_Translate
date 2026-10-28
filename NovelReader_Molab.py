"""NovelReader: interactive translation and audio inside MoLab; no public tunnel."""
# /// script
# requires-python = ">=3.11"
# dependencies = ["marimo==0.25.2"]
# ///
import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo
    import os
    import sys
    import subprocess
    import importlib.util as module_util
    import urllib.request as url_request
    from pathlib import Path
    return Path, mo, module_util, os, subprocess, sys, url_request


@app.cell
def _(Path, module_util, os, subprocess, sys, url_request):
    # Override in Secrets when using another reviewed source branch/commit.
    source_ref = os.getenv("NOVEL_SOURCE_REF", "fix/molab-native-runtime")
    _base = Path.cwd().resolve()
    repo_dir = _base if (_base / "main.py").is_file() else _base / "NovelReader_T4_Web"
    repo_dir.mkdir(parents=True, exist_ok=True)
    _bootstrap_path = repo_dir / "notebook/molab_bootstrap.py"
    if not _bootstrap_path.is_file():
        _bootstrap_path.parent.mkdir(parents=True, exist_ok=True)
        _url = "https://raw.githubusercontent.com/dungbeommm/NovelReader_Translate/" + source_ref + "/notebook/molab_bootstrap.py"
        with url_request.urlopen(_url, timeout=60) as _response:
            _source = _response.read(1024 * 1024)
        _bootstrap_path.write_bytes(_source)
    _spec = module_util.spec_from_file_location("novelreader_molab_bootstrap", _bootstrap_path)
    _bootstrap = module_util.module_from_spec(_spec)
    _spec.loader.exec_module(_bootstrap)
    _repaired = _bootstrap.restore_missing(repo_dir, source_ref)
    if _repaired:
        print(f"Đã khôi phục {len(_repaired)} tệp mã nguồn/phụ thuộc còn thiếu.")
    _bootstrap.prepare_environment(repo_dir)
    if str(repo_dir) not in sys.path:
        sys.path.insert(0, str(repo_dir))
    # Install missing dependencies only; never start Uvicorn or any tunnel.
    _required = ("fastapi", "ebooklib", "bs4", "huggingface_hub", "ctranslate2",
                 "sentencepiece", "gradio_client", "opencc", "piper", "onnxruntime", "psutil")
    if os.getenv("NOVEL_SKIP_INSTALL") != "1" and any(module_util.find_spec(_name) is None for _name in _required):
        print("Đang cài thư viện NovelReader; bước này có thể mất vài phút.", flush=True)
        subprocess.run([sys.executable, "-m", "pip", "install", "--no-cache-dir",
                        "--disable-pip-version-check", "-r", str(repo_dir / "requirements.txt")],
                       check=True, timeout=1800)
    if os.getenv("NOVEL_SKIP_INSTALL") != "1":
        _bootstrap.ensure_tools()
    _module_name = "novelreader_molab_native"
    if _module_name not in sys.modules:
        _spec = module_util.spec_from_file_location(_module_name, repo_dir / "notebook/molab_native.py")
        _native = module_util.module_from_spec(_spec)
        sys.modules[_module_name] = _native
        _spec.loader.exec_module(_native)
    controller = sys.modules[_module_name].initialize()
    return controller, repo_dir, source_ref


@app.cell
def _(mo):
    mo.md("""
    # NovelReader · Molab
    Nạp truyện, dịch và tạo audio ngay trong notebook.

    Molab vẫn có thể thu hồi phiên. **Checkpoint đã upload thành công** mới khôi phục
    được sau khi mất máy chạy. Đặt `HF_TOKEN` và `HF_BUCKET_ID` trong **Secrets**;
    token không cần điền vào mã nguồn. Không tự chạy lại tác vụ khi mở notebook.
    """)
    return


@app.cell
def _(mo, os):
    bucket = mo.ui.text(value=os.getenv("HF_BUCKET_ID", "uri410/novelreader-storage"),
                        label="Bucket Hugging Face", full_width=True)
    book_upload = mo.ui.file(filetypes=[".txt", ".epub", ".zip"], max_size=50 * 1024**2,
                             label="Chọn truyện TXT / EPUB / ZIP")
    restore_upload = mo.ui.file(filetypes=[".zip"], max_size=2 * 1024**3, label="Checkpoint ZIP")
    checkpoint_path = mo.ui.text(label="Đường dẫn checkpoint HF", placeholder="checkpoints/…/….zip", full_width=True)
    with_audio = mo.ui.checkbox(value=False, label="Kèm audio trong checkpoint (tối đa 2 GB)")
    mo.vstack([bucket, book_upload])
    return book_upload, bucket, checkpoint_path, restore_upload, with_audio


@app.cell
def _(book_upload, bucket, checkpoint_path, controller, mo, restore_upload, with_audio):
    def _load():
        if not book_upload.value:
            raise ValueError("Hãy chọn tệp truyện.")
        return controller.load_book(book_upload.name(), book_upload.contents())
    def _restore_file():
        if not restore_upload.value:
            raise ValueError("Hãy chọn checkpoint ZIP.")
        return controller.restore_file(restore_upload.contents())
    load_book = mo.ui.button(label="Nạp truyện mới (thay truyện hiện tại)", on_click=lambda _: controller.invoke(_load))
    restore_file = mo.ui.button(label="Khôi phục từ ZIP", on_click=lambda _: controller.invoke(_restore_file))
    restore_hf = mo.ui.button(label="Khôi phục từ HF", on_click=lambda _: controller.invoke(
        lambda: controller.restore_cloud(bucket.value, checkpoint_path.value)))
    list_hf = mo.ui.button(label="Liệt kê checkpoint HF", on_click=lambda _: controller.invoke(
        lambda: controller.list_cloud(bucket.value)))
    save_hf = mo.ui.button(label="Lưu checkpoint HF ngay", on_click=lambda _: controller.invoke(
        lambda: controller.save_cloud(bucket.value, with_audio.value)))
    mo.vstack([load_book, mo.accordion({"Lưu và khôi phục tiến độ": mo.vstack([
        with_audio, save_hf, list_hf, checkpoint_path, restore_hf, restore_upload, restore_file,
        mo.download(data=lambda: controller.download_checkpoint(with_audio.value).read_bytes(),
                    filename="NovelReader_checkpoint.zip", label="Tải checkpoint về máy (khi tác vụ đã dừng)"),
        mo.md("Khôi phục thay truyện hiện tại. Sau khi khôi phục, kiểm tra cấu hình rồi bấm Bắt đầu. Audio không có trong ZIP sẽ được tạo lại.")
    ])})])
    return list_hf, load_book, restore_file, restore_hf, save_hf


@app.cell
def _(controller, load_book, mo, os, restore_file, restore_hf):
    # Recreate settings from the restored book, rather than stale UI defaults.
    _ = (load_book.value, restore_file.value, restore_hf.value)
    _saved = controller.saved_config()
    from translation.engines import MODELS
    _models = {item["name"]: key for key, item in MODELS.items()}
    _model_label = next((label for label, key in _models.items() if key == _saved['engine']), next(iter(_models)))
    settings_form = mo.md("""
    **Cấu hình dịch và audio**

    {engine} {backend} {batch_size}

    {generate_audio} {tts_engine} {voice_id}

    {start_pos} {end_pos}

    {glossary}

    {cloud_checkpoint} {checkpoint_include_audio}

    {cloud_checkpoint_every} {cloud_checkpoint_minutes}
    """).batch(
        engine=mo.ui.dropdown(_models, value=_model_label, label="Mô hình"),
        backend=mo.ui.dropdown(["ct2", "transformers"], value=_saved['backend'] if _saved['backend'] != 'pytorch' else 'transformers', label="Backend"),
        batch_size=mo.ui.number(1, 128, value=min(128, _saved['batch_size']), label="Batch"),
        generate_audio=mo.ui.checkbox(value=_saved['generate_audio'], label="Tạo audio"),
        tts_engine=mo.ui.dropdown(["piper", "vieneu"], value=_saved['tts_engine'], label="TTS"),
        voice_id=mo.ui.text(value=_saved['voice_id'], label="ID giọng đọc"),
        start_pos=mo.ui.number(0, 1000000, value=_saved['start_pos'] or 0, label="Từ chương (0 = toàn bộ)"),
        end_pos=mo.ui.number(0, 1000000, value=_saved['end_pos'] or 0, label="Đến chương (0 = hết)"),
        glossary=mo.ui.text_area(value=_saved['glossary'], label="Glossary", full_width=True),
        cloud_checkpoint=mo.ui.checkbox(value=bool(os.getenv('HF_TOKEN')) or _saved['cloud_checkpoint'], label="Tự lưu checkpoint lên HF khi chạy"),
        checkpoint_include_audio=mo.ui.checkbox(value=_saved['checkpoint_include_audio'], label="Tự lưu kèm audio (ZIP ≤ 2 GB)"),
        cloud_checkpoint_every=mo.ui.number(1, 10000, value=2, label="Lưu sau số chương"),
        cloud_checkpoint_minutes=mo.ui.number(1, 1440, value=1, label="Hoặc số phút (kiểm tra khi xong chương)"),
    ).form(submit_button_label="Áp dụng cấu hình")
    mo.vstack([settings_form, mo.md("Mặc định 1 audio worker, hàng chờ 2. Đổi cấu hình dịch giữa chừng sẽ được kiểm tra trước khi tiếp tục.")])
    return (settings_form,)


@app.cell
def _(controller, settings_form):
    config_payload = controller.saved_config()
    if settings_form.value is not None:
        config_payload.update(settings_form.value)
        config_payload['start_pos'] = config_payload['start_pos'] or None
        config_payload['end_pos'] = config_payload['end_pos'] or None
        config_payload['chapter_ids'] = None
    config_payload.update(audio_workers=1, audio_queue_size=2, reset=False, force_retranslate=False)
    return (config_payload,)


@app.cell
def _(bucket, config_payload, controller, mo, settings_form):
    start_job = mo.ui.button(label="Bắt đầu / Tiếp tục từ checkpoint", kind="success", disabled=settings_form.value is None, on_click=lambda _: controller.invoke(
        lambda: controller.start(config_payload, bucket.value)))
    pause_job = mo.ui.button(label="Tạm dừng", on_click=lambda _: controller.invoke(lambda: controller.control('pause')))
    resume_job = mo.ui.button(label="Tiếp tục tác vụ tạm dừng", on_click=lambda _: controller.invoke(lambda: controller.control('resume')))
    stop_job = mo.ui.button(label="Dừng sau batch hiện tại", kind="warn", on_click=lambda _: controller.invoke(lambda: controller.control('stop')))
    refresh = mo.ui.button(label="Cập nhật tiến độ", on_click=lambda value: (value or 0) + 1, value=0)
    mo.vstack([mo.md("Bấm **Áp dụng cấu hình** để bật nút Bắt đầu."),
               mo.hstack([start_job, pause_job, resume_job, stop_job, refresh], wrap=True)])
    return pause_job, refresh, resume_job, start_job, stop_job


@app.cell
def _(controller, list_hf, load_book, mo, pause_job, refresh, restore_file, restore_hf, resume_job, save_hf, start_job, stop_job):
    _ = (refresh.value, start_job.value, pause_job.value, resume_job.value, stop_job.value,
         load_book.value, restore_file.value, restore_hf.value, save_hf.value, list_hf.value)
    _state = controller.snapshot()
    _last = (_state['last_cloud'] or {}).get('id', '(chưa upload checkpoint thành công)')
    mo.vstack([
        mo.callout(str(controller.notice), kind="warn" if str(controller.notice).startswith('Lỗi:') else "info"),
        mo.md(f"**{_state['book']}** · {_state['status']} · {_state['done']}/{_state['total']} chương · {_state['audio_done']} audio hoàn tất"),
        mo.md(f"RAM tiến trình: **{_state['process_ram_mib']} MiB**. Checkpoint HF gần nhất: `{_last}`"),
        mo.md(_state['message'] or ""),
        mo.callout(_state['cloud_error'], kind="danger") if _state['cloud_error'] else mo.md(""),
        mo.ui.table(controller.store.list(), selection=None, page_size=15),
        mo.md("Chỉ checkpoint đã upload mới tồn tại sau khi Molab thu hồi máy. Tiến độ chưa lưu có thể cần làm lại; notebook không kéo dài giới hạn phiên của Molab.")
    ])
    return


if __name__ == "__main__":
    app.run()
