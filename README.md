# NovelReader

NovelReader nhập truyện TXT/EPUB, dịch sang tiếng Việt và tạo audio bằng Piper hoặc VieNeu. Giao diện HTML của ứng dụng được phục vụ bởi FastAPI; `NovelReader_Molab.py` khởi động toàn bộ ứng dụng trong phiên Molab và hiển thị nút mở giao diện.

## Chạy trên Molab

1. Mở `NovelReader_Molab.py` trong Molab.
2. Chọn bộ đọc và giọng đọc, sau đó chạy lần lượt các cell từ trên xuống.
3. Chờ cài thư viện và chuẩn bị giọng hoàn tất. Cell cuối khởi chạy server và tạo Cloudflare Quick Tunnel.
4. Bấm **Mở giao diện NovelReader** trong thẻ HTML được hiển thị.

Nếu Molab đã mở cả repository, notebook dùng trực tiếp mã nguồn đó. Nếu chỉ tải notebook lên, nó lấy mã nguồn từ GitHub vào thư mục phiên. CPU được dùng khi không tìm thấy NVIDIA GPU. Piper là lựa chọn nhẹ; VieNeu tải các thành phần inference và model cần thiết, nên bước chuẩn bị sẽ lâu hơn.

Giữ phiên Molab hoạt động trong khi dùng ứng dụng. Khi phiên runtime kết thúc, server, tunnel và cache model trong runtime cũng dừng. Lưu tiến độ qua **Cài đặt → Sao lưu & Khôi phục** trong giao diện trước khi kết thúc phiên. Có thể khôi phục checkpoint ở phiên sau.

Liên kết mở ứng dụng chứa access token của phiên. Chỉ chia sẻ với người được phép truy cập. Đích Hugging Face Bucket mặc định là công khai; chỉ tải lên nội dung có thể chia sẻ công khai.

## Chạy cục bộ

Cài thư viện từ `requirements.txt`, rồi chạy:

```powershell
python main.py
```

Mở `http://127.0.0.1:8000`. Model dịch và giọng đọc có thể tải/chọn từ giao diện.
