# NovelReader

NovelReader nhập truyện TXT/EPUB, dịch sang tiếng Việt và tạo audio bằng Piper hoặc VieNeu. Giao diện web chạy trên FastAPI. `NovelReader_Molab.py` cung cấp giao diện ngay trong notebook Molab và dùng cùng backend.

## Chạy trên Molab

1. Mở `NovelReader_Molab.py` trong Molab.
2. Chọn bộ đọc và giọng đọc, sau đó chạy lần lượt các cell từ trên xuống.
3. Chờ cài thư viện và chuẩn bị giọng hoàn tất. Notebook khởi chạy backend tại `127.0.0.1:8000`.
4. Nạp truyện, dịch, theo dõi tiến độ và tải kết quả ngay trong notebook.

Nếu Molab đã mở cả repository, notebook dùng trực tiếp mã nguồn đó. Nếu chỉ tải notebook lên, nó lấy mã nguồn từ GitHub vào thư mục phiên. CPU được dùng khi không tìm thấy NVIDIA GPU. Piper là lựa chọn nhẹ; VieNeu tải các thành phần inference và model cần thiết, nên bước chuẩn bị sẽ lâu hơn.

Giữ phiên Molab hoạt động trong khi dùng ứng dụng. Khi phiên runtime kết thúc, server và cache model trong runtime cũng dừng. Trước khi kết thúc phiên, tải các tệp kết quả cần giữ về máy.

Nếu dùng giao diện web và Hugging Face Bucket, chỉ tải lên nội dung có thể chia sẻ công khai vì bucket mặc định là công khai.

## Chạy cục bộ

Cài thư viện từ `requirements.txt`, rồi chạy:

```powershell
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Mở `http://127.0.0.1:8000`. Model dịch và giọng đọc có thể tải/chọn từ giao diện.
