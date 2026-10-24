# v4.6 — Tùy chọn dịch, bảng Xuất và Cài đặt gọn hơn

## Đã sửa
- Công tắc Phồn thể → Giản thể và menu Chữ Hán nay đồng bộ hai chiều. Tắt công tắc gửi `normalize_mode=none` thật, không tiếp tục chuyển chữ ngầm.
- API đồng bộ cấu hình cũ `normalize_t2s` với cấu hình mới. Nếu gửi cả hai và mâu thuẫn, `normalize_mode` là giá trị ưu tiên.
- Bộ dịch CT2 dự phòng cũng áp dụng chia theo câu/đoạn; đoạn quá dài vẫn được tách để tránh vượt giới hạn token.
- Không còn bắt mọi `TypeError` rồi gọi dịch lại mà bỏ Beam/chunk/normalize. Chỉ lọc tham số theo chữ ký của engine cũ, ghi cảnh báo tham số không hỗ trợ; lỗi nội bộ được báo đúng.
- Beam vẫn truyền thành `beam_size` cho CT2 hoặc `num_beams` cho PyTorch. Beam cao tìm kiếm nhiều phương án hơn, thường tốn thời gian/bộ nhớ hơn, không bảo đảm dịch hay hơn.
- “Tự động phồn → giản” và “Ép giản thể” hiện dùng cùng chuyển đổi OpenCC; không phải hai mức chất lượng AI khác nhau. Giữ nguyên thật sự bỏ chuyển đổi.
- Hậu kỳ xưng hô/đại từ là quy tắc, không hiểu ngữ cảnh hoàn hảo.

Thay đổi tùy chọn tác động lượt dịch mới. Muốn so sánh chương đã dịch cần dịch lại/reset chương; giữ một bản sao trước khi reset.

## Một nút Xuất
Thanh trên chỉ còn một nút **Xuất**. Bảng mở ra cho chọn:
1. Văn bản TXT, sách EPUB hoặc audio đã tạo.
2. Tải về máy, Google Drive hoặc Pixeldrain.
3. Xem tên truyện, số chương đã dịch và số tệp audio thực có trước khi xuất.

TXT/EPUB xuất toàn bộ truyện hiện tại theo thứ tự, có đánh dấu phần chưa dịch. Chưa có xuất riêng một dải chương. Audio không tự tạo mới và không đổi giọng/codec/bitrate khi xuất. Tải về máy/Pixeldrain dùng ZIP; Google Drive giữ từng tệp audio. Tệp audio gộp cũng được xuất nếu đã có. Tệp ẩn, tệp tạm và liên kết tượng trưng được loại khỏi danh sách ở cả ba đích. Dừng job trước khi xuất audio.

Kết nối Drive và Pixeldrain vẫn dùng các luồng hiện có. Người có link Pixeldrain có thể tải dữ liệu; không chia sẻ checkpoint nhạy cảm.

## Cài đặt: năm mục
- **Dịch thuật:** Beam, chia câu/đoạn, chữ Hán và hậu kỳ. Model/bộ máy/batch vẫn ở cột cấu hình chính.
- **Giọng đọc:** bộ đọc, giọng, định dạng, bitrate. Noise/temperature/top-p/batch GPU/tần số nằm trong Nâng cao.
- **Lưu trữ:** Pixeldrain và kết nối Drive.
- **Sao lưu:** bảng tạm, checkpoint, khôi phục ZIP/link Pixeldrain.
- **Dọn dẹp:** xóa chương rỗng; thao tác xóa dữ liệu khác thu gọn kèm cảnh báo.

Bỏ công tắc tự loại mục lục vốn không có xử lý phía sau để tránh tùy chọn giả. Giữ chức năng quét/xóa chương rỗng có thật. Bố cục cột cấu hình và khung đọc song song, màu xanh tối vẫn giữ. Cài đặt có điều hướng bàn phím, giữ focus trong bảng và Escape để đóng.

## Cách chạy bản này
- Molab: dùng `NovelReader_Molab.py` trong ZIP hoặc tệp `NovelReader_Molab_v4.6.py` gửi riêng.
- Colab: mở `NovelReader_Colab.ipynb` trong ZIP, chạy các bước theo thứ tự.
- Nguồn v4.6 tích hợp trong cả hai notebook, không cần chờ ZIP GitHub cập nhật. Không kèm trọng số model, API key, token hay truyện cá nhân. Chạy lại bootstrap không ghi đè thư mục dữ liệu/model và `.env`.
- Máy local: giải nén, cài `requirements.txt` và chạy theo README. Sao lưu dữ liệu cũ trước khi nâng cấp; không chép đè thư mục runtime khi job đang chạy.

VieNeu/Piper kế thừa bản v4.5; xem [giới hạn model và cài đặt](UPDATE_V4_5_VI.md). VieNeu dùng backbone/codec chính thức tải riêng, không chạy GGUF Vbook.

## Kiểm chứng và giới hạn
- Kiểm thử Python gồm schema, OpenCC, fallback chunking, truyền Beam/chunk/normalize, API, bảng tạm, xuất audio và notebook bootstrap.
- Kiểm thử trình duyệt cục bộ: payload UI đi đến engine giả lập đúng; TXT/EPUB/ZIP audio tải thật; sáu nhánh gọi xuất Drive/Pixeldrain dùng phản hồi mô phỏng, không phải tài khoản cloud thật.
- Rà giao diện 1440×1000 và 390×844, năm mục Cài đặt, Nâng cao, bảng Xuất; kiểm tra không tràn ngang.
- Chưa chạy mô hình dịch/TTS, GPU, Google OAuth hay upload Pixeldrain thật trong môi trường này. Không cam kết GPU 100% hoặc chất lượng giọng/dịch từ kiểm thử giả lập.

## Đề xuất — chưa triển khai
Ưu tiên cho bản tiếp theo:
1. **Nghe thử 15–30 giây:** chọn giọng/tham số rồi nghe trước khi tạo cả truyện.
2. **Đo tốc độ và VRAM:** thời gian/chương, hệ số thời gian thực, bộ nhớ đỉnh; gợi ý cấu hình an toàn theo GPU thay vì tăng batch mù quáng.
3. **Kiểm tra audio lỗi:** phát hiện đoạn im lặng/quá ngắn/lặp bất thường; tạo lại riêng đoạn lỗi.
4. **Checkpoint định kỳ:** lưu sau N chương, có lịch sử và xác nhận khôi phục sau khi notebook mất kết nối.
5. **Xuất theo chương/dải chọn:** tránh tải lại toàn bộ truyện khi chỉ sửa một phần.
