> **Hotfix v4.7.1:** sửa xung đột TorchVision/VieNeu trên Colab. Xem `docs/TTS_HOTFIX_v4.7.1.md`.

# NovelReader T4 Web — Dịch truyện và tạo audio

## Bản cập nhật v4.7 — Giám sát tài nguyên và tiến trình

Thanh dưới bên trái có vòng CPU/GPU/VRAM/RAM/Đĩa; bên phải mở bảng tốc độ dịch (ký tự/s), % tạo audio từng chương, tốc độ thời gian thực và thời gian hoàn tất. Số đo lấy từ máy chạy tool, không từ máy mở Web. Thiếu GPU/mất kết nối hiển thị “—”. [Hướng dẫn, cách tính và giới hạn](docs/UPDATE_V4_7_VI.md).

Dùng `NovelReader_Molab.py` / `NovelReader_Colab.ipynb` trong gói này (nguồn v4.7 tích hợp). Cài lại requirements để có psutil. Lịch sử đo audio tối đa 200 chương trong phiên server; chưa lưu vào checkpoint. Kiểm thử CPU/mock, chưa benchmark GPU/model thật.

## Bản cập nhật v4.6 — Dịch thuật và giao diện gọn hơn

Sửa công tắc Phồn–Giản, chia đoạn ở bộ dịch dự phòng và xử lý lỗi bỏ tham số. Gộp xuất TXT/EPUB/Audio vào một nút **Xuất** có bảng chọn định dạng, nơi lưu và thông tin kiểm tra. Cài đặt chia năm mục rõ ràng; tham số ít dùng nằm trong Nâng cao. Bố cục khung đọc giữ nguyên.

**Chạy bản mới:** dùng `NovelReader_Molab.py` hoặc `NovelReader_Colab.ipynb` trong gói này. Cả hai tích hợp nguồn v4.6, không phụ thuộc ZIP cũ trên GitHub; các hướng dẫn phiên bản cũ bên dưới chỉ để tham khảo lịch sử. Xem [thay đổi, cách chạy và đề xuất tính năng](docs/UPDATE_V4_6_VI.md). Kiểm thử CPU/mock; chưa xác minh model/GPU và cloud thật.

## Bản cập nhật v4.5 — Piper + VieNeu

Tự cài/tải JSON và model theo bộ đọc trên Molab/Colab; thêm 25 reference giọng Vbook, sửa tùy chọn audio từng chương và lưu cấu hình. Giữ bố cục cũ. **Không chạy GGUF**: VieNeu dùng backbone ONNX/PyTorch và codec chính thức tải riêng; chưa xác minh inference GPU thực. Xem [hướng dẫn và giới hạn v4.5](docs/UPDATE_V4_5_VI.md).

## Bản cập nhật v4.4

Batch Web/API **1–1024**, chọn **1–8 chương audio đồng thời**, Molab tải đủ JSON giọng đọc, checkpoint/bảng tạm và khôi phục qua Pixeldrain. Giữ bố cục giao diện cũ. Xem [hướng dẫn cập nhật, kiểm thử và giới hạn xác minh](docs/UPDATE_V4_4_VI.md). Không cam kết GPU đầy 100%; cần đo trên GPU thực tế.


Bản Web/Colab từ mã nguồn đính kèm, tối ưu luồng CTranslate2 + Piper. Không kèm trọng số model, tài khoản, token hay dữ liệu truyện cá nhân. Không có thành phần bot.

## Drive: audio lưu từng file, không tạo ZIP

Khi chọn **Lưu: Google Drive → Xuất Audio**, ứng dụng tải trực tiếp từng file MP3/WAV/M4A/M4B/OPUS/AAC/OGG vào `NovelReader_Exports/<truyện>/audio/<thời gian_mã lượt xuất>/`. Giữ nguyên tên file và các thư mục con, không tạo ZIP audio ở bước chuẩn bị hoặc trên Drive. Có snapshot tệp rời tạm ở runtime để tránh nội dung thay đổi trong lúc upload; snapshot được dọn sau tác vụ.

