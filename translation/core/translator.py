"""HachimiMT Marian translation backend."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Callable, Iterator

import sentencepiece as spm
from huggingface_hub import snapshot_download

from translation.core.chunker import split_chunks
from translation.core.hardware import (
    HardwareProfile,
    auto_all_gpus_by_default,
    detect_hardware_profile,
    resolve_gpu_indices,
)
from translation.core.line_restore import (
    assemble_paragraph_output,
    assemble_sentence_output,
    paragraph_chunk_fallback_indices,
    split_layout_lines,
)
from translation.core.token_chunker import (
    source_token_ids,
    split_for_translation,
    split_paragraphs_with_plan,
    split_sentence_lines_with_plan,
)

from translation.core.ct2_safe_import import import_ctranslate2

ctranslate2 = import_ctranslate2()

ROOT = Path(__file__).resolve().parents[2]
from paths import translation_models
MODELS_DIR = translation_models()
SPECIAL_ID_TO_TOKEN = {0: "<pad>", 1: "<s>", 2: "</s>", 3: "<unk>"}
SPECIAL_TOKEN_TO_ID = {token: token_id for token_id, token in SPECIAL_ID_TO_TOKEN.items()}
EOS_TOKEN_ID = 2


class Backend(str, Enum):
    CT2 = "ct2"
    TRANSFORMERS = "transformers"


@dataclass(frozen=True)
class ModelConfig:
    label: str
    model_id: str
    use_marian_class: bool
    generate_kwargs: dict
    ct2_max_input_tokens: int
    ct2_max_output_tokens: int
    ct2_max_batch_size: int = 8
    default_beam: int = 2
    # Dung lượng xấp xỉ bản CT2 INT8 (MB) — chỉ để hiển thị badge "sẽ tải ~XMB".
    # Khai khi thêm model mới; để None thì badge chỉ hiện "chưa tải" không kèm số.
    ct2_size_mb: int | None = None
    # Tên thư mục con chứa bản CT2 trên repo HF. Mặc định "ct2-int8_float32";
    # một số repo dùng tên khác (vd "ct2-int8"), khai lại ở đây cho từng model.
    ct2_subdir: str = "ct2-int8_float32"
    # Nếu bản CT2 nằm ở repo khác với model gốc, khai riêng ở đây. PyTorch backend
    # vẫn tải từ model_id, còn CT2 tải từ repo này vào cùng thư mục cache local.
    ct2_model_id: str | None = None
    # Model train với quy ước "1 space giả sau dấu mở" (“ Khấu Hồng”): bật để gỡ
    # space đó khỏi output ngay tại ranh giới decode (invert_opener_spacing).
    # Model KHÔNG theo quy ước phải để False — invert bừa sẽ ăn mất space hợp lệ
    # sau dấu mở.
    opener_spacing: bool = False
    # Model train với marker xuống dòng trong vocab (piece SentencePiece
    # USER_DEFINED, vd "<NL>"): khai marker ở đây để tokenizer CT2 đổi "\n" của
    # chunk thành marker trước khi tokenize và đổi ngược lại sau khi decode →
    # chế độ "Theo đoạn" giữ xuống dòng do chính model sinh ra. None = model
    # không có marker: mọi đường tokenize/decode giữ nguyên như cũ.
    newline_token: str | None = None


# Quy ước opener-spacing (MT-zhvi-medium-train scripts/postprocess/
# opener_spacing.py — port NGUYÊN VĂN phép invert; cùng bảng dấu với webMT và
# vietphrase-app quotes.js). SPM metaspace không có piece "bare" cho hầu hết âm
# tiết VI nên từ mở thoại bị đánh vần; model train với 1 space sau dấu MỞ không
# nhập nhằng để từ đó đi đường piece `▁X` đã train tốt. Runtime gỡ đúng 1 space
# giữa dấu mở và CHỮ; số, dấu câu, quote thẳng và ≥2 space không đụng.
_OPENER_SPACING_OPENERS = "“‘«「『【《([{（［｛"
_OPENER_SPACING_INVERSE = re.compile(
    "([" + re.escape(_OPENER_SPACING_OPENERS) + r"]) (?=[^\W\d_])"
)


def invert_opener_spacing(text: str) -> str:
    if not text or not any(ch in _OPENER_SPACING_OPENERS for ch in text):
        return text
    return _OPENER_SPACING_INVERSE.sub(r"\1", text)


# Codec xuống dòng cho model có marker trong vocab (ModelConfig.newline_token).
# Port NGUYÊN VĂN 2 phép biến đổi của MT-zhvi-medium-train scripts/postprocess/
# joint_loop_codec.py (cùng hàm với hachimi40.py trên repo HF của model):
# encode gỡ space quanh "\n", thay bằng marker rồi chèn ĐÚNG 1 space sau marker
# (trừ khi theo sau là marker khác hoặc hết chuỗi) để từ kế tiếp vẫn đi đường
# piece `▁X`; decode đổi marker (kèm space ngang hai bên) về "\n".
@lru_cache(maxsize=8)
def _newline_marker_patterns(marker: str) -> tuple[re.Pattern[str], re.Pattern[str]]:
    escaped = re.escape(marker)
    return (
        re.compile(escaped + r"(?!" + escaped + r"|$)"),
        re.compile(r"[^\S\n]*" + escaped + r"[^\S\n]*"),
    )


def encode_newline_marker(text: str, marker: str) -> str:
    if marker in text:
        # Người dùng gõ sẵn đúng chuỗi marker: tách ra để không thành xuống dòng giả.
        text = text.replace(marker, marker[0] + " " + marker[1:])
    if "\n" not in text and "\r" not in text:
        return text
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[^\S\n]*\n[^\S\n]*", marker, text)
    return _newline_marker_patterns(marker)[0].sub(marker + " ", text)


def decode_newline_marker(text: str, marker: str) -> str:
    if marker not in text:
        return text
    return _newline_marker_patterns(marker)[1].sub("\n", text)


MODELS: dict[str, ModelConfig] = {
    "HachimiMT-60": ModelConfig(
        label="HachimiMT-60",
        model_id="ngocdang83/HachimiMT-60-zh-vi",
        use_marian_class=True,
        generate_kwargs={
            "max_new_tokens": 300,
            # BỎ no_repeat_ngram_size=2 (đo 2026-06-26, entity-drift probe): cùng
            # lý do MoxhiMT-60 — =2 cấm cứng tên 2-token lặp → entity DRIFT. beam=2
            # tự chống lặp không phạt tên. Drift 36.1%→9.7%; stutter không tăng.
            # Giữ repetition_penalty (cô lập: vô tội với drift, lưới chống lặp nhẹ).
            # Xem docs/runs/2026-06-26-entity-drift-6model-decode-not-arch.md.
            "repetition_penalty": 1.2,
        },
        # Cap 160 (đồng đều như HachimiMT-30): model nhỏ drift tên riêng trên chunk
        # dài, nhất là chế độ "Theo đoạn" (gom dòng). Đo 1-knob (HMT-60, file dày
        # tên riêng): paragraph cap 256 mất 13 tên đúng vs "Theo câu", cap 160 mất
        # 8 → 160 giảm thiệt hại. "Theo câu" (mặc định) không đổi (mỗi dòng ngắn ≤
        # cap = 1 chunk; chỉ dòng rất dài bị char-split nhỏ hơn, tự ghép lại 1 dòng).
        ct2_max_input_tokens=160,
        ct2_max_output_tokens=300,
        default_beam=2,
        ct2_size_mb=57,
    ),
    "HachimiMT-60-QT": ModelConfig(
        label="HachimiMT-60-QT",
        model_id="ngocdang83/HachimiMT-60-QT",
        use_marian_class=True,
        generate_kwargs={
            "max_new_tokens": 300,
            # QT-register variant: same 60M Marian family as HachimiMT-60, but
            # targets are normalized toward ta/nguoi/han/nang. Keep the 60M
            # decode profile and DO NOT add no_repeat_ngram_size: 711d70e showed
            # no_repeat causes duplicate-name entity drift. repetition_penalty
            # was isolated as safe there.
            "repetition_penalty": 1.2,
        },
        ct2_max_input_tokens=160,
        ct2_max_output_tokens=300,
        default_beam=2,
        ct2_size_mb=58,
    ),
    "HachimiMT-40-QT": ModelConfig(
        label="HachimiMT-40-QT",
        model_id="ngocdang83/HachimiMT-40-QT",
        use_marian_class=True,
        generate_kwargs={
            "max_new_tokens": 256,
            # Cấu hình decode ĐÃ ĐO của model này: greedy + repetition_penalty
            # 1.05, KHÔNG no_repeat_ngram_size (cùng lý do 711d70e: cấm n-gram
            # gây drift tên lặp). 1.2 như dòng 60M chưa đo trên model này.
            "repetition_penalty": 1.05,
        },
        # Encoder 4 lõi dùng chung × 3 vòng (12 lượt), giọng QT ta/ngươi/hắn/nàng.
        # Tokenizer joint ZH/VI RIÊNG (không dùng chung với 30-QT/60-QT) có marker
        # "<NL>": chunk nhiều dòng ("Theo đoạn") được model trả về kèm xuống dòng.
        # Cap 160 đồng đều như các model khác (model đo tới 256, chưa đo drift
        # tên riêng ở chunk dài trong app này nên giữ mức thận trọng).
        ct2_max_input_tokens=160,
        ct2_max_output_tokens=256,
        default_beam=1,
        ct2_size_mb=43,
        opener_spacing=True,
        newline_token="<NL>",
    ),
    "HachimiMT-30": ModelConfig(
        label="HachimiMT-30",
        model_id="ngocdang83/HachimiMT-30-zh-vi",
        use_marian_class=False,
        generate_kwargs={
            "max_length": 512,
        },
        # Input cap 160 (KHÔNG 512/256): model 37M scratch không giữ nổi context dài.
        # Đo thực (sweep 512/256/160/câu trên đoạn dày entity): entity khớp 42%/62%/
        # 94%/83%. 256 chunk-đầu vẫn VỠ nửa sau (lặp loạn). 160 = điểm ngọt: mỗi
        # chunk ~165 token, đủ ngắn để không vỡ + đủ context giữ nhất quán tên riêng.
        # Câu-thuần (context tối thiểu) NGƯỢC lại hại: 苍梧城→"Thương Ngô thành" (mất
        # context → 城 dịch thành danh từ). Đường cong chữ U, 160 đáy. Output giữ 512.
        ct2_max_input_tokens=160,
        ct2_max_output_tokens=512,
        default_beam=1,
        ct2_size_mb=35,
    ),
    "MoxhiMT-60": ModelConfig(
        label="MoxhiMT-60",
        model_id="DanVP/MoxhiMT-60",
        use_marian_class=True,
        generate_kwargs={
            "max_new_tokens": 300,
            # BỎ no_repeat_ngram_size=2 (đo 2026-06-26, entity-drift probe): =2 cấm
            # cứng tên 2-token lặp → entity DRIFT (vd 墨画→"Mặc Hoạ" rồi "Mặc Họa").
            # beam=2 (default_beam) đã tự chống lặp tốt mà KHÔNG phạt tên đáng-lặp.
            # Drift 38.9%→6.9%; stutter short-source không tăng (câu lặp thật như
            # "钱呢？钱呢？" vẫn dịch đúng "Tiền đâu? Tiền đâu?"). Giữ repetition_penalty
            # (đo cô lập: VÔ TỘI với drift, vẫn là lưới chống lặp nhẹ an toàn).
            # Xem docs/runs/2026-06-26-entity-drift-6model-decode-not-arch.md.
            "repetition_penalty": 1.2,
        },
        # Cap 160 đồng đều (xem HachimiMT-60): cùng bệnh drift tên riêng trên chunk
        # dài; 160 giảm thiệt hại chế độ "Theo đoạn", không hại "Theo câu".
        ct2_max_input_tokens=160,
        ct2_max_output_tokens=300,
        default_beam=2,
        ct2_size_mb=58,
        ct2_subdir="ct2-int8",  # repo này dùng tên thư mục CT2 khác
    ),
    "MoxhiMT-30": ModelConfig(
        label="MoxhiMT-30",
        model_id="DanVP/MoxhiMT-30",
        use_marian_class=True,
        generate_kwargs={
            "max_new_tokens": 300,
            # BỎ no_repeat_ngram_size (đo 2026-06-26, entity-drift probe 72 câu):
            # =2 CẤM CỨNG tên 2-token lặp (vd [Mặc][Hoạ]) → decoder buộc viết lại
            # khác đi lần 2 ("Mặc Họa", mất dấu) = entity DRIFT. Nâng default_beam
            # 1→2: beam=2 tự chống lặp KHÔNG phạt tên đáng-lặp. Đo @beam=2: bỏ
            # no_repeat → drift 6.9% (giữ no_repeat=3 vẫn 23.6%); stutter short =0
            # (ca "钱呢？钱呢？"→"Tiền đâu? Tiền đâu?" là lặp ĐÚNG nguồn). repetition_penalty
            # giữ (cô lập: VÔ TỘI với drift, lưới chống lặp nhẹ). Đánh đổi: beam=2
            # chậm hơn beam=1 ~1.5×, user chấp nhận để cắt drift sâu.
            # Xem docs/runs/2026-06-26-entity-drift-6model-decode-not-arch.md.
            "repetition_penalty": 1.2,
        },
        # 30M model drifts/hallucinates on dense paragraph chunks. Keep the
        # source cap short enough to split long entity-heavy paragraphs.
        ct2_max_input_tokens=160,
        ct2_max_output_tokens=512,
        default_beam=2,
        ct2_size_mb=38,
    ),
    "MoxhiMT-30-QT": ModelConfig(
        label="MoxhiMT-30-QT",
        model_id="DanVP/MoxhiMT-30-QT",
        use_marian_class=True,
        generate_kwargs={
            "max_new_tokens": 300,
            # QT-register variant: same 37M Marian family as MoxhiMT-30, but
            # targets are normalized toward ta/nguoi/han/nang. Keep the short
            # 30M input cap and DO NOT add no_repeat_ngram_size: 711d70e showed
            # no_repeat causes duplicate-name entity drift. repetition_penalty
            # was isolated as safe there. Default beam stays 1 because this model
            # is meant as a simple stable-pronoun option.
            "repetition_penalty": 1.2,
        },
        ct2_max_input_tokens=160,
        ct2_max_output_tokens=512,
        default_beam=1,
        ct2_size_mb=38,
        # v1.1 (2026-09-21, kinfix F600): 我/你 → ta/ngươi theo chữ nguồn thay vì
        # đoán quan hệ (em/muội/chàng/con) khi câu có hô ngữ 师姐/哥/娘…; dòng
        # train này theo quy ước opener-spacing. Bật với weights v1.0 cũng vô hại
        # (v1.0 gần như không sinh "dấu mở + space + chữ").
        opener_spacing=True,
    ),
    "HirashibaMT-Medium": ModelConfig(
        label="HirashibaMT-Medium",
        model_id="Moleys/hirashiba-mt-medium",
        use_marian_class=True,
        generate_kwargs={
            "max_new_tokens": 256,
        },
        ct2_max_input_tokens=128,
        ct2_max_output_tokens=256,
        default_beam=4,
        ct2_size_mb=62,
        ct2_model_id="ngungodan/hirashiba-mt-medium-ct2",
    ),
    "HirashibaMT-Tiny": ModelConfig(
        label="HirashibaMT-Tiny",
        model_id="chi-vi/hirashiba-mt-tiny-zh-vi",
        use_marian_class=True,
        generate_kwargs={
            "max_length": 512,
        },
        # Tiny uses a 4-layer Marian model. Keep paragraph chunks short and use
        # greedy/low-beam decoding; higher beams can introduce light duplicates.
        ct2_max_input_tokens=160,
        ct2_max_output_tokens=512,
        default_beam=1,
        ct2_size_mb=17,
        ct2_subdir="ct2-int8-keeppad",
        ct2_model_id="ngungodan/hirashiba-mt-tiny-zh-vi-ct2",
    ),
}

# Model tải sẵn khi chạy setup (dùng được ngay); các model khác lazy-download.
DEFAULT_MODEL_KEY = "HachimiMT-60"

# Thư mục CT2 mặc định; model nào khác thì khai ModelConfig.ct2_subdir.
DEFAULT_CT2_SUBDIR = "ct2-int8_float32"


def _ct2_download_patterns(config: ModelConfig) -> list[str]:
    return [
        "config.json",
        "generation_config.json",
        "source.spm",
        "target.spm",
        "tokenizer.json",
        "vocab.json",
        "tokenizer_config.json",
        f"{config.ct2_subdir}/*",
    ]


def _ct2_repo_id(config: ModelConfig) -> str:
    return config.ct2_model_id or config.model_id


SourceTokenJobs = list[Future[list[list[str]]]]


def _env_int(name: str, default: int, *, min_value: int = 1, max_value: int = 1024) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(min_value, min(max_value, int(raw)))
    except ValueError:
        return default


def _batched(items: list[str], size: int) -> Iterator[list[str]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def default_ct2_window_multiplier(profile: HardwareProfile) -> int:
    """Choose the CT2 input window before any env override is applied."""
    if profile.has_cuda:
        return 16
    return 4


def default_ct2_compute_type(device: str) -> str:
    env_compute_type = os.environ.get("HACHIMIMT_COMPUTE_TYPE", "").strip()
    if env_compute_type:
        return env_compute_type
    return "int8_float16" if device == "cuda" else "int8_float32"


def _ct2_gpu_index_attempts(gpu_indices: list[int]) -> list[list[int]]:
    """Try all requested GPUs first, then one GPU before giving up to CPU."""
    if len(gpu_indices) <= 1:
        return [list(gpu_indices)]
    return [list(gpu_indices), [gpu_indices[0]]]


def _ct2_translator_kwargs(
    *,
    device: str,
    compute_type: str,
    intra_threads: int,
    inter_threads: int,
    gpu_indices: list[int] | None = None,
) -> tuple[dict[str, object], int, str | None]:
    actual_inter_threads = max(1, int(inter_threads))
    requested_intra_threads = max(1, int(intra_threads))
    kwargs: dict[str, object] = dict(
        device=device,
        compute_type=compute_type,
        inter_threads=actual_inter_threads,
    )
    worker_count = actual_inter_threads
    device_indices_label = None
    if device != "cuda":
        kwargs["intra_threads"] = max(1, requested_intra_threads // worker_count)
        return kwargs, worker_count, device_indices_label

    if not gpu_indices:
        raise RuntimeError("Không có GPU CUDA khả dụng.")

    selected = list(dict.fromkeys(gpu_indices))
    if len(selected) == 1:
        # Luôn truyền device_index, kể cả single GPU: env "1" phải dùng GPU 1.
        kwargs["device_index"] = selected[0]
    else:
        # CT2 inter_threads = replica trên MỖI device. Với nhiều GPU, giữ 1
        # replica/GPU để tránh nhân VRAM và đã nhanh hơn trong benchmark T4x2.
        kwargs["device_index"] = selected
        kwargs["inter_threads"] = 1

    actual_inter_threads = int(kwargs["inter_threads"])
    worker_count = len(selected) * actual_inter_threads
    kwargs["intra_threads"] = max(1, requested_intra_threads // worker_count)
    device_indices_label = ",".join(str(i) for i in selected)
    return kwargs, worker_count, device_indices_label


@lru_cache(maxsize=1)
def _torch_import_probe_ok(timeout_s: float = 8.0) -> bool:
    code = "import torch"
    try:
        result = subprocess.run(
            [sys.executable, "-c", code],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout_s,
        )
    except Exception:
        return False
    return result.returncode == 0


@lru_cache(maxsize=1)
def _optional_torch():
    if "torch" not in sys.modules and not _torch_import_probe_ok():
        return None
    try:
        import torch
    except Exception:
        return None
    return torch


def _require_torch():
    # An explicitly requested accelerator may need more than the optional
    # startup probe's eight seconds on its first Windows DLL load.
    if os.getenv("HACHIMIMT_TORCH_DEVICE", "auto").strip().lower() == "xpu":
        try:
            import torch
        except ImportError as exc:
            raise RuntimeError("XPU cần PyTorch Intel GPU trong môi trường đang chạy.") from exc
    else:
        torch = _optional_torch()
    if torch is None:
        raise RuntimeError(
            "Backend PyTorch cần cài torch. Engine mặc định CTranslate2 không cần torch. "
            "Nếu muốn dùng PyTorch, cài torch rồi cài: pip install -r requirements-pytorch.txt"
        )
    return torch


def _select_torch_device(torch) -> str:
    requested = os.getenv("HACHIMIMT_TORCH_DEVICE", "auto").strip().lower()
    if requested not in {"auto", "cpu", "cuda", "xpu"}:
        raise ValueError("HACHIMIMT_TORCH_DEVICE phải là auto/cpu/cuda/xpu.")
    if requested == "cpu":
        return "cpu"
    if requested != "auto":
        runtime = getattr(torch, requested, None)
        if runtime is None or not runtime.is_available():
            raise RuntimeError(f"PyTorch không thấy thiết bị {requested}; không chuyển sang CPU.")
        return requested
    try:
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def _torch_cuda_available() -> bool:
    torch = _optional_torch()
    if torch is None:
        return False
    try:
        return bool(torch.cuda.is_available())
    except Exception:
        return False


def _torch_cuda_device_name() -> str | None:
    torch = _optional_torch()
    if torch is None:
        return None
    try:
        if torch.cuda.is_available():
            return str(torch.cuda.get_device_name(0))
    except Exception:
        return None
    return None


def _torch_empty_cuda_cache() -> None:
    torch = _optional_torch()
    if torch is None:
        return
    try:
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        return


class CT2SentencePieceTokenizer:
    """Minimal Marian SentencePiece tokenizer for CTranslate2 inference."""

    pad_token_id = 0

    def __init__(self, model_path: Path, newline_token: str | None = None) -> None:
        self._source_sp = spm.SentencePieceProcessor(model_file=str(model_path / "source.spm"))
        self._target_sp = spm.SentencePieceProcessor(model_file=str(model_path / "target.spm"))
        self._newline_token = newline_token
        if newline_token is not None:
            # Marker phải là MỘT piece thật ở cả hai phía; nếu không (nhầm
            # tokenizer của model khác) thì fail ngay lúc nạp thay vì dịch sai.
            for side, processor in (("source", self._source_sp), ("target", self._target_sp)):
                if processor.piece_to_id(newline_token) == processor.unk_id():
                    raise RuntimeError(
                        f"Tokenizer {side}.spm không có piece xuống dòng {newline_token!r}."
                    )
        self._encode_cache_max = _env_int(
            "HACHIMIMT_TOKEN_CACHE_SIZE",
            0,
            min_value=0,
            max_value=500_000,
        )
        self._encode_cache: OrderedDict[str, list[int]] = OrderedDict()
        self._cache_hits = 0
        self._cache_misses = 0

    def _full_encode_one(self, text: str) -> list[int]:
        if self._encode_cache_max > 0:
            cached = self._encode_cache.get(text)
            if cached is not None:
                self._encode_cache.move_to_end(text)
                self._cache_hits += 1
                return list(cached)

        self._cache_misses += 1
        source = text
        if self._newline_token is not None:
            source = encode_newline_marker(text, self._newline_token)
        token_ids = list(self._source_sp.encode(source, out_type=int))
        token_ids.append(EOS_TOKEN_ID)
        if self._encode_cache_max > 0:
            self._encode_cache[text] = list(token_ids)
            self._encode_cache.move_to_end(text)
            while len(self._encode_cache) > self._encode_cache_max:
                self._encode_cache.popitem(last=False)
        return token_ids

    def cache_stats(self) -> dict[str, int]:
        return {
            "token_cache_entries": len(self._encode_cache),
            "token_cache_hits": self._cache_hits,
            "token_cache_misses": self._cache_misses,
        }

    def _encode_one(
        self,
        text: str,
        *,
        truncation: bool = False,
        max_length: int | None = None,
    ) -> list[int]:
        token_ids = self._full_encode_one(text)
        if truncation and max_length is not None and len(token_ids) > max_length:
            token_ids = token_ids[:max_length]
            if token_ids:
                token_ids[-1] = EOS_TOKEN_ID
        return token_ids

    def __call__(
        self,
        text_or_texts: str | list[str],
        *,
        truncation: bool = False,
        max_length: int | None = None,
        padding: bool = False,
    ) -> dict[str, list[int] | list[list[int]]]:
        del padding
        if isinstance(text_or_texts, str):
            return {
                "input_ids": self._encode_one(
                    text_or_texts,
                    truncation=truncation,
                    max_length=max_length,
                )
            }
        return {
            "input_ids": [
                self._encode_one(text, truncation=truncation, max_length=max_length)
                for text in text_or_texts
            ]
        }

    def convert_ids_to_tokens(self, token_ids: list[int]) -> list[str]:
        tokens: list[str] = []
        for token_id in token_ids:
            if token_id in SPECIAL_ID_TO_TOKEN:
                tokens.append(SPECIAL_ID_TO_TOKEN[token_id])
            else:
                tokens.append(self._source_sp.id_to_piece(int(token_id)))
        return tokens

    def convert_tokens_to_ids(self, tokens: list[str]) -> list[int]:
        token_ids: list[int] = []
        for token in tokens:
            if token in SPECIAL_TOKEN_TO_ID:
                token_ids.append(SPECIAL_TOKEN_TO_ID[token])
            else:
                token_ids.append(int(self._target_sp.piece_to_id(token)))
        return token_ids

    def decode(self, token_ids: list[int], *, skip_special_tokens: bool = True) -> str:
        return self.batch_decode([token_ids], skip_special_tokens=skip_special_tokens)[0]

    def batch_decode(
        self,
        token_ids_batch: list[list[int]],
        *,
        skip_special_tokens: bool = True,
    ) -> list[str]:
        decoded: list[str] = []
        for token_ids in token_ids_batch:
            if skip_special_tokens:
                token_ids = [
                    token_id
                    for token_id in token_ids
                    if token_id not in SPECIAL_ID_TO_TOKEN
                ]
            pieces = [self._target_sp.id_to_piece(int(token_id)) for token_id in token_ids]
            decoded.append(self._restore_newlines(self._target_sp.decode(pieces)))
        return decoded

    def _restore_newlines(self, text: str) -> str:
        if self._newline_token is None:
            return text
        return decode_newline_marker(text, self._newline_token)

    def decode_tokens_batch(self, tokens_batch: list[list[str]]) -> list[str]:
        decoded: list[str] = []
        for tokens in tokens_batch:
            pieces = [token for token in tokens if token not in SPECIAL_TOKEN_TO_ID]
            decoded.append(self._restore_newlines(self._target_sp.decode(pieces)).strip())
        return decoded


class CT2FastTokenizer:
    """Minimal tokenizer.json wrapper for CTranslate2 inference."""

    def __init__(self, model_path: Path) -> None:
        try:
            from tokenizers import Tokenizer
        except Exception as exc:
            raise RuntimeError(
                "Model này dùng tokenizer.json; cần cài package tokenizers."
            ) from exc

        self._tokenizer = Tokenizer.from_file(str(model_path / "tokenizer.json"))
        self.pad_token_id = self._tokenizer.token_to_id("<pad>")
        self._eos_token_id = self._tokenizer.token_to_id("</s>")
        self._encode_cache_max = _env_int(
            "HACHIMIMT_TOKEN_CACHE_SIZE",
            0,
            min_value=0,
            max_value=500_000,
        )
        self._encode_cache: OrderedDict[str, list[int]] = OrderedDict()
        self._cache_hits = 0
        self._cache_misses = 0

    def _full_encode_one(self, text: str) -> list[int]:
        if self._encode_cache_max > 0:
            cached = self._encode_cache.get(text)
            if cached is not None:
                self._encode_cache.move_to_end(text)
                self._cache_hits += 1
                return list(cached)

        self._cache_misses += 1
        token_ids = list(self._tokenizer.encode(text).ids)
        if self._encode_cache_max > 0:
            self._encode_cache[text] = list(token_ids)
            self._encode_cache.move_to_end(text)
            while len(self._encode_cache) > self._encode_cache_max:
                self._encode_cache.popitem(last=False)
        return token_ids

    def cache_stats(self) -> dict[str, int]:
        return {
            "token_cache_entries": len(self._encode_cache),
            "token_cache_hits": self._cache_hits,
            "token_cache_misses": self._cache_misses,
        }

    def _encode_one(
        self,
        text: str,
        *,
        truncation: bool = False,
        max_length: int | None = None,
    ) -> list[int]:
        token_ids = self._full_encode_one(text)
        if truncation and max_length is not None and len(token_ids) > max_length:
            token_ids = token_ids[:max_length]
            if token_ids and self._eos_token_id is not None:
                token_ids[-1] = self._eos_token_id
        return token_ids

    def __call__(
        self,
        text_or_texts: str | list[str],
        *,
        truncation: bool = False,
        max_length: int | None = None,
        padding: bool = False,
    ) -> dict[str, list[int] | list[list[int]]]:
        del padding
        if isinstance(text_or_texts, str):
            return {
                "input_ids": self._encode_one(
                    text_or_texts,
                    truncation=truncation,
                    max_length=max_length,
                )
            }
        return {
            "input_ids": [
                self._encode_one(text, truncation=truncation, max_length=max_length)
                for text in text_or_texts
            ]
        }

    def convert_ids_to_tokens(self, token_ids: list[int]) -> list[str]:
        tokens: list[str] = []
        for token_id in token_ids:
            token = self._tokenizer.id_to_token(int(token_id))
            if token is None:
                raise ValueError(f"Token id không có trong vocab: {token_id}")
            tokens.append(token)
        return tokens

    def convert_tokens_to_ids(self, tokens: list[str]) -> list[int]:
        token_ids: list[int] = []
        for token in tokens:
            token_id = self._tokenizer.token_to_id(token)
            if token_id is None:
                raise ValueError(f"Token không có trong vocab: {token!r}")
            token_ids.append(int(token_id))
        return token_ids

    def decode(self, token_ids: list[int], *, skip_special_tokens: bool = True) -> str:
        return self.batch_decode([token_ids], skip_special_tokens=skip_special_tokens)[0]

    def batch_decode(
        self,
        token_ids_batch: list[list[int]],
        *,
        skip_special_tokens: bool = True,
    ) -> list[str]:
        return [
            self._tokenizer.decode(token_ids, skip_special_tokens=skip_special_tokens)
            for token_ids in token_ids_batch
        ]

    def decode_tokens_batch(self, tokens_batch: list[list[str]]) -> list[str]:
        token_ids_batch = [self.convert_tokens_to_ids(tokens) for tokens in tokens_batch]
        return [
            text.strip()
            for text in self.batch_decode(token_ids_batch, skip_special_tokens=True)
        ]


def _load_ct2_tokenizer(model_path: Path, newline_token: str | None = None):
    if (model_path / "source.spm").exists() and (model_path / "target.spm").exists():
        return CT2SentencePieceTokenizer(model_path, newline_token=newline_token)
    if newline_token is not None:
        raise RuntimeError("newline_token chỉ hỗ trợ tokenizer SentencePiece (source.spm/target.spm).")
    if (model_path / "tokenizer.json").exists():
        return CT2FastTokenizer(model_path)
    raise RuntimeError("Không tìm thấy tokenizer CT2: cần source.spm/target.spm hoặc tokenizer.json.")


def model_local_dir(config: ModelConfig) -> Path:
    return MODELS_DIR / config.model_id.split("/")[-1]


def _ct2_ready(path: Path, ct2_subdir: str = DEFAULT_CT2_SUBDIR) -> bool:
    # model.bin >0 byte, không phải "thư mục có file bất kỳ": download dở
    # (mất mạng/Ctrl-C) để lại file phụ → ready giả → CT2 crash khó hiểu.
    model_bin = path / ct2_subdir / "model.bin"
    try:
        return model_bin.is_file() and model_bin.stat().st_size > 0
    except OSError:
        return False


def _pytorch_ready(path: Path) -> bool:
    try:
        weight_files = [*path.glob("*.safetensors"), *path.glob("pytorch_model*.bin")]
        return any(f.is_file() and f.stat().st_size > 0 for f in weight_files)
    except OSError:
        return False


def _tokenizer_ready(path: Path) -> bool:
    has_sentencepiece = (path / "source.spm").exists() and (path / "target.spm").exists()
    return has_sentencepiece or (path / "tokenizer.json").exists()


def is_model_downloaded(model_key: str, backend: Backend | str = Backend.CT2) -> bool:
    """Model (theo backend) đã có sẵn trong MODELS_DIR chưa — để UI hiện badge.

    Dùng đúng điều kiện mà ensure_model_files() kiểm tra, nên kết quả khớp với
    việc bấm Dịch có phải tải hay không.
    """
    if isinstance(backend, str):
        backend = Backend(backend)
    if model_key not in MODELS:
        return False
    config = MODELS[model_key]
    path = model_local_dir(config)
    if backend == Backend.CT2:
        weights_ready = _ct2_ready(path, config.ct2_subdir)
    else:
        weights_ready = _pytorch_ready(path)
    return weights_ready and _tokenizer_ready(path)


def ensure_model_files(config: ModelConfig, backend: Backend) -> Path:
    """Download model vào MODELS_DIR nếu chưa có."""
    local_dir = model_local_dir(config)
    local_dir.mkdir(parents=True, exist_ok=True)

    if backend == Backend.CT2:
        if _ct2_ready(local_dir, config.ct2_subdir) and _tokenizer_ready(local_dir):
            return local_dir
        patterns = _ct2_download_patterns(config)
        repo_id = _ct2_repo_id(config)
    else:
        if _pytorch_ready(local_dir) and _tokenizer_ready(local_dir):
            return local_dir
        patterns = None
        repo_id = config.model_id

    snapshot_download(
        repo_id,
        local_dir=str(local_dir),
        allow_patterns=patterns,
    )
    return local_dir


def download_all_models(*, include_pytorch_weights: bool = False) -> list[Path]:
    """Tải trước tất cả model vào MODELS_DIR (dùng cho setup.bat).

    Mặc định chỉ tải bản CT2 INT8 (~95 MB tổng) vì đó là engine mặc định.
    PyTorch weights (~nặng gấp ~4 lần) chỉ tải khi include_pytorch_weights=True
    hoặc tự động khi người dùng đổi sang engine PyTorch lần đầu (ensure_model_files).
    """
    saved: list[Path] = []
    for config in MODELS.values():
        ensure_model_files(config, Backend.CT2)
        saved.append(model_local_dir(config))
        if include_pytorch_weights:
            ensure_model_files(config, Backend.TRANSFORMERS)
    return saved


class HachimiTranslator:
    def __init__(self, profile: HardwareProfile | None = None) -> None:
        self._profile = profile or detect_hardware_profile()
        self._torch_device = "cpu"
        self._model_key: str | None = None
        self._backend: Backend | None = None
        self._tokenizer = None
        self._torch_model = None
        self._ct2_model = None
        self._model_path: Path | None = None
        self._ct2_threads = self._profile.ct2_threads
        self._ct2_inter_threads = _env_int("HACHIMIMT_INTER_THREADS", 1, max_value=8)
        self._ct2_window_multiplier = _env_int(
            "HACHIMIMT_CT2_WINDOW_MULTIPLIER",
            default_ct2_window_multiplier(self._profile),
            max_value=16,
        )
        self._tokenize_job_size = _env_int("HACHIMIMT_TOKENIZE_JOB_SIZE", 32, max_value=256)
        batch_type = os.environ.get("HACHIMIMT_CT2_BATCH_TYPE", "tokens").strip().lower()
        self._ct2_batch_type = batch_type if batch_type in {"examples", "tokens"} else "tokens"
        self._ct2_compute_type: str | None = None
        self._ct2_actual_intra_threads = self._ct2_threads
        self._ct2_actual_inter_threads = self._ct2_inter_threads
        self._ct2_worker_count = 1
        self._ct2_device_indices_label: str | None = None
        self._batch_size = self._profile.batch_size
        self._tokenize_workers = self._profile.tokenize_workers
        self._tokenize_pool: ThreadPoolExecutor | None = None
        self._last_profile: dict[str, float | int | str] = {}

    @property
    def hardware_profile(self) -> HardwareProfile:
        return self._profile

    @property
    def batch_size(self) -> int:
        return self._batch_size

    @property
    def last_profile(self) -> dict[str, float | int | str]:
        return dict(self._last_profile)

    def _reset_profile(self) -> None:
        self._last_profile = {}

    def _profile_add(self, key: str, seconds: float) -> None:
        self._last_profile[key] = float(self._last_profile.get(key, 0.0)) + seconds

    def _profile_set(self, key: str, value: float | int | str) -> None:
        self._last_profile[key] = value

    def set_batch_size(self, batch_size: int) -> None:
        self._batch_size = max(4, min(128, int(batch_size)))

    def apply_hardware_profile(self, profile: HardwareProfile | None = None) -> None:
        profile = profile or detect_hardware_profile()
        threads_changed = profile.ct2_threads != self._ct2_threads
        workers_changed = profile.tokenize_workers != self._tokenize_workers
        self._profile = profile
        self._ct2_threads = profile.ct2_threads
        self._batch_size = profile.batch_size
        self._tokenize_workers = profile.tokenize_workers
        if workers_changed and self._tokenize_pool is not None:
            self._tokenize_pool.shutdown(wait=False, cancel_futures=True)
            self._tokenize_pool = None

        if threads_changed and self._backend == Backend.CT2 and self._model_key:
            model_key = self._model_key
            self._unload_models()
            self._load_ct2(MODELS[model_key])
            self._model_key = model_key
            self._backend = Backend.CT2

    @property
    def device(self) -> str:
        if self._backend == Backend.CT2 and self._ct2_model is not None:
            return self._ct2_model.device
        return self._torch_device

    def device_label(self) -> str:
        """Tên thiết bị inference thực tế (để phân biệt iGPU vs NVIDIA)."""
        if self.device == "cuda":
            if self._backend == Backend.TRANSFORMERS:
                return _torch_cuda_device_name() or self._profile.gpu_name or "CUDA GPU"
            return self._profile.gpu_name or "CUDA GPU"
        if self.device == "xpu":
            return f"Intel XPU · {_require_torch().xpu.get_device_name(0)}"
        return "CPU"

    @property
    def backend(self) -> Backend | None:
        return self._backend

    def load(self, model_key: str, backend: Backend | str = Backend.CT2) -> str:
        if isinstance(backend, str):
            backend = Backend(backend)

        if model_key not in MODELS:
            raise ValueError(f"Unknown model: {model_key}")

        if (
            self._model_key == model_key
            and self._backend == backend
            and self._tokenizer is not None
            and (self._ct2_model is not None or self._torch_model is not None)
        ):
            return self._status_message(model_key, backend, cached=True)

        config = MODELS[model_key]
        self._unload_models()

        if backend == Backend.CT2:
            self._load_ct2(config)
        else:
            self._load_transformers(config)

        self._model_key = model_key
        self._backend = backend

        # Warmup: dịch 1 câu để CT2/torch cấp phát buffer + nạp kernel. Cold-run
        # đầu rất chậm nếu không warmup → lần dịch đầu của user nhanh ngay + số đo
        # thời gian sạch (không gánh chi phí khởi tạo). Best-effort, không fatal.
        try:
            self.translate_chunk("你好。", beam_size=1)
        except Exception:  # noqa: BLE001 — warmup hỏng không được chặn load
            pass

        return self._status_message(model_key, backend, cached=False)

    def _status_message(
        self,
        model_key: str,
        backend: Backend,
        *,
        cached: bool,
        beam_size: int | None = None,
    ) -> str:
        prefix = "Model" if cached else "Đã tải"
        config = MODELS[model_key]
        engine = "CTranslate2 INT8" if backend == Backend.CT2 else "PyTorch"
        msg = f"{prefix} {config.label} · {engine} · {self.device_label()}"
        if backend == Backend.CT2 and self._ct2_compute_type:
            msg += f" · compute={self._ct2_compute_type}"
            window_multiplier = self._ct2_effective_window_multiplier()
            window_part = f"window={self._ct2_window_multiplier}x"
            if window_multiplier != self._ct2_window_multiplier:
                window_part += f"/{window_multiplier}x"
            msg += (
                f" · batch_type={self._ct2_batch_type}"
                f" · {window_part}"
                f" · intra={self._ct2_actual_intra_threads}"
                f" · inter={self._ct2_actual_inter_threads}"
            )
            if self._ct2_worker_count > 1:
                msg += f" · workers={self._ct2_worker_count}"
            if self._ct2_device_indices_label:
                msg += f" · gpu={self._ct2_device_indices_label}"
        if beam_size is not None:
            msg += f" · beam={beam_size}"
        return msg

    @staticmethod
    def clamp_beam(beam_size: int) -> int:
        return max(1, min(4, int(beam_size)))

    def _unload_models(self) -> None:
        self._torch_model = None
        self._ct2_model = None
        self._tokenizer = None
        self._model_path = None
        self._ct2_compute_type = None
        self._ct2_actual_intra_threads = self._ct2_threads
        self._ct2_actual_inter_threads = self._ct2_inter_threads
        self._ct2_worker_count = 1
        self._ct2_device_indices_label = None
        if self._tokenize_pool is not None:
            self._tokenize_pool.shutdown(wait=False, cancel_futures=True)
            self._tokenize_pool = None
        if self._torch_device == "cuda":
            _torch_empty_cuda_cache()
        elif self._torch_device == "xpu":
            _require_torch().xpu.empty_cache()

    def _get_tokenize_pool(self) -> ThreadPoolExecutor:
        if self._tokenize_pool is None:
            self._tokenize_pool = ThreadPoolExecutor(
                max_workers=self._tokenize_workers,
                thread_name_prefix="hachimi-tokenize",
            )
        return self._tokenize_pool

    def _tokenize_chunks_parallel(self, chunks: list[str]) -> list[list[str]]:
        if not chunks:
            return []
        if len(chunks) <= self._tokenize_job_size or self._tokenize_workers <= 1:
            return self._source_tokens_batch(chunks)
        pool = self._get_tokenize_pool()
        groups = list(_batched(chunks, self._tokenize_job_size))
        nested = pool.map(self._source_tokens_batch, groups)
        return [tokens for group in nested for tokens in group]

    def _submit_tokenize_jobs(self, chunks: list[str]) -> SourceTokenJobs:
        pool = self._get_tokenize_pool()
        return [
            pool.submit(self._source_tokens_batch, group)
            for group in _batched(chunks, self._tokenize_job_size)
        ]

    @staticmethod
    def _collect_tokenize_jobs(jobs: SourceTokenJobs) -> list[list[str]]:
        return [tokens for job in jobs for tokens in job.result()]

    def _finalize_outputs(self, texts: list[str]) -> list[str]:
        """Hậu xử lý theo model ở ranh giới decode — TRƯỚC line-restore/ghép dòng.

        Model không bật cờ nào: trả đúng list cũ, không copy, không đổi 1 byte.
        """
        config = MODELS.get(self._model_key) if self._model_key else None
        if config is None or not config.opener_spacing:
            return texts
        return [invert_opener_spacing(text) for text in texts]

    def _decode_ct2_results(self, results) -> list[str]:
        start = time.perf_counter()
        hypotheses = [result.hypotheses[0] for result in results]
        decode_tokens_batch = getattr(self._tokenizer, "decode_tokens_batch", None)
        if callable(decode_tokens_batch):
            decoded = self._finalize_outputs(decode_tokens_batch(hypotheses))
            self._profile_add("decode_s", time.perf_counter() - start)
            return decoded
        token_ids = [self._tokenizer.convert_tokens_to_ids(tokens) for tokens in hypotheses]
        decoded = self._finalize_outputs([
            text.strip()
            for text in self._tokenizer.batch_decode(token_ids, skip_special_tokens=True)
        ])
        self._profile_add("decode_s", time.perf_counter() - start)
        return decoded

    def _load_ct2(self, config: ModelConfig) -> None:
        model_path = ensure_model_files(config, Backend.CT2)
        tokenizer = _load_ct2_tokenizer(model_path, newline_token=config.newline_token)

        env_compute_type = os.environ.get("HACHIMIMT_COMPUTE_TYPE", "").strip()
        ct2_device = "cuda" if self._profile.has_cuda else "cpu"
        attempts: list[tuple[str, str, list[int] | None]] = []
        if ct2_device == "cuda":
            try:
                cuda_count = ctranslate2.get_cuda_device_count()
            except Exception:
                cuda_count = 0
            gpu_indices = resolve_gpu_indices(
                cuda_count,
                os.environ.get("HACHIMIMT_GPU_INDICES"),
                auto_all=auto_all_gpus_by_default(),
            )
            compute_types = [default_ct2_compute_type("cuda")]
            if not env_compute_type and "int8_float32" not in compute_types:
                compute_types.append("int8_float32")
            for compute_type in compute_types:
                for candidate_indices in _ct2_gpu_index_attempts(gpu_indices):
                    attempts.append(("cuda", compute_type, candidate_indices))
            attempts.append(("cpu", "int8_float32", None))
        else:
            cpu_compute_type = default_ct2_compute_type("cpu")
            attempts.append(("cpu", cpu_compute_type, None))
            if cpu_compute_type != "int8_float32":
                attempts.append(("cpu", "int8_float32", None))

        translator = None
        last_error: Exception | None = None
        for device, compute_type, gpu_indices in attempts:
            try:
                kwargs, worker_count, device_indices_label = _ct2_translator_kwargs(
                    device=device,
                    compute_type=compute_type,
                    intra_threads=self._ct2_threads,
                    inter_threads=self._ct2_inter_threads,
                    gpu_indices=gpu_indices,
                )
                translator = ctranslate2.Translator(
                    str(model_path / config.ct2_subdir), **kwargs
                )
                self._ct2_compute_type = compute_type
                self._ct2_actual_intra_threads = int(kwargs["intra_threads"])
                self._ct2_actual_inter_threads = int(kwargs["inter_threads"])
                self._ct2_worker_count = worker_count
                self._ct2_device_indices_label = device_indices_label
                break
            except Exception as exc:
                last_error = exc

        if translator is None:
            raise RuntimeError("Không tải được CTranslate2 backend.") from last_error

        self._tokenizer = tokenizer
        self._ct2_model = translator
        self._model_path = model_path

    def _load_transformers(self, config: ModelConfig) -> None:
        torch = _require_torch()
        try:
            from transformers import AutoModelForSeq2SeqLM, AutoTokenizer, MarianMTModel
        except Exception as exc:
            raise RuntimeError(
                "Backend PyTorch cần transformers/sacremoses/safetensors. "
                "Cài thêm: pip install -r requirements-pytorch.txt"
            ) from exc

        model_path = ensure_model_files(config, Backend.TRANSFORMERS)
        tokenizer = AutoTokenizer.from_pretrained(model_path)
        self._torch_device = _select_torch_device(torch)
        if config.use_marian_class:
            model = MarianMTModel.from_pretrained(model_path)
        else:
            model = AutoModelForSeq2SeqLM.from_pretrained(model_path)

        if self._torch_device == "xpu":
            model = model.to(device="xpu", dtype=torch.float16).eval()
        else:
            model = model.to(self._torch_device).eval()
        self._tokenizer = tokenizer
        self._torch_model = model

    def _chunk_text(self, text: str, chunk_mode: str) -> list[str]:
        config = MODELS[self._model_key]
        if self._backend == Backend.CT2 and self._tokenizer is not None:
            return split_for_translation(
                self._tokenizer,
                text,
                max_tokens=config.ct2_max_input_tokens,
                chunk_mode=chunk_mode,
            )
        return split_chunks(text, mode=chunk_mode)

    def _source_tokens(self, text: str) -> list[str]:
        config = MODELS[self._model_key]
        token_ids = source_token_ids(
            self._tokenizer,
            text,
            max_length=config.ct2_max_input_tokens,
            truncation=True,
        )
        return self._tokenizer.convert_ids_to_tokens(token_ids)

    def _source_tokens_batch(self, chunks: list[str]) -> list[list[str]]:
        config = MODELS[self._model_key]
        encoded = self._tokenizer(
            chunks,
            truncation=True,
            max_length=config.ct2_max_input_tokens,
            padding=False,
        )["input_ids"]
        pad_id = self._tokenizer.pad_token_id
        if pad_id is not None:
            encoded = [
                [token_id for token_id in token_ids if token_id != pad_id]
                for token_ids in encoded
            ]
        return [self._tokenizer.convert_ids_to_tokens(token_ids) for token_ids in encoded]

    def _decode_tokens(self, tokens: list[str]) -> str:
        token_ids = self._tokenizer.convert_tokens_to_ids(tokens)
        return self._tokenizer.decode(token_ids, skip_special_tokens=True).strip()

    def _torch_generate_kwargs(self, beam_size: int) -> dict:
        config = MODELS[self._model_key]
        kwargs = dict(config.generate_kwargs)
        kwargs["num_beams"] = beam_size
        if config.use_marian_class:
            kwargs["early_stopping"] = beam_size > 1
        return kwargs

    def _runtime_batch_size(self, beam_size: int) -> int:
        """PyTorch tốn VRAM hơn theo beam — giảm batch để tránh OOM."""
        if self._backend == Backend.CT2:
            return self._batch_size
        beam_size = self.clamp_beam(beam_size)
        vram_factor = max(1, beam_size * 2)
        return max(4, min(self._batch_size, 48 // vram_factor))

    def _runtime_window_size(self, beam_size: int) -> int:
        batch_size = self._runtime_batch_size(beam_size)
        if self._backend == Backend.CT2:
            return max(batch_size, batch_size * self._ct2_effective_window_multiplier())
        return batch_size

    def _ct2_effective_window_multiplier(self) -> int:
        multiplier = self._ct2_window_multiplier
        if self._ct2_batch_type == "tokens" and self._ct2_worker_count > 1:
            # Multi-GPU needs enough queued chunks for CT2 to split into multiple
            # token sub-batches. Kaggle T4 x2 benchmarks need a 32x effective
            # window to keep both GPUs saturated; cap keeps large files bounded.
            multiplier *= min(self._ct2_worker_count * 4, 8)
        return max(1, min(32, multiplier))

    def _ct2_max_batch_size(self, config: ModelConfig) -> int:
        if self._ct2_batch_type == "tokens":
            return self._batch_size * config.ct2_max_input_tokens
        return self._batch_size

    def _translate_torch_batch(self, chunks: list[str], *, beam_size: int) -> list[str]:
        if not chunks:
            return []

        torch = _require_torch()
        config = MODELS[self._model_key]
        max_length = 256 if config.use_marian_class else 512
        marker = config.newline_token
        sources = chunks if marker is None else [encode_newline_marker(c, marker) for c in chunks]
        inputs = self._tokenizer(
            sources,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=max_length,
        ).to(self._torch_device)

        with torch.inference_mode():
            outputs = self._torch_model.generate(
                **inputs,
                **self._torch_generate_kwargs(beam_size),
            )

        decoded = [
            self._tokenizer.decode(output, skip_special_tokens=True).strip()
            for output in outputs
        ]
        if marker is not None:
            # Đường PyTorch không có plan chunk→dòng (restore theo toàn tài liệu như
            # các model khác) nên trả bản dịch MỘT dòng; chỉ đường CT2 giữ xuống
            # dòng do model sinh.
            decoded = [" ".join(decode_newline_marker(text, marker).split()) for text in decoded]
        return self._finalize_outputs(decoded)

    def translate_chunk(self, text: str, *, beam_size: int = 2) -> str:
        if self._tokenizer is None:
            raise RuntimeError("Chưa tải model. Gọi load() trước.")

        beam_size = self.clamp_beam(beam_size)

        if self._backend == Backend.CT2:
            return self._translate_chunks_ct2([text], beam_size=beam_size)[0]

        return self._translate_torch_batch([text], beam_size=beam_size)[0]

    def count_chunks(self, text: str, chunk_mode: str = "sentence") -> int:
        if not self._model_key:
            raise RuntimeError("Chưa tải model. Gọi load() trước.")
        return len(self._chunk_text(text, chunk_mode))

    @staticmethod
    def _ct2_repetition_kwargs(config: "ModelConfig") -> dict:
        """Lấy tham số chống lặp cho CT2 translate_batch TỪ generate_kwargs của
        model (nhất quán với đường PyTorch). Chỉ lấy key CT2 hỗ trợ — model nào
        không khai (vd HachimiMT-30) trả {} → không áp. Vá để đường CT2 (chạy
        thật) cũng chống lặp như PyTorch; model có tiền sử lặp trên source ngắn."""
        gk = config.generate_kwargs
        kwargs = {}
        if "no_repeat_ngram_size" in gk:
            kwargs["no_repeat_ngram_size"] = gk["no_repeat_ngram_size"]
        if "repetition_penalty" in gk:
            kwargs["repetition_penalty"] = gk["repetition_penalty"]
        return kwargs

    def _translate_ct2_batch(
        self,
        chunks: list[str],
        *,
        beam_size: int,
        source_batches: list[list[str]] | None = None,
    ) -> list[str]:
        config = MODELS[self._model_key]
        if source_batches is None:
            tokenize_start = time.perf_counter()
            source_batches = self._tokenize_chunks_parallel(chunks)
            self._profile_add("tokenize_s", time.perf_counter() - tokenize_start)
        infer_start = time.perf_counter()
        results = self._ct2_model.translate_batch(
            source_batches,
            max_batch_size=self._ct2_max_batch_size(config),
            batch_type=self._ct2_batch_type,
            beam_size=beam_size,
            max_decoding_length=config.ct2_max_output_tokens,
            **self._ct2_repetition_kwargs(config),
        )
        self._profile_add("ct2_infer_s", time.perf_counter() - infer_start)
        return self._keep_source_newlines_only(chunks, self._decode_ct2_results(results), config)

    @staticmethod
    def _keep_source_newlines_only(
        chunks: list[str], outputs: list[str], config: "ModelConfig"
    ) -> list[str]:
        """Model có newline_token: chunk MỘT dòng mà output lỡ có xuống dòng thì
        trả về một dòng (mọi chunk của "Theo câu" là một dòng → bố cục 1:1 giữ
        nguyên). Chunk nhiều dòng giữ xuống dòng của model cho line-restore.
        Model không có newline_token: trả đúng list cũ, không copy."""
        if config.newline_token is None:
            return outputs
        return [
            output if "\n" in chunk or "\n" not in output else " ".join(output.split())
            for chunk, output in zip(chunks, outputs)
        ]

    def _translate_ct2_batch_pipelined(
        self,
        chunks: list[str],
        *,
        beam_size: int,
        prefetched_tokens: SourceTokenJobs | None,
    ) -> list[str]:
        if prefetched_tokens is not None:
            wait_start = time.perf_counter()
            source_batches = self._collect_tokenize_jobs(prefetched_tokens)
            self._profile_add("tokenize_wait_s", time.perf_counter() - wait_start)
        else:
            source_batches = None
        return self._translate_ct2_batch(
            chunks,
            beam_size=beam_size,
            source_batches=source_batches,
        )

    def _translate_chunks_ct2(self, chunks: list[str], *, beam_size: int) -> list[str]:
        if self._ct2_model is None:
            raise RuntimeError("CTranslate2 chưa được tải.")

        beam_size = self.clamp_beam(beam_size)
        if not chunks:
            return []
        return self._translate_ct2_batch(chunks, beam_size=beam_size)

    def translate_text_iter(
        self,
        text: str,
        *,
        chunk_mode: str = "sentence",
        beam_size: int = 2,
    ) -> Iterator[tuple[int, int, str, list[tuple[int, str, str]] | None, str | None]]:
        """Yield (done, total, message, rows_or_none, full_text_or_none) sau mỗi batch."""
        beam_size = self.clamp_beam(beam_size)
        self._reset_profile()
        self._profile_set("backend", self._backend.value if self._backend else "")
        self._profile_set("beam", beam_size)
        chunk_start = time.perf_counter()
        # "Theo câu" + CT2: chia kèm plan dòng-nguồn → chunk-index.
        # "Theo đoạn" + CT2: gom nhiều dòng vào chunk nhưng giữ chunk → line-id
        # để restore/fallback cục bộ, không đoán theo toàn tài liệu.
        sentence_plan: list[list[int] | None] | None = None
        paragraph_plan: list[tuple[int, ...]] | None = None
        if chunk_mode == "sentence" and self._backend == Backend.CT2 and self._tokenizer is not None:
            chunks, sentence_plan = split_sentence_lines_with_plan(
                self._tokenizer, text, max_tokens=MODELS[self._model_key].ct2_max_input_tokens
            )
        elif chunk_mode == "paragraph" and self._backend == Backend.CT2 and self._tokenizer is not None:
            chunks, paragraph_plan = split_paragraphs_with_plan(
                self._tokenizer, text, max_tokens=MODELS[self._model_key].ct2_max_input_tokens
            )
        else:
            chunks = self._chunk_text(text, chunk_mode)
        self._profile_set("chunk_s", time.perf_counter() - chunk_start)
        total = len(chunks)
        self._profile_set("chunks", total)

        yield 0, total, f"Đã chia {total} chunk, chuẩn bị dịch...", None, None

        translations: list[str] = []
        batch_size = self._runtime_batch_size(beam_size)
        window_size = self._runtime_window_size(beam_size)
        next_tokens: SourceTokenJobs | None = None
        if self._backend == Backend.CT2 and total:
            first_end = min(window_size, total)
            submit_start = time.perf_counter()
            next_tokens = self._submit_tokenize_jobs(chunks[:first_end])
            self._profile_add("tokenize_submit_s", time.perf_counter() - submit_start)

        for start in range(0, total, window_size):
            end = min(start + window_size, total)
            worker_label = (
                f", workers {self._ct2_worker_count}"
                if self._backend == Backend.CT2 and self._ct2_worker_count > 1
                else ""
            )
            batch_label = (
                f"window {window_size}, batch {batch_size}, {self._ct2_batch_type}{worker_label}"
                if self._backend == Backend.CT2
                else f"batch {batch_size}"
            )
            yield (
                start,
                total,
                f"Đang dịch chunk {start + 1}–{end}/{total} ({batch_label})...",
                None,
                None,
            )

            batch = chunks[start:end]
            if self._backend == Backend.CT2:
                current_tokens = next_tokens
                next_tokens = None
                next_start = start + window_size
                next_end = min(next_start + window_size, total)
                if next_start < total:
                    next_batch = chunks[next_start:next_end]
                    submit_start = time.perf_counter()
                    next_tokens = self._submit_tokenize_jobs(next_batch)
                    self._profile_add("tokenize_submit_s", time.perf_counter() - submit_start)

                translations.extend(
                    self._translate_ct2_batch_pipelined(
                        batch,
                        beam_size=beam_size,
                        prefetched_tokens=current_tokens,
                    )
                )
            else:
                translations.extend(self._translate_torch_batch(batch, beam_size=beam_size))

            yield end, total, f"Đã xong {end}/{total} chunk", None, None

        if chunk_mode == "paragraph":
            fallback_line_translations: dict[int, str] = {}
            if paragraph_plan is not None:
                fallback_chunk_indices = paragraph_chunk_fallback_indices(
                    text,
                    chunks,
                    translations,
                    paragraph_plan,
                    require_native_newlines=bool(MODELS[self._model_key].newline_token),
                )
                if fallback_chunk_indices:
                    source_lines = split_layout_lines(text)
                    fallback_line_ids: list[int] = []
                    seen_line_ids: set[int] = set()
                    for chunk_index in fallback_chunk_indices:
                        for line_index in paragraph_plan[chunk_index]:
                            if line_index not in seen_line_ids:
                                fallback_line_ids.append(line_index)
                                seen_line_ids.add(line_index)

                    fallback_chunks: list[str] = []
                    fallback_map: list[tuple[int, int, int]] = []
                    config = MODELS[self._model_key]
                    for line_index in fallback_line_ids:
                        line = source_lines[line_index].strip()
                        start = len(fallback_chunks)
                        line_chunks = split_for_translation(
                            self._tokenizer,
                            line,
                            max_tokens=config.ct2_max_input_tokens,
                            chunk_mode="sentence",
                        )
                        fallback_chunks.extend(line_chunks)
                        fallback_map.append((line_index, start, len(fallback_chunks)))

                    self._profile_set("paragraph_fallback_chunks", len(fallback_chunks))
                    self._profile_set("paragraph_fallback_lines", len(fallback_line_ids))
                    yield (
                        total,
                        total,
                        f"Dịch lại {len(fallback_line_ids)} dòng để giữ xuống dòng...",
                        None,
                        None,
                    )
                    fallback_translated = self._translate_chunks_ct2(
                        fallback_chunks,
                        beam_size=beam_size,
                    )
                    if len(fallback_translated) != len(fallback_chunks):
                        raise RuntimeError("Dịch lại từng dòng trả thiếu chunk")
                    for line_index, start, end in fallback_map:
                        if config.newline_token and any(not item.strip() for item in fallback_translated[start:end]):
                            raise RuntimeError("Dịch lại từng dòng chưa trả về bản dịch đầy đủ")
                        fallback_line_translations[line_index] = " ".join(
                            (" ".join(item.splitlines()).strip() if config.newline_token else item.strip())
                            for item in fallback_translated[start:end] if item.strip()
                        ).strip()

            assemble_start = time.perf_counter()
            # Chunk gom nhiều dòng → model nuốt xuống dòng. Khôi phục bố cục dòng
            # gốc (cho full_text) + ghép rows 1:1 dòng-gốc/dòng-dịch để bảng đối
            # chiếu khớp bản tải về. Xem line_restore.assemble_paragraph_output.
            rows, full_text = assemble_paragraph_output(
                text,
                chunks,
                translations,
                plan=paragraph_plan,
                fallback_line_translations=fallback_line_translations,
                require_native_newlines=bool(paragraph_plan is not None and MODELS[self._model_key].newline_token),
            )
        elif sentence_plan is not None:
            assemble_start = time.perf_counter()
            # "Theo câu": ghép theo plan → GIỮ dòng trống + gộp dòng dài đa-chunk
            # về 1 dòng. Deterministic (không phỏng đoán tỉ lệ như "Theo đoạn").
            rows, full_text = assemble_sentence_output(text, chunks, translations, sentence_plan)
        else:
            assemble_start = time.perf_counter()
            rows = [
                (index, chunk, translated)
                for index, (chunk, translated) in enumerate(zip(chunks, translations), start=1)
            ]
            full_text = "\n".join(translations)
        self._profile_add("assemble_s", time.perf_counter() - assemble_start)
        cache_stats = getattr(self._tokenizer, "cache_stats", None)
        if callable(cache_stats):
            for key, value in cache_stats().items():
                self._profile_set(key, value)
        yield total, total, "Hoàn tất dịch.", rows, full_text

    def translate_text(
        self,
        text: str,
        *,
        chunk_mode: str = "sentence",
        beam_size: int = 2,
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> tuple[list[tuple[int, str, str]], str]:
        rows: list[tuple[int, str, str]] = []
        full_text = ""
        for done, total, message, result_rows, result_text in self.translate_text_iter(
            text,
            chunk_mode=chunk_mode,
            beam_size=beam_size,
        ):
            if on_progress:
                on_progress(done, total, message)
            if result_rows is not None and result_text is not None:
                rows = result_rows
                full_text = result_text
        return rows, full_text
