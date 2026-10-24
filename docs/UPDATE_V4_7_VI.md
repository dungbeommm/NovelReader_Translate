# v4.7 — Giám sát tài nguyên, dịch và audio

## Thanh dưới
- Bên trái: năm vòng hiển thị % CPU, GPU, VRAM, RAM và Đĩa; màu xanh dương, tím, cam, xanh ngọc và vàng. Bấm cụm vòng để mở tài nguyên chi tiết.
- Bên phải: tóm tắt dịch và audio với thanh tiến trình. Bấm để mở bảng tác vụ. Trên điện thoại hai cụm xếp thành hai hàng để không tràn ngang.
- Giữ bố cục nguồn truyện/cấu hình bên trái và khung đọc song song. Popup có nút đóng, Escape, cuộn nội dung độc lập và trở lại đầu khi mở lại.

## Tài nguyên lấy từ đâu?
Mọi số liệu lấy từ máy/backend đang chạy tool (local, Molab, Colab…), **không phải điện thoại/máy đang mở Web**.
- CPU: phần trăm tải chung của các CPU logic khả kiến qua psutil; không phải phần trăm riêng tác vụ dịch và không phải mức GPU.
- RAM: ưu tiên hạn mức/sử dụng cgroup v2/v1 khi container có giới hạn thấp hơn RAM host; nếu không đọc được thì dùng tổng bộ nhớ khả kiến của hệ điều hành. Có thêm RSS của tiến trình Web trong phần Phạm vi đo.
- GPU: NVIDIA qua `nvidia-smi`, mỗi thiết bị có tên, tải và VRAM đã dùng/tổng. Vòng GPU dùng trung bình các GPU đọc được; vòng VRAM dùng tổng dung lượng dùng/tổng dung lượng đọc được. Không gán 0 cho thiết bị không đo được.
- Đĩa (người dùng thường gọi ROM): filesystem chứa dữ liệu. Không phải bộ nhớ chỉ đọc hay quota/giới hạn thuê bao nhà cung cấp. Các thư mục dữ liệu/audio/text trên cùng filesystem chỉ tính một lần; filesystem khác có thêm thông tin trong phần Phạm vi đo.
- Có đỉnh sử dụng kể từ khi server mở. GPU AMD/Apple và môi trường không có quyền/nvidia-smi sẽ hiện dấu “—”, không giả báo 0%.

Lấy mẫu nền mục tiêu khoảng 2 giây, có timeout NVIDIA 2 giây; đọc API dùng cache, không gọi nvidia-smi cho mỗi khách Web. Mất kết nối hoặc mẫu cũ quá 10 giây thì vòng và giá trị hiện tại chuyển thành “—”. Đỉnh phiên và cấu hình đã biết có thể còn hiển thị nhưng luôn được ghi nhãn.

## Đo dịch chương
- % theo số ký tự nguồn không kể khoảng trắng trong các segment đã hoàn tất so với toàn chương, gồm tiêu đề. Có xét phần đã hoàn tất từ checkpoint.
- Tốc độ ký tự/giây = ký tự mới hoàn tất / tổng thời gian gọi engine thành công của chương. Không phải từ/giây hoặc token/giây; không cộng phần đã có từ checkpoint vào tử số tốc độ.
- Thời gian chương là thời gian thực gồm cả chờ/tạm dừng/hậu kỳ. Ước lượng còn lại dựa vào tốc độ batch, không gồm thời gian chờ audio hoặc nạp model, không phải cam kết.
- Cập nhật sau batch thật. Chương chỉ có một batch có thể nhảy từ 0 lên 100%, không chạy phần trăm giả trong lúc engine chưa trả kết quả.
- Bảng hiện chương đang dịch hoặc chương đo cuối cùng, số chương hoàn tất trong phạm vi. Khi dừng/lỗi, không tự gán 100%.

## Đo audio từng chương
- Theo dõi hàng đợi, nạp model, chờ bộ đọc, tổng hợp, mã hóa, hoàn tất/lỗi/hủy.
- Piper: đếm sau mỗi nhóm văn bản tổng hợp thành công.
- VieNeu: chia nhóm ngoài tối đa 4.000 ký tự để đo thật; mỗi nhóm vẫn dùng SDK với `batch_size` đã chọn và model dùng chung. Khác bản trước gọi SDK một lần cho cả chương; ranh giới nhóm có thể ảnh hưởng nhịp nối. Không phải callback tiến trình nội bộ của từng token SDK.
- % dựa vào ký tự nhóm TTS hoàn tất. Giữ tối đa 99% trong lúc mã hóa, chỉ 100% sau khi tệp cuối xuất bản thành công. Đây không phải tỷ lệ thời gian xử lý; mã hóa lâu không làm % chạy tự động.
- Tốc độ tạo = giây audio đã tổng hợp / giây xử lý thực. Ví dụ 2× thời gian thực nghĩa là tạo được khoảng 2 giây âm thanh trong 1 giây xử lý. RTF là chiều ngược lại; RTF nhỏ hơn 1 là nhanh hơn thời gian thực.
- Có ký tự/giây, thời gian đã xử lý, độ dài âm thanh, thời gian tạo xong và giờ kết thúc. Độ dài lấy từ số khung PCM và tốc độ đọc; định dạng nén có thể có phần đệm encoder nhỏ.
- Áp dụng cho cả pipeline dịch + audio và nút Tạo Audio từng chương. Nhiều worker có bộ đếm độc lập, không trộn tiến độ.
- Lịch sử tối đa 200 chương audio trong **phiên server hiện tại**, mỗi chương giữ lượt đo mới nhất. Tải lại Web vẫn đọc phiên hiện tại; khởi động lại server xóa lịch sử đo. Chưa ghi lịch sử thời gian vào checkpoint. Audio cũ không có đo sẽ không được gán thời gian giả.

## Chạy bản mới
- Dùng Molab `NovelReader_Molab.py` hoặc `NovelReader_Molab_v4.7.py` gửi riêng; Colab dùng notebook trong ZIP.
- Hai notebook và ZIP GPU lồng trong gói đều tích hợp cùng nguồn v4.7. Thêm phụ thuộc nhẹ `psutil` (Molab kiểm tra/cài cả khi runtime đã có các thư viện cũ).
- Local: cài lại `pip install -r requirements.txt`, khởi động server mới. Một worker Web như cấu hình mặc định; telemetry là trạng thái trong tiến trình, không hỗ trợ chia nhiều worker Uvicorn.
- Sao lưu checkpoint trước khi nâng cấp; không chép đè dữ liệu/model khi tác vụ đang chạy.

## Kiểm chứng
Kiểm thử schema/luồng cũ và mới; đồng thời nhiều audio, cập nhật batch, lỗi/hủy, thiếu GPU, cgroup RAM, giới hạn lịch sử, API vẫn đọc được trong lúc Tạo Audio giữ khóa job. Trình duyệt thử 3 chương với engine dịch/Piper giả lập có độ trễ và WAV thật, FFmpeg mã hóa thật; không có lỗi JS. Rà màn 1440×1000 và 390×844: vòng tài nguyên, popup, đang chạy/xong, dữ liệu trống, NVIDIA mẫu, mất kết nối và nội dung dài.

CPU/RAM/đĩa đo thật trong môi trường kiểm thử; GPU được kiểm thử bằng phản hồi NVIDIA mẫu. Chưa chạy inference neural/GPU hoặc đo hiệu năng trên Molab/Colab thật; số tốc độ từ bộ máy giả lập **không phải benchmark model**. Các giới hạn cloud/VieNeu của v4.5–v4.6 vẫn áp dụng.
