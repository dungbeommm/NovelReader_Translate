# NovelReader T4 Web — Dịch truyện và tạo audio

Bản Web/Colab từ mã nguồn đính kèm, tối ưu luồng CTranslate2 + Piper. Không kèm trọng số model, tài khoản, token hay dữ liệu truyện cá nhân. Không có thành phần bot.

## Chạy trên Colab T4 — phiên bản 4

1. Mở `NovelReader_Colab_GitHub_Drive_v4.ipynb` bằng Colab, hoặc `NovelReader_Colab.ipynb` trong gói này.
2. Chọn **Runtime → Change runtime type → T4 GPU**.
3. Chạy bước 1: tự tải từ `https://raw.githubusercontent.com/dungbeommm/NovelReader_Translate/main/NovelReader_GPU_notebook.zip`. **Không cần tự tải/chọn ZIP**. Notebook có lớp cập nhật nguồn v4 nên vẫn hoạt động nếu ZIP trên GitHub còn là v3; không tự đẩy thay đổi lên GitHub.
4. Chạy bước 2–4: cài CT2 4.6.0 / ORT-GPU 1.23.2 / cuDNN 9.10.2.21 và kiểm tra inference GPU. Nếu lỗi, xử lý trước khi mở Web.
5. Mở **link riêng theo phiên** được in ở bước 5; lần đầu đổi secret trong URL sang cookie HttpOnly và xóa query khỏi địa chỉ. Không chia sẻ link đó. Cell 5 phải tiếp tục chạy để nhận yêu cầu quyền Drive.
6. Trong Web, **Lưu: Google Drive** là mặc định trên notebook mới. Bấm **Xuất TXT / EPUB / Audio**. Nếu chưa kết nối Drive, **quay về tab Colab** để cấp quyền khi được hỏi; không cần nhập Client ID/Secret/token vào Web.
7. Kết quả được sao chép vào `MyDrive/NovelReader_Exports/<tên truyện>/`. Tên có timestamp + mã ngắn, không ghi đè bản trước. Audio được đóng thành ZIP trên ổ cục bộ trước khi chép. Bản gốc vẫn giữ tại Colab.
8. Chọn **Lưu: Tải về máy** nếu không muốn cấp quyền Drive. Đợi thông báo hoàn tất trước khi Stop server hoặc ngắt runtime.

Drive mount do Colab thực hiện trong tab notebook, không giả lập popup Google trong tab Cloudflare. Google có thể không hỏi lại nếu đã cấp quyền/mount. Quyền mount có thể cho runtime truy cập rộng hơn thư mục xuất; chỉ chạy mã nguồn tin cậy và không chia sẻ link Web.

Nếu đã import ONNX Runtime/Piper/CT2 vào kernel rồi mới cài lại thư viện, hãy **Restart session** rồi chạy từ bước 1. Bước 1 giữ `data/`, `models/`, output và `.env` hiện có. **Restart** khác với xóa runtime; luôn sao lưu kết quả trước khi bỏ phiên.

Lưu ý: file ZIP đính kèm có thể đổi tên thành `NovelReader_GPU_notebook.zip` để bạn chủ động cập nhật vào repository. Notebook tải từ GitHub, không phụ thuộc file ZIP trong máy người dùng. Chưa thực hiện upload hoặc commit GitHub thay bạn.

### Cấu hình khởi đầu

| Thiết lập | Notebook T4 |
| --- | --- |
| Backend | CT2 |
| Model tải khi kiểm tra | HachimiMT-60-QT |
| Batch Web (số đoạn đưa vào engine mỗi lượt) | 96 (cho phép 1–256) |
| Batch CT2 nội bộ | 96 |
| CT2 batch type / window | tokens / 16 |
| Compute type | int8_float16 |
| Beam Web | 2; thử 1 nếu chấp nhận đánh đổi chất lượng |
| Pipeline audio | Bật, một worker, tối đa 2 chương đợi |
| Tự gộp audio | Mặc định tắt; khi bật chỉ gộp ở cuối tác vụ |
| Piper | Bắt buộc CUDA, báo lỗi thay vì chuyển CPU âm thầm |

