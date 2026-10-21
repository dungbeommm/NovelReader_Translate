# QA v4.4

## Đã chạy

- `python -m pytest -q --disable-warnings`: **194 passed** (CPU/mock).
- `node --check web/static/app.js`: thành công.
- Python compileall: thành công.
- `python -m marimo check NovelReader_Molab.py`: thành công.
- Chromium 1440 × 1000 và 390 × 844: đã xem ảnh trạng thái nguồn rỗng, hiệu năng audio, tab cloud và khôi phục. Không có horizontal page overflow hay lỗi JavaScript trong các luồng được thử.
- Playwright thao tác thực với backend cục bộ: nạp truyện mẫu, chọn batch 1024 / 4 audio workers / hàng chờ 8; lưu/nạp bảng tạm, giữ tốc độ 1.0; tải ZIP, khôi phục ZIP; chặn URL ngoài Pixeldrain. Thành công.
- Kiểm thử mới bao gồm: các worker dùng phiên Piper riêng; hàm tổng hợp chạy chồng nhau; khôi phục SQLite với segment chưa hoàn tất; thiếu audio; hash sai; đường dẫn ZIP không hợp lệ; không đưa key vào backup; upload file streaming; không xóa token Drive khi lưu tùy chọn.

## Chưa xác minh

- GPU NVIDIA/CUDA thật, VRAM tối đa và throughput audio/dịch.
- Upload/download Pixeldrain bằng tài khoản thật hoặc Google OAuth thật.
- Khởi chạy toàn bộ pipeline trong Molab/Colab/Kaggle thực tế và tải toàn bộ model giọng qua mạng.

Không suy ra “GPU 100%”, tăng tốc cụ thể hay tương thích mọi GPU từ các bài kiểm thử CPU/mock này.