TXT và EPUB vẫn lưu đúng định dạng gốc. **Tải về máy** và **sao lưu bước 6** giữ ZIP như trước. Nếu lỗi giữa chừng, các file đã lên Drive và file gốc vẫn giữ; trạng thái báo số file hoàn tất. Bấm xuất lại tạo lượt/thư mục mới, không tự tiếp tục lượt lỗi và không ghi đè lượt cũ.

GPU 0, batch 96 và mã dịch/TTS không thay đổi, không thêm chia tải hai GPU. Xem `docs/DRIVE_AUDIO_DIRECT.md`.

## Bản v4.2 — chỉ sửa Google Drive

Bản này dựa đúng trên ZIP/notebook v4.2 được gửi lại. **Không thêm chia tải hai GPU.** Mã dịch, TTS/audio, workflow, storage, script cài GPU và cấu hình GPU 0 giữ nguyên theo từng byte. Batch 96 và các sửa đăng nhập trước đó giữ nguyên.

Mở `NovelReader_v4_2_DriveDirect_Kaggle_Colab.ipynb` hoặc `NovelReader_Colab.ipynb` trong gói. Kaggle: bật Internet và GPU, chạy bước 1–5. Notebook tự tải ZIP GitHub và áp dụng bản vá Drive; không cần sửa code. Colab vẫn dùng mount native trong notebook. Kaggle không gọi `google.colab.drive.mount()` nữa.

### Drive trên Kaggle
1. Trong Google Cloud, bật **Google Drive API**, cấu hình OAuth consent/Test users nếu app ở Testing. Tạo OAuth client loại **Desktop app**, tải JSON về máy.
2. Trong Web bấm **Kết nối Drive**, chọn JSON rồi **Tạo link đăng nhập Google**. Mở link và cấp quyền. Chỉ xin scope `drive.file` cho tệp do ứng dụng tạo.
3. Google chuyển về `http://127.0.0.1:8765/?state=...&code=...` trên máy bạn. Trang có thể báo không kết nối được: sao chép **toàn bộ URL trên thanh địa chỉ**, dán vào ô trong Web rồi bấm **Hoàn tất kết nối**. Không gửi URL hoặc JSON vào chat.
4. Chọn **Lưu: Google Drive**, xuất TXT/EPUB/audio. Bản gốc vẫn giữ trong runtime. Nếu không muốn tạo OAuth client, chọn **Lưu: Tải về máy** rồi tự đưa lên Drive.

Quyền API lưu `/tmp/novelreader-drive` (ngoài Output và ZIP sao lưu), mất khi runtime bị xóa. Giữ notebook/link Web/mã truy cập và JSON riêng tư; không publish output còn chứa mã hiệu lực. Nút Ngắt kết nối xóa quyền khỏi runtime; quản lý quyền ứng dụng tại Google để thu hồi phía Google. Không có OAuth client chung hoặc token dựng sẵn trong gói.

Bước 1 ưu tiên giữ checkpoint cũ nếu từng dùng notebook Colab trên Kaggle. Sao lưu bước 6 trước khi kết thúc vì dữ liệu runtime có thể bị xóa. Kiểm thử CPU/mock, chưa xác minh Google OAuth/Kaggle/GPU thật; xem `docs/DRIVE_FIX_V4_2.md`.

## Chạy trên Colab T4 — phiên bản 4.2

