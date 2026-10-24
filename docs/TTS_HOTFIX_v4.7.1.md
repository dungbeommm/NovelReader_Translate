# v4.7.1 — sửa xung đột TorchVision khi khởi tạo VieNeu

## Nguyên nhân
Log Colab: TorchVision 0.26.0+cu130 yêu cầu Torch 2.11.0 nhưng bộ cài TTS cũ ép Torch/TorchAudio 2.8.0+cu128. `torchvision::nms does not exist` làm Transformers không import được `PreTrainedModel`. Đây không phải lỗi giọng Trúc Ly hay API key.

## Bản vá
- Giữ phiên bản Torch hiện có nếu import và phép tính CUDA nhỏ hoạt động; không ép về 2.8.
- Chỉ khi hoàn toàn chưa có Torch mới cài cặp Torch/TorchAudio 2.8.0 (CPU hoặc driver CUDA >=12.6).
- TorchAudio cần trùng build Torch, lấy từ đúng wheel channel, không kéo dependency thay Torch/CUDA. Build tùy biến cần cài thủ công.
- Import TorchVision trong tiến trình con. Giữ nguyên bản tốt; gỡ bản lỗi vì TTS không cần xử lý ảnh. Tác vụ ảnh trong cùng runtime sẽ cần cài lại TorchVision tương thích.
- Ràng buộc các phiên bản Torch, TorchAudio, TorchVision còn giữ, Triton và NVIDIA khi cài SDK. Không tự thử hạ/nâng native stack nếu bị lỗi.
- Khi SDK kéo CPU ONNX Runtime, gỡ distribution CPU rồi khôi phục chính phiên bản GPU ORT trước đó để tránh mất file module chung. Nếu chưa có GPU ORT mới chọn bản >=1.21,<2.
- Kiểm tra import Torch/TorchAudio/PreTrainedModel, CUDA và danh sách ORT providers trước tải model. Có provider không thay thế kiểm thử inference thực tế.

## Sửa runtime đang lỗi, giữ model/dữ liệu
1. Dừng tác vụ và server Web đang chạy. Sao lưu tiến độ nếu có.
2. Upload `Repair_VieNeu_TTS_v4.7.1.py` vào Colab và chạy trong một cell:
   ```python
   %run /content/Repair_VieNeu_TTS_v4.7.1.py
   ```
   Script mặc định sửa `/content/NovelReader_T4_Web`, sao lưu hai file mã cũ thành `.before-v471`, cập nhật hai script bootstrap, gỡ **chỉ** TorchVision bị lỗi import và kiểm tra phụ thuộc. Không cài lại Torch/CUDA/SDK, không tải model, không xóa dữ liệu hay giọng. Đây không phải script tự sửa mọi dạng hỏng CUDA/TorchAudio; trường hợp khác sẽ dừng và hiện lỗi.
3. Nếu Torch/Transformers/TorchVision đã được import trong kernel, dùng **Restart session**, không dùng chức năng xóa/reset toàn bộ runtime. Các server khác cũng phải khởi động lại. Chạy lại cell cấu hình/biến môi trường, không cần chạy lại pip cài toàn bộ.
4. Chạy cell TTS hoặc:
   ```python
   import subprocess, sys
   subprocess.run([sys.executable, '/content/NovelReader_T4_Web/scripts/setup_tts.py',
       '--engine', 'vieneu', '--voice', 'truc_ly', '--device', 'cuda', '--preload'], check=True)
   ```
   Không có `--install`: dùng thư viện đã có. Cache model được tái sử dụng; phần model còn thiếu vẫn cần tải.

## Dùng bộ nguồn mới
Notebook Colab và Molab đều nhúng nguồn v4.7.1; chức năng giao diện/tài nguyên v4.7 được giữ nguyên. Bản vá giới hạn ở thiết lập VieNeu, không thay chính sách cài CUDA của các script setup nền tảng khác.

Kiểm thử mới mô phỏng resolver, subprocess và version mismatch; không thực sự pip cài bộ Torch vào máy kiểm thử. Chưa xác nhận synthesis VieNeu trên GPU Colab/Molab. Việc giữ bộ Torch mới không đồng nghĩa SDK đã được chứng minh tương thích với mọi phiên bản; preload/smoke test vẫn là bước bắt buộc.
