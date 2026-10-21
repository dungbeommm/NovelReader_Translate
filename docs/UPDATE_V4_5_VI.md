# v4.5 — VieNeu và tùy chọn âm thanh

## Thay đổi
- Giữ bố cục thanh trên / cấu hình trái / khung đọc phải và mobile. Thêm chọn Piper hoặc VieNeu.
- Piper: danh mục 22 giọng, tự tải đủ config JSON + ONNX giọng chọn, hoặc tất cả ONNX nếu chọn tải toàn bộ.
- VieNeu: danh mục 25 giọng Vbook; tải gói giọng, kiểm tra SHA256, chuyển embedding 192 chiều và reference codes N×16 sang `models/vieneu/voices.json`.
- Notebook tự cài dependencies/tải model theo engine. Bước mở server Molab phụ thuộc bước tải model hoàn tất.
- Sửa API tạo audio từng chương đọc đúng request. Pipeline và từng chương dùng cùng một bộ ánh xạ tham số.
- Lưu Cài Đặt cập nhật cấu hình audio của truyện và bảng tạm; checkpoint giữ các trường mới. Đổi tùy chọn đánh dấu cần tạo lại audio nhưng giữ bản dịch. Audio cũ chỉ bị thay sau khi tạo mới thành công, tránh phát nhầm định dạng cũ.

## Lưu ý quan trọng về model bạn gửi
Gói `vieneu-v3-turbo.zip` trong Darkrai9x/vbook-settings là **GGUF + 25 bộ tham chiếu giọng**. Adapter này **không chạy GGUF**. Nó nhập 25 bộ tham chiếu và dùng SDK chính thức với backbone ONNX/CPU hoặc PyTorch/CUDA tải riêng.

- `vieneu==3.8.3`, `transformers==4.57.6`.
- Backbone `pnnbao-ump/VieNeu-TTS-v3-Turbo`, thư mục `update` (GPU) / `onnx_update` (CPU).
- Codec GPU `OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano`.
- PyTorch/torchaudio 2.8.0; trình cài dùng wheel cu128 khi cần cài mới. Cần driver phù hợp CUDA 12.8. Không cam kết tương thích mọi notebook/GPU.
- Nguồn giọng: https://github.com/Darkrai9x/vbook-settings/releases/download/ai-tts/vieneu-v3-turbo.zip
- Gói 187,993,859 byte, SHA256 `cf29fcf43ceea672a9078c1eee21497fd1bd14e552bac866a88216ff2c9c578c`.
- Lần đầu tải khoảng 188 MB gói giọng **và thêm backbone/codec lớn hơn**, không phải chỉ 188 MB. Cần đủ Internet, đĩa, RAM/VRAM. Cache được giữ để tránh tải lại.
- Chưa nghe xác minh 25 giọng hoặc chạy suy luận thực với backbone này tại môi trường đích. Hãy nghe thử một chương ngắn trước. Kiểm tra giấy phép của các model trước khi dùng thương mại.

## Chạy Molab
1. Mở `NovelReader_Molab.py` trong ZIP hoặc file độc lập `NovelReader_Molab_v4.5.py`. File đã có mã nguồn v4.5 tích hợp, không cần tự tải ZIP cũ từ GitHub.
2. Chọn **Bộ đọc → VieNeu v3 Turbo**, rồi chọn ở menu **Giọng VieNeu**. Piper có menu riêng.
3. Chạy các bước từ 1 đến 5. Bước 4 tự cài SDK, tải 25 reference và nạp backbone/codec; lỗi sẽ dừng bước tải, không giả báo sẵn sàng.
4. VieNeu dùng một model chung và xử lý từng chương. Tăng **Batch đoạn / GPU** trong Nâng cao để gộp đoạn trong chương (bắt đầu 4–8). CPU/ONNX chạy tuần tự, không hưởng batch GPU.
5. Nếu đổi từ Piper sang VieNeu sau khi server đã chạy mà chưa cài SDK, dừng server, chọn VieNeu ở notebook và chạy bước cài/tải rồi mở lại.

## Colab / Kaggle
Mở `NovelReader_Colab.ipynb`, sửa cell 3:

```python
TTS_ENGINE = 'vieneu'  # hoặc 'piper'
TTS_VOICE = 'truc_ly' if TTS_ENGINE == 'vieneu' else 'ngochuyennew'
VIENEU_DEVICE = 'cuda'  # 'cpu' nếu không có GPU
```

Chạy từ bước 1–5. Nên dùng runtime sạch. Nếu kernel đã import torch/ORT rồi mới thay wheel, restart kernel và chạy lại. Không xóa cache nếu muốn tránh tải model lại. Không chạy hai notebook cùng lúc vào một thư mục dữ liệu.

## Cài ngoài notebook

