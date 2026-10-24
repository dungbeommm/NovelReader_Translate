# NovelReader

NovelReader nhập truyện TXT/EPUB, dịch sang tiếng Việt và tạo audio bằng Piper hoặc VieNeu. Giao diện web chạy trên FastAPI. `NovelReader_Molab.py` cung cấp giao diện ngay trong notebook Molab và dùng cùng backend.

## Chạy trên Molab

1. Mở `NovelReader_Molab.py` trong Molab.
2. Chọn bộ đọc và giọng đọc, sau đó chạy lần lượt các cell từ trên xuống.
3. Chờ cài thư viện và chuẩn bị giọng hoàn tất. Notebook khởi chạy backend tại `127.0.0.1:8000`.
4. Nạp truyện, dịch, theo dõi tiến độ và tải kết quả ngay trong notebook.

### Public URL từ Molab

Notebook chỉ sử dụng Cloudflare Tunnel. Tunnel không tự bật khi mở notebook;
chọn chế độ Cloudflare sau khi backend đã sẵn sàng. URL quick tunnel đổi sau
mỗi phiên; mọi request vẫn cần `access_token` riêng của phiên.

Muốn có URL cố định, tạo Cloudflare Tunnel kiểu **remotely-managed**, trỏ hostname của bạn tới `http://127.0.0.1:8000`, rồi đặt secret trong Molab trước khi chạy notebook:

```python
import os
os.environ["NOVEL_PUBLIC_TUNNEL"] = "named"
os.environ["NOVEL_PUBLIC_HOSTNAME"] = "novel.example.com"
os.environ["CLOUDFLARE_TUNNEL_TOKEN"] = "<Cloudflare tunnel token>"
```

Không ghi tunnel token hoặc Hugging Face token vào notebook đã chia sẻ công khai. Molab vẫn là nơi chạy backend, model, dữ liệu tạm và tunnel client; Cloudflare chỉ chuyển tiếp HTTP.

Nếu Molab đã mở cả repository, notebook dùng trực tiếp mã nguồn đó. Nếu chỉ
tải notebook lên, đặt `NOVELREADER_SOURCE_BUNDLE` tới source bundle đã xác minh;
notebook không tải và thực thi một branch GitHub tùy ý. CPU được dùng khi không
tìm thấy NVIDIA GPU. Piper là lựa chọn nhẹ; VieNeu tải các thành phần
inference và model cần thiết, nên bước chuẩn bị sẽ lâu hơn.

Giữ phiên Molab hoạt động trong khi dùng ứng dụng. Khi phiên runtime kết thúc, server và cache model trong runtime cũng dừng. Trước khi kết thúc phiên, tải các tệp kết quả cần giữ về máy.

## Tự lưu vào Hugging Face Bucket

Vào **Cài đặt → Hugging Face**, nhập token có quyền ghi rồi bấm **Kết nối**.
Có thể đặt `HF_TOKEN`, `HF_USERNAME` và `HF_BUCKET_ID` trước khi khởi động,
hoặc dùng file private được trỏ bởi `NOVELREADER_PRIVATE_CONFIG`. Bucket phải
được chỉ định rõ; tên gợi ý là `novelreader-storage` dưới namespace cá nhân.

Khi có token, ứng dụng tự đồng bộ bản dịch TXT từng chương, TXT/EPUB toàn truyện, audio từng chương, audio gộp và checkpoint tiến độ. Các tệp đã có trước lúc kết nối cũng được xếp hàng. Trạng thái chờ hoặc lỗi hiện trong mục Hugging Face và bảng tải kết quả. Tải TXT/EPUB/audio về máy vẫn dùng được.

Bucket được tạo private khi API có quyền phù hợp. Token không ghi vào log,
frontend, checkpoint hay ZIP. Token nhập qua giao diện chỉ tồn tại trong phiên
backend; dùng secret store hoặc file private ngoài source để tự kết nối lại.

Checkpoint local dùng SQLite backup API và checksum. Khi đẩy remote, archive và
manifest được upload trước, sau đó mới cập nhật con trỏ `latest`.

Các adapter Google Drive/Pixeldrain trong source ZIP được giữ lại nhưng route
được tắt mặc định để giảm bề mặt truy cập. Bật `NOVEL_ENABLE_LEGACY_EXPORTS=1`
khi cần dùng chúng.

## Chạy cục bộ

Cài thư viện từ `requirements.txt`, rồi chạy:

```powershell
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Mở `http://127.0.0.1:8000`. Model dịch và giọng đọc có thể tải/chọn từ giao diện.
