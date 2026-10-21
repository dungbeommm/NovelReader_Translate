# Cập nhật v4.4 — GPU, Pixeldrain & checkpoint

## Dùng bản cập nhật

1. Giải nén toàn bộ gói mới; không chép đè thư mục `data`, `models`, `output_text`, `output_audio` đang có. Sao lưu trước khi cập nhật.
2. Cài các thư viện trong `requirements.txt`, sau đó chạy lại backend. Không cần tạo lại database.
3. Molab: mở `NovelReader_Molab.py`. File này có overlay mã nguồn v4.4 tích hợp, nên khi chạy độc lập không bị lùi về mã ZIP cũ trên GitHub. Hoặc chạy ngay từ thư mục mã nguồn đã giải nén.
4. Colab/Kaggle: dùng notebook đi kèm; bootstrap giữ database, output, model và không nạp `.env` từ ZIP. Gói `NovelReader_GPU_notebook.zip` cũng được xây lại từ nguồn mới.

## GPU và audio

- Batch dịch Web/API: **1–1024 segment/lượt**, mặc định giữ nguyên; đây **không phải** số chương hay độ dài token.
- UI có **1–8 chương audio đồng thời**, hàng chờ **1–32 chương**. Số chương chạy chỉ có tác dụng khi bật tạo audio và pipeline.
- Mỗi worker dùng phiên Piper/ONNX riêng, tránh khóa toàn bộ quá trình tổng hợp. Giải phóng các phiên worker khi job kết thúc để không giữ VRAM thừa.
- Tắt pipeline: chạy tuần tự một chương. Dừng/tạm dừng vẫn chờ lời gọi đang chạy; file audio chỉ xuất hiện khi đã chuyển đổi xong.
- Thử batch **96 → 256 → 512 → 1024**, audio **1 → 2 → 4** trên cùng vài chương rồi so thời gian. Không nên đặt mọi thông số tối đa ngay.
- Giữ cơ chế tự giảm batch dịch khi OOM. OOM audio được báo ở từng chương; giảm số worker rồi tiếp tục để tạo lại audio thiếu/lỗi.
- Batch nội bộ CT2 và batch Web là hai tầng khác nhau. Giữ các mặc định CT2 an toàn, không tự ép VRAM đầy. Tăng worker nhân số phiên model và có thể làm giảm tốc nếu tranh GPU/CPU.

## Molab: đầy đủ giọng đọc

- Có sẵn danh mục JSON **22 giọng** tại `tts/voices_catalog.json`, UI vẫn hiện danh mục khi runtime chưa có model.
- Mặc định Molab tải **toàn bộ config `.onnx.json` + manifest**, chỉ tải ONNX của giọng chọn; giọng khác tải khi sử dụng.
- Chọn **Tải toàn bộ JSON + tất cả model ONNX** ở đầu Molab nếu muốn cài sẵn mọi giọng. Dữ liệu model lớn, cần đủ ổ đĩa và mạng.
- Script cập nhật thêm thư mục giọng từ GitHub khi truy cập được, có fallback danh mục đi kèm; JSON được kiểm tra cấu trúc Piper, file tải và manifest ghi nguyên tử.
- Nếu một giọng tải lỗi, log/exit code báo lỗi; danh mục không bị rút gọn, có thể chạy lại.

```bash
python scripts/download_voices.py --catalog-only
python scripts/download_voices.py --all
python scripts/download_voices.py --voice ngochuyennew
```

## Pixeldrain

Vào **Cài đặt → Lưu trữ Đám mây & Pixeldrain**:

1. Nhập API key → **Lưu Key** → **Kiểm tra kết nối**. “Đã cấu hình” chưa đồng nghĩa đã xác thực với dịch vụ.
2. Key lưu tại backend trong `NOVEL_DATA/private/pixeldrain.json` với quyền `0600`, không trả lại cho trình duyệt. Key trình duyệt từ bản cũ được chuyển một lần rồi xóa khỏi localStorage.
3. Ưu tiên key theo thứ tự: key gửi riêng trong request tương thích cũ → `PIXELDRAIN_API_KEY` → file backend. Xóa key đã lưu không xóa được biến môi trường; cần chỉnh runtime nếu muốn bỏ key môi trường.
4. Chọn **Lưu: Pixeldrain** ở thanh trên để xuất TXT/EPUB/audio. ZIP audio và upload file lớn dùng file trên đĩa, không đọc toàn bộ vào RAM phía server.
5. Không tự upload lại khi timeout để tránh tạo file trùng. Kiểm tra tài khoản trước khi thử lại. Giới hạn/tốc độ/thời gian lưu phụ thuộc chính sách tài khoản Pixeldrain.

