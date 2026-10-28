# NovelReader

Xuất mặc định và checkpoint dùng duy nhất bucket Hugging Face **`uri410/novelreader-storage`**. Google Drive và Pixeldrain đã được gỡ khỏi mã chạy, giao diện và dependencies. Vẫn có thể chọn tải tệp về máy.

TXT/EPUB được lưu trong `exports/<truyện>/<lượt-xuất>/`; audio trong `audio/<truyện>/<lượt-xuất>/` dưới dạng từng tệp gốc, giữ thư mục con; checkpoint ZIP trong `checkpoints/<truyện>/<lượt-xuất>/`. Mỗi lượt có timestamp và mã riêng để tránh ghi đè.

Cần tạo bucket đúng địa chỉ trên và cấp quyền đọc/ghi cho token. Cấu hình `HF_TOKEN` trong môi trường của tiến trình chạy backend. Với PowerShell:

```powershell
$env:HF_TOKEN = Read-Host 'Hugging Face token' -MaskInput
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Backend cũng hỗ trợ token lưu riêng tại `data/private/huggingface.json`; tệp này nằm ngoài Git, notebook đóng gói và checkpoint. Với Docker Compose, đặt `HF_TOKEN` trong `.env` (xem `.env.example`); Compose truyền vào container. Không nhúng token vào JavaScript hay notebook chia sẻ.

Trong Cài đặt → Lưu trữ, bấm **Kiểm tra kết nối**. Khôi phục cloud nhận link `tree/main`/`resolve` hoặc đường dẫn `checkpoints/...zip` trong đúng kho cố định. Thư mục `docs/` giữ hướng dẫn GPU/TTS, giám sát tài nguyên và mẫu đầu vào.

`NovelReader_Molab.py` và `NovelReader_Colab.ipynb` chứa mã nguồn mới, không phụ thuộc ZIP cũ trên GitHub. Thiết lập biến môi trường `HF_TOKEN` trong runtime notebook trước khi khởi động Web. Sau khi sửa mã, chạy `python scripts/package_notebooks.py` để cập nhật cả hai notebook và ZIP nguồn; script loại dữ liệu runtime, token và model khỏi gói.

## Chạy cục bộ (CPU hoặc GPU đã cài CUDA)

Khuyên dùng **Python 3.11**, FFmpeg/ffprobe trong PATH. Linux cần libgomp1/espeak-ng tùy runtime.

```sh
python3.11 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python scripts/download_model.py --model HachimiMT-60-QT
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --workers 1
```

Giọng được tải khi dùng lần đầu. `scripts/download_voices.py` vẫn có thể tải cả kho giọng nếu bạn chủ động chạy; notebook chỉ tải giọng cần dùng.

Requirements mặc định dùng ORT CPU để hỗ trợ máy không GPU. Với Colab dùng script cài GPU riêng. Không giữ đồng thời hai distribution `onnxruntime` và `onnxruntime-gpu`.

`PIPER_DEVICE=auto|cpu|cuda` (mặc định `auto`); `PIPER_REQUIRE_CUDA=1` buộc dừng khi CUDA không dùng được. Chế độ `auto` có thể fallback CPU nhưng có cảnh báo log. Sau khi đổi thiết bị, khởi động lại server để bỏ cache giọng cũ.

Giữ **một Uvicorn worker** vì thư viện truyện và hàng đợi nằm trong cùng tiến trình. Không chạy nhiều phiên server dùng chung database/output.

### Docker CPU

```sh
docker compose up --build -d web
```

Web bind `127.0.0.1:8000`. Đây là cấu hình CPU, **không phải image CUDA/T4**. Trên Linux chuẩn bị quyền ghi cho UID/GID **10001** ở các thư mục bind mount, không dùng chmod 777. `webdata` chứa checkpoint; model và output được bind mount.

Service TTS riêng là tùy chọn, không cần cho Web:

```sh
docker compose --profile tts up --build -d tts
# Hoặc cục bộ:
python -m uvicorn tts.server:app --host 127.0.0.1 --port 8010 --workers 1
```

Service riêng vẫn dùng cấu hình riêng của nó; kiểm tra CUDA/strict mode trong bản vá tập trung vào luồng Web `audio/audio_service.py`.

## Đầu ra và thao tác truyện

```text
models/translation/                  model dịch tải về
models/voices/                       model giọng .onnx + .onnx.json
output_text/<tên truyện>/
  chuong_0001.txt
  toan_bo_truyen.txt                  cập nhật ở cuối tác vụ
output_audio/<tên truyện>/
  chuong_0001.mp3
  audio_gop/chuong_0001_0050.mp3
