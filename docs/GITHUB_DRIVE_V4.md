# GitHub + Google Drive — phiên bản 4

## Chức năng
- Bước 1 tự tải ZIP từ URL raw GitHub của người dùng, không dùng files.upload().
- Xác nhận đã tải được ZIP GitHub thực tế: 133 tệp, đúng thư mục NovelReader_T4_Web.
- Giới hạn kích thước/số tệp, chặn zip traversal/symlink; không ghi đè dữ liệu, model, output, .env.
- Notebook có overlay nguồn v4, nên không cần cập nhật ZIP GitHub ngay mới chạy được.
- Chọn nơi xuất trên thanh công cụ: Google Drive hoặc Tải về máy. Colab mặc định Drive.
- Chỉ khi bấm xuất mới tạo yêu cầu quyền; notebook xử lý bằng google.colab.drive.mount.
- Quyền được cấp trong tab Colab, không cần Client ID/Secret hay token trong Web.
- TXT/EPUB dùng snapshot database. Audio ZIP tạo trên đĩa, không gom toàn bộ ZIP vào RAM.
- Bỏ qua file audio đang ghi trong thư mục ẩn; giữ bản gốc; tên đích duy nhất; chép tạm rồi đổi tên.
- Tối đa 2 tác vụ xuất backend; timeout cấp quyền 5 phút. Sau khi từ chối/lỗi có thể bấm xuất lại.
- Yêu cầu của phiên cũ không tự gọi cấp quyền trong phiên mới.
- Link Web chứa secret ngẫu nhiên theo phiên, chuyển thành cookie HttpOnly và xóa query sau khi mở.
- API/static/WebSocket bị chặn khi chưa có quyền phiên; không lưu secret trong ZIP hoặc bản sao lưu.

## Đã kiểm thử
- **143 passed** trên Linux/Python 3.13, CPU. 12 bài mới về Drive/bootstrap/quyền truy cập.
- Bootstrap notebook chạy với HTTP response ZIP giả lập: đúng URL GitHub, không gọi upload(),
  có overlay xuất Drive, không ghi đè checkpoint và không nạp .env từ archive.
- Test TXT/EPUB/audio ZIP -> worker -> callback mount giả lập -> thư mục đích trên ổ cục bộ.
- Test từ chối quyền, không có audio, mã tác vụ traversal, capability API, quyền Web/API/WebSocket,
  HttpOnly cookie, xóa token khỏi query và không tự xin quyền từ tác vụ phiên trước.
- Chromium local E2E: bấm 3 nút xuất và xác nhận tạo đủ TXT/EPUB/ZIP ở mount giả lập;
  chọn Tải về máy vẫn nhận download; không lỗi JavaScript, không tràn ngang ở 390px.
- Đã xem screenshot desktop/mobile. Kiểm tra cú pháp Python/JS/notebook thành công.

## Chưa xác minh
- Chưa chạy Colab Google authorization/Drive mount thật, chưa upload lên tài khoản Drive thật.
- Chưa chạy T4 inference hoặc đo tốc độ phiên bản này. Các callback mount/khuyến nghị GPU trong test được giả lập.
- Chưa mở Cloudflare thật; link HTTPS/cookie reverse-proxy cần được xác nhận trong runtime của người dùng.
- Chưa đẩy ZIP/notebook lên GitHub; chỉ tải nguồn công khai từ URL người dùng cung cấp.
- Drive mount là quyền rộng của Colab, không phải OAuth scope chỉ dành riêng thư mục NovelReader_Exports.
- Không đóng cell 5 trong lúc đang chép file lớn. Nếu runtime ngắt bất ngờ, bản gốc vẫn còn trong phiên,
  nhưng `/content` sẽ mất nếu runtime bị xóa; phải tải/sao lưu kết quả kịp thời.
