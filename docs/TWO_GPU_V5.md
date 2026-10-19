# v5 — chia tải tối đa hai GPU

## Đã thay đổi
Tự dò GPU trong notebook; chọn tối đa hai GPU logic theo CUDA_VISIBLE_DEVICES. CT2 có hai bản sao model và bộ chia việc tường minh (số đoạn chênh tối đa một, cân bằng thêm token). Cả core và fallback loader đều dùng cơ chế này. CT2 fallback không sử dụng core tải dở.

Piper Web có một session/GPU, kiểm tra device_id thực tế sau cấu hình ORT, giữ chính sách cuDNN Conv1D và cấm runtime CPU fallback trong notebook. Đoạn audio tạo song song, dùng file/khóa riêng, ghép lại theo chỉ số gốc. Piper 1.8.0 được cố định vì phiên bản này có khóa eSpeak phonemization nội bộ.

Các phiên bản khác, UI tải xuống, xuất Drive, đăng nhập bằng mã và xóa bot giữ nguyên. Không đưa trọng số hoặc dữ liệu truyện vào ZIP.

## Kiểm thử
175 kiểm thử CPU đạt, gồm giả lập hai GPU: đếm/chọn 0–3 GPU, 96 đoạn chia 48/48, barrier chứng minh hai luồng chạy đồng thời, bảo toàn thứ tự, lỗi/OOM chờ các worker xong, core và fallback đều dùng hai GPU, Piper nạp đúng session 0/1, không cache pool tải dở, provider trỏ sai GPU bị từ chối, PCM ghép đúng thứ tự.

Trình duyệt Chromium cục bộ kiểm tra đăng nhập, nhãn hai GPU với phản hồi hardware giả lập, xuất TXT/EPUB/audio vào Drive giả lập, tải file và giao diện mobile. Không có hai GPU thật, Google OAuth thật hoặc Cloudflare thật để đo tốc độ, VRAM, kiểm chứng CUDA/cuDNN inference trong môi trường kiểm thử. Bước 4 notebook chạy inference thật để kiểm tra từng GPU trước khi mở Web.

## Sử dụng
Dừng ô Web cũ sau khi tác vụ hoàn tất. Dùng notebook v5, chạy bước 1–5. Bước 3 in `Phát hiện 2 GPU; dùng [0, 1] cho cả CT2 và Piper.` nếu runtime có hai GPU. Bước 4 kiểm tra CT2 và Piper trên thiết bị được chọn. Nếu chỉ có một T4, chương trình chạy một GPU; không thể tự cấp GPU thứ hai.

Theo dõi log `BALANCE CT2` và `BALANCE Piper`. RAM GPU không phải chỉ số % sử dụng GPU. Không đảm bảo cân bằng thời gian tuyệt đối hoặc gấp đôi tốc độ; chia theo token/ký tự chỉ là ước lượng tải.
