# Bản vá v4.1: thông báo truy cập

- Khai báo Content-Type text/plain; charset=utf-8 để trình duyệt đọc đúng tiếng Việt.
- Thêm hướng dẫn mở lại link riêng trong Colab, xử lý link phiên cũ và trình duyệt khác.
- Vẫn giữ xác thực: không bỏ bảo vệ API, WebSocket hoặc Drive.
- Mã 403 khi thiếu quyền là hành vi đúng, không phải lỗi GPU.

## Cách mở ứng dụng
Quay về ô Web đang chạy trong Colab và bấm **Mở NovelReader**. Không dùng địa chỉ Cloudflare bị bỏ phần access_token. Sau khi khởi động lại Web, sử dụng link mới. Không chia sẻ link riêng.

Chưa kiểm thử trên Colab/T4 thật hoặc Google OAuth thật trong môi trường này.