```bash
# Trong thư mục dự án đã cài requirements.txt; FFmpeg phải có trong PATH.
python scripts/setup_tts.py --engine vieneu --device cuda --install --preload
# Hoặc CPU:
python scripts/setup_tts.py --engine vieneu --device cpu --install --preload
# Chỉ tải và kiểm tra 25 reference, chưa nạp backbone:
python scripts/setup_tts.py --engine vieneu --refs-only
# Piper: đủ JSON + model giọng chọn:
python scripts/setup_tts.py --engine piper --voice ngochuyennew
```

Đặt `NOVEL_TTS_ENGINE=vieneu`, `NOVEL_TTS_VOICE=truc_ly`, `VIENEU_DEVICE=cuda` trước khi chạy Web để đổi mặc định. Truyện cũ ưu tiên cấu hình đã lưu; đổi trong Web rồi Lưu Cài Đặt để chuyển engine. `requirements-vieneu.txt` là phụ thuộc tùy chọn; script xử lý cài wheel CUDA/ORT đúng thứ tự.

## Các tùy chọn thực sự làm gì?

| Tùy chọn | Piper | VieNeu |
| --- | --- | --- |
| Giọng | ONNX + config đúng ID | Speaker embedding + reference codes đúng ID |
| Tốc độ | `length_scale=1/speed` lúc tổng hợp | FFmpeg `atempo`, không đổi cao độ |
| Noise / Noise W | Truyền SynthesisConfig | Ẩn, không truyền nhầm |
| Temperature / Top-p | Không áp dụng | Truyền SDK infer, tác động lấy mẫu |
| Batch đoạn / GPU | Không áp dụng | 1–64 đoạn trong chương; chỉ có tác dụng trên GPU |
| Chương đồng thời | 1–8 worker, thêm VRAM mỗi phiên | 1 chương, một model chung |
| Bitrate / kHz xuất | FFmpeg mã hóa / resample | Cùng bộ mã hóa; model gốc 48 kHz |

**Không có preset ép cảm xúc buồn/vui/kịch tính.** Noise chỉ điều chỉnh độ biến thiên. SDK VieNeu v3 Turbo bỏ qua `style`, nên bản này không tạo menu cảm xúc giả.

- Bitrate kbps không phải tần số kHz. WAV PCM không dùng bitrate, UI vô hiệu hóa kbps. AAC/Opus có thể lệch bitrate mục tiêu theo nội dung/chế độ mã hóa.
- Opus luôn xuất 48 kHz; cấu hình API được chuẩn hóa theo đó.
- MP3 192 kbps cần xuất 44.1/48 kHz; ở 22.05/24 kHz FFmpeg có thể âm thầm hạ xuống 160. Bản này chặn để không báo sai. Nếu giữ tần số gốc model thấp, dùng 128 kbps hoặc thấp hơn.
- Tăng kHz không tạo thêm chi tiết mà model chưa sinh ra. Tăng kbps không sửa phát âm hay nâng model thành HD.
- Đổi tham số không tự chuyển đổi file cũ: bấm **Tạo Audio** hoặc chạy lại audio các chương bị đánh dấu cần tạo.
- Batch dịch 1–1024 khác batch đoạn VieNeu 1–64. Tăng quá cao có thể OOM; giảm batch/worker khi hết VRAM. Không đảm bảo GPU luôn 100%.

## Kiểm thử và giới hạn
- Bộ hồi quy cũ cùng kiểm thử mới chạy bằng pytest; xem `tests/test_vieneu_v45.py` và `docs/TEST_RESULTS_V4_5.txt`.
- FFmpeg/ffprobe thực: bitrate MP3 64/192 kbps, tần số đầu ra, tốc độ 0.4/1.25/2.5, WAV bỏ qua kbps, Opus 48 kHz, chặn MP3 192 ở tần số thấp.
- API/SDK contract và pipeline kiểm thử bằng inference giả lập. Giao diện Playwright trên server cục bộ ở 1440×1000 và 390×844; tạo audio mẫu tone để xác minh request, **không phải giọng AI thật**.
- Gói Vbook đã được tải thật, xác minh SHA256 và chuyển đủ 25 bộ tham chiếu trong quá trình phát triển trước khi môi trường đóng gói khởi động lại. Không kèm gói model/runtime data trong bản phát hành.
- Python compile, JS syntax, Marimo static check; kiểm tra đối chiếu nguồn trong hai notebook và ZIP lồng.
- **Chưa chạy suy luận VieNeu/Piper thật hoặc benchmark GPU/Molab, chưa xác minh chất lượng/nhận diện của 25 giọng, driver cu128/HF trên runtime của bạn.** Notebook có smoke test suy luận thực để chạy ở runtime đích. Không suy ra GPU chạy thật chỉ từ tên provider.
- Kết nối Pixeldrain/Drive kế thừa v4.4; không dùng tài khoản cloud thật trong lần kiểm thử này. Giữ bí mật API key/link checkpoint; không chia sẻ checkpoint chứa dữ liệu truyện cá nhân.
