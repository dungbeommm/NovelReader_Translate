# Báo cáo kiểm thử — 2026-10-17

## Kết quả đã xác minh

1. **59/59 test đạt**: 9 test tích hợp mới và 50 test của bộ dịch gốc.
   - Hàng đợi SQLite, khôi phục trạng thái sau restart, giới hạn số tác vụ.
   - Kiểm tra chủ sở hữu, ID an toàn, từ chối user ngoài allowlist và chat nhóm.
   - Tiếp tục dịch từ checkpoint, không nạp lại engine nếu sách đã dịch xong.
   - Không cho `/retry` đua với tác vụ đang hủy; không vượt giới hạn hàng đợi khi retry.
   - Pipeline audio và chia MP3 bằng FFmpeg thật (voice/HTTP giả trong unit test).
   - HTTP TTS validation và WAV → MP3 thật (voice giả trong unit test).
   - Gửi Telegram giả lập, checkpoint danh sách file đã gửi; lỗi subprocess chuyển tác vụ sang failed.
   - Các kiểm thử gốc về API, file/EPUB, glossary, đoạn/chương và job.

2. **Model dịch thật**: tải `ngocdang83/HachimiMT-60-QT`, chạy CPU CTranslate2.
   - Nguồn: `你好，世界。今天天气很好。`
   - Kết quả: `Chào ngươi, thế giới. Hôm nay thời tiết rất tốt.`
   - Đây là smoke test hoạt động, không đánh giá chất lượng toàn bộ tiểu thuyết. Văn phong QT có thể không phù hợp truyện hiện đại.

3. **Model giọng thật**: Piper 1.2.0 đọc bằng `ngochuyennew.onnx` từ ZIP gốc, chuyển MP3 bằng FFmpeg. Audio mẫu câu dịch dài khoảng 3,27 giây.

4. **End-to-end thật, không dùng Telegram**: chạy `runner.py` với một TXT tự tạo gồm một chương tiếng Trung, dịch bằng engine thật, gọi HTTP TTS nội bộ dùng giọng thật, rồi chia MP3 bằng FFmpeg thật.
   - Xuất `ban_dich.txt`: 210 bytes.
   - Xuất `ban_dich.epub`: 2.469 bytes.
   - Xuất `chuong_00001_000.mp3`: 56.155 bytes.
   - Không gửi truyện người dùng lên Hugging Face Space, Telegram, Internet Archive hoặc GitHub trong các smoke test này. Chỉ tải model công khai từ Hugging Face.

5. Kiểm tra cú pháp 52 file Python theo grammar Python 3.11 cho bot/dịch và 3.10 cho TTS: không lỗi.

## Môi trường kiểm thử và giới hạn

- Host Linux x86-64; Python 3.13 cho test suite/dịch. Bộ dịch thật dùng CTranslate2 4.8.3, SentencePiece 0.2.2, huggingface-hub 2.2.0.
- Host chỉ có Python 3.9 và 3.13. Do đó smoke test giọng/HTTP TTS chạy bằng **Python 3.9**, Piper 1.2.0, NumPy 1.26.4, ONNX Runtime **1.19.2**. Cấu hình triển khai TTS dùng **Python 3.10 / ONNX Runtime 1.20.1**; không coi smoke test host là chứng nhận image đó.
- **Chưa build/chạy Docker Compose**: môi trường kiểm thử không có Docker Engine. Cấu hình image, volume, quyền ghi và restart cần xác minh trên VPS đích.
- **Chưa kết nối Telegram thật**: chưa có bot token/user ID. Các tương tác Telegram chỉ được kiểm thử bằng mock. Cần thử nhận file, `/status`, `/cancel`, `/retry`, trả TXT/EPUB/MP3 bằng bot thật sau triển khai.
- Chưa có VPS được cấp quyền nên **chưa triển khai online**, chưa đo uptime, hiệu năng truyện dài, độ bền khi hết đĩa hoặc tải nhiều người.
- Chưa đánh giá giấy phép/phân phối lại model giọng nói; dùng model từ tệp người dùng cung cấp. Kiểm tra quyền sử dụng trước khi chia sẻ/chạy dịch vụ thương mại.

## Sửa lỗi phát hiện trong bản nguồn

- `translator/main.py` từng mount UI Gradio nhưng `requirements.txt` không khai báo `gradio`, khiến web không khởi động. Bản này giữ UI HTML/CSS/JS gốc tại `/` và `/classic`, bỏ mount Gradio `/gradio` cùng quyền phục vụ thư mục tạm rộng. Các file nguồn Gradio vẫn được giữ để tham khảo, không được khởi chạy.
- Tách môi trường dịch/Piper thành hai service thay vì ép dùng một Python environment.

## Kiểm tra chấp nhận sau triển khai

1. Điền `.env` riêng trên server, không gửi token qua chat.
2. `docker compose up -d --build`; kiểm tra `docker compose ps`, `docker compose logs`.
3. Tài khoản được phép: gửi một TXT Trung ngắn bằng `/full`; nhận TXT, EPUB và audio nghe được.
4. Tài khoản không được phép và chat nhóm: không được tạo job/đọc tiến độ người khác.
5. Truyện dài hơn: thử `/cancel`, đợi worker dừng, `/retry`; thử restart container và kiểm tra checkpoint.
6. Thử `/xoa`, xác nhận dung lượng và file được xóa trên server.
7. Không mở port TTS/web công khai; web chỉ dùng localhost hoặc SSH tunnel.
