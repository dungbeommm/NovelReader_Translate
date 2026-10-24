# NovelReader

NovelReader nhập truyện TXT/EPUB, dịch sang tiếng Việt và tạo audio bằng Piper hoặc VieNeu. Giao diện web chạy trên FastAPI. `NovelReader_Molab.py` cung cấp giao diện ngay trong notebook Molab và dùng cùng backend.

## Chạy trên Molab

1. Mở `NovelReader_Molab.py` trong Molab.
2. Chọn bộ đọc và giọng đọc, sau đó chạy lần lượt các cell từ trên xuống.
3. Chờ cài thư viện và chuẩn bị giọng hoàn tất. Notebook khởi chạy backend tại `127.0.0.1:8000`.
4. Nạp truyện, dịch, theo dõi tiến độ và tải kết quả ngay trong notebook.

### Public URL từ Molab

Notebook tự cài `cloudflared` vào runtime và tạo quick tunnel mặc định. URL này công khai nhưng đổi sau mỗi phiên; mọi request vẫn cần `access_token` riêng của phiên.

Muốn có URL cố định, tạo Cloudflare Tunnel kiểu **remotely-managed**, trỏ hostname của bạn tới `http://127.0.0.1:8000`, rồi đặt secret trong Molab trước khi chạy notebook:

```python
import os
os.environ["NOVEL_PUBLIC_TUNNEL"] = "named"
os.environ["NOVEL_PUBLIC_HOSTNAME"] = "novel.example.com"
os.environ["CLOUDFLARE_TUNNEL_TOKEN"] = "<Cloudflare tunnel token>"
```

Không ghi tunnel token hoặc Hugging Face token vào notebook đã chia sẻ công khai. Molab vẫn là nơi chạy backend, model, dữ liệu tạm và tunnel client; Cloudflare chỉ chuyển tiếp HTTP.

Nếu Molab đã mở cả repository, notebook dùng trực tiếp mã nguồn đó. Nếu chỉ tải notebook lên, nó lấy mã nguồn từ GitHub vào thư mục phiên. CPU được dùng khi không tìm thấy NVIDIA GPU. Piper là lựa chọn nhẹ; VieNeu tải các thành phần inference và model cần thiết, nên bước chuẩn bị sẽ lâu hơn.

Giữ phiên Molab hoạt động trong khi dùng ứng dụng. Khi phiên runtime kết thúc, server và cache model trong runtime cũng dừng. Trước khi kết thúc phiên, tải các tệp kết quả cần giữ về máy.

## Tự lưu vào Hugging Face Bucket

Vào **Cài đặt → Hugging Face**, nhập token có quyền ghi rồi bấm **Kết nối**. Có thể đặt `HF_TOKEN` hoặc `HUGGINGFACE_HUB_TOKEN` trước khi khởi động. Bucket mặc định là `uri410/NovelReader_Cloud_Audio`; đổi bằng `NOVEL_HF_BUCKET` nếu cần.

Khi có token, ứng dụng tự đồng bộ bản dịch TXT từng chương, TXT/EPUB toàn truyện, audio từng chương, audio gộp và checkpoint tiến độ. Các tệp đã có trước lúc kết nối cũng được xếp hàng. Trạng thái chờ hoặc lỗi hiện trong mục Hugging Face và bảng tải kết quả. Tải TXT/EPUB/audio về máy vẫn dùng được.

Bucket mặc định là công khai: chỉ đồng bộ nội dung bạn có quyền chia sẻ. Token nhập qua giao diện chỉ tồn tại trong phiên backend hiện tại; dùng biến môi trường để tự kết nối sau khi khởi động lại.

## Chạy cục bộ

Cài thư viện từ `requirements.txt`, rồi chạy:

```powershell
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Mở `http://127.0.0.1:8000`. Model dịch và giọng đọc có thể tải/chọn từ giao diện.
