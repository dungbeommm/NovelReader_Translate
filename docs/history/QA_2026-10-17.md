# Kiểm thử bàn giao — 2026-10-17

## Đã chạy

- Môi trường thực thi: Linux x86_64, Python 3.13.
- Python unit/integration: **38 passed** (`python -m pytest -q`).
- Syntax: `python -m compileall -q .`, `node --check static/app.js`.
- Download + nạp **model thật CTranslate2 INT8 CPU**; không dùng mock cho smoke.
- Space thật: `view_api()` thành công và dịch một câu mẫu kèm glossary thành công.
- Chromium/Playwright local end-to-end:
  - mở UI, WebSocket kết nối thật;
  - upload TXT fixture 2 chương, nhập glossary, bắt đầu Local;
  - đợi 2/2 chương, kiểm tra Lâm Vũ và Huyền Kiếm Tông ở bản dịch;
  - xuất TXT và EPUB thành công;
  - nhập glossary sai, xác minh thông báo lỗi rõ;
  - không có JS pageerror, không tràn ngang ở 390px.
- Đã render và xem ảnh riêng lẻ: empty desktop/mobile, dịch xong desktop/mobile,
  và thông báo lỗi; bố cục/đoạn hai cột không chồng nhau.
- Viewport desktop 1440×1080; mobile 390×844, screenshot toàn trang.
- Đã đọc EPUB xuất lại bằng ebooklib và kiểm tra có metadata vi/nav/mimetype.
- Pause/resume/stop/khôi phục checkpoint và lỗi một chương không dừng chương kế
  được kiểm tra bằng fake engine có synchronization gate trong unit tests.
- Origin guard, header guard, upload lỗi, WS snapshot được integration test.

## Không khẳng định đã làm

- Chưa kiểm thử bằng Windows/macOS thật; hướng dẫn và launcher được cung cấp,
  nhưng máy bàn giao hiện tại là Linux.
- Chưa benchmark toàn bộ truyện 2847 chương hay đo chất lượng dịch bằng bộ chuẩn.
- Chưa chạy EPUB DRM/ảnh/footnote phức tạp; chỉ hỗ trợ text reflow mới, không giữ
  bố cục gốc. EPUB spine/export được test bằng fixture sinh bằng ebooklib.
- Chưa stress test nhiều người dùng hoặc nhiều tiến trình; không hỗ trợ mô hình đó.
- Chưa kiểm thử button pause trên dịch vụ Space khi đang outage; đã test logic
  worker bằng fake và timeout adapter riêng.
- Không bảo đảm Space sẽ tiếp tục giữ API/khả dụng sau ngày kiểm tra.
- Không có SPEC JSON đầu vào; chỉ triển khai mô tả giao diện bằng chữ.

## Lưu ý chất lượng

Đại từ/tên riêng là đầu ra ML, không phải bảo chứng ngữ nghĩa. Glossary fallback
có thể giảm độ tự nhiên khi phải dịch tách các khoảng nguồn. Cần biên tập trước
khi xuất bản. Lỗi Unicode từ placeholder đã được thêm regression test.
