# AI Novel Translator

Ứng dụng **local-first** dịch tiểu thuyết Trung → Việt bằng HachimiMT-60-QT.
FastAPI + worker thread + SQLite/WAL + WebSocket; frontend HTML/CSS/JS thuần,
dark theme, font Inter / JetBrains Mono đóng gói sẵn để dùng offline.

> **SPEC JSON chưa được cung cấp trong yêu cầu.** Giao diện này dựa trên phần mô
> tả bằng chữ: sidebar nguồn/từ điển/mục lục, header trạng thái/xuất file, reader
> song song và accent xanh lá. Đây không phải khẳng định khớp một JSON chưa có.

## 1. Cài và chạy

Khuyến nghị **Python 3.11 hoặc 3.12, 64-bit**. Mã nguồn hỗ trợ Python 3.10+;
wheel CTranslate2 phải có sẵn cho hệ điều hành/kiến trúc và phiên bản Python của bạn.
Không cần Node, GPU, Torch hay tài khoản Hugging Face cho model công khai.

### Windows (PowerShell)

```powershell
cd ai-novel-translator
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

Sau lần cài đầu, có thể bấm `start.bat`.

### macOS / Linux

```bash
cd ai-novel-translator
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python main.py
```

Mở **http://localhost:8000**. Ứng dụng chỉ bind `127.0.0.1` mặc định.
Không đổi sang `0.0.0.0` / public server nếu chưa thêm xác thực, phân quyền,
quota và sandbox đường dẫn. Không chạy nhiều worker Uvicorn: bộ điều phối job
hiện là single-process, single-user.

### Tải model trước khi offline

```bash
python scripts/download_model.py
# Sau khi tải thành công, tùy chọn:
# Linux/macOS: export HF_HUB_OFFLINE=1
# PowerShell: $env:HF_HUB_OFFLINE="1"
python main.py
```

Model được cache tại `./models/HachimiMT-60-QT/`. ZIP mã nguồn **không kèm
weights**; lần đầu cần Internet. Các lần sau engine đọc weights trực tiếp từ
cache, không gọi Hub nếu đủ file. Font cũng được phục vụ local, không gọi Google.
Dành ít nhất 300 MB ổ đĩa trống và khoảng 1 GB RAM trống để khởi đầu; dung lượng
runtime thực tế tùy sách/batch và nền tảng, không phải benchmark bảo đảm.

Nếu bị rate-limit Hub, có thể đặt `HF_TOKEN` theo hướng dẫn Hugging Face trên máy
của bạn. Không đưa token vào mã nguồn hay gửi token trong chat.

## 2. Model và API đã xác minh

Nguồn tham chiếu:
- https://huggingface.co/spaces/ngocdang83/HachimiMT-demo
- https://huggingface.co/spaces/ngocdang83/HachimiMT-demo/blob/main/README.md
- https://huggingface.co/spaces/ngocdang83/HachimiMT-demo/blob/main/src/translator.py
- https://huggingface.co/ngocdang83/HachimiMT-60-QT
- Mã nguồn upstream: https://github.com/ngocdang8311/qt2

Kiểm tra ngày 2026-10-17:
- Space là **Gradio**, README ghi SDK 6.18.0, không phải FastAPI.
- `Client(...).view_api()` có endpoint **`/translate_text_ui`**.
- Input theo thứ tự: `source`, `model_key`, `backend`, `beam_size`, `chunk_mode`,
  `normalize_mode`, `honorific_kinship`, `honorific_pronouns`,
  `pronoun_harmonizer_v9`, `auto_batch`, `manual_batch`, `glossary_rows`.
- Output 6 thành phần; **index 2 là toàn văn bản dịch dạng text**. Không scrape
  HTML của Gradio. Schema được lưu trong `docs/space-api.json`.
- Model gốc `ngocdang83/HachimiMT-60-QT` có thư mục
  **`ct2-int8_float32/`**, file `model.bin`, config và shared vocabulary.
  Tokenizer là SentencePiece `source.spm` / `target.spm` ở root.
- Upstream ghi CT2 khoảng **58 MB**, khác ước lượng ~215 MB trong yêu cầu
  (các định dạng weights khác có kích thước khác). Adapter không tải safetensors.
- Local dùng CTranslate2 CPU INT8, beam 2, repetition penalty 1.2; không cắt bỏ
  input quá 160 token: chia nhỏ thêm và ghép lại.
- Snapshot/phiên bản kiểm thử được ghi ở `docs/model-info.json` và
  `docs/tested-versions.txt`. Mặc định tải repo ở `main`; hãy lưu cache đã kiểm thử
  nếu cần tái lập tuyệt đối, tránh tự thay weights đang dùng.

Tự kiểm tra lại schema khi Space thay đổi:

```bash
python scripts/probe_space.py
python scripts/probe_space.py --translate  # gửi 1 câu mẫu tới Space
```

Adapter tự kiểm tra tên/thứ tự tham số, báo lỗi rõ nếu API thay đổi. Space là dịch
vụ công khai do bên thứ ba vận hành: có thể ngủ, quá tải, đổi schema, giới hạn
thời gian/độ dài hoặc không sẵn sàng; không có SLA.

## 3. Cách dùng

1. Chọn/kéo thả `.txt` hoặc `.epub`, tối đa 50 MB. Nạp truyện mới **thay thế** sách
   và kết quả đang lưu, nên xuất trước nếu muốn giữ.
2. Hoặc nhập đường dẫn file trên **máy chạy Python backend**. Đường dẫn Windows
   chỉ hoạt động khi server cũng chạy trên chính máy Windows đó. Trình duyệt
   không có quyền tự đọc một đường dẫn trên máy khác.
3. Chọn Local hoặc Space API. Local giữ nội dung trên máy; Space gửi segment
   truyện/thuật ngữ lên Hugging Face, có hộp xác nhận trước khi gửi.
4. Nhập từ điển, mỗi dòng `原文 -> Bản dịch`. Ví dụ trong `samples/glossary.txt`.
   Các dòng trống và comment bắt đầu `#` được bỏ qua; thuật ngữ dài ưu tiên trước.
   Đây là **từ điển ánh xạ**, không phải ô prompt tự do gửi vào LLM.