```

- Tên thư mục mặc định là tên file; có thể nhập tên tiếng Việt bằng **Tên truyện / thư mục đầu ra**. Đổi tên chuyển cả hai nhánh output.
- Nạp truyện mới không xóa output truyện cũ. Database chỉ quản lý **truyện hiện tại**, không phải thư viện nhiều truyện.
- Chọn dải chương chỉ xử lý dải đó; nhóm cuối thiếu số chương vẫn có thể gộp. Nhóm thiếu chương ở giữa không nhảy cóc.
- Thay model/backend/glossary hoặc thiết lập nội dung cần reset/dịch lại để tránh trộn checkpoint cũ.
- Khi job đang chạy/đang chờ audio hoàn tất, không reset/xóa/đổi tên/tạo audio thủ công đồng thời.
- Gộp audio hiện có bằng nút gộp thủ công; fingerprint nguồn giữ các nhóm không đổi để tránh mã hóa lặp.

## Di chuyển dữ liệu cũ

Dừng ứng dụng và sao lưu trước; giải nén bản mới vào thư mục riêng, không chép đè dữ liệu đang chạy.

```sh
python scripts/migrate_layout.py --source /duong/dan/ban_cu
# Kiểm tra kế hoạch rồi mới thêm --apply.
```

Công cụ chỉ sao chép, không xóa nguồn và từ chối ghi đè tệp có nội dung khác. Hỗ trợ `translator/models`, `tts/voice`, `translator/data`, output theo thư mục truyện. Chỉ dùng `--flat-output` nếu output cũ dạng phẳng chắc chắn thuộc truyện SQLite hiện tại.

## Kiểm thử và đo tốc độ

```sh
pip install -r requirements.txt -r requirements-dev.txt
HF_HUB_OFFLINE=1 python -m pytest tests -q
node --check web/static/app.js
```

Trên Colab, không cài lại requirements CPU sau setup GPU chỉ để chạy test.

```sh
# Chạy trên runtime T4 đã cài đúng thư viện; có thể tải model/giọng:
python scripts/check_gpu.py --model HachimiMT-60-QT --voice ngochuyennew

# Chỉ đo core dịch; dừng Web trước khi chạy để tránh tranh GPU:
python -m translation.core.benchmark_sweep /content/mau.txt \
  --model HachimiMT-60-QT --backend ct2 --single-gpu \
  --beams 1,2 --batches 64,96 --windows 16
```



## Bản vá Conv1D/cuDNN trên T4

Sau log `HEURISTIC_QUERY_FAILED`/`No valid engine configs` do người dùng cung cấp:
- Đổi padding Conv1D sang `[N,C,1,D]` và đặt `cudnn_conv_algo_search=DEFAULT`.
- Gọi `session.disable_fallback()` trong chế độ CUDA bắt buộc trước suy luận;
  kiểm tra provider cả trước và sau, không chỉ khi nạp model.
- Cố định cuDNN 9.10.2.21 thay vì cho phép tự cập nhật lên 9.27.x.
  Đây là rollback tương thích để thử, chưa xác nhận giải quyết trên GPU người dùng.
- Smoke test giọng ngắn và dài dùng WAV riêng và kiểm tra CUDA sau inference.
- Không chuyển TTS sang CPU và tuyên bố là đã sửa GPU.

Phải dừng server, cài runtime rồi restart session Colab để bỏ các thư viện CUDA/cuDNN đã nạp.
Bản vá không xóa database, model hoặc output. Xem `docs/CUDNN_T4_FIX.md`.


## Batch Web phiên bản 3

Colab mặc định 96 đoạn/lượt, bằng mức cấu hình CT2 96; giới hạn Web/API tăng lên 256.
Có thể thử Web batch 128 → 192 → 256 và so thời gian cùng vài chương; tăng Web batch
không tự tăng ngân sách CT2 nội bộ 96. GPU không cần đầy VRAM để chạy hiệu quả.
Nếu truyện đã lưu batch 64, nhập 96 trong giao diện; bản mới không tự ghi đè thiết lập
đã lưu của truyện. Không cần chỉnh mã nguồn. Giữ beam 2 và một worker TTS.

## Module architecture (MoLab + FastAPI)

- `core/`: canonical runtime singleton, env flags, cross-process `job.lock` and non-secret `job_state.json`.
- `notebook/`: MoLab GPU/bootstrap/model setup and control-plane HTTP client.
- `server/`: FastAPI app, API router registration and zrok share URL helper.
- `translation/`, `audio/`, `tts/`, `storage/`, `monitoring/`: existing domain modules preserved.
- `web/static/`: original HTML/CSS/JavaScript kept unchanged.
- `web/application.py`, `web/runtime.py`: compatibility facades for existing imports and tests.

While WebUI is reachable, Marimo sends import/start/pause/resume/stop to FastAPI rather than starting another local job. When WebUI is offline, Marimo can work locally. A per-database advisory lease blocks concurrent translation workers. A second Store is opened with recovery disabled if another worker is active, so it cannot silently reset in-progress chapter rows. File operations still use idle checks; use a single notebook and WebUI on one sandbox.

The root notebook keeps *blank* HF/zrok inline token slots for a **private notebook copy only**. Never commit real tokens to this public repo. Revoke any tokens previously committed.

Tests: `python -m pytest tests/test_architecture_refactor.py tests/test_api.py tests/test_jobs.py -q`. Run `python scripts/package_notebooks.py` after pulling to rebuild distributable Colab notebook/ZIP from the updated packages. MoLab's empty-sandbox bootstrap clones the current repo.

Additional service boundaries: `server/auth/access.py` owns session authentication, `monitoring/logger.py` owns logger setup, and `storage/sync_manager.py` owns the periodic + final Hugging Face checkpoint lifecycle. Compatibility imports via `web.access` are preserved.