Batch Web và batch nội bộ **khác nhau**. Thay biến môi trường cần khởi động lại backend để nạp lại model. UI lấy batch đề xuất phần cứng rồi giới hạn tối đa 256; cấu hình đã lưu của truyện vẫn được giữ.

Thiếu VRAM khi dịch: chương trình giảm batch và thử lại **cùng đoạn**, không bỏ đoạn. Với OOM ở TTS hoặc lỗi không phục hồi được: chương audio được đánh dấu lỗi; hãy giảm tải/đổi sang chạy tuần tự rồi tiếp tục. Khi chỉnh lại notebook có thể giảm batch nội bộ 96 → 64 → 32. Không dùng BF16 trên T4.

Không bảo đảm số lần tăng tốc hay số ký tự/giây. Pipeline có thể tranh GPU với CT2; bỏ chọn **Pipeline dịch + audio** để so sánh chế độ tuần tự trên cùng vài chương, cùng giọng/beam.

### Dữ liệu và an toàn Colab

- Model, SQLite, text, audio đang xử lý nằm trên `/content`, không ghi trực tiếp vào thư mục Drive mount. Đây là lưu trữ tạm: **sao lưu trước khi runtime ngắt**.
- Bước sao lưu lấy snapshot SQLite và text/audio sau khi dừng server, không kèm cấu hình/token Drive. Muốn khôi phục: dừng server, đặt `data/novel.sqlite3`, `output_text/`, `output_audio/` của bản sao lưu vào đúng các thư mục dự án, rồi khởi động lại. Không trộn database với output của truyện khác.
- Notebook v4 bảo vệ Web/tài nguyên/API/WebSocket bằng secret ngẫu nhiên theo phiên và cookie HttpOnly. Ai có link riêng vẫn có thể truy cập ứng dụng; không chia sẻ. Đây không phải cơ chế phân quyền nhiều người dùng. Bản chạy local không đặt secret chỉ nên bind localhost.
- Cell server dùng file log, không dùng pipe chưa được đọc. Stop gửi SIGTERM, đợi tối đa khoảng 135 giây rồi mới buộc dừng. Audio đang dở có thể cần tạo lại.

## Những thay đổi chính

- Pipeline có hàng đợi giới hạn, một consumer TTS + mã hóa audio. Dịch chương kế tiếp không phải chờ MP3 chương trước; job chỉ chuyển idle khi worker đã kết thúc.
- Công tắc pipeline/tuần tự trong Web; API có `audio_pipeline`, `audio_queue_size` (1–4).
- Audio lỗi/thiếu được tiếp tục trên bản dịch đã hoàn thành khi chạy tiếp toàn bộ, không phải dịch lại. Lưu ý: hành vi cũ **chọn dải mà mọi chương đã dịch xong** vẫn là dịch lại dải đó; để chỉ bổ sung audio, bấm chạy tiếp toàn bộ hoặc dùng nút audio từng chương khi job rảnh.
- Pause chặn việc bắt đầu audio tiếp theo; Stop kết thúc audio đang gọi rồi bỏ các phần đang đợi, giữ checkpoint. Trạng thái audio `queued/generating` được phục hồi sau khi khởi động lại.
- Gộp chỉ một lần ở cuối tác vụ, đúng phạm vi chương. Lỗi gộp được báo thành lỗi job.
- Xuất `toan_bo_truyen.txt` một lần ở cuối (kể cả dừng có kiểm soát), thay vì ghi lại toàn bộ sau mỗi chương. Text từng chương và checkpoint vẫn cập nhật trong lúc chạy.
- Xuất file tổng và audio theo tệp tạm rồi thay thế an toàn, không lộ MP3 đang viết dở.
- Có `/api/tts/status`, log providers của session Piper, và `scripts/check_gpu.py` kiểm tra CUDA + inference ngắn.
- Docker/Compose mặc định chạy Web; không còn phụ thuộc, biến môi trường, volume hay lệnh khởi động bot.

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
- Cấu hình Google Drive có thể chứa token; không đưa `data/`, `.env` vào nơi công khai.

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

Core benchmark không bao gồm checkpoint Web, TTS hay MP3. Log Web có `TIMING translation` và `TIMING audio` theo chương. Xem `docs/GITHUB_DRIVE_V4.md` cho kiểm thử hiện tại; các báo cáo phiên bản trước ghi riêng trong docs.


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