1. Mở `NovelReader_v4_2_DriveDirect_Kaggle_Colab.ipynb` bằng Colab, hoặc `NovelReader_Colab.ipynb` trong gói này.
2. Chọn **Runtime → Change runtime type → T4 GPU**.
3. Chạy bước 1: tự tải từ `https://raw.githubusercontent.com/dungbeommm/NovelReader_Translate/main/NovelReader_GPU_notebook.zip`. **Không cần tự tải/chọn ZIP**. Notebook có lớp cập nhật nguồn v4 nên vẫn hoạt động nếu ZIP trên GitHub còn là v3; không tự đẩy thay đổi lên GitHub.
4. Chạy bước 2–4: cài CT2 4.6.0 / ORT-GPU 1.23.2 / cuDNN 9.10.2.21 và kiểm tra inference GPU. Nếu lỗi, xử lý trước khi mở Web.
5. Nếu link không tự đăng nhập, mở địa chỉ Web và dán **Mã truy cập** được in ngay dưới nút mở Web trong Colab vào biểu mẫu đăng nhập. Mở Web trong tab riêng và cho phép cookie của trang. Mở **link riêng theo phiên** được in ở bước 5; lần đầu đổi secret trong URL sang cookie HttpOnly và xóa query khỏi địa chỉ. Không chia sẻ link đó. Cell 5 phải tiếp tục chạy để nhận yêu cầu quyền Drive.
6. Trong Web, **Lưu: Google Drive** là mặc định trên notebook mới. Bấm **Xuất TXT / EPUB / Audio**. Nếu chưa kết nối Drive, **quay về tab Colab** để cấp quyền khi được hỏi; không cần nhập Client ID/Secret/token vào Web.
7. Kết quả được sao chép vào `MyDrive/NovelReader_Exports/<tên truyện>/`. Tên có timestamp + mã ngắn, không ghi đè bản trước. Audio được tải từng file gốc vào thư mục audio của lượt xuất, không tạo ZIP khi lưu Drive. Bản gốc vẫn giữ tại Colab.
8. Chọn **Lưu: Tải về máy** nếu không muốn cấp quyền Drive. Đợi thông báo hoàn tất trước khi Stop server hoặc ngắt runtime.

Drive mount do Colab thực hiện trong tab notebook, không giả lập popup Google trong tab Cloudflare. Google có thể không hỏi lại nếu đã cấp quyền/mount. Quyền mount có thể cho runtime truy cập rộng hơn thư mục xuất; chỉ chạy mã nguồn tin cậy và không chia sẻ link Web.

Nếu đã import ONNX Runtime/Piper/CT2 vào kernel rồi mới cài lại thư viện, hãy **Restart session** rồi chạy từ bước 1. Bước 1 giữ `data/`, `models/`, output và `.env` hiện có. **Restart** khác với xóa runtime; luôn sao lưu kết quả trước khi bỏ phiên.

Lưu ý: file ZIP đính kèm có thể đổi tên thành `NovelReader_GPU_notebook.zip` để bạn chủ động cập nhật vào repository. Notebook tải từ GitHub, không phụ thuộc file ZIP trong máy người dùng. Chưa thực hiện upload hoặc commit GitHub thay bạn.

### Cấu hình khởi đầu

| Thiết lập | Notebook T4 |
| --- | --- |
| Backend | CT2 |
| Model tải khi kiểm tra | HachimiMT-60-QT |
| Batch Web (số đoạn đưa vào engine mỗi lượt) | 96 (cho phép 1–1024) |
| Batch CT2 nội bộ | 96 |
| CT2 batch type / window | tokens / 16 |
| Compute type | int8_float16 |
| Beam Web | 2; thử 1 nếu chấp nhận đánh đổi chất lượng |
| Pipeline audio | Bật, một worker, tối đa 2 chương đợi |
| Tự gộp audio | Mặc định tắt; khi bật chỉ gộp ở cuối tác vụ |
| Piper | Bắt buộc CUDA, báo lỗi thay vì chuyển CPU âm thầm |

Batch Web và batch nội bộ **khác nhau**. Thay biến môi trường cần khởi động lại backend để nạp lại model. UI lấy batch đề xuất phần cứng rồi giới hạn tối đa 1024; cấu hình đã lưu của truyện vẫn được giữ.

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
