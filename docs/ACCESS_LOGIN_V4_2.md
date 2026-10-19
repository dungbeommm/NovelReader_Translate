# Bản v4.2: sửa luồng đăng nhập

Bản v4.1 chỉ sửa mã hóa thông báo, chưa cung cấp cách phục hồi đăng nhập. Bản này:

- Địa chỉ gốc khi chưa có quyền hiển thị biểu mẫu nhập mã, thay vì trang chặn 403. API và WebSocket vẫn từ chối nếu chưa đăng nhập.
- Notebook in mã truy cập bên dưới nút mở Web. Có thể dán mã vào biểu mẫu nếu link thiếu token hoặc không nhận cookie.
- Đổi cookie HttpOnly từ SameSite Strict sang Lax cho điều hướng từ Colab. Không khẳng định đây là nguyên nhân duy nhất trên máy người dùng.
- Token đúng được đổi thành cookie; token không được lặp lại trong trang đăng nhập hay Location chuyển hướng.
- Nếu cookie bị chặn, hiện hướng dẫn mở tab riêng và cho phép cookie; không tự chuyển hướng lặp vô hạn.
- Mã cũ/sai, Unicode sai, origin khác và body quá lớn bị từ chối. Dữ liệu Drive không mở công khai.

## Sử dụng
Dừng ô Web cũ sau khi tác vụ hoàn tất; mở notebook v4.2, chạy các bước cần thiết và mở link mới. Nếu hiện biểu mẫu, sao chép mã được in trong cùng ô Web đang chạy và dán vào biểu mẫu. Không dùng mã của phiên trước, không chia sẻ mã.

## Kiểm thử
148 kiểm thử CPU đạt. Trình duyệt Chromium cục bộ thử URL thiếu mã, mã sai/đúng, điều hướng từ origin Colab giả lập sang app, cookie Lax HttpOnly, API/WebSocket được bảo vệ. Kiểm tra xuất TXT/EPUB/audio bằng Drive mount giả lập. Không có T4, Cloudflare thật hoặc Google OAuth thật trong môi trường kiểm thử.
