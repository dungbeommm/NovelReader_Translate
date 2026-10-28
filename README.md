# NovelReader — MoLab

Hệ thống dịch truyện Trung → Việt, tạo audio bằng Piper/VieNeu, quản lý tiến độ qua FastAPI WebUI, công khai WebUI bằng zrok và lưu kết quả/checkpoint trên Hugging Face.

## Khởi chạy trên MoLab

1. Mở [NovelReader_Molab.py](NovelReader_Molab.py) tại `molab.marimo.io`.
2. Cell khởi tạo sẽ tải source hiện tại từ GitHub khi sandbox chưa có code.
3. Cấu hình model dịch, giọng đọc, bucket Hugging Face và zrok.
4. Chạy backend WebUI rồi mở URL zrok do notebook hiển thị.
5. Nạp TXT/EPUB/ZIP, chọn chương và chạy dịch → audio. Theo dõi tiến độ và checkpoint trên WebUI.

**Chú ý:** Một sandbox đã clone repo từ trước **không tự cập nhật** sau khi GitHub đổi code. Chỉ đồng bộ khi không có job chạy; tránh xóa `data/`, `output_text/` và `output_audio/`.

Notebook có các vị trí `HF_TOKEN_INLINE`, `ZROK_ACCOUNT_TOKEN_INLINE` để điền trực tiếp trên **bản notebook cá nhân riêng tư**. Repo công khai giữ hai giá trị rỗng. Token đã từng xuất hiện trong commit cũ cần thu hồi và tạo lại; xóa file hoặc sửa commit mới không xóa token khỏi Git history.

## Chạy FastAPI cục bộ

Yêu cầu Python 3.11, FFmpeg; trên Linux thường cần espeak-ng, libgomp1.

```bash
python -m pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --workers 1
```

Tùy chọn Docker CPU:

```bash
docker compose up --build -d web
```

Đặt `HF_TOKEN` trong môi trường hoặc tệp `.env` khi dùng Docker. Bucket mặc định là `uri410/novelreader-storage`, nhưng có thể cấu hình bucket mới qua notebook/WebUI. TTS và model được tải/cấu hình riêng; đọc `requirements-vieneu.txt` và `scripts/setup_tts.py` khi sử dụng VieNeu.

## Cấu trúc

| Thư mục | Vai trò |
| --- | --- |
| `core/` | Runtime, khóa job liên tiến trình và trạng thái |
| `notebook/` | Khởi tạo MoLab, kiểm tra GPU, tải model, điều khiển WebUI |
| `server/` | FastAPI, xác thực, tunnel zrok |
| `translation/` | HachimiMT, CTranslate2/PyTorch và hậu xử lý |
| `tts/`, `audio/` | Piper/VieNeu, tổng hợp, ghép và mã hóa audio |
| `workflows/` | Điều phối chương, hàng đợi audio |
| `storage/` | SQLite WAL, Hugging Face Bucket, checkpoints |
| `monitoring/` | Giám sát tài nguyên, tác vụ và logging |
| `web/static/` | HTML/CSS/JS giao diện hiện tại |
| `tests/` | Các bài kiểm thử |

Sơ đồ chi tiết: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Lưu trữ và khôi phục

- `data/`: SQLite, cấu hình riêng tư, log và thông tin checkpoint.
- `models/`: model dịch và giọng đã tải.
- `output_text/<tên_truyện>/`: TXT theo chương, toàn bộ truyện.
- `output_audio/<tên_truyện>/`: MP3 và các nhóm audio.
- Hugging Face: `exports/`, `audio/`, `checkpoints/` với thư mục phân theo truyện/lượt tạo.

Checkpoint định kỳ lưu dữ liệu cần khôi phục, **không kèm audio**; có thể xuất checkpoint cuối với audio tùy cấu hình. Thời gian kích hoạt checkpoint theo mốc chương và được kiểm tra khi chương hoàn thành, không phải hẹn giờ độc lập.

## Kiểm thử

```bash
python -m pip install -r requirements-dev.txt
python -m pytest tests/test_architecture_refactor.py tests/test_cloud_sync_manager.py tests/test_api.py tests/test_jobs.py -q
```

Repo này ưu tiên **MoLab**. Notebook Colab, ZIP nguồn đóng sẵn và các script hỗ trợ Colab/VPS cũ đã được gỡ khỏi nhánh `main`; các commit cũ vẫn có thể truy cập trong lịch sử Git.