**Lưu ý:** Ai có link Pixeldrain có thể tải dữ liệu. Không dùng để sao lưu nội dung bí mật nếu chưa chấp nhận cách chia sẻ này.

## Bảng tạm và checkpoint

“Bảng tạm” ở bản cập nhật này nghĩa là **cấu hình đang nhập trong giao diện**: model, glossary, batch, giọng, tốc độ, phạm vi chương, audio và tùy chọn cloud. Không đọc clipboard hệ điều hành, không lưu clipboard history.

- **Lưu bảng tạm / Nạp bảng tạm** lưu và nạp các giá trị cấu hình; không tự chạy job.
- **Tải checkpoint ZIP** hoặc **Lưu Pixeldrain** tự lưu bảng tạm hiện tại trước khi tạo bản sao.
- Checkpoint gồm SQLite snapshot (nguồn truyện, segment/plan, bản dịch, trạng thái), output text và bảng tạm đã lưu. Tùy chọn kèm audio; mặc định không kèm để nhẹ hơn.
- **Không** sao lưu `.env`, API key, token Drive, log hay model. Sau khi đổi runtime, nhập lại key hoặc thiết lập biến môi trường.
- Bật tự lưu cloud **trước khi bắt đầu job** để upload khi hoàn tất/dừng có kiểm soát, bao gồm job có lỗi. Đây **không phải** backup định kỳ; runtime bị tắt đột ngột trước lúc upload vẫn có thể mất thay đổi chưa sao lưu cloud. SQLite cục bộ vẫn checkpoint từng segment như cũ.
- Khôi phục thủ công: dừng job, chọn ZIP hoặc nhập link/ID Pixeldrain → xác nhận thay truyện hiện tại → **Nạp bảng tạm** → kiểm tra phạm vi/reset rồi tiếp tục.
- API kiểm tra ZIP, đường dẫn, SHA256 và dữ liệu trước khi thay database. Database thay trong một transaction; output cũ được giữ, output khôi phục dùng thư mục riêng. Không thực thi schema SQL từ file nhập.
- Trạng thái đang dịch trở về pending, giữ segment đã làm; audio queued/generating hoặc thiếu file trở về none để tạo lại.
- Giới hạn khôi phục: **2 GB/ZIP**, tối đa **8 GB sau giải nén**. Nếu lớn, sao lưu không kèm audio rồi xuất audio riêng.
- Chỉ hỗ trợ ZIP checkpoint v1 tạo từ mục mới. ZIP backup cũ không có manifest không tự động nhập để tránh làm hỏng dữ liệu.
- Nút sao lưu Molab dùng API checkpoint mới; giữ Web server chạy nhưng dừng job. Cloud lưu thất bại không xóa SQLite/output cục bộ.

## Google Drive

- Lưu cài đặt giao diện không còn làm rỗng access/refresh token đang có.
- API trạng thái/cài đặt không trả client secret, access token hay refresh token. UI dùng cờ trạng thái, secret để trống nghĩa là giữ nguyên.
- File cấu hình ghi nguyên tử với quyền `0600`. Giữ nguyên các cách kết nối Drive hiện tại, không mở rộng scope.

## Kiểm thử và giới hạn xác minh

- Chạy kiểm thử CPU/mock, cú pháp JS/Python và `marimo check`.
- Có kiểm thử batch 1024, cấu hình worker, tổng hợp chạy chồng nhau, lưu key, upload streaming, checkpoint có/không audio, khôi phục segment, ZIP lỗi/path traversal và giữ token Drive.
- Xem giao diện thực trên Chromium tại 1440px và 390px; giữ header, sidebar, mục lục và reader song song.
- **Chưa benchmark trên GPU thật; chưa xác minh upload/download bằng tài khoản Pixeldrain hoặc Google OAuth thật; chưa chạy toàn bộ notebook trong Molab/Colab/Kaggle thực tế.** Không cam kết GPU 100% hay tăng tốc một tỷ lệ cụ thể.
