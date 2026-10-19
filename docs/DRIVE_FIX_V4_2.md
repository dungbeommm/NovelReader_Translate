# Bản vá Drive riêng trên v4.2

Nền: hai file v4.2 người dùng đính kèm. Không lấy v5/v6 làm nền, không thêm phân tải hai GPU.

Chỉ cập nhật module xuất Drive, bridge môi trường, route API, UI cấp quyền và notebook Kaggle/Colab. Thêm các phụ thuộc Google API/OAuth. Các file trong translation, tts, audio, workflows, storage và scripts so với ZIP gốc giống từng byte. Toàn bộ cấu hình GPU cũ được giữ làm tiền tố cell cấu hình; GPU 0, batch 96, kiểm tra GPU cũ không đổi. Xem DRIVE_ONLY_SCOPE.json.

Kaggle không hỗ trợ drive.mount của Colab; dùng Drive API với OAuth Desktop JSON riêng, PKCE S256/state, hết hạn 10 phút và URL loopback được chuyển thủ công từ trình duyệt người dùng. Chỉ scope drive.file; token lưu private ngoài Output, không trả qua status và không đưa vào backup. Colab giữ mount native. API key/service account JSON không thay Desktop OAuth JSON. Luôn có Tải về máy nếu không muốn cấu hình OAuth.

166 kiểm thử CPU đạt. Chromium cục bộ kiểm tra đăng nhập Web, giao diện kết nối Drive, PKCE, TXT/EPUB/audio export qua OAuth/upload giả lập, tải file và mobile. Không đăng nhập Google thật, không upload cloud thật, không chạy Kaggle/Cloudflare/GPU thật. Chưa khẳng định vượt qua chính sách riêng của từng Google account/Cloud project.

Nguồn chuẩn OAuth: https://developers.google.com/identity/protocols/oauth2/native-app . Chuyển toàn bộ URL callback thủ công là phần tích hợp remote notebook của dự án, không phải mount hoặc listener tự động trên máy người dùng.
