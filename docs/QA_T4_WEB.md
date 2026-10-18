# Kiểm thử bản T4 Web

## Đã chạy trên máy bàn giao (Linux, Python 3.13)

- **123 passed**: toàn bộ `tests/`, bao gồm 15 test mới về pipeline/CLI/GPU-policy; engine và giọng được giả lập trong test điều phối.
- CT2 **4.6.0**, ONNX Runtime **1.23.2 CPU**, Piper **1.8.0** được cài trong môi trường kiểm thử tách biệt. Đây không phải bằng chứng GPU inference.
- Test pipeline: dịch tiến lên trong lúc TTS bị chặn; job giữ active đến khi audio/mã hóa xong; bật/tắt tuần tự; hàng đợi có giới hạn; pause/stop không deadlock khi hàng đợi đầy; audio lỗi vẫn tiếp tục các chương khác.
- Test checkpoint: phục hồi queued/generating sau restart; tiếp tục audio thiếu/lỗi mà không dịch lại text hoàn tất.
- Test OOM: giảm batch, thử lại cùng đoạn, đủ output, không bỏ nguồn; giảm budget inference nội bộ đến 1.
- Test xuất/gộp: chỉ xuất toàn bộ truyện một lần; chỉ gộp một lần sau khi audio xong; lỗi gộp đánh dấu lỗi job; giữ đúng phạm vi chương.
- Test Piper strict: giả lập session chỉ có CPU provider, xác nhận báo lỗi và không thử fallback CPU khi yêu cầu CUDA.
- Những kiểm thử FFmpeg hiện có chạy FFmpeg/ffprobe thật với audio mẫu/WAV tổng hợp; không dùng model giọng thật.
- API: nhập TXT/EPUB, xuất TXT/EPUB, validation/guard, phạm vi chương, tên thư mục, reset/xóa, TTS HTTP với giọng giả lập.
- `python -m compileall -q .`: thành công.
- `node --check web/static/app.js`: thành công.
- Notebook: mọi code cell parse bằng Python AST; regex tunnel khớp URL mẫu; không còn clone/pull code gốc.
- Benchmark CLI `--help` khởi động không cần Gradio; sweep `--dry-run` sinh 4 cấu hình beam/batch. Chưa chạy benchmark suy luận.
- Chromium/Playwright local: Web thật, recommendation phần cứng **giả lập** T4 batch 96; UI clamp thành 64, payload có công tắc pipeline, beam mặc định 2 và auto-group mặc định tắt.
- Nhập TXT 2 chương qua HTTP, reload UI, kiểm tra `/api/tts/status`, không lỗi JavaScript, không trùng DOM id.
- Đã chụp và xem UI desktop/mobile; sửa header mobile, kiểm tra không tràn ngang ở viewport 390px.
- Đã rà soát tên/mã/tham chiếu cấu hình bot: không còn trong mã chạy, Docker, migration hay hướng dẫn hiện tại.

## Chưa chạy / không cam kết

- Không có T4/CUDA trên máy kiểm thử: **chưa chạy notebook đầy đủ trên Colab**, chưa chạy CT2/Piper inference GPU, chưa đo tốc độ thực tế hoặc tăng tốc phần trăm.
- Bước cài runtime Colab và script `check_gpu.py` phải được chạy trên Colab; script kiểm tra thật sẽ báo lỗi nếu CT2/Piper không dùng CUDA hoặc inference thất bại.
- ORT GPU **1.23.2** và CT2 **4.6.0** được cố định cho nhánh CUDA 12/cuDNN 9; không bảo đảm runtime Colab tương lai không thay đổi. Cần kiểm tra driver và log nếu Colab cập nhật.
- Chưa build/run Docker; Docker mặc định CPU, không tự cấu hình GPU passthrough.
- Chưa mở tunnel Cloudflare thật, chưa xác thực/upload Google Drive, không gửi nội dung truyện ra ngoài.
- Chưa stress test cả bộ truyện lớn, mất nguồn đột ngột, Windows/macOS hoặc nhiều người dùng đồng thời.
- Không bảo đảm pipeline luôn nhanh hơn tuần tự khi CT2 và Piper cùng tranh một T4. So sánh cùng dữ liệu/giọng/beam trước khi chọn cấu hình.
- Model dịch và giọng không được nhúng vào ZIP; tải khi chạy. Kiểm tra giấy phép model/giọng và biên tập nội dung trước khi xuất bản.

Tài liệu kiểm thử có sẵn từ bản nguồn được đưa vào `docs/history/` để phân biệt với kết quả bản này.
