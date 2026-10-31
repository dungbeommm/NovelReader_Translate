# Tích hợp tải truyện 番茄小说 bằng ID

**Phạm vi:** NovelReader vẫn là WebUI duy nhất. Giao diện của Rust Tomato-Novel-Downloader không cần mở; WebUI NovelReader nhận ID và hiển thị trạng thái tải ngay ở mục **Truyện nguồn**.

## Luồng xử lý

1. Nhập ID chữ số của truyện, bấm **Tải và dịch**.
2. FastAPI kiểm tra chưa có job dịch/tải đang chạy, xác thực yêu cầu thay thế truyện hiện tại.
3. `TomatoClient` gọi **Web API chính thức của tiến trình Rust** (`POST /api/jobs`). Không sử dụng CLI `--download` đã bị vô hiệu hóa.
4. Worker thăm dò `GET /api/jobs?id=...`; cập nhật tổng số chương, số chương đã lưu; tự chọn tên mặc định và định dạng TXT khi Rust yêu cầu lựa chọn.
5. Khi tải thành công, duyệt `/api/library`, chọn TXT/EPUB phù hợp với **ID/tên truyện** (hoặc một file mới duy nhất) rồi lấy dữ liệu qua `/download/...`.
6. Dùng chính `storage.files.parse_file` để tách chương, `runtime.store.replace` để nhập vào NovelReader.
7. Tự gọi `runtime.job.start` với cấu hình dịch/TTS đang chọn trên WebUI. Công việc tiếp theo thuộc về job manager của NovelReader (HachimiMT → Piper/VieNeu tùy cấu hình).
8. Xuất TXT/EPUB/MP3 và lưu Hugging Face bằng cơ chế hiện có; bật tùy chọn checkpoint cloud nếu muốn tự sao lưu trong quá trình dịch.

Không có mã nguồn riêng tư/API endpoint/token bên thứ ba của Tomato được sao chép vào NovelReader. Đáp ứng điều khoản của website nguồn và chỉ tải nội dung có quyền sử dụng.

## Cấu trúc

```
core/tomato_service.py      Worker HTTP, xác định TXT/EPUB, chuyển dữ liệu cho job dịch
web/routes/tomato.py       GET status; POST start/cancel
web/static/tomato.js       Form và polling trạng thái
web/static/tomato.css      CSS kế thừa màu WebUI hiện tại
web/static/index.html      Form ngay trong panel Truyện nguồn
server/api/__init__.py     Đăng ký router
core/runtime.py            Chặn nạp/xóa truyện khác khi đang tải
compose.tomato.yaml        Chạy thêm dịch vụ Rust nội bộ qua Docker Compose
```

## Cách chạy — Docker

Tomato không chạy được chỉ bằng JavaScript trong trình duyệt. Cần **tiến trình Rust** chạy cùng máy hoặc mạng riêng với FastAPI.

Tạo file `.env` ở máy triển khai (không commit):

```env
TOMATO_WEB_PASSWORD=<đặt-mật-khẩu-dài-ngẫu-nhiên>
HF_TOKEN=<token-riêng-nếu-cần>
```

Khởi chạy:

```bash
docker compose -f compose.yaml -f compose.tomato.yaml up -d --build
```

- NovelReader: `http://127.0.0.1:8000`
- Tomato: chỉ mở cổng nội bộ trong mạng Compose, không công khai `18423`.
- Thư viện tải gốc lưu trên Docker volume `tomato-data`.

**Khuyến nghị:** Trong cấu hình của Tomato Downloader, chọn định dạng xuất **TXT**, tắt TTS tiếng Trung vì NovelReader sẽ tự đọc tiếng Việt. Nếu Tomato được đặt ở định dạng PDF hoặc nhiều tệp TXT rời, việc nhập tự động sẽ báo lỗi rõ ràng.

## Cách chạy — Local / MoLab

Khởi chạy Tomato Downloader bản Rust riêng bằng:

```bash
TOMATO_WEB_ADDR=127.0.0.1:18423 TOMATO_WEB_PASSWORD=<mật-khẩu> tomato-novel-downloader --server
```

Đồng thời đặt biến môi trường của tiến trình NovelReader:

```env
TOMATO_WEB_URL=http://127.0.0.1:18423
TOMATO_WEB_PASSWORD=<cùng-mật-khẩu>
```

Nếu muốn sử dụng trong MoLab, phải cài được executable Linux tương ứng và giữ **hai tiến trình** hoạt động. Notebook dừng sẽ ngắt các job đang chạy; checkpoint của NovelReader và cơ chế tải tiếp của Rust hỗ trợ khởi động lại nhưng bản tích hợp hiện tại **chưa tự nối lại job tải sau khi tiến trình FastAPI khởi động lại**.

## API NovelReader

- `POST /api/tomato/start`: `{"book_id":"7318247498772674083","replace_existing":false,"config":{...}}`
- `GET /api/tomato/status`: `{"stage":"downloading","active":true,"saved":30,"total":100,...}`
- `POST /api/tomato/cancel`: hủy lượt tải đang chạy, không hủy các chương đã dịch từ job khác.

Bảo vệ API NovelReader như các endpoint hiện có: xác thực web và header `X-App-Request: novel-translator` đối với các lệnh POST. Không truyền URL do người dùng tự cung cấp vào backend Tomato (chỉ nhận ID chữ số); đích đến Rust được cấu hình từ biến môi trường máy chủ.

## Giới hạn được biết

- Phiên bản Rust từ repo chính có thể yêu cầu thư viện Official-API riêng; dùng bản binary/image được tác giả phát hành. Build `no-official-api` có hạn chế API.
- Cần một cấu hình Tomato hỗ trợ TXT hoặc EPUB; nếu chỉ xuất PDF/âm thanh, NovelReader không nạp được.
- Cần kiểm thử tích hợp thực tế với runtime Rust và một truyện có quyền tải. Các bài test đơn vị không kiểm chứng API bên ngoài hoặc chất lượng mô hình dịch.
- Không thay thế một truyện đang được dịch. Việc nhấn đồng ý thay truyện sẽ thay **bản ghi cơ sở dữ liệu hiện tại**; file xuất của các truyện cũ được NovelReader giữ theo thư mục.
