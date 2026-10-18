# Batch Web 96 — phiên bản 3

- Colab mặc định Web batch 96, CT2 nội bộ 96. Web/API cho phép 1–256.
- Giao diện không cắt mức đề xuất 96 xuống 64 nữa.
- Cấu hình truyện đã lưu được giữ: nếu còn 64, chọn 96 trong ô Batch size.
- Giữ bản vá cuDNN v2, OOM adaptive batching, pipeline audio và loại bỏ bot.
- 131 tests passed trên CPU, gồm kiểm tra batch 96/128/192/256 và từ chối 0/257.
- JavaScript syntax check và Python/notebook AST parse thành công.
- Chưa benchmark GPU T4; chưa chạy lại kiểm thử browser cho phiên bản 3. Các báo cáo UI trước đó là của phiên bản trước.
- Tăng Web batch không tăng batch CT2 nội bộ và không bảo đảm GPU bận hơn hoặc tốc độ tăng.
