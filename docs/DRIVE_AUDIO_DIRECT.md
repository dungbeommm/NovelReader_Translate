# Drive audio trực tiếp — v4.2

Chỉ thay đổi nhánh xuất audio lên Drive. stage_export tạo snapshot từng file audio rời, không import/tạo ZIP. Colab copy từng file qua temp rồi rename; Kaggle dùng API resumable cho từng file (8 MB/chunk), cùng một kết nối Drive cho lượt xuất. Giữ tên và đường dẫn tương đối; thư mục mỗi lượt `NovelReader_Exports/<truyện>/audio/<timestamp_task>/` tránh ghi đè bản cũ. Tệp trong thư mục ẩn, đang tạo tạm hoặc symlink không được đưa vào snapshot.

Theo dõi tổng số file/đã hoàn tất; lỗi giữ bản gốc và những file đã lên Drive. File tạm được dọn. Upload lại tạo lượt mới, không tiếp tục lượt dở tự động. TXT/EPUB giữ nguyên định dạng. Tải ZIP về máy và ZIP sao lưu vẫn như cũ. ZIP mã nguồn phân phối không phải audio ZIP trên Drive.

Không sửa mã dịch, TTS/audio, workflow, storage, script cài GPU và cấu hình GPU 0/batch 96 của bản v4.2 người dùng gửi.

172 kiểm thử CPU đạt, gồm snapshot không ZIP, loại tệp tạm/symlink, giữ tên/thư mục con, Colab copy từng file, Kaggle dùng upload_audio thay single-file ZIP, progress và lỗi một phần giữ bản gốc. Các kiểm thử TXT/EPUB và ZIP download cũ vẫn đạt. Chromium cục bộ kiểm tra nút xuất Drive qua OAuth/API giả lập, MP3 hiện bằng tên gốc, không có ZIP trên Drive giả lập, tải về và mobile vẫn hoạt động. Chưa kiểm chứng Google OAuth/upload cloud/Kaggle/Colab/GPU thật.
