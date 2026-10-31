---
title: NovelReader
emoji: 📚
colorFrom: blue
colorTo: green
sdk: gradio
sdk_version: "6.30.0"
python_version: "3.12"
app_file: app.py
pinned: false
---

# NovelReader

## Triển khai WebUI lên Render (CPU)

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/dungbeommm/NovelReader_Translate)

Cấu hình đã có sẵn tại [render.yaml](render.yaml), [Dockerfile.render](Dockerfile.render) và [requirements-render.txt](requirements-render.txt). Sử dụng **Blueprint Free** ở vùng Singapore. Trong bước tạo Blueprint, đặt `NOVEL_WEB_ACCESS_TOKEN` thành một mật khẩu dài, ngẫu nhiên, giữ bí mật; cần dùng mã này để đăng nhập WebUI. Không commit token lên GitHub. Có thể thêm `HF_TOKEN` tại phần Environment trên Render nếu cần kết nối kho Hugging Face riêng.

**Giới hạn quan trọng:** Render Free chỉ phù hợp kiểm tra giao diện/API, không dành cho dịch hoặc TTS lâu dài. Gói Free có RAM thấp và hệ thống tự ngủ khi không có truy cập; dữ liệu SQLite, chương đã tải lên, model và file audio lưu cục bộ **sẽ bị mất khi restart, redeploy hoặc spin down**. Với các tác vụ thật, cần máy chủ có ổ lưu bền vững hoặc thiết kế tách WebUI khỏi worker xử lý và đồng bộ dữ liệu lên kho từ xa.

Notebook giờ chỉ là **launcher cho WebUI**, không hiển thị bảng điều khiển dịch/TTS/truyện.


## Tải truyện 番茄小说 bằng ID

NovelReader có thêm ô **Tải truyện bằng ID** ngay trong mục **Truyện nguồn**. Chỉ nhập ID, công cụ sử dụng Tomato-Novel-Downloader (dịch vụ Rust riêng) để tải chữ, tự nhập danh sách chương rồi khởi động HachimiMT và TTS theo cài đặt của NovelReader. Không cần mở WebUI Tomato riêng.

Để chạy cả hai dịch vụ trong Docker Compose, thêm `TOMATO_WEB_PASSWORD` vào file `.env` riêng tư, rồi chạy:

```bash
docker compose -f compose.yaml -f compose.tomato.yaml up -d --build
```

Hướng dẫn cài local/MoLab, sơ đồ xử lý, API và lưu ý an toàn: **[Tích hợp Tomato Downloader](docs/TOMATO_INTEGRATION.md)**.

## Notebook
- [NovelReader_Molab.py](NovelReader_Molab.py): chạy bằng Marimo/MoLab.
- [NovelReader_Colab.ipynb](NovelReader_Colab.ipynb): chạy bằng Google Colab.
- Hai notebook dùng chung [notebook/webui_launcher.py](notebook/webui_launcher.py).
- Kết quả in ở notebook: `WEBUI_URL`, `MA_TRUY_CAP`, `LOCAL_URL`, GPU/CPU, và logcat WebUI/zrok/job.
- Điền token mới vào `HF_TOKEN_INLINE`, `ZROK_ACCOUNT_TOKEN_INLINE` **chỉ trong bản cá nhân riêng tư**; không lưu token thật trên GitHub công khai.
- Nếu không có token zrok, WebUI vẫn khởi chạy cục bộ nhưng không có URL public.

## Chức năng nghiệp vụ
Trên WebUI: nạp TXT/EPUB/ZIP, chọn chương, dịch HachimiMT, tạo Piper/VieNeu audio, ghép MP3, xem tiến độ, quản lý Hugging Face Bucket, checkpoint và khôi phục.

## Các module
`core/` runtime/job lock; `server/` FastAPI, API, auth và tunnel;
`translation/` dịch, `audio/` và `tts/` giọng đọc;
`storage/` SQLite/HF/checkpoint, `workflows/` tác vụ; `web/static/` UI.

## Vận hành
Notebook tự clone repo ở sandbox trống; sandbox cũ không tự cập nhật. Đừng xóa `data/`, `output_text/`, `output_audio/` khi đổi source. Chạy bằng một Uvicorn worker.

```bash
python -m pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --workers 1
```

Kiểm thử: `python -m pytest tests/test_architecture_refactor.py tests/test_notebook_launcher.py tests/test_api.py -q`.

Sơ đồ đầy đủ: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
