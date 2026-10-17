# Bản sửa: dịch theo dải và tự gộp audio

## Sử dụng

- Dừng app trước khi cập nhật. Sao lưu thư mục hiện tại.
- Dùng mã nguồn trong gói này, giữ lại `.venv`, model dịch, giọng đọc, dữ liệu SQLite và output của máy bạn.
- Không xóa thư mục cũ trước khi sao lưu. Gói sửa không kèm dữ liệu thử nghiệm, database hoặc model.
- Khởi động lại bằng `start_web.bat`, tải mới trang bằng Ctrl+F5.
- Cách dùng và quy tắc nhóm thiếu chương có trong README.md.

## Nguyên nhân và thay đổi

- Một đầu dải trống hoặc danh sách chọn rỗng có thể bị hiểu thành toàn bộ truyện. Frontend, API và Job đều chặn phạm vi không hợp lệ.
- Payload danh sách chọn có thể mang theo dải cũ, khiến backend ưu tiên nhầm dải. Hai kiểu phạm vi giờ loại trừ nhau.
- Dịch dải trước đây phụ thuộc cờ audio chung. Dịch dải giờ luôn tạo audio đúng chương trong dải.
- Job dịch dải gọi tự gộp trên toàn bộ audio. Giờ tự gộp giới hạn theo ID mục tiêu của job; nút gộp thủ công mới quét toàn bộ audio có sẵn.
- Cách chia cũ bỏ chương thiếu rồi chia lại danh sách, làm lệch mốc nhóm và gộp cả nhóm chưa đủ. Giờ dùng các mốc cố định, chỉ gộp nhóm đủ N chương có audio.
- Luồng gộp nền trước đây có thể chồng nhau và gộp lặp lúc kết thúc. Giờ gộp tuần tự có khóa, lưu fingerprint nguồn để tái sử dụng nhóm không thay đổi; không gộp thêm lần cuối job.
- Cấu hình nhóm lưu trước đó chỉ được khôi phục nếu tồn tại control modal không có trong HTML. Đã sửa để khôi phục trực tiếp các control thực tế.
- Bỏ các nút thừa trong Mục lục, giữ hai thao tác chính. Không bỏ API cũ hay các chức năng khác của app.
- Lỗi TTS và gộp audio được báo riêng; job không còn báo sẵn sàng như thành công khi audio bị lỗi.

## Các file thay đổi so với ZIP gốc

- `translator/static/index.html`
- `translator/static/app.js`
- `translator/static/style.css`
- `translator/app/jobs.py`
- `translator/app/audio_service.py`
- `translator/main.py`
- `README.md`
- Mới: `translator/tests/test_range_audio_workflow.py`, tài liệu này và ảnh giao diện sửa.

## Kiểm thử

- 30/30 bài hồi quy mới đạt: dải 1–5, không đụng chương ngoài dải, dải thiếu/ngược/rỗng, phạm vi ID xung đột, nhóm 50, audio thiếu, cache, lỗi TTS/gộp, API gộp không gọi dịch/TTS.
- Ghép WAV và MP3 bằng FFmpeg thật đạt; kiểm tra số frame WAV và codec/thời lượng MP3 bằng ffprobe.
- Kiểm tra cú pháp JavaScript và biên dịch Python đạt.
- Kiểm tra giao diện bằng Chromium/Playwright ở viewport 1366×1000 và 390×844: hai nút chính, payload chính xác, audio bắt buộc khi dịch dải, đồng bộ/khôi phục nhóm, chặn dữ liệu nhập sai; không có lỗi JavaScript.
- Bộ test toàn dự án: 79 đạt, 1 lỗi có sẵn ở `test_jobs.py::test_job_resume`. Test này kỳ vọng đổi glossary phải ném ValueError nhưng mã gốc không thực hiện điều đó. Đã chạy đối chiếu mã nguyên bản và xác nhận cùng lỗi; không sửa hành vi ngoài phạm vi để ép test cũ đạt.
- Chưa chạy model dịch và Piper TTS thật vì ZIP gốc không có trọng số model/giọng `.onnx`. Phần điều phối dịch/TTS được kiểm tra bằng fake engine/TTS; không phải đánh giá chất lượng dịch hay giọng đọc.

Chạy test hồi quy từ thư mục `tool/` sau khi cài phụ thuộc dự án và pytest/httpx:

```sh
PYTHONPATH=translator python -m pytest translator/tests/test_range_audio_workflow.py -q
```

Trên Windows CMD:

```bat
set PYTHONPATH=translator
python -m pytest translator/tests/test_range_audio_workflow.py -q
```

Máy chạy test cần FFmpeg và ffprobe trong PATH. Máy chạy app vẫn cần môi trường và model dịch/TTS như trước.
