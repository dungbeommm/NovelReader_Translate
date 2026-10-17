# Novel Tool — Dịch truyện, tạo audio và quản lý đầu ra

Mã nguồn được chia ngang hàng theo chức năng, không còn thư mục `translator/` bao ngoài.

## Cấu trúc

```text
tool/
├── main.py                         # Điểm chạy Web UI
├── paths.py                        # Đường dẫn dùng chung, không phụ thuộc thư mục chạy
├── web/                            # Giao diện và API
│   ├── application.py              # Ghép FastAPI, middleware, lifespan
│   ├── runtime.py                  # Store và Job dùng chung
│   ├── schemas.py                  # Kiểm tra dữ liệu API
│   ├── routes/                     # books, translation, audio, gdrive, system, progress
│   └── static/                     # HTML, JS, CSS, font
├── translation/                    # Engine, thuật ngữ, xử lý văn bản
│   └── core/                       # Backend Hachimi và mã bổ trợ được giữ lại
├── tts/                            # Service giọng đọc Piper
│   ├── server.py
│   ├── synthesis.py                # Adapter Piper dùng chung cho Web và service
│   ├── pipeline/batch_tts.py
│   └── requirements.txt
├── audio/                          # Tạo audio chương và gộp audio
│   ├── audio_service.py
│   └── merge_service.py
├── gdrive/                         # Google Drive
│   └── gdrive_service.py
├── telegram/                       # Telegram Bot
│   ├── bot.py
│   ├── runner.py
│   ├── state.py
│   └── requirements.txt
├── workflows/                      # Điều phối dịch → text → TTS → gộp → upload
│   └── jobs.py
├── storage/                        # Database, nhập/xuất TXT và EPUB
│   ├── store.py
│   └── files.py
├── models/
│   ├── translation/                # Model dịch tải về
│   └── voices/                     # .onnx, .onnx.json và thông tin giọng đọc
├── data/                           # Database/cấu hình, tạo khi chạy
│   ├── novel.sqlite3
│   ├── gdrive_config.json          # Chỉ tạo khi lưu cấu hình Drive; có thể chứa token
│   ├── logs/
│   └── telegram/                   # Hàng đợi và staging riêng của bot
├── output_text/
│   └── Tên truyện đã dịch/
│       ├── chuong_0001.txt
│       ├── chuong_0002.txt
│       └── toan_bo_truyen.txt
├── output_audio/
│   └── Tên truyện đã dịch/
│       ├── chuong_0001.mp3
│       ├── chuong_0002.mp3
│       └── audio_gop/
│           ├── chuong_0001_0050.mp3
│           └── chuong_0051_0100.mp3
├── scripts/                        # Tải model/giọng và chuyển dữ liệu cũ
├── tests/                          # Unit, regression và integration tests
├── docs/
├── compose.yaml
├── Dockerfile
├── requirements.txt
├── .env.example
├── start_web.bat
├── FIX_NOTES.md
└── README.md
```

Các thư mục model/data/output có thể trống trong ZIP. Database/log chỉ sinh khi chạy. Gói mã không kèm trọng số model hay dữ liệu cá nhân.

## Cài đặt và chạy Web

Khuyến nghị **Python 3.11**, FFmpeg và ffprobe trong PATH. Cần model dịch và giọng Piper có quyền sử dụng. Web dùng Piper cục bộ; không cần khởi động service TTS riêng.

Windows CMD, từ thư mục `tool/`:

```bat
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe scripts\download_model.py --model HachimiMT-60-QT
.venv\Scripts\python.exe scripts\download_voices.py
start_web.bat
```

Các lệnh tải model/giọng cần Internet và có thể tải nhiều file lớn. Nếu đã có model, dùng công cụ chuyển dữ liệu bên dưới thay vì tải lại.

Linux/macOS:

```sh
python3.11 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --workers 1
```

Mở `http://localhost:8000`. Không chạy nhiều worker vì ứng dụng dùng một thư viện truyện hiện tại và một hàng đợi dịch trong tiến trình.

## Tên truyện và cách lưu output

1. Nạp TXT/EPUB. Mặc định tên thư mục là tên file không có phần mở rộng.
2. Muốn dùng tên tiếng Việt, nhập ở **Tên truyện / thư mục đầu ra** và bấm **Lưu tên truyện**. Hệ thống không tự đoán tên dịch; bạn cung cấp tên muốn dùng.
3. Text và audio được lưu ở hai nhánh có cùng tên thư mục. Đổi tên sẽ chuyển cả hai nhánh cùng dữ liệu hiện có.
4. Nạp truyện mới chỉ thay thư viện SQLite hiện tại; output truyện trước vẫn được giữ. Tên trùng được thêm `_2`, `_3`… để không ghi đè. Database chưa phải thư viện nhiều truyện: output cũ được lưu, nhưng checkpoint chỉ dành cho truyện hiện tại.
5. Tên có ký tự không hợp lệ trên Windows được làm sạch. Xóa truyện/reset/purge chỉ tác động output truyện hiện tại, không xóa output các truyện khác.

Audio gộp chỉ có một bản trong `audio_gop/`. Không tạo thêm bản sao audio chương dạng `chapter_<id>` hay bản sao audio gộp ở ngoài.

## Dịch theo dải và gộp audio

