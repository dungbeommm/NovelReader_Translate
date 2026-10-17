"""First-run setup: install deps and pre-download the DEFAULT model into ./models/.

Chỉ tải sẵn 1 model mặc định (bản CT2 INT8) để app dùng được ngay sau setup.
Các model khác trong danh sách sẽ tự tải khi người dùng chọn dịch lần đầu
(lazy-download), nên thêm bao nhiêu model vào list cũng không làm setup nặng thêm.
"""

from __future__ import annotations

from translation.core.translator import (
    DEFAULT_MODEL_KEY,
    MODELS,
    MODELS_DIR,
    Backend,
    HachimiTranslator,
    ensure_model_files,
)

WARMUP_TEXT = "他抬头看向远处的山门。"


def main() -> None:
    print(f"Thư mục model: {MODELS_DIR.resolve()}\n")

    config = MODELS[DEFAULT_MODEL_KEY]
    size = f"~{config.ct2_size_mb} MB" if config.ct2_size_mb else "bản CT2"
    print(f"Tải model mặc định: {DEFAULT_MODEL_KEY} ({size}, CT2 INT8)...")
    path = ensure_model_files(config, Backend.CT2)
    print(f"  ✓ {path.name} → {path}")

    print(f"\n=== Warmup {DEFAULT_MODEL_KEY} (CTranslate2) ===")
    translator = HachimiTranslator()
    print(translator.load(DEFAULT_MODEL_KEY, backend=Backend.CT2))
    rows, _ = translator.translate_text(WARMUP_TEXT, beam_size=1)
    print(f"OK: {rows[0][2]}")

    others = [k for k in MODELS if k != DEFAULT_MODEL_KEY]
    print(f"\nSetup hoàn tất. Model lưu tại: {MODELS_DIR.resolve()}")
    print(f"Đã tải sẵn: {DEFAULT_MODEL_KEY} (CT2). Dùng được ngay.")
    if others:
        print(f"Các model khác ({', '.join(others)}) sẽ tự tải khi bạn chọn dịch lần đầu.")
    print("Engine PyTorch là tùy chọn: cài torch + requirements-pytorch.txt trước khi dùng.")
    print("Chạy app: start.bat (Windows) hoặc ./start_macos.sh (macOS)")


if __name__ == "__main__":
    main()
