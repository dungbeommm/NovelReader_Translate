# QA của bản tái cấu trúc

## Đã chạy

- `python -m pytest tests -q`: **114 passed**.
- Bộ test gồm kiểm tra nhập/xuất TXT/EPUB, tách chương/thuật ngữ/hậu xử lý, API, CSRF, phạm vi dịch, lỗi audio, cache gộp nhóm, lưu trữ theo tên truyện và chuyển dữ liệu.
- Kiểm tra riêng output: nạp truyện B không xóa output A; trùng tên không ghi đè; đổi tên chuyển cả text/audio; SQLite schema cũ nâng cấp được; reset chỉ vô hiệu hóa nhóm liên quan; tên Windows/Unicode/tên dài hợp lệ.
- Telegram: hàng đợi, quyền người dùng, tiếp tục checkpoint, phân phối file không gửi lặp; không đăng nhập hoặc gửi tới Telegram thật.
- TTS HTTP: dùng giọng giả lập và chuyển WAV → MP3 bằng FFmpeg thật. Adapter Piper dùng SynthesisConfig của thư viện thật với Voice giả lập; signature được đối chiếu trực tiếp với Piper đã cài.
- FFmpeg/ffprobe thật: gộp WAV kiểm tra số frame, gộp MP3 kiểm tra codec/thời lượng, tạo audio chương WAV và chia file gửi Telegram.
- Trình duyệt Chromium/Playwright: viewport 1366×1000 và 390×844; hai nút tác vụ chính ở Mục lục, payload dải 1–5, audio bắt buộc, dải thiếu/ngược không gọi API, nhóm sai không gọi API, đồng bộ/khôi phục số nhóm, đổi tên truyện qua API thật và hiển thị đường dẫn thư mục; không có lỗi JavaScript.
- WebSocket thật tới máy chủ local: trạng thái **Đã kết nối**.
- `node --check web/static/app.js` và Python compileall đạt.
- YAML Compose đọc được; các nguồn COPY trong hai Dockerfile đều tồn tại; không còn thư mục translator/ hay tts/voice/ trong bản mới.
- CLI `scripts/migrate_layout.py --help`, `scripts/download_model.py --help` chạy được, không tải model khi gọi help.

## Giới hạn

- Không có trọng số model dịch hoặc giọng trong ZIP nguồn. Không đánh giá chất lượng dịch/phát âm và chưa chạy suy luận với model thật.
- Không xác thực Google Drive hoặc Telegram thật, không upload/gửi dữ liệu ra ngoài. Các integration được kiểm thử ở phạm vi điều phối/HTTP giả lập.
- Không có Docker engine trong môi trường kiểm thử: đã kiểm tra YAML/đường dẫn, chưa build image hoặc chạy Docker Compose.
- Chưa chạy `start_web.bat` trên Windows thực. Đã cập nhật lệnh để khởi động main:app ở thư mục gốc; các quy tắc tên file Windows được kiểm tra bằng test.

Các báo cáo tại `docs/history/` là lịch sử của gói nguồn hoặc bản sửa trước, không phải kết quả hiện tại.
