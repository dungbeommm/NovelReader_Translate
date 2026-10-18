# Conv1D/cuDNN trên T4: bản vá từ log người dùng

Log ghi cuDNN 9.27.0, T4 smVersion 750, Conv FP32 với input [1,192,1239,1].
Lỗi là HEURISTIC_QUERY_FAILED ở bước chọn execution plan; sau đó ORT bắt EPFail và
fallback toàn session về CPU. Log không phải thông báo thiếu VRAM.
Không đủ bằng chứng kết luận toàn bộ cuDNN 9.27 không hỗ trợ T4.

Thay đổi: provider options cho padding [N,C,1,D], thuật toán DEFAULT; tắt ORT
session.run fallback trong chế độ CUDA bắt buộc; guard trước/sau inference;
rollback cuDNN cố định 9.10.2.21; smoke test thêm chuỗi dài.

125 tests passed trên CPU (2 test thêm cho policy/fallback). Chưa kiểm thử GPU T4:
đây là bản vá có cơ sở từ log và tài liệu, không phải cam kết đã sửa xong lỗi thực tế.
Nếu vẫn lỗi, cung cấp output scripts/check_gpu.py gồm phần đầu phiên bản và lỗi cuối.
Có thể chủ động chọn CPU TTS để tiếp tục công việc, nhưng không gọi đó là sửa GPU.

Tài liệu tham khảo:
- https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html
- https://docs.nvidia.com/deeplearning/cudnn/backend/v9.27.0/reference/support-matrix.html