5. Chọn batch size (1–64, mặc định 8), bấm **Bắt đầu Dịch**.
6. Chọn chương bất kỳ để xem 2 cột. Không tự cướp chương đang đọc khi worker
   chuyển chương. Chương nhiều có tìm kiếm và nút tải thêm từng 100 mục.
7. **Tạm dừng** có hiệu lực tại ranh giới batch. Tiếp tục giữ cùng worker.
   **Dừng** hủy job, bỏ batch đang bay khi lời gọi engine trả về; checkpoint cũ
   vẫn còn. Bấm Bắt đầu để tạo job tiếp tục, không tự chạy sau khi mở lại app.
8. Khi khởi động lại, các chương `translating` trở về `pending`, các segment đã
   commit được giữ nguyên. Cấu hình đã bắt đầu job được lưu trong SQLite.
9. Đổi engine/từ điển khi đã có kết quả cần tick **Dịch lại từ đầu** và xác nhận
   xóa kết quả. Đổi batch size không buộc dịch lại.
10. Xuất TXT/EPUB: chỉ chương `done` có bản dịch; các chương còn lại là ghi chú
    rõ chưa hoàn tất. Chương lỗi/đang dịch không bị xuất như nội dung hoàn chỉnh.

## 4. Pipeline và độ tin cậy

- Encoding TXT: UTF-8 trước, rồi charset-normalizer giới hạn UTF/GBK/GB18030/Big5.
  Tự nhận encoding là heuristic; file rất ngắn/mixed encoding có thể bị đoán sai.
  Nếu thấy chữ lỗi, chuyển sang UTF-8 trước khi nhập.
- Heading dòng: `第…[章节節回卷]`, chữ số Hán/Ả Rập hoặc `Chapter N`.
  Giữ lời mở đầu; không có heading thì cắt khoảng 3000 ký tự thành `Phần N`.
- EPUB đọc theo **spine**, bỏ nav/non-linear. Đây là trình dịch văn bản, không bảo
  toàn bố cục, ảnh, footnote, CSS gốc hoặc DRM. Mỗi document spine không có
  heading nhận tên tự động; EPUB xuất mới có metadata `vi`, nav, NCX và CSS.
- Mỗi dòng không rỗng của TXT là một đoạn. Giữ thứ tự và đoạn hội thoại, chuẩn
  hóa CRLF/ngoặc kép, bỏ dòng trống thừa.