- Nhập **1 đến 5**, bấm **Dịch + tạo audio dải này**: chỉ dịch lại và tạo audio chương 1–5. Nếu chỉ nhập 1 đầu số (VD: Từ chương 5), hệ thống tự động dịch đến giới hạn truyện (từ chương 5 đến hết).
- **Tự động gộp audio khi nhỏ hơn số chương trong nhóm**: Không cần đủ số chương mới gộp; hệ thống tự động gộp file audio trong 2 trường hợp:
  1. Số chương còn lại ở cuối truyện sau khi chia nhóm nhỏ hơn số chương quy định (VD: 120 chương, nhóm 50 → gộp 1–50, 51–100 và nhóm còn lại 101–120).
  2. Số chương được chọn dịch nhỏ hơn số chương trong nhóm (VD: chọn dịch 1–5 với nhóm 50 → tự động gộp thành 1 file Chương 1–5).
- **Gộp audio đã có theo nhóm N** đọc audio có sẵn của truyện. Nhóm thiếu audio ở giữa chờ bổ sung, không nhảy cóc; nhóm đủ hoặc nhóm còn lại ở cuối truyện đều được gộp.
- Bật **Tự động gộp audio thành file lớn** để tự động kiểm tra và gộp nhóm sau khi các chương dịch xong.
- Nhóm không đổi được dùng lại qua fingerprint nguồn, không mã hóa lại liên tục. Reset chương sẽ vô hiệu hóa audio gộp có chứa chương đó.
- Đổi model/glossary hoặc thiết lập dịch khi đã có checkpoint cần reset/dịch lại để không trộn kết quả cũ với cấu hình mới.

## Service TTS và Telegram

Cài phụ thuộc bot nếu dùng:

```sh
pip install -r telegram/requirements.txt
```

Chạy TTS từ thư mục gốc:

```sh
python -m uvicorn tts.server:app --host 127.0.0.1 --port 8010 --workers 1
```

Đặt `TELEGRAM_BOT_TOKEN`, `ALLOWED_USER_IDS` và `TTS_URL=http://127.0.0.1:8010` trong biến môi trường rồi chạy:

```sh
python telegram/bot.py
```

Không dùng `python -m telegram.bot`: thư mục launcher `telegram/` cố ý không có `__init__.py` để không che thư viện **python-telegram-bot**. Bot giữ staging/checkpoint theo từng tác vụ trong `data/telegram/`; các nhánh `output_text/<tên>/` và `output_audio/<tên>/` của runner nằm riêng trong tác vụ để không lẫn dữ liệu giữa người dùng. File gửi Telegram vẫn được chia theo giới hạn dung lượng.

Bot từ chối khởi động nếu chưa đặt danh sách người dùng được phép. Không công khai TTS nội bộ hoặc Web local ra Internet nếu chưa bổ sung xác thực.

## Docker

Tạo `.env` từ `.env.example`, điền thông tin bot trên máy của bạn. Model giọng đặt ở `models/voices/`.

```sh
docker compose up --build -d tts bot
docker compose --profile web up --build -d web
```

Web chỉ mở trên `127.0.0.1:8000`, TTS không publish cổng. Trên Linux, user trong container có UID/GID **10001**: chuẩn bị quyền ghi phù hợp cho bind mount `models/translation`, `output_text`, `output_audio`; không dùng chmod 777. Model giọng chỉ cần quyền đọc. Docker Desktop có thể xử lý quyền bind mount khác Linux.

## Chuyển từ thư mục cũ

**Dừng app/bot cũ và sao lưu trước. Giải nén bản mới vào thư mục riêng; không chép đè lên cây cũ.**

Xem trước kế hoạch, không thay đổi file:

```bat
.venv\Scripts\python.exe scripts\migrate_layout.py --source "D:\tool_cu"
```

Nếu output cũ ở dạng phẳng và bạn chắc chắn chúng thuộc truyện hiện tại, thêm `--flat-output` để chuyển vào tên truyện đọc từ SQLite:

```bat
.venv\Scripts\python.exe scripts\migrate_layout.py --source "D:\tool_cu" --flat-output
```

Xác nhận kế hoạch đúng rồi thêm `--apply`:

```bat
.venv\Scripts\python.exe scripts\migrate_layout.py --source "D:\tool_cu" --flat-output --apply
```

Công cụ chỉ sao chép, không xóa nguồn; từ chối ghi đè file đích có nội dung khác. Model dịch → `models/translation/`, giọng → `models/voices/`, dữ liệu Web → `data/`, dữ liệu bot → `data/telegram/`. Không bật `--flat-output` nếu thư mục cũ trộn nhiều truyện chưa phân loại. Chuyển dữ liệu trước khi chạy bản mới; nếu bản mới đã tạo database, dùng thư mục đích sạch hoặc sao lưu và xử lý xung đột thủ công.

Không mang database, token Google Drive hoặc `.env` lên nơi công khai.

## Kiểm thử

```sh
pip install pytest httpx
python -m pytest tests -q
```

Cần FFmpeg/ffprobe. Bộ test giả lập model dịch và giọng đọc; có ghép/chuyển audio bằng FFmpeg thật. Xem `docs/QA_CURRENT.md` để biết phạm vi xác minh và giới hạn.
