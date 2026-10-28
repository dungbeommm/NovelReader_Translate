# NovelReader

## MoLab: dịch và tạo audio ngay trong notebook

Mở [NovelReader_Molab.py](NovelReader_Molab.py) trong Molab. Bản này dùng widget marimo
và engine dùng chung trong cùng kernel; **không khởi chạy Uvicorn, zrok hay LocalTunnel**.

1. Chạy các cell cài đặt. Source và `requirements.txt` bị thiếu sau khi Molab dừng
   được khôi phục từ repo; mã hiện có và dữ liệu người dùng không bị ghi đè.
2. Trong **Secrets**, đặt `HF_TOKEN` và `HF_BUCKET_ID` (dạng `tài_khoản/tên_bucket`)
   để lưu checkpoint qua phiên mới. Không đặt token trong mã nguồn notebook.
3. Nạp TXT/EPUB/ZIP hoặc mở **Lưu và khôi phục tiến độ**, liệt kê checkpoint HF rồi
   dán đường dẫn checkpoint cần khôi phục. Có thể khôi phục ZIP từ máy.
4. Chọn model, backend, giọng đọc và phạm vi chương, rồi bấm **Áp dụng cấu hình**.
   Nếu bật tự lưu HF, notebook kiểm tra kết nối và lưu checkpoint đầu tiên trước
   khi bắt đầu tải model/chạy tác vụ. Bấm **Bắt đầu / Tiếp tục từ checkpoint**.
5. Dùng **Cập nhật tiến độ**, **Tạm dừng**, **Tiếp tục** và **Dừng** ngay trong notebook.
   Bấm lưu/tải checkpoint thủ công sau khi tác vụ đã dừng.

Cấu hình mới dùng batch 8, một audio worker và hàng chờ 2. Tự lưu mặc định trong
form là sau 2 chương hoặc sau 1 phút, kiểm tra khi hoàn thành chương. Tùy chọn
**kèm audio** áp dụng cả checkpoint định kỳ lẫn checkpoint cuối phiên; ZIP tối đa
2 GB. Không kèm audio thì bản dịch vẫn khôi phục được, audio sẽ được tạo lại.
Chỉ checkpoint upload thành công mới an toàn khi mất sandbox; bảng tiến độ hiện
đường dẫn checkpoint gần nhất và lỗi upload. Không tự khôi phục/chạy lại một truyện
chưa được người dùng chọn.

Molab có thể thu hồi sandbox; thiết kế này không bảo đảm uptime và không né giới
hạn 12 giờ/90 phút idle. Molab không cho dùng tunnel/backend WebUI ngoài notebook:
[xem chính sách sử dụng](https://marimo.io/pages/molab/restrictions).
Trạng thái `Notebook stopped — sandbox stopped responding and was reclaimed`
là mất runtime; đổi tunnel không khôi phục được runtime đó.

Trong khi bản sửa chờ hợp nhất, `NOVEL_SOURCE_REF` mặc định là
`fix/molab-native-runtime`. Đặt biến này trong Secrets nếu dùng branch hoặc commit
khác có các module native tương ứng. Notebook không tự cập nhật mã đã tồn tại;
để nâng phiên bản, dùng checkout/thu mục source mới và khôi phục checkpoint.

## WebUI trên máy chủ riêng hoặc Colab

[NovelReader_Colab.ipynb](NovelReader_Colab.ipynb) tiếp tục dùng
[notebook/webui_launcher.py](notebook/webui_launcher.py). WebUI chứa các công cụ
đọc đối chiếu, quản lý kho HF và ghép audio. Chạy trên máy chủ cho phép phục vụ web:

```bash
python -m pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --workers 1
```

## Cấu trúc và kiểm thử

- `notebook/molab_native.py`: điều khiển native, upload/restore checkpoint, báo lỗi HF.
- `notebook/molab_bootstrap.py`: khôi phục tệp source thiếu và cài công cụ audio.
- `core/`, `workflows/`, `translation/`, `audio/`, `tts/`: engine và khóa một tác vụ.
- `storage/`: SQLite, Hugging Face Bucket và checkpoint không chứa credentials.
- `server/`, `web/`: WebUI khi chạy trên máy chủ phù hợp.

```bash
python -m pytest tests/test_molab_native.py tests/test_cloud_sync_manager.py tests/test_jobs.py tests/test_notebook_launcher.py -q
marimo check NovelReader_Molab.py
```