- Segment tối đa khoảng 200 ký tự, ưu tiên `。！？；`, tránh cắt giữa term đã biết;
  Local có thể chia tiếp theo giới hạn token. Không truncate nguồn.
- Title cũng được dịch. Mỗi segment được gắn paragraph index; ghép theo index,
  không split bản dịch theo newline một cách đoán mò. Hai cột cùng chiều cao từng
  hàng và đồng bộ scroll.
- Glossary dùng `⟦G1⟧`… và kiểm đếm chính xác. Nếu mất/lặp/hỏng token hoặc sinh
  ký tự U+FFFD, fallback **dịch các khoảng nguồn giữa thuật ngữ rồi chèn bản Việt
  trực tiếp**. Không đoán alias khi model đã làm mất tên. Cách này giữ tên nhưng
  có thể giảm ngữ cảnh/độ trôi chảy. Ký tự lỗi còn sót gây retry thay vì lưu bản
  dịch hỏng làm kết quả hoàn tất.
- Hậu xử lý dấu câu tiếng Việt/viết hoa đầu câu; không có quy tắc thay mọi đại từ
  thành một từ duy nhất. Model QT chuyên register ta/ngươi/hắn/nàng, nhưng không
  bảo đảm đúng người nói/quan hệ trong mọi ngữ cảnh; cần đọc soát trước xuất bản.
- SQLite WAL commit sau **mỗi batch**, không đợi cả chương. WS phát
  `chapter_started`, `segment_done`, `chapter_done`, `error`, `job_finished`.
  Đây là streaming kết quả segment/batch, **không phải token streaming**.
- Chương lỗi thử tối đa 3 lượt, giữ segment đã lưu, rồi chuyển chương kế. Space
  thêm 3 lần thử cho mỗi RPC, timeout 120s/lần, khoảng cách tối thiểu 1.5s/RPC.
  Vì có retry ở cả RPC và chương, lúc Space chết một chương có thể mất lâu.
  Local load/download hoặc RPC đang chạy không bị kill cưỡng bức bởi nút Dừng.
- Space gửi từng segment riêng để giữ alignment, nên batch UI không biến thành
  8 RPC chạy đồng thời; đây là chủ ý giới hạn tải cho demo CPU dùng chung.

## 5. Cấu trúc

```text
main.py                  FastAPI, WS, bảo vệ local origin, serve static
app/
  engines.py             TranslatorEngine + LocalEngine + SpaceEngine
  glossary.py            parse, protect, validate, source-span fallback
  text.py                chuẩn hóa, tách chương/segment, ghép đoạn
  files.py               TXT/EPUB import/export và giới hạn zip
  store.py               SQLite, transaction, checkpoint
  jobs.py                worker, pause/resume/stop, retry, broadcast
static/                  UI HTML/CSS/JS + font local và license font
scripts/                 tải model, probe Space API
samples/                 truyện fixture tự viết và glossary
tests/                  unit / integration tests (thư mục tests không có dấu cách)
docs/                    schema, nguồn nghiên cứu, test report, phiên bản
models/                  tự tạo khi tải weights (không kèm ZIP)
data/                    tự tạo: novel.sqlite3, app.log (không kèm ZIP)
```

Để thêm engine: kế thừa `TranslatorEngine`, triển khai `load()` và
`translate_raw(list[str])`; `translate(texts, glossary)` dùng chung wrapper
bảo vệ thuật ngữ. Đăng ký ở `create_engine`, enum request và dropdown.

Biến môi trường:
- `NOVEL_DATA`: thư mục SQLite/log (mặc định `./data` theo vị trí main.py).
- `NOVEL_MODELS`: thư mục model (mặc định `./models`).
- `HF_HUB_OFFLINE=1`: chỉ dùng cache. `HF_TOKEN`: token Hub nếu cần.

## 6. Kiểm thử

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

Bộ test không gọi mạng, không tải model. Bao phủ tách chương, GB18030, segmentation
không mất chữ, ưu tiên term dài, placeholder mất/lặp/ký tự lỗi, ghép đoạn, EPUB
spine/export, checkpoint restart, pause/resume/stop, retry bỏ qua chương lỗi, API,
WebSocket handshake và origin/header guard.

Smoke với model thật được tách khỏi unit test để không phát sinh tải mạng ngầm:

