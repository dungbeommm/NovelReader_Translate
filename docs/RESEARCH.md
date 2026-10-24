# Xác minh nguồn HachimiMT

Ngày kiểm tra: 2026-10-17. Chỉ đọc/tải mã nguồn công khai và gọi một câu mẫu
ngắn; không sửa Space/model upstream, không gửi nội dung truyện riêng của người dùng.

1. Space README công bố `sdk: gradio`, `sdk_version: 6.18.0`, entrypoint `app.py`.
2. Root `app.py` thêm `src` vào import path rồi gọi `src/app.py`.
3. `src/translator.py` cấu hình `HachimiMT-60-QT` →
   `ngocdang83/HachimiMT-60-QT`, tokenizer SentencePiece, CT2 INT8.
4. Repo model API liệt kê `ct2-int8_float32/model.bin`, `config.json`,
   `shared_vocabulary.json`, `source.spm`, `target.spm`; tokenizer gốc cũng ở root.
   Model card công bố **CC-BY-4.0**; kiểm tra điều kiện attribution khi phân phối.
5. `gradio_client.Client(...).view_api(return_format='dict')` trả
   `/translate_text_ui` với 12 input công khai, 6 output. Output index 2 là
   textbox bản dịch toàn văn. Xem JSON snapshot đi kèm; không giả định một REST
   `/translate` không tồn tại.
6. Local smoke: `你好。` → `Chào ngươi.`
7. Space smoke với glossary `林羽 -> Lâm Vũ`:
   `林羽站在山门前。` → `Lâm Vũ đứng trước sơn môn.`
8. Tìm được lỗi thật khi thử placeholder: local trả `Chương hai ⟦G1⟧�` cho
   `第二章 ⟦G1⟧`. Adapter đã kiểm tra cả ký tự lỗi và đếm placeholder, rồi fallback
   theo source-span; kết quả cuối không chứa U+FFFD.

URL nguồn:
- https://huggingface.co/spaces/ngocdang83/HachimiMT-demo/tree/main
- https://huggingface.co/spaces/ngocdang83/HachimiMT-demo/blob/main/README.md
- https://huggingface.co/spaces/ngocdang83/HachimiMT-demo/blob/main/src/app.py
- https://huggingface.co/spaces/ngocdang83/HachimiMT-demo/blob/main/src/translator.py
- https://huggingface.co/ngocdang83/HachimiMT-60-QT
- https://github.com/ngocdang8311/qt2

Không tái sử dụng nguyên khối code upstream: adapter rút gọn được viết riêng,
không sao chép cả hệ thống postprocess/glossary của Space. Vì vậy output Local
có thể khác Space ở chuẩn hóa kính ngữ/đại từ; không tuyên bố bit-identical.