```bash
python scripts/download_model.py
python scripts/probe_space.py --translate
```

Xem `docs/QA.md` để biết đúng những gì đã/ chưa kiểm thử. Không suy ra benchmark
truyện 2847 chương hoặc chất lượng toàn bộ thể loại từ truyện mẫu hai chương.

## 7. API

Swagger: http://localhost:8000/docs. Với thao tác POST trong Swagger/curl, thêm
header **`X-App-Request: novel-translator`** (frontend đã tự thêm). Swagger UI
không tự thêm header này; dùng curl hoặc client Python để gọi write endpoints.

```bash
curl -H 'X-App-Request: novel-translator' \
  -F 'file=@samples/sample.txt' http://localhost:8000/api/upload
curl -H 'X-App-Request: novel-translator' -H 'Content-Type: application/json' \
  -d '{"engine":"local","batch_size":8,"glossary":""}' \
  http://localhost:8000/api/translate/start
```

| Method | Path | Công dụng |
|---|---|---|
| POST | /api/upload | multipart file |
| POST | /api/load-path | JSON `{"path":"..."}` |
| GET | /api/state | book + progress/config |
| GET | /api/chapters | metadata mục lục |
| GET | /api/chapters/{id} | original paragraphs, plan/outputs, translation |
| POST | /api/translate/start | engine, glossary, batch_size, reset |
| POST | /api/translate/pause | tạm dừng sau batch |
| POST | /api/translate/resume | tiếp tục worker |
| POST | /api/translate/stop | hủy job, giữ checkpoint |
| GET | /api/export/txt | TXT UTF-8 BOM |
| GET | /api/export/epub | EPUB với lang vi |
| WS | /ws/progress | realtime events; client reconnect tự động |

Frontend có polling 3s bổ trợ WS. Khi socket chậm, server timeout gửi 2s để không
để client chậm treo cả broadcast. Không gửi toàn văn truyện trong event.

## 8. An toàn, giới hạn, xử lý sự cố

- Local-first, **chưa có login/multi-user**. Bảo vệ Host + same-origin + custom
  write header chống trang bên ngoài gọi trình đọc đường dẫn cục bộ qua browser.
  Đây không thay thế xác thực nếu công khai server; client không phải browser
  trên cùng máy vẫn có thể gọi API. Không dùng như dịch vụ Internet.
- ZIP EPUB giới hạn tổng uncompressed 200 MB/20.000 mục, từ chối đường dẫn `..`,
  absolute và encrypted entries. File không đáng tin nên xử lý trong môi trường
  cách ly. Chưa phải bộ quét malware hay hardened document sandbox.
- Frontend chèn nội dung bằng `textContent`; export EPUB escape HTML.
- Log ở `data/app.log`; không chủ động log toàn văn sách, nhưng thông báo thư
  viện/đường dẫn lỗi có thể chứa thông tin cục bộ. Tránh chia sẻ log chưa rà soát.
- “Không hỗ trợ WebSocket”: cài lại requirements (có `websockets`) rồi restart.
- Thiếu wheel CTranslate2: thử Python 3.11/3.12 64-bit, cập nhật pip, cài Microsoft
  Visual C++ Redistributable trên Windows theo hướng dẫn upstream nếu thiếu DLL.
- Không đọc được đường dẫn: kiểm tra máy chạy backend, quyền file, dấu `\\` nếu
  tự gọi JSON; textarea đường dẫn trên UI không cần escape.
- Model download lỗi/Space bận: kiểm tra mạng, rate-limit, chạy probe, đổi Local.
- Port 8000 bị chiếm: dừng app cũ. Không chạy hai bản cùng database.
- Dừng có thể chậm khi đang tải model/chờ network; để app kết thúc an toàn. Nếu
  buộc đóng tiến trình, các transaction đã commit được giữ, batch cuối dịch lại.

## 9. Giấy phép

Mã nguồn mới của ứng dụng: MIT (`LICENSE`). Model không được phân phối trong
ZIP; giấy phép model được công bố trong repository model (bản kiểm tra ghi
CC-BY-4.0), không mặc nhiên được cấp lại theo MIT. Font Inter / JetBrains Mono
kèm license OFL trong `static/fonts/`. Kiểm tra quyền sử dụng truyện và điều
khoản Hugging Face trước khi gửi lên Space hoặc phân phối bản dịch.
