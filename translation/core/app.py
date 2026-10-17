"""Gradio UI for HachimiMT zh→vi translation."""

from __future__ import annotations

import atexit
import hashlib
import html
import os
import platform
import tempfile
import time
import unicodedata
import uuid
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


def _patch_windows_platform() -> None:
    """Avoid Python 3.13 WMI calls during pandas/Gradio import on Windows."""
    if os.name != "nt":
        return
    platform.system = lambda: "Windows"
    raw_machine = (
        os.environ.get("PROCESSOR_ARCHITEW6432")
        or os.environ.get("PROCESSOR_ARCHITECTURE")
    )
    if not raw_machine:
        return
    aliases = {
        "amd64": "AMD64",
        "x86_64": "AMD64",
        "arm64": "ARM64",
        "aarch64": "ARM64",
        "x86": "x86",
        "i386": "x86",
    }
    machine = aliases.get(raw_machine.strip().lower(), raw_machine.strip())
    if machine:
        platform.machine = lambda: machine


_patch_windows_platform()

import gradio as gr

from translation.core.glossary import (
    PLACEHOLDER_SCOPE_DOCUMENT,
    PLACEHOLDER_SCOPE_LINE,
    GlossaryValidationError,
    apply_glossary_rows,
    compile_glossary,
    glossary_table_rows,
    protect_glossary_text,
    read_glossary_file,
    restore_glossary_rows,
    write_glossary_file,
)
from translation.core import hardware
from translation.core.hardware import detect_hardware_profile
from translation.core.progress_tracker import finish_progress, reset_progress, set_progress, snapshot
from translation.core.text_preprocess import (
    NORMALIZE_AUTO,
    NORMALIZE_NONE,
    NORMALIZE_T2S,
    normalization_message,
    normalize_chinese_text,
)
from translation.core.honorific_normalize import normalize_honorifics
from translation.core.postprocess_policy import classify_genre, v9_route_for_decision
from translation.core.pronoun_harmonizer_v9 import harmonize_pronouns_v9
from translation.core.translator import (
    DEFAULT_MODEL_KEY,
    MODELS,
    Backend,
    HachimiTranslator,
    ensure_model_files,
    is_model_downloaded,
)
from translation.core.novel_tab import build_novel_tab, NOVEL_CSS


def _env_float(name: str, default: float, *, min_value: float = 0.0, max_value: float = 60.0) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(min_value, min(max_value, float(raw)))
    except ValueError:
        return default


ROOT = Path(__file__).resolve().parents[2]
EXPORTS_DIR = ROOT / "exports"
PID_FILE = ROOT / ".hachimimt.pid"
APP_PORT = 7860
EXPORT_FILE_PREFIX = "hachimi_export_"
SPACE_EXPORT_MAX_AGE_SECONDS = 24 * 60 * 60
# HF Space tự set SPACE_ID. Khi ở Space: CPU-only (ẩn nút cài GPU/torch), process
# do HF quản (bỏ PID file), HF tự lo host/port (không ép 127.0.0.1). App chạy
# local KHÔNG đổi gì.
IS_HF_SPACE = bool(os.environ.get("SPACE_ID") or os.environ.get("SPACE_HOST"))
# ⚠️ cpu-basic Space: os.cpu_count() báo số core MÁY CHỦ vật lý (16-32) chứ không
# phải 2 vCPU thực được cấp → hardware-detect set ct2_threads/batch quá cao →
# OVERSUBSCRIPTION, dịch chậm 10-17×. Ép mức an toàn cho cpu-basic (giống Space
# demo cũ: 2 threads) TRƯỚC khi detect_hardware_profile() chạy. User vẫn override
# được qua env nếu chạy Space tier mạnh hơn.
if IS_HF_SPACE:
    # "Space fast mode" cho cpu-basic (đo bởi Codex: kéo 16 chunk 17.8s → ~Space cũ).
    # os.cpu_count() báo core MÁY CHỦ (16-32) ≠ 2 vCPU thực → tránh oversubscription
    # + dùng cấu hình batch hợp CPU nhỏ (examples/window=1, như Space demo cũ). Set
    # TRƯỚC detect_hardware_profile(). KHÔNG ảnh hưởng bản local (gate IS_HF_SPACE).
    os.environ.setdefault("HACHIMIMT_THREADS", "2")
    os.environ.setdefault("HACHIMIMT_TOKENIZE_WORKERS", "2")
    os.environ.setdefault("HACHIMIMT_BATCH_SIZE", "8")
    os.environ.setdefault("HACHIMIMT_INTER_THREADS", "1")
    os.environ.setdefault("HACHIMIMT_CT2_BATCH_TYPE", "examples")
    os.environ.setdefault("HACHIMIMT_CT2_WINDOW_MULTIPLIER", "1")
    os.environ.setdefault("HACHIMIMT_PROGRESS_SECONDS", "1.0")

def _env_truthy(name: str) -> bool:
    """CHỈ "1"/"true"/"yes" (case-insensitive) mới bật → tránh env rác bật nhầm."""
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes"}


# Panel feedback/sửa câu là DEV-ONLY: chỉ người phát triển (cải thiện model) cần.
# Bản zip share cho người đọc truyện KHÔNG đặt biến này → không thấy panel.
DEV_FEEDBACK = _env_truthy("HACHIMIMT_DEV_FEEDBACK")


def feedback_panel_enabled(dev_flag: bool, is_space: bool) -> bool:
    """Panel chỉ hiện cho dev local: bật cờ DEV_FEEDBACK và KHÔNG ở HF Space
    (Space filesystem ephemeral → ghi sẽ mất, hiện panel là trải nghiệm dối)."""
    return dev_flag and not is_space


def _feedback_honorific_label(kinship: bool, pronouns: bool) -> str:
    """Nhãn cố định cho metadata feedback (không build ad-hoc trong handler)."""
    if kinship and pronouns:
        return "kinship+pronoun"
    if kinship:
        return "kinship"
    if pronouns:
        return "pronoun"
    return "none"

# Package bản chạy-máy (GPU/offline/file lớn) — .zip đặt NGAY trong Space repo
# (public, không cần đăng nhập; repo GitHub đang private nên không link tới đó).
# Banner + hướng dẫn cài CHỈ hiện trên Space (local thì đang chạy local rồi → thừa).
LOCAL_ZIP_URL = "https://huggingface.co/spaces/ngocdang83/HachimiMT-demo/resolve/main/hachimimt-local.zip"
# Notebook Colab đặt ở repo GitHub PUBLIC riêng (Colab chỉ import được từ GitHub/
# Drive, KHÔNG từ HF Space URL — đã test). Chạy app trên CPU/GPU free của Google.
COLAB_URL = "https://colab.research.google.com/github/ngocdang8311/hachimimt-colab/blob/master/HachimiMT_Colab.ipynb"
# Kaggle import-from-GitHub: kernels/welcome?src=<github blob url> → MỞ Kaggle tạo
# notebook từ repo public (như nút Colab). KHÔNG dùng link resolve .ipynb của Space —
# cái đó chỉ TẢI file JSON thô (text/plain), không mở Kaggle → gây hiểu nhầm.
KAGGLE_NOTEBOOK_URL = "https://www.kaggle.com/kernels/welcome?src=https://github.com/ngocdang8311/hachimimt-colab/blob/master/HachimiMT_Kaggle.ipynb"
MAX_TABLE_ROWS = 300
# Số ký tự tối đa hiển thị trong ô "Bản dịch đầy đủ" (file xuất .txt vẫn đầy đủ).
FULL_OUTPUT_DISPLAY_LIMIT = 50_000
RESULT_OUTPUT_COUNT = 7
# Trên Space cpu-basic (2 vCPU dùng chung, công khai): cắt văn bản đầu vào để 1
# người tải nguyên bộ truyện không giữ CPU/RAM quá lâu. Bản dài → Colab/cài máy.
# Local/Colab KHÔNG giới hạn (gate trong cap_input_for_space).
SPACE_MAX_INPUT_CHARS = 150_000
PROGRESS_UPDATE_SECONDS = _env_float("HACHIMIMT_PROGRESS_SECONDS", 0.5, max_value=10.0)
TEXT_ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "gbk", "big5")
LEGACY_TEXT_ENCODINGS = ("gb18030", "gbk", "big5")
DECODE_SCORE_SAMPLE_CHARS = 200_000

HW_PROFILE = detect_hardware_profile()
translator = HachimiTranslator(HW_PROFILE)
EXPORTS_DIR.mkdir(exist_ok=True)


def gpu_available_but_idle() -> bool:
    """Máy CÓ GPU NVIDIA vật lý nhưng app đang chạy CPU (thiếu torch-CUDA).

    Đây là nhóm nên được mời cài torch để bật GPU (nhanh hơn nhiều lần).
    Trên HF Space: CPU-only, KHÔNG cho pip install runtime → luôn False (ẩn nút
    cài GPU + khối gpu-hint; mọi chỗ dùng hàm này tự đúng theo).
    """
    if IS_HF_SPACE:
        return False
    return bool(hardware.PHYSICAL_NVIDIA_GPU) and not HW_PROFILE.has_cuda


def render_gpu_hint_html() -> str:
    if not gpu_available_but_idle():
        return ""
    gpu = html.escape(hardware.PHYSICAL_GPU_NAME or "GPU NVIDIA")
    return (
        '<div class="gpu-hint">'
        f"⚡ Phát hiện <b>{gpu}</b> nhưng app đang chạy bằng <b>CPU</b> "
        "(thiếu thư viện CUDA). Bật GPU sẽ dịch nhanh hơn nhiều lần. "
        "Bấm nút bên dưới để cài tự động (tải ~2–3 GB, cần ~5 GB ổ trống, một lần)."
        "</div>"
    )

# App khoá ở light mode hoàn toàn bằng CSS: khối ":root, .dark" bên dưới
# ánh xạ mọi biến theme sang palette "giấy cũ", nên giao diện đúng bất kể
# trình duyệt đang ở light hay dark (system-theme-proof). Không dùng JS ép
# theme vì Gradio bỏ qua nó ở đây và CSS đã đủ.

# Preload font trong <head> để giảm nhấp nháy khi tải.
HEAD_HTML = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<script>
window.__hachimimtRefreshGlossaryTable = () => {
    window.dispatchEvent(new Event("resize"));
    document
        .querySelector("#glossary-table .virtual-table-viewport")
        ?.dispatchEvent(new Event("scroll"));
};

document.addEventListener("click", (event) => {
    const target = event.target instanceof Element
        ? event.target.closest(
            '[role="menuitem"][aria-label="Add row above"], ' +
            '[role="menuitem"][aria-label="Add row below"]'
        )
        : null;
    if (!target) return;
    requestAnimationFrame(() => {
        window.__hachimimtRefreshGlossaryTable();
        requestAnimationFrame(window.__hachimimtRefreshGlossaryTable);
    });
});
</script>
"""

CUSTOM_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,600;0,9..144,700;1,9..144,500&family=Literata:ital,opsz,wght@0,7..72,400;0,7..72,500;0,7..72,600;1,7..72,400&family=Noto+Serif+SC:wght@400;600&display=swap');

/* ── Palette "giấy cũ / thư phòng" ─────────────────────────────────── */
:root, .dark {
    --paper:      #f4ecdc;   /* nền giấy */
    --paper-deep: #e7dac2;   /* giấy đậm (đáy gradient) */
    --card:       #fbf6ea;   /* mặt thẻ */
    --card-soft:  #f7efe0;   /* thẻ phụ */
    --ink:        #221b12;   /* mực chính */
    --ink-soft:   #514537;   /* mực nhạt */
    --muted:      #8a7a64;   /* chú thích */
    --accent:     #b03a26;   /* son / chu sa */
    --accent-2:   #c8553a;   /* son sáng */
    --gold:       #9c7b3f;   /* nhũ vàng cũ */
    --border:     #d8cbb1;   /* viền giấy */
    --border-soft:#e6dcc8;
    --shadow:     rgba(60, 44, 24, 0.10);

    /* Ánh xạ vào biến chuẩn của Gradio để mọi widget theo theme này
       (đây là gốc rễ của bug cũ: dark-mode còn sót làm chữ trắng/nền tối). */
    --body-background-fill: transparent;
    --body-text-color: var(--ink);
    --body-text-color-subdued: var(--muted);
    --background-fill-primary: var(--card);
    --background-fill-secondary: var(--card-soft);
    --block-background-fill: var(--card);
    --block-label-background-fill: transparent;
    --block-border-color: var(--border);
    --block-label-text-color: var(--ink-soft);
    --block-title-text-color: var(--ink-soft);
    --border-color-primary: var(--border);
    --border-color-accent: var(--accent);
    --input-background-fill: #fffdf7;
    --input-background-fill-focus: #fffefb;
    --input-border-color: var(--border);
    --input-border-color-focus: var(--accent);
    --input-placeholder-color: #b6a88f;
    --neutral-950: var(--ink);
    --color-accent: var(--accent);
    --color-accent-soft: #efd9c9;
    --link-text-color: var(--accent);
    --table-border-color: var(--border);
    --table-even-background-fill: var(--card);
    --table-odd-background-fill: var(--card-soft);
    --button-secondary-background-fill: #efe6d3;
    --button-secondary-background-fill-hover: #e7dcc4;
    --button-secondary-text-color: var(--ink);
    --button-secondary-border-color: var(--border);
    /* Toast lỗi: dark-mode Gradio đặt nền #0f0e0d (đen) — ép về giấy. */
    --error-background-fill: var(--card);
    --error-border-color: var(--accent);
    --error-text-color: var(--accent);
    --color-red-50: #f7e7e2;
}

/* ── HARD-OVERRIDE dark mode (HF) ──────────────────────────────────────
   HF Space đặt class `.dark` trên <body> và định nghĩa lại MỘT SỐ biến nền ở
   selector sâu hơn (vd --block-background-fill, --background-fill-primary) nên
   override ở :root thua specificity → card/khối con ra nền nâu-đen, chữ mờ.
   CSS custom property CÓ hỗ trợ !important và nó thắng mọi định nghĩa thường
   bất kể specificity. App này CHỈ light → ép cứng các biến nền/text về giấy. */
body.dark, .dark, gradio-app.dark {
    --background-fill-primary: var(--card) !important;
    --background-fill-secondary: var(--card-soft) !important;
    --block-background-fill: var(--card) !important;
    --block-label-background-fill: transparent !important;
    --body-background-fill: transparent !important;
    --body-text-color: var(--ink) !important;
    --body-text-color-subdued: var(--muted) !important;
    --block-label-text-color: var(--ink-soft) !important;
    --block-title-text-color: var(--ink-soft) !important;
    --input-background-fill: #fffdf7 !important;
    --panel-background-fill: var(--card) !important;
    --border-color-primary: var(--border) !important;
    /* Dataframe có dark overrides riêng cho bảng, nằm ngoài nhóm background
       chung ở trên. Thiếu ba biến này làm bảng đen dù app đã khoá light mode. */
    --table-even-background-fill: var(--card) !important;
    --table-odd-background-fill: var(--card-soft) !important;
    --table-border-color: var(--border) !important;
    /* nhóm neutral Gradio dùng cho nền/scale tối */
    --neutral-950: var(--ink) !important;
    --neutral-900: #2a2014 !important;
    --neutral-800: #514537 !important;
    --color-accent-soft: #efd9c9 !important;
    --error-background-fill: var(--card) !important;
    color-scheme: light !important;
}

/* ── Nền & khung tổng thể ──────────────────────────────────────────── */
/* Phủ nền lên html + body + gradio-app: <gradio-app> rộng hết khung và ở
   dark-mode có nền đen — nếu bỏ sót, hai bên (ngoài container 1180px) và
   vùng overscroll sẽ lộ màu đen. Đây là nguồn gốc các "dải đen" còn lại. */
html { background: #ecdfc9 !important; }
html, body, gradio-app, .gradio-container {
    background:
        radial-gradient(1200px 600px at 12% -8%, #fbf4e6 0%, transparent 60%),
        radial-gradient(1000px 700px at 110% 0%, #efe2cb 0%, transparent 55%),
        linear-gradient(168deg, #f4ecdc 0%, #ecdfc9 55%, #e4d6bd 100%) !important;
    color: var(--ink) !important;
}
gradio-app { display: block; min-height: 100vh; }
/* Lớp grain giấy rất nhẹ để bớt phẳng */
.gradio-container::before {
    content: "";
    position: fixed; inset: 0; z-index: 0; pointer-events: none;
    opacity: 0.5;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='160'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2' stitchTiles='stitch'/%3E%3CfeColorMatrix type='saturate' values='0'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.035'/%3E%3C/svg%3E");
}
.gradio-container > * { position: relative; z-index: 1; }
.gradio-container { max-width: 1180px !important; margin: 0 auto !important; }

/* ── Typography ────────────────────────────────────────────────────── */
body, .gradio-container, .prose, button, input, textarea, select, .gr-button {
    font-family: 'Literata', Georgia, 'Times New Roman', serif !important;
}
h1, h2, h3, h4, .prose h1, .prose h2, .prose h3 {
    font-family: 'Fraunces', Georgia, serif !important;
    color: var(--ink) !important;
    letter-spacing: -0.01em;
}

/* ── Header (tiêu đề + triện) ──────────────────────────────────────── */
/* Quan trọng: ép overflow visible + bỏ giới hạn cao của khối Markdown,
   nếu không Gradio sinh scrollbar con ngay cạnh logo (chữ cao hơn khối
   vài px → overflow:auto). user-select:none để bỏ select nền xanh chướng. */
#app-header, #app-title {
    overflow: visible !important;
    max-height: none !important;
    user-select: none;
    background: transparent !important;
    border: none !important;
}
#app-header { text-align: center; margin: 0.6rem 0 0.2rem; }
#app-title h1 {
    font-size: clamp(2.4rem, 5vw, 3.4rem) !important;
    font-weight: 600 !important;
    margin: 0 !important;
    line-height: 1.18;
    padding: 0.08em 0;
    background: linear-gradient(180deg, #2a2014 0%, #6a3a26 120%);
    -webkit-background-clip: text; background-clip: text;
    -webkit-text-fill-color: transparent;
}
#app-title h1::after {
    content: "譯";                /* "Dịch" — con triện đỏ cạnh tiêu đề */
    -webkit-text-fill-color: #fff;
    font-family: 'Noto Serif SC', serif;
    font-size: 0.42em;
    font-weight: 600;
    vertical-align: 0.5em;
    margin-left: 0.45rem;
    background: var(--accent);
    padding: 0.12em 0.18em 0.04em;
    border-radius: 6px;
    box-shadow: 0 2px 6px rgba(176,58,38,0.35);
}
#app-rule {
    width: 90px; height: 2px; margin: 0.7rem auto 1.3rem;
    background: linear-gradient(90deg, transparent, var(--gold), transparent);
}

/* Banner demo (chỉ Space) — mời tải bản local. Khớp palette giấy, viền son nhạt. */
#demo-banner {
    max-width: 1180px;
    margin: -0.4rem auto 1.1rem;
    padding: 10px 18px;
    background: linear-gradient(180deg, #fbf1e2, #f6ead4);
    border: 1px solid var(--gold);
    border-radius: 12px;
    font-size: 0.92rem;
    line-height: 1.5;
    color: var(--ink-soft);
    text-align: center;
    box-shadow: 0 1px 3px var(--shadow);
}
#demo-banner a {
    color: var(--accent) !important;
    font-weight: 600;
    text-decoration: underline;
    text-underline-offset: 2px;
}

/* ── Khối / thẻ ────────────────────────────────────────────────────── */
.gr-group, .block, .gr-box {
    border-radius: 14px !important;
    border-color: var(--border) !important;
}
#settings-card {
    background: var(--card) !important;
    border: 1px solid var(--border) !important;
    border-radius: 16px !important;
    box-shadow: 0 1px 2px var(--shadow), 0 10px 30px -22px var(--shadow);
    padding: 6px 16px 14px !important;
}
.section-label, .section-label p {
    font-family: 'Fraunces', Georgia, serif !important;
    font-size: 0.78rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: var(--gold) !important;
    margin: 0.2rem 0 0.1rem !important;
}

/* Nhãn các control: bỏ kiểu "pill cam" nặng nề của Gradio,
   chuyển thành nhãn chữ nhỏ thanh thoát. */
.block > label > span,
span[data-testid="block-info"],
.gr-form > div > label > span {
    background: transparent !important;
    color: var(--ink-soft) !important;
    font-family: 'Literata', serif !important;
    font-weight: 600 !important;
    font-size: 0.86rem !important;
    letter-spacing: 0.01em;
    padding: 0 0 2px 0 !important;
}

/* ── Input / textarea ──────────────────────────────────────────────── */
input, textarea, .gr-input, .wrap.svelte-1ipelgc {
    background: #fffdf7 !important;
    color: var(--ink) !important;
    border-color: var(--border) !important;
}
textarea::placeholder, input::placeholder { color: #b6a88f !important; }
textarea:focus, input:focus { border-color: var(--accent) !important; }

.source-input textarea, .file-preview textarea, #full-output textarea {
    font-family: 'Literata', Georgia, serif !important;
    font-size: 1.02rem !important;
    line-height: 1.75 !important;
}

/* ── Nút ───────────────────────────────────────────────────────────── */
button.primary, .gr-button-primary, button[variant="primary"] {
    background: linear-gradient(180deg, var(--accent-2), var(--accent)) !important;
    border: 1px solid #93311f !important;
    color: #fff7ef !important;
    font-weight: 600 !important;
    letter-spacing: 0.01em;
    box-shadow: 0 2px 8px -2px rgba(176,58,38,0.5) !important;
    transition: transform 0.12s ease, box-shadow 0.12s ease, filter 0.12s ease !important;
}
button.primary:hover, .gr-button-primary:hover {
    filter: brightness(1.05);
    transform: translateY(-1px);
    box-shadow: 0 6px 16px -4px rgba(176,58,38,0.55) !important;
}
button.secondary, .gr-button-secondary {
    background: #efe6d3 !important;
    border: 1px solid var(--border) !important;
    color: var(--ink) !important;
    font-weight: 600 !important;
}
button.secondary:hover, .gr-button-secondary:hover { background: #e7dcc4 !important; }

/* ── Tabs ──────────────────────────────────────────────────────────── */
/* Bỏ nền/viền/padding thừa của khối bao Tabs để thanh tab liền mạch
   với nền giấy thay vì nằm trong một thẻ riêng. */
.tabs, .tab-wrapper, .tabitem {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    padding-top: 0 !important;
}
.tab-nav { border-bottom: 1px solid var(--border) !important; }
.tab-nav button {
    font-family: 'Fraunces', Georgia, serif !important;
    font-size: 1rem !important;
    color: var(--muted) !important;
}
.tab-nav button.selected {
    color: var(--accent) !important;
    border-bottom: 2px solid var(--accent) !important;
}

/* ── Radio / Checkbox ──────────────────────────────────────────────── */
/* Mặc định (chưa chọn): nền giấy, chữ mực — ghi đè màu tối còn sót của
   dark-mode Gradio (đây là chỗ widget bị "đen" trên nền sáng). */
.gr-check-radio label,
fieldset label:has(input[type="radio"]),
fieldset label:has(input[type="checkbox"]) {
    background: #f1e7d4 !important;
    color: var(--ink) !important;
    border: 1px solid var(--border) !important;
    border-radius: 9px !important;
    transition: background 0.12s ease, border-color 0.12s ease !important;
}
.gr-check-radio label:hover,
fieldset label:has(input[type="radio"]):hover,
fieldset label:has(input[type="checkbox"]):hover {
    background: #ebe0ca !important;
    border-color: var(--gold) !important;
}
/* Đang chọn: nền son nhạt, viền son */
.gr-check-radio label.selected, label.selected,
fieldset label:has(input:checked) {
    background: var(--color-accent-soft) !important;
    border-color: var(--accent) !important;
    color: var(--ink) !important;
}
/* Chấm radio / ô checkbox khi tick */
input[type="radio"]:checked, input[type="checkbox"]:checked {
    background-color: var(--accent) !important;
    border-color: var(--accent) !important;
}

/* ── Accordion "Tuỳ chọn chuẩn hóa xưng hô" (collapse, mặc định đóng) ───
   3 checkbox cùng chủ đề, tách hẳn khỏi card cấu hình dịch. Label gọn 1 dòng,
   bỏ info dài của Gradio (gây ngộp) → 1 dòng hint chung bên dưới. */
#honorific-accordion label { font-weight: 500 !important; white-space: nowrap; }
#honorific-accordion .gr-check-radio span,
#honorific-accordion label > span:not(:first-child) { font-size: 0.92rem !important; }
/* Gradio render info trong block-info/.info — ẩn để khỏi chiếm 3-4 dòng/ô */
#honorific-accordion div[data-testid="block-info"],
#honorific-accordion .info { display: none !important; }
/* dòng hint chung: nhỏ, italic, mực nhạt */
#honorific-accordion .honorific-hint, #honorific-accordion .honorific-hint p {
    font-size: 0.82rem !important;
    font-style: italic;
    color: var(--muted) !important;
    margin: 10px 2px 2px !important;
    line-height: 1.45 !important;
}
/* chip "thử nghiệm": son nhạt trên giấy, không in nghiêng */
#honorific-accordion .honorific-hint .exp-badge {
    display: inline-block;
    font-style: normal;
    font-size: 0.72rem;
    font-weight: 600;
    letter-spacing: 0.02em;
    color: var(--accent);
    background: rgba(176, 58, 38, 0.10);
    border: 1px solid rgba(176, 58, 38, 0.28);
    border-radius: 999px;
    padding: 1px 9px;
    margin-right: 6px;
    vertical-align: 1px;
    white-space: nowrap;
}

/* ── Slider ────────────────────────────────────────────────────────── */
input[type="range"]::-webkit-slider-thumb { background: var(--accent) !important; }
.gr-slider .head, .slider_input_container .slider { accent-color: var(--accent) !important; }
/* Beam: chỉ chọn 1–4 → ẩn ô nhập số + nút reset (thừa, gây lệch), giữ thanh kéo.
   Scoped #beam-slider để KHÔNG ảnh hưởng ô số của slider Batch size (cần nhập tay).
   Gradio 6 đặt nút reset aria-label="Reset to default value". */
#beam-slider input[type="number"],
#beam-slider .number-input,
#beam-slider button[aria-label*="eset"],
#beam-slider button[title*="eset"] { display: none !important; }

/* ── Thanh tiến trình tuỳ biến ─────────────────────────────────────── */
.progress-wrap {
    border: 1px solid var(--border);
    background: var(--card);
    border-radius: 14px;
    padding: 14px 18px;
    box-shadow: 0 1px 2px var(--shadow);
}
.progress-head {
    display: flex; justify-content: space-between; align-items: baseline;
    margin-bottom: 9px;
}
.progress-pct {
    font-family: 'Fraunces', Georgia, serif;
    font-size: 1.15rem; font-weight: 600; color: var(--accent);
}
.progress-state {
    font-size: 0.85rem; color: var(--muted); font-style: italic;
}
.progress-track {
    height: 9px; border-radius: 999px;
    background: #e6dac2; overflow: hidden;
    box-shadow: inset 0 1px 2px rgba(90,66,30,0.18);
}
.progress-fill {
    position: relative; overflow: hidden;
    height: 100%; border-radius: 999px;
    background: linear-gradient(90deg, var(--accent), var(--accent-2), var(--gold));
    transition: width 0.3s ease;
}
/* Sọc chéo chạy (tông đỏ chu sa cùng nút Dịch) — báo "đang dịch" rõ, hợp tông
   giấy cũ. Đặt trên ::after để Gradio diff giữ node .progress-fill, animation
   không reset giữa các lần cập nhật % (gr.HTML 6.18 diff in-place). */
.progress-fill.is-running::after {
    content: "";
    position: absolute; inset: 0; border-radius: 999px;
    background-image: repeating-linear-gradient(
        45deg,
        rgba(255,255,255,0.00) 0 11px,
        rgba(122,32,20,0.55) 11px 22px);
    background-size: 31px 31px;
    animation: progress-stripes 0.65s linear infinite;
}
@keyframes progress-stripes { to { background-position: 31px 0; } }
.progress-msg { margin-top: 8px; font-size: 0.92rem; color: var(--ink-soft); }

/* ── Khung đối chiếu song song (xen kẽ câu Trung · Việt) ────────────── */
#compare-view { max-height: 560px; overflow-y: auto; padding-right: 6px; }
/* Thanh cuộn mảnh hợp tông giấy */
#compare-view::-webkit-scrollbar { width: 9px; }
#compare-view::-webkit-scrollbar-thumb { background: #d2c3a6; border-radius: 999px; }
#compare-view::-webkit-scrollbar-track { background: transparent; }

.compare-list { display: flex; flex-direction: column; }
/* Lưới 3 cột: số thứ tự · câu Trung · câu Việt. Cột 1fr/1fr tự wrap nên
   không tràn ngang (lỗi cũ của Dataframe). */
.cmp-head, .cmp-row {
    display: grid;
    grid-template-columns: 2rem 1fr 1fr;
    gap: 16px;
    align-items: start;
}
.cmp-head {
    position: sticky; top: 0; z-index: 2;
    padding: 4px 8px 8px;
    background: linear-gradient(180deg, var(--card) 70%, rgba(251,246,234,0));
    border-bottom: 1px solid var(--border);
}
.cmp-col {
    font-family: 'Fraunces', Georgia, serif;
    font-size: 0.82rem; font-weight: 600; letter-spacing: 0.04em;
    color: var(--gold);
    text-transform: uppercase;
}
.cmp-row {
    padding: 13px 8px 14px;
    border-bottom: 1px solid var(--border-soft);
    border-radius: 10px;
    transition: background 0.12s ease;
}
.cmp-row:last-child { border-bottom: none; }
/* Linked highlight: rê vào hàng → cả ô Trung và ô Việt cùng sáng */
.cmp-row:hover { background: #f4e8d2; }
.cmp-num {
    grid-column: 1;
    min-width: 1.8rem; height: 1.8rem;
    display: inline-flex; align-items: center; justify-content: center;
    font-family: 'Fraunces', Georgia, serif;
    font-size: 0.82rem; font-weight: 600;
    color: var(--accent);
    background: #f3e7d3;
    border: 1px solid var(--border);
    border-radius: 999px;
}
.cmp-row:hover .cmp-num { background: var(--accent); color: #fff7ef; border-color: var(--accent); }
.cmp-zh {
    grid-column: 2; min-width: 0;
    font-family: 'Noto Serif SC', serif;
    font-size: 1.0rem; line-height: 1.7;
    color: var(--ink-soft);
    margin: 0;
}
.cmp-vi {
    grid-column: 3; min-width: 0;
    font-family: 'Literata', Georgia, serif;
    font-size: 1.02rem; line-height: 1.7;
    color: var(--ink);
    margin: 0;
}
.cmp-note {
    padding: 12px 6px 2px; font-size: 0.88rem; font-style: italic;
    color: var(--muted);
}
.compare-empty {
    padding: 22px 8px; text-align: center;
    color: var(--muted); font-style: italic; font-size: 0.95rem;
}

/* ── Accordion ─────────────────────────────────────────────────────── */
/* Header accordion mặc định lấy --body-text-color (trắng ở dark-mode) →
   gần như vô hình trên nền giấy. Ép chữ mực + nền giấy cho rõ. */
.gr-accordion {
    background: var(--card) !important;
    border: 1px solid var(--border) !important;
    border-radius: 12px !important;
}
.gr-accordion .label-wrap, .gr-accordion .label-wrap span, .gr-accordion button.label-wrap {
    color: var(--ink-soft) !important;
    font-family: 'Fraunces', Georgia, serif !important;
    font-weight: 600 !important;
}
.gr-accordion .label-wrap:hover, .gr-accordion .label-wrap:hover span {
    color: var(--accent) !important;
}
.gr-accordion .label-wrap .icon, .gr-accordion .label-wrap svg { color: var(--accent) !important; }

/* ── Khối thông tin máy / engine ───────────────────────────────────── */
.info-card {
    background: var(--card-soft) !important;
    border: 1px solid var(--border-soft) !important;
    border-radius: 12px !important;
    padding: 10px 16px !important;
    font-size: 0.9rem;
    color: var(--ink-soft) !important;
}
.info-card p { margin: 0.2rem 0 !important; color: var(--ink-soft) !important; }
.info-card strong, .info-card code { color: var(--ink) !important; }
code, .prose code {
    background: #efe4cf !important;
    color: var(--accent) !important;
    border-radius: 5px;
    padding: 0.05em 0.4em;
}

/* ── Toast thông báo / lỗi ─────────────────────────────────────────── */
/* Ghi đè trực tiếp (biến cấp .dark của Gradio thắng được khai báo :root),
   đảm bảo toast luôn nền giấy + chữ son, không bị nền đen của dark-mode. */
.toast-body {
    background: var(--card) !important;
    border: 1px solid var(--border) !important;
    color: var(--ink) !important;
    box-shadow: 0 8px 28px -8px var(--shadow) !important;
}
.toast-body.error, .toast-body.warning, .toast-body.info {
    border-left: 4px solid var(--accent) !important;
}
.toast-title, .toast-text, .toast-body * { color: var(--ink) !important; }
.toast-icon, .toast-body svg { color: var(--accent) !important; fill: var(--accent) !important; }
.toast-close { color: var(--muted) !important; }
/* Thanh đếm ngược của toast */
.timer { background: var(--accent) !important; }

/* ── Banner kết quả ────────────────────────────────────────────────── */
/* Rỗng (chưa dịch) → ẩn hẳn, tránh thẻ kem trống chiếm chỗ. */
#result-summary:not(:has(p)):not(:has(li)) { display: none !important; }
#result-summary:has(p), #result-summary:has(li) {
    background: linear-gradient(180deg, #f7ece0, #f2e3d2) !important;
    border: 1px solid var(--border) !important;
    border-left: 4px solid var(--accent) !important;
    border-radius: 12px !important;
    padding: 12px 18px !important;
    margin: 4px 0 6px !important;
}
#result-summary p { margin: 0.15rem 0 !important; color: var(--ink) !important; }

/* ── Badge trạng thái tải model ────────────────────────────────────── */
#model-badge { margin: -0.2rem 0 0.1rem; }
.model-meta {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    flex-wrap: wrap;
}
.model-hf-link {
    font-size: 0.8rem;
    color: var(--accent) !important;
    text-decoration: none;
    border-bottom: 1px solid transparent;
    transition: border-color 0.15s;
}
.model-hf-link:hover { border-bottom-color: var(--accent); }
.model-badge {
    display: inline-block;
    font-size: 0.82rem;
    font-weight: 500;
    padding: 0.18em 0.7em;
    border-radius: 999px;
    border: 1px solid var(--border);
    letter-spacing: 0.01em;
}
.model-badge.ready {
    background: #e8efe0;
    color: #3f5a32;
    border-color: #c2d2b0;
}
.model-badge.pending {
    background: #f6ecd6;
    color: var(--gold);
    border-color: #ddcaa5;
}

/* ── Gợi ý bật GPU (chỉ hiện khi có GPU NVIDIA nhưng đang chạy CPU) ──── */
#gpu-hint-box {
    background: linear-gradient(180deg, #f3ece2, #efe6d4) !important;
    border: 1px solid var(--border) !important;
    border-left: 4px solid var(--gold) !important;
    border-radius: 12px !important;
    padding: 12px 16px !important;
    margin: 4px 0 2px !important;
}
.gpu-hint {
    color: var(--ink-soft);
    font-size: 0.9rem;
    line-height: 1.5;
    margin-bottom: 0.5rem;
}
.gpu-hint b { color: var(--ink); }

footer { display: none !important; }
"""
CUSTOM_CSS = CUSTOM_CSS + "\n" + NOVEL_CSS


def write_pid_file() -> None:
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")


def remove_pid_file() -> None:
    PID_FILE.unlink(missing_ok=True)


def resolve_batch_size(auto_batch: bool, manual_batch: float) -> int:
    if auto_batch:
        profile = detect_hardware_profile()
        translator.apply_hardware_profile(profile)
        return profile.batch_size
    batch = int(manual_batch)
    translator.set_batch_size(batch)
    return batch


def ensure_model(model_key: str, backend: str, beam_size: float) -> str:
    status = translator.load(model_key, backend=backend)
    beam = HachimiTranslator.clamp_beam(beam_size)
    return f"{status} · beam={beam} · batch={translator.batch_size}"


def on_auto_batch_toggle(auto_batch: bool) -> dict:
    profile = detect_hardware_profile()
    return gr.update(value=profile.batch_size, interactive=not auto_batch)


def _model_hf_link(config) -> str:
    url = html.escape(f"https://huggingface.co/{config.model_id}", quote=True)
    return (
        f'<a class="model-hf-link" href="{url}" target="_blank" rel="noopener">'
        "↗ Trang Hugging Face</a>"
    )


def render_model_badge(model_key: str, backend: str) -> str:
    """Badge cho biết model (theo engine đang chọn) đã tải sẵn hay sẽ phải tải,
    kèm link tới trang Hugging Face của model."""
    if model_key not in MODELS:
        return ""
    config = MODELS[model_key]
    link = _model_hf_link(config)

    if is_model_downloaded(model_key, backend):
        badge = '<span class="model-badge ready">✓ Đã tải — dịch được ngay</span>'
        return f'<div class="model-meta">{badge}{link}</div>'

    if backend == Backend.CT2.value and config.ct2_size_mb:
        size = f" (~{config.ct2_size_mb} MB)"
    elif backend != Backend.CT2.value:
        size = " (bản PyTorch, nặng hơn)"
    else:
        size = ""
    badge = (
        f'<span class="model-badge pending">⬇ Chưa có{size} — '
        "sẽ tự tải từ Hugging Face ở lần dịch đầu</span>"
    )
    return f'<div class="model-meta">{badge}{link}</div>'


def on_model_change(model_key: str, backend: str) -> tuple[float, str]:
    return float(MODELS[model_key].default_beam), render_model_badge(model_key, backend)


def install_gpu_torch_ui():
    """Handler nút 'Cài torch để bật GPU'. Stream log pip realtime vào textbox.

    Yield TỪNG dòng pip ngay khi có, nên người dùng thấy tiến trình tải/cài liên
    tục (không bị 'đứng hình' như khi gọi hàm blocking rồi mới in một lần)."""
    if not gpu_available_but_idle():
        yield gr.update(), "Không cần cài: máy không có GPU NVIDIA đang rảnh."
        return

    from translation.core.gpu_setup import (
        _stream_pip,
        choose_cuda_channel,
        torch_install_command,
        verify_ct2_cuda,
        verify_torch_cuda,
    )

    channel = choose_cuda_channel(hardware.DRIVER_CUDA_VERSION)
    if channel is None:
        yield gr.update(), (
            "Driver NVIDIA quá cũ so với các bản torch CUDA hiện có. "
            "Hãy cập nhật driver rồi thử lại."
        )
        return

    logs = [
        f"Cài torch CUDA ({channel}) — tải ~2–3 GB, cần ~5 GB ổ trống. "
        "Vui lòng đợi và ĐỪNG tắt app…",
    ]
    yield gr.update(interactive=False, value="Đang cài… đừng tắt app"), "\n".join(logs)

    exit_code = None
    for line in _stream_pip(torch_install_command(channel)):
        if line.startswith("__EXIT__:"):
            exit_code = int(line.split(":", 1)[1])
            continue
        if line:
            logs.append(line)
            # Giữ textbox gọn: chỉ hiện 200 dòng cuối.
            yield gr.update(interactive=False), "\n".join(logs[-200:])

    if exit_code != 0:
        logs.append("")
        logs.append(f"❌ Cài thất bại (mã {exit_code}). Kiểm tra mạng/đĩa hoặc cài thủ công (README).")
        yield (
            gr.update(interactive=True, value="Thử cài lại"),
            "\n".join(logs[-200:]),
        )
        return

    # pip exit 0 chưa chắc có CUDA (vd đã có torch-CPU). Xác minh thật.
    logs.append("")
    logs.append("Đang kiểm tra torch và CTranslate2 có nhận GPU không…")
    yield gr.update(interactive=False), "\n".join(logs[-200:])

    torch_ok, verify_msg = verify_torch_cuda()
    logs.append(("✅ " if torch_ok else "❌ ") + verify_msg)
    ct2_ok = False
    if torch_ok:
        ct2_ok, ct2_msg = verify_ct2_cuda()
        logs.append(("✅ " if ct2_ok else "❌ ") + ct2_msg)
    ok = torch_ok and ct2_ok
    if ok:
        logs.append("Hãy TẮT và MỞ LẠI app (stop.bat rồi start.bat) để bật GPU.")
    yield (
        gr.update(
            interactive=not ok,
            value="Cài xong — khởi động lại app" if ok else "Thử cài lại",
        ),
        "\n".join(logs[-200:]),
    )


def _engine_hint_text(backend: str) -> str:
    if backend == Backend.CT2.value:
        return "**Engine:** CTranslate2 — khuyên dùng, tận dụng GPU + batch tốt, nhanh nhất."
    return (
        "**Engine:** PyTorch — đã hỗ trợ batch GPU, nhưng vẫn chậm hơn CT2. "
        "GPU % thấp là bình thường với model ~60M."
    )


def on_backend_change(backend: str, model_key: str) -> tuple[str, str]:
    """Đổi engine → cập nhật cả gợi ý engine lẫn badge trạng thái tải của model."""
    return _engine_hint_text(backend), render_model_badge(model_key, backend)


def render_progress_html(pct: float, message: str, running: bool) -> str:
    status = "Đang dịch…" if running else "Sẵn sàng"
    safe_message = html.escape(message, quote=True)
    safe_status = html.escape(status, quote=True)
    running_cls = " is-running" if running else ""
    return f"""
    <div class="progress-wrap">
        <div class="progress-head">
            <span class="progress-pct">{pct:.0f}%</span>
            <span class="progress-state">{safe_status}</span>
        </div>
        <div class="progress-track">
            <div class="progress-fill{running_cls}" style="width: {pct:.1f}%;"></div>
        </div>
        <div class="progress-msg">{safe_message}</div>
    </div>
    """


def _session_key(request: gr.Request | None) -> str | None:
    """session_hash của phiên Gradio; None (không lấy được) rơi về key mặc định
    trong progress_tracker — tức hành vi global cũ, không tệ hơn trước."""
    return getattr(request, "session_hash", None) if request is not None else None


def poll_progress_ui(active: bool, request: gr.Request | None = None) -> str:
    if not active:
        return gr.update()
    state = snapshot(session=_session_key(request))
    return render_progress_html(state.pct, state.message, state.running)


EMPTY_COMPARE_HTML = (
    '<div class="compare-empty">Dịch xong, bản gốc và bản dịch sẽ hiện đối chiếu ở đây '
    "— từng câu một, cuộn dọc để đọc soát.</div>"
)


def render_compare_html(rows: list[tuple[int, str, str]]) -> str:
    """Render đối chiếu song song 2 cột (Trung | Việt), mỗi chunk một hàng.

    Mỗi hàng là một chunk (câu hoặc cả đoạn, tùy chế độ chia) đã khớp sẵn từ
    backend → rê chuột vào một hàng
    thì cả ô Trung lẫn ô Việt cùng sáng (linked highlight kiểu Google Dịch),
    chỉ bằng CSS :hover vì đây là markup của ta trong gr.HTML."""
    if not rows:
        return EMPTY_COMPARE_HTML

    display = rows[:MAX_TABLE_ROWS]
    items = [
        '<div class="cmp-head">'
        '<span class="cmp-num"></span>'
        '<div class="cmp-col">Tiếng Trung</div>'
        '<div class="cmp-col">Tiếng Việt</div>'
        "</div>"
    ]
    for idx, zh, vi in display:
        safe_zh = html.escape(zh, quote=True)
        safe_vi = html.escape(vi, quote=True)
        items.append(
            f'<div class="cmp-row">'
            f'<span class="cmp-num">{idx}</span>'
            f'<p class="cmp-zh">{safe_zh}</p>'
            f'<p class="cmp-vi">{safe_vi}</p>'
            f"</div>"
        )

    note = ""
    if len(rows) > MAX_TABLE_ROWS:
        note = (
            f'<div class="cmp-note">Hiển thị {MAX_TABLE_ROWS}/{len(rows)} đoạn đầu. '
            "Xem bản dịch đầy đủ ở khối bên dưới.</div>"
        )
    return f'<div class="compare-list">{"".join(items)}{note}</div>'


def _decoded_text_score(text: str) -> int:
    """Lower is better. Helps avoid Big5 bytes decoded as valid GB18030 junk."""
    score = 0
    for char in text:
        if char == "\ufffd":
            score += 100
            continue
        if char in "\n\r\t":
            continue
        category = unicodedata.category(char)
        if category.startswith("C"):
            score += 20
            continue
        name = unicodedata.name(char, "")
        if (
            "HIRAGANA" in name
            or "KATAKANA" in name
            or "BOPOMOFO" in name
            or "HANGUL" in name
        ):
            score += 6
    return score


def _candidate_decode_score(text: str) -> int:
    return _decoded_text_score(text[:DECODE_SCORE_SAMPLE_CHARS])


def _utf8_sequence_length(first_byte: int) -> int:
    if 0xC2 <= first_byte <= 0xDF:
        return 2
    if 0xE0 <= first_byte <= 0xEF:
        return 3
    if 0xF0 <= first_byte <= 0xF4:
        return 4
    return 0


def _is_utf8_punctuation_patch(char: str) -> bool:
    codepoint = ord(char)
    if 0x3000 <= codepoint <= 0x303F:  # CJK symbols/punctuation, e.g. 《》
        return True
    if 0xFF00 <= codepoint <= 0xFFEF:  # fullwidth forms
        return True
    return char in "—–“”‘’…"


UTF8_LEGACY_PATCH_CHARS = (
    "《》〈〉「」『』【】（）〔〕，。！？；：“”‘’、—–…"
)


def _decode_mixed_utf8_legacy_fast(data: bytes, encoding: str) -> str | None:
    patched = data
    changed = False
    for char in UTF8_LEGACY_PATCH_CHARS:
        try:
            source = char.encode("utf-8")
            target = char.encode(encoding)
        except UnicodeEncodeError:
            continue
        if source in patched:
            patched = patched.replace(source, target)
            changed = True
    if not changed:
        return None
    try:
        return patched.decode(encoding)
    except UnicodeDecodeError:
        return None


def _decode_utf8_char_at(data: bytes, index: int) -> tuple[str, int] | None:
    length = _utf8_sequence_length(data[index])
    if not length or index + length > len(data):
        return None
    chunk = data[index : index + length]
    try:
        char = chunk.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if len(char) != 1:
        return None
    return char, index + length


def _decode_legacy_char_at(
    data: bytes,
    index: int,
    encoding: str,
) -> tuple[str, int] | None:
    if data[index] < 0x80:
        return chr(data[index]), index + 1
    lengths = (2, 4) if encoding == "gb18030" else (2,)
    for length in lengths:
        if index + length > len(data):
            continue
        try:
            return data[index : index + length].decode(encoding), index + length
        except UnicodeDecodeError:
            continue
    return None


def _decode_mixed_utf8_legacy(data: bytes, encoding: str) -> str | None:
    """Decode legacy Chinese text with occasional UTF-8 punctuation patches.

    Some Quick Translator-era txt files contain GBK/GB18030 body bytes but UTF-8
    CJK punctuation around titles (for example UTF-8 ``《`` + GBK title bytes).
    Strict legacy decode fails on those UTF-8 punctuation bytes, while UTF-8
    replacement decode turns the body into mojibake. Prefer UTF-8 only for known
    punctuation ranges; normal Chinese body bytes stay on the legacy decoder.
    """
    fast_decoded = _decode_mixed_utf8_legacy_fast(data, encoding)
    if fast_decoded is not None:
        return fast_decoded

    output: list[str] = []
    index = 0
    patched = False
    while index < len(data):
        utf8 = _decode_utf8_char_at(data, index)
        if (
            utf8 is not None
            and utf8[1] - index >= 3
            and _is_utf8_punctuation_patch(utf8[0])
        ):
            output.append(utf8[0])
            index = utf8[1]
            patched = True
            continue

        legacy = _decode_legacy_char_at(data, index, encoding)
        if legacy is not None:
            output.append(legacy[0])
            index = legacy[1]
            continue

        if utf8 is not None:
            output.append(utf8[0])
            index = utf8[1]
            patched = True
            continue

        return None

    if not patched:
        return None
    return "".join(output)


def _decode_text_bytes(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue

    candidates: list[tuple[int, int, str]] = []
    for index, encoding in enumerate(LEGACY_TEXT_ENCODINGS):
        try:
            decoded = data.decode(encoding)
        except UnicodeDecodeError:
            decoded = None
        if decoded is not None:
            candidates.append((_candidate_decode_score(decoded), index * 2, decoded))
        mixed_decoded = _decode_mixed_utf8_legacy(data, encoding)
        if mixed_decoded is not None:
            candidates.append((_candidate_decode_score(mixed_decoded), index * 2 + 1, mixed_decoded))

    if candidates:
        return min(candidates, key=lambda item: (item[0], item[1]))[2]
    return data.decode("utf-8", errors="replace")


def read_text_file(path: Path, *, max_chars: int | None = None) -> str:
    text = _decode_text_bytes(path.read_bytes())
    return text[:max_chars] if max_chars is not None else text


# Dấu kết câu để cắt PREVIEW gọn (không đứt giữa câu).
_PREVIEW_SENTENCE_END = "。！？!?…」』）》】”’\n"
_PREVIEW_TRUNCATED_NOTICE = (
    "⚠️ Xem trước chỉ hiển thị phần đầu file — nút Dịch vẫn dịch TOÀN BỘ file."
)


def build_file_preview(text: str, *, max_chars: int = 8000) -> str:
    """Cắt văn bản preview ở ranh giới câu gần ``max_chars`` + ghi chú nếu cắt.

    Tránh hiểu nhầm "file bị cắt": ô xem trước chỉ hiển thị phần đầu, còn nút
    Dịch file đọc toàn bộ. Nếu trong tầm không có dấu câu thì cắt cứng (vẫn ghi
    chú) để không hiển thị vô hạn.
    """
    if len(text) <= max_chars:
        return text
    head = text[:max_chars]
    cut = max((head.rfind(ch) for ch in _PREVIEW_SENTENCE_END), default=-1)
    # Chỉ nhận ranh giới câu nếu nó không quá sớm (giữ ≥ 60% nội dung preview).
    if cut >= int(max_chars * 0.6):
        head = head[: cut + 1]
    return f"{head.rstrip()}\n\n{_PREVIEW_TRUNCATED_NOTICE}"


def cap_input_for_space(source: str) -> tuple[str, str]:
    """Trên Space (CPU dùng chung, công khai): cắt văn bản dài để tránh 1 người
    giữ tài nguyên quá lâu. Trả (văn_bản_đã_cắt, ghi_chú). Local/Colab: trả nguyên
    văn + ghi chú rỗng."""
    if not IS_HF_SPACE or len(source) <= SPACE_MAX_INPUT_CHARS:
        return source, ""
    capped = source[:SPACE_MAX_INPUT_CHARS]
    notice = (
        f" ⚠️ Bản Space (CPU dùng chung) giới hạn ~{SPACE_MAX_INPUT_CHARS:,} ký tự/lần "
        f"— đã dịch phần đầu ({SPACE_MAX_INPUT_CHARS:,}/{len(source):,}). Muốn dịch trọn "
        f"bộ truyện dài, hãy dùng **Google Colab/Kaggle (GPU)** hoặc **bản cài máy** ở phần "
        f"\"🚀 Dùng nhanh/mạnh hơn\" bên trên (không giới hạn, nhanh hơn nhiều)."
    )
    return capped, notice


def _exception_message(exc: Exception) -> str:
    return str(exc).strip() or exc.__class__.__name__


def _request_session_token(request: gr.Request | None) -> str:
    """Return a short, non-reversible scope token without exposing session_hash."""
    session_hash = str(getattr(request, "session_hash", "") or "")
    if not session_hash:
        return "local"
    return hashlib.sha256(session_hash.encode("utf-8")).hexdigest()[:12]


def _unique_export_path(
    kind: str,
    suffix: str,
    request: gr.Request | None = None,
) -> Path:
    safe_kind = "".join(c if c.isalnum() or c in "-_" else "_" for c in kind)
    safe_kind = safe_kind.strip("_")[:80] or "file"
    safe_suffix = suffix.lower().lstrip(".")
    if safe_suffix not in {"txt", "tsv", "json"}:
        raise ValueError(f"Unsupported export suffix: {suffix}")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_token = _request_session_token(request)
    nonce = uuid.uuid4().hex
    return EXPORTS_DIR / (
        f"{EXPORT_FILE_PREFIX}{safe_kind}_{timestamp}_{session_token}_{nonce}.{safe_suffix}"
    )


def _cleanup_old_space_exports(
    *,
    now: float | None = None,
    max_age_seconds: int = SPACE_EXPORT_MAX_AGE_SECONDS,
) -> None:
    """Best-effort cleanup of this app's old ephemeral exports on HF Space only."""
    if not IS_HF_SPACE:
        return
    cutoff = (time.time() if now is None else now) - max_age_seconds
    try:
        candidates = list(EXPORTS_DIR.iterdir())
    except OSError:
        return
    for path in candidates:
        if (
            not path.is_file()
            or not path.name.startswith(EXPORT_FILE_PREFIX)
            or path.suffix.lower() not in {".txt", ".tsv", ".json"}
        ):
            continue
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            continue


def export_translation(
    full_text: str,
    filename_stem: str,
    request: gr.Request | None = None,
) -> str | None:
    if not full_text.strip():
        raise gr.Error("Chưa có bản dịch để xuất.")

    safe_stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in filename_stem) or "translation"
    _cleanup_old_space_exports()
    out_path = _unique_export_path(f"{safe_stem}_vi", "txt", request)
    out_path.write_text(full_text, encoding="utf-8")
    return str(out_path)


def export_translation_ui(
    full_text: str,
    request: gr.Request | None = None,
) -> str | None:
    return export_translation(full_text, "hachimimt", request)


def add_glossary_row_ui(rows) -> list[list[object]]:
    """Append one editable glossary row without relying on Gradio's cell menu."""
    if isinstance(rows, dict):
        rows = rows.get("data", [])
    elif hasattr(rows, "tolist"):
        rows = rows.tolist()

    blank_row: list[object] = ["", "", "", "", True]
    table_rows: list[list[object]] = []
    if isinstance(rows, (list, tuple)):
        for row in rows:
            if not isinstance(row, (list, tuple)):
                continue
            normalized = blank_row.copy()
            for index, value in enumerate(row[: len(blank_row)]):
                normalized[index] = value
            table_rows.append(normalized)

    table_rows.append(blank_row.copy())
    return table_rows


def import_glossary_ui(file_obj) -> tuple[list[list[object]], str]:
    if file_obj is None:
        raise gr.Error("Chọn file glossary .tsv hoặc .json.")
    try:
        rows = read_glossary_file(Path(file_obj))
    except (OSError, GlossaryValidationError) as exc:
        raise gr.Error(f"Không nạp được glossary: {_exception_message(exc)}") from exc
    return rows, f"Đã nạp **{len(rows)}** mục từ `{Path(file_obj).name}`."


def export_glossary_ui(
    rows,
    file_format: str,
    request: gr.Request | None = None,
) -> tuple[str, str]:
    try:
        table_rows = glossary_table_rows(rows)
    except GlossaryValidationError as exc:
        raise gr.Error(f"Glossary không hợp lệ: {_exception_message(exc)}") from exc
    if not table_rows:
        raise gr.Error("Glossary đang trống.")

    file_format = (file_format or "tsv").strip().lower()
    if file_format not in {"tsv", "json"}:
        raise gr.Error("Định dạng glossary phải là TSV hoặc JSON.")
    _cleanup_old_space_exports()
    out_path = _unique_export_path("glossary", file_format, request)
    try:
        write_glossary_file(out_path, table_rows, file_format=file_format)
    except (OSError, GlossaryValidationError) as exc:
        raise gr.Error(f"Không xuất được glossary: {_exception_message(exc)}") from exc
    return str(out_path), f"Đã xuất **{len(table_rows)}** mục glossary."


def _format_duration(seconds: float) -> str:
    """Định dạng thời gian gọn: '12,3 giây' hoặc '2 phút 5 giây'."""
    if seconds < 60:
        return f"{seconds:.1f} giây".replace(".", ",")
    minutes = int(seconds // 60)
    rem = int(round(seconds - minutes * 60))
    if rem == 0:
        return f"{minutes} phút"
    return f"{minutes} phút {rem} giây"


def _clamp_full_text(full_text: str) -> str:
    """Giới hạn text hiển thị trong ô 'Bản dịch đầy đủ' để tránh lag với file lớn.

    Textbox chứa vài MB (truyện hàng chục nghìn câu) làm trình duyệt giật khi
    render/cuộn. File xuất .txt vẫn ĐẦY ĐỦ — đây chỉ cắt phần HIỂN THỊ. User đọc
    trọn bộ bằng nút tải file bên dưới.
    """
    if len(full_text) <= FULL_OUTPUT_DISPLAY_LIMIT:
        return full_text
    head = full_text[:FULL_OUTPUT_DISPLAY_LIMIT].rsplit("\n", 1)[0]
    omitted = len(full_text) - len(head)
    omitted_label = f"{omitted:,}".replace(",", ".")
    return (
        f"{head}\n\n"
        f"────────────────────\n"
        f"[Đã ẩn ~{omitted_label} ký tự còn lại để tránh lag. "
        f"Bản dịch ĐẦY ĐỦ đã lưu — bấm “Xuất bản dịch .txt” / tải file bên dưới.]"
    )


def _build_feedback_context(
    *, rows, run_id, source_kind, model, backend,
    chunk_mode, normalize_mode, honorific, pronoun_v9,
) -> dict:
    """Snapshot toàn ngữ cảnh bản dịch để panel feedback đọc (KHÔNG đọc control
    hiện tại — user có thể đã đổi sau khi dịch)."""
    from translation.core.feedback_log import SCHEMA_VERSION
    return {
        "rows": rows,
        "run_id": run_id,
        "schema_version": SCHEMA_VERSION,
        "source_kind": source_kind,
        "model": model,
        "backend": backend,
        "chunk_mode": chunk_mode,
        "normalize_mode": normalize_mode,
        "honorific": honorific,
        "pronoun_v9": pronoun_v9,
    }


def _build_results(
    rows: list[tuple[int, str, str]],
    full_text: str,
    status: str,
    summary: str,
    download_path: str | None,
    context: dict,
) -> tuple:
    return (
        render_compare_html(rows),
        _clamp_full_text(full_text),
        status,
        download_path,
        summary,
        full_text,  # bản đầy đủ → gr.State cho nút Xuất .txt
        context,    # snapshot → gr.State cho panel feedback
    )


def _progress_stream_update(active: bool = True, *, session: str | None = None) -> tuple:
    state = snapshot(session=session)
    return (
        render_progress_html(state.pct, state.message, state.running),
        active,
        *(gr.update() for _ in range(RESULT_OUTPUT_COUNT)),
    )


def _progress_stream_final(results: tuple, *, session: str | None = None) -> tuple:
    state = snapshot(session=session)
    return (render_progress_html(state.pct, state.message, state.running), False, *results)


def prepare_progress_ui(message: str, *, session: str | None = None) -> tuple[str, bool]:
    set_progress(0, message, session=session)
    return render_progress_html(0, message, True), True


def prepare_text_progress_ui(source: str, request: gr.Request | None = None) -> tuple[str, bool]:
    if not source.strip():
        raise gr.Error("Nhập văn bản tiếng Trung cần dịch.")
    return prepare_progress_ui("Đang chuẩn bị dịch văn bản...", session=_session_key(request))


def prepare_file_progress_ui(file_obj, request: gr.Request | None = None) -> tuple[str, bool]:
    if file_obj is None:
        raise gr.Error("Chọn file .txt cần dịch.")
    path = Path(file_obj)
    if path.suffix.lower() != ".txt":
        raise gr.Error("Chỉ hỗ trợ file .txt")
    return prepare_progress_ui(f"Đang đọc file {path.name}...", session=_session_key(request))


def _layout_lines(text: str) -> list[str]:
    """Tách giữ nguyên bố cục dòng (kể cả dòng trống đầu/cuối), chuẩn hóa newline."""
    return (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")


def rebuild_paragraph_layout(
    source_text: str, rows: list[tuple[int, str, str]]
) -> str:
    """Ghép bản dịch của các dòng (rows) trở lại ĐÚNG bố cục dòng của nguồn.

    rows chỉ chứa dòng nguồn KHÔNG rỗng (1 row / 1 dòng non-blank); hàm này đặt
    chúng lại theo vị trí TUYỆT ĐỐI, chèn dòng trống đúng chỗ nguồn có dòng trống.
    Dùng cho chế độ "Theo đoạn" để hậu xử lý không làm mất ranh giới đoạn.
    """
    translated_iter = iter(vi for _, _, vi in rows)
    output: list[str] = []
    for source_line in _layout_lines(source_text):
        if source_line.strip():
            output.append(next(translated_iter, ""))
        else:
            output.append("")
    sentinel = object()
    if next(translated_iter, sentinel) is not sentinel:
        raise RuntimeError("Số row dịch lớn hơn số dòng nguồn không rỗng")
    return "\n".join(output)


def _result_text_from_rows(
    source_text: str,
    rows: list[tuple[int, str, str]],
    backend: str,
) -> str:
    if backend == Backend.CT2.value:
        return rebuild_paragraph_layout(source_text, rows)
    return "\n".join(translated_vi for _, _, translated_vi in rows)


def _retry_glossary_failed_rows(
    rows: list[tuple[int, str, str]],
    failed_indices: tuple[int, ...],
    *,
    beam_size: int,
) -> list[tuple[int, str, str]]:
    """Translate failed placeholder rows again from their original source."""
    failed = set(failed_indices)
    source_by_index = {
        index: source_zh
        for index, source_zh, _translated_vi in rows
        if index in failed
    }
    missing = failed - set(source_by_index)
    if missing:
        raise RuntimeError(
            "Không tìm thấy dòng nguồn để fallback glossary: "
            + ", ".join(str(index) for index in sorted(missing))
        )

    fallback_by_index: dict[int, str] = {}
    for index in failed_indices:
        fallback_text: str | None = None
        for _done, _total, _message, result_rows, result_text in translator.translate_text_iter(
            source_by_index[index],
            chunk_mode="paragraph",
            beam_size=beam_size,
        ):
            if result_rows is not None and result_text is not None:
                fallback_text = result_text
        if fallback_text is None:
            raise RuntimeError(f"Fallback glossary không trả kết quả cho dòng {index}.")
        fallback_by_index[index] = fallback_text.strip()

    return [
        (
            index,
            source_zh,
            fallback_by_index.get(index, translated_vi),
        )
        for index, source_zh, translated_vi in rows
    ]


def apply_postprocess_rows(
    rows: list[tuple[int, str, str]],
    *,
    honorific_kinship: bool,
    honorific_pronouns: bool,
    pronoun_harmonizer_v9: bool,
    raw_full_text: str | None = None,
    source_text: str = "",
    chunk_mode: str = "sentence",
) -> tuple[list[tuple[int, str, str]], str, dict]:
    raw_rows = list(rows)
    # raw_full_text = bản đã restore (từ translator). Nếu caller không truyền thì
    # dựng tạm từ rows.
    if raw_full_text is None:
        raw_full_text = "\n".join(vi for _, _, vi in raw_rows)
    try:
        fixed_rows, fixed_full_text, report = _apply_postprocess_rows(
            raw_rows,
            honorific_kinship=honorific_kinship,
            honorific_pronouns=honorific_pronouns,
            pronoun_harmonizer_v9=pronoun_harmonizer_v9,
        )
        # _apply_postprocess_rows trả full_text join phẳng (mất dòng trống). Cả
        # "Theo câu" lẫn "Theo đoạn" nay đều có rows = 1-dòng-non-blank/row →
        # dựng lại full_text theo bố cục nguồn (giữ dòng trống) từ rows ĐÃ hậu xử
        # lý (row count giữ nhờ guard V9). Test cũ không truyền source_text →
        # giữ đường join phẳng (backward-compat).
        if source_text:
            fixed_full_text = rebuild_paragraph_layout(source_text, fixed_rows)
        return fixed_rows, fixed_full_text, report
    except Exception as exc:
        # Trả raw_full_text THẬT (đã restore), không dựng lại từ rows non-blank.
        return raw_rows, raw_full_text, {
            "genre_decision": None,
            "honorific_changed": 0,
            "honorific_pronouns_effective": False,
            "honorific_kinship_effective": False,
            "pronoun_report": {},
            "warning": _exception_message(exc),
            "fallback": "raw",
        }


def _policy_rows(rows: list[tuple[int, str, str]]) -> list[tuple[int, str, str]]:
    return [
        (index, normalize_chinese_text(chunk_zh, NORMALIZE_T2S), translated_vi)
        for index, chunk_zh, translated_vi in rows
    ]


def _apply_postprocess_rows(
    rows: list[tuple[int, str, str]],
    *,
    honorific_kinship: bool,
    honorific_pronouns: bool,
    pronoun_harmonizer_v9: bool,
) -> tuple[list[tuple[int, str, str]], str, dict]:
    policy_rows = _policy_rows(rows)
    genre_decision = classify_genre(policy_rows) if policy_rows else None
    honorific_changed = 0
    pronoun_report = {}

    honorific_pronouns_effective = bool(honorific_pronouns and genre_decision and genre_decision.is_classical)
    honorific_kinship_effective = bool(honorific_kinship)
    honorific_on_effective = honorific_kinship_effective or honorific_pronouns_effective

    if honorific_on_effective and rows:
        new_rows = []
        for (index, chunk_zh, translated_vi), (_, policy_zh, _) in zip(rows, policy_rows):
            fixed = normalize_honorifics(
                policy_zh, translated_vi,
                apply_kinship=honorific_kinship_effective,
                apply_pronouns=honorific_pronouns_effective,
                classical_context=genre_decision.is_classical if genre_decision else None,
            )
            if fixed != translated_vi:
                honorific_changed += 1
            new_rows.append((index, chunk_zh, fixed))
        rows = new_rows

    if pronoun_harmonizer_v9 and rows:
        v9_policy_rows = [
            (index, normalize_chinese_text(chunk_zh, NORMALIZE_T2S), translated_vi)
            for index, chunk_zh, translated_vi in rows
        ]
        v9_rows, pronoun_report = harmonize_pronouns_v9(
            v9_policy_rows,
            route=v9_route_for_decision(genre_decision) if genre_decision else "unknown_copy_guard",
        )
        if len(v9_rows) != len(rows):
            raise RuntimeError(f"V9 row count mismatch: expected {len(rows)}, got {len(v9_rows)}")
        for (original_index, _, _), (fixed_index, _, _) in zip(rows, v9_rows):
            if original_index != fixed_index:
                raise RuntimeError(f"V9 row index mismatch: {original_index} != {fixed_index}")
        rows = [
            (index, original_zh, fixed_vi)
            for (index, original_zh, _), (_, _, fixed_vi) in zip(rows, v9_rows)
        ]

    full_text = "\n".join(vi for _, _, vi in rows)
    return rows, full_text, {
        "genre_decision": genre_decision,
        "honorific_changed": honorific_changed,
        "honorific_pronouns_effective": honorific_pronouns_effective,
        "honorific_kinship_effective": honorific_kinship_effective,
        "pronoun_report": pronoun_report,
    }


def _translate_run(
    source: str,
    model_key: str,
    backend: str,
    beam_size: float,
    chunk_mode: str,
    normalize_mode: str,
    honorific_kinship: bool,
    honorific_pronouns: bool,
    pronoun_harmonizer_v9: bool,
    auto_batch: bool,
    manual_batch: float,
    *,
    glossary_rows=None,
    filename_stem: str,
    summary_prefix: str,
    source_kind: str,
    session: str | None = None,
) -> Iterator[tuple]:
    try:
        source, space_cap_notice = cap_input_for_space(source)
        original_source = source
        source = normalize_chinese_text(source, normalize_mode)
        normalize_msg = normalization_message(original_source, source, normalize_mode)
        try:
            glossary_entries = compile_glossary(
                glossary_rows,
                normalize_source=lambda term: normalize_chinese_text(term, normalize_mode),
            )
        except GlossaryValidationError as exc:
            raise gr.Error(f"Glossary không hợp lệ: {_exception_message(exc)}") from exc
        honorific_kinship = bool(honorific_kinship)
        honorific_pronouns = bool(honorific_pronouns)
        honorific_on = honorific_kinship or honorific_pronouns
        pronoun_harmonizer_v9 = bool(pronoun_harmonizer_v9)
        placeholder_scope = (
            PLACEHOLDER_SCOPE_LINE
            if backend == Backend.CT2.value
            else PLACEHOLDER_SCOPE_DOCUMENT
        )
        glossary_protection = protect_glossary_text(
            source,
            glossary_entries,
            scope=placeholder_scope,
        )
        model_source = glossary_protection.text

        if is_model_downloaded(model_key, backend):
            load_msg = "Đang nạp model..."
        else:
            label = MODELS[model_key].label if model_key in MODELS else model_key
            load_msg = f"Đang tải model {label} từ Hugging Face (lần đầu, vui lòng đợi)..."
        set_progress(0, load_msg, session=session)
        yield _progress_stream_update(session=session)

        resolve_batch_size(auto_batch, manual_batch)
        status = ensure_model(model_key, backend, beam_size)

        protection_note = (
            f" Đã bảo vệ {glossary_protection.protected_occurrences} tên/thuật ngữ."
            if glossary_protection.protected_occurrences
            else ""
        )
        set_progress(
            2,
            f"{normalize_msg}{protection_note} Đang chia chunk...",
            session=session,
        )
        yield _progress_stream_update(session=session)

        rows: list[tuple[int, str, str]] = []
        full_text = ""
        last_progress_update = 0.0
        translate_start = time.perf_counter()
        run_id = uuid.uuid4().hex[:8]

        for done, total, message, result_rows, result_text in translator.translate_text_iter(
            model_source,
            chunk_mode=chunk_mode,
            beam_size=int(beam_size),
        ):
            if result_rows is not None and result_text is not None:
                rows = result_rows
                full_text = result_text
                continue

            now = time.perf_counter()
            should_update_progress = (
                done == 0
                or done == total
                or now - last_progress_update >= PROGRESS_UPDATE_SECONDS
            )
            if not should_update_progress:
                continue

            pct = round(done / max(total, 1) * 100, 1)
            detail = f"{message} ({pct}%)"
            set_progress(pct, detail, session=session)
            last_progress_update = now
            yield _progress_stream_update(session=session)

        translate_profile = dict(translator.last_profile)
        glossary_restore_report = None
        glossary_retry_rows = 0
        if glossary_protection.protected_occurrences:
            rows, glossary_restore_report = restore_glossary_rows(
                rows,
                glossary_protection,
            )
            if glossary_restore_report.failed_indices:
                glossary_retry_rows = glossary_restore_report.failed_rows
                set_progress(
                    99,
                    f"Glossary: dịch lại {glossary_retry_rows} dòng có placeholder lỗi...",
                    session=session,
                )
                yield _progress_stream_update(session=session)
                rows = _retry_glossary_failed_rows(
                    rows,
                    glossary_restore_report.failed_indices,
                    beam_size=int(beam_size),
                )
            full_text = _result_text_from_rows(source, rows, backend)

        rows, full_text, postprocess_report = apply_postprocess_rows(
            rows,
            honorific_kinship=honorific_kinship,
            honorific_pronouns=honorific_pronouns,
            pronoun_harmonizer_v9=pronoun_harmonizer_v9,
            raw_full_text=full_text,
            source_text=source,
            chunk_mode=chunk_mode,
        )
        genre_decision = postprocess_report.get("genre_decision")
        honorific_changed = int(postprocess_report.get("honorific_changed") or 0)
        honorific_pronouns_effective = bool(postprocess_report.get("honorific_pronouns_effective"))
        pronoun_report = postprocess_report.get("pronoun_report") or {}
        postprocess_warning = str(postprocess_report.get("warning") or "")
        glossary_report = None
        glossary_warning = ""
        if glossary_entries:
            before_glossary_rows = rows
            before_glossary_text = full_text
            try:
                rows, glossary_report = apply_glossary_rows(rows, glossary_entries)
                if glossary_report.changed_rows:
                    full_text = _result_text_from_rows(source, rows, backend)
            except Exception as exc:
                rows = before_glossary_rows
                full_text = before_glossary_text
                glossary_warning = _exception_message(exc)

        translate_seconds = time.perf_counter() - translate_start

        # KHÔNG auto-tạo file .txt mỗi lần dịch (tránh rác temp) — file chỉ sinh
        # khi user bấm nút "Xuất bản dịch .txt" (export_btn.click). Bản dịch đầy đủ
        # vẫn nằm trong ô + full_text_state để xuất khi cần.
        download_path = None
        duration = _format_duration(translate_seconds)
        chunk_count = int(translate_profile.get("chunks") or len(rows))
        fallback_chunks = int(translate_profile.get("paragraph_fallback_chunks") or 0)
        fallback_lines = int(translate_profile.get("paragraph_fallback_lines") or 0)
        measured_chunks = max(chunk_count + fallback_chunks, 1)
        rate = measured_chunks / translate_seconds if translate_seconds > 0 else 0.0
        time_note = f"⏱ {duration}"
        if rate >= 1:
            time_note += f" ({rate:.0f} chunk/giây)"
        fallback_note = ""
        if fallback_lines:
            fallback_note = (
                f" Fallback giữ dòng: dịch lại {fallback_lines} dòng"
                f" ({fallback_chunks} chunk)."
            )
        honorific_note = ""
        if honorific_on:
            parts = []
            if honorific_kinship:
                parts.append("thân tộc")
            if honorific_pronouns:
                parts.append("đại từ" if honorific_pronouns_effective else "đại từ bỏ qua")
            honorific_note = (f" Đã chuẩn hóa xưng hô ({' + '.join(parts)}): "
                              f"{honorific_changed} chunk chỉnh.")
        pronoun_note = ""
        if pronoun_harmonizer_v9:
            pronoun_note = (
                " Ổn định ngôi xưng V9: "
                f"{pronoun_report.get('changed_rows', 0)} chunk chỉnh, "
                f"route `{pronoun_report.get('route', 'n/a')}`."
            )
        route_note = f" Route hậu kỳ `{genre_decision.route}`." if genre_decision and (honorific_on or pronoun_harmonizer_v9) else ""
        warning_note = f" Hậu kỳ lỗi, đã giữ bản dịch thô: {postprocess_warning}." if postprocess_warning else ""
        glossary_note = ""
        if glossary_report is not None:
            glossary_note = (
                f" Glossary: {glossary_report.entries} mục, "
                f"{glossary_report.source_hits} hit nguồn; "
                f"{glossary_report.replacements} thay thế alias, "
                f"{glossary_report.satisfied} đã đúng, "
                f"{glossary_report.unresolved} chưa khớp alias."
            )
            if glossary_restore_report is not None:
                glossary_note += (
                    f" Placeholder: {glossary_restore_report.protected_occurrences} bảo vệ, "
                    f"{glossary_restore_report.restored_occurrences} restore"
                )
                if glossary_restore_report.skipped_occurrences:
                    glossary_note += (
                        f", {glossary_restore_report.skipped_occurrences} vượt pool"
                    )
                if glossary_retry_rows:
                    glossary_note += f", {glossary_retry_rows} dòng retry"
                glossary_note += "."
        elif glossary_warning:
            glossary_note = (
                f" Glossary lỗi, đã giữ bản trước glossary: {glossary_warning}."
            )
        summary = f"{summary_prefix} **{chunk_count}** chunk · {time_note}. {normalize_msg}{fallback_note}{route_note}{honorific_note}{pronoun_note}{warning_note}{glossary_note}{space_cap_notice}"
        status = f"{status} · {time_note}"
        finish_progress(
            f"Hoàn tất — {chunk_count} chunk trong {duration} (100%)",
            session=session,
        )

        feedback_context = _build_feedback_context(
            rows=rows,
            run_id=run_id,
            source_kind=source_kind,
            model=model_key,
            backend=backend,
            chunk_mode=chunk_mode,
            normalize_mode=normalize_mode,
            honorific=_feedback_honorific_label(honorific_kinship, honorific_pronouns),
            pronoun_v9=pronoun_harmonizer_v9,
        )
        yield _progress_stream_final(
            _build_results(rows, full_text, status, summary, download_path, feedback_context),
            session=session,
        )
    except Exception as exc:
        reset_progress(f"Lỗi: {_exception_message(exc)}", session=session)
        yield _progress_stream_update(active=False, session=session)
        raise


def translate_text_ui(
    source: str,
    model_key: str,
    backend: str,
    beam_size: float,
    chunk_mode: str,
    normalize_mode: str,
    honorific_kinship: bool,
    honorific_pronouns: bool,
    pronoun_harmonizer_v9: bool,
    auto_batch: bool,
    manual_batch: float,
    glossary_rows=None,
    request: gr.Request | None = None,
) -> Iterator[tuple]:
    if not source.strip():
        raise gr.Error("Nhập văn bản tiếng Trung cần dịch.")

    yield from _translate_run(
        source,
        model_key,
        backend,
        beam_size,
        chunk_mode,
        normalize_mode,
        honorific_kinship,
        honorific_pronouns,
        pronoun_harmonizer_v9,
        auto_batch,
        manual_batch,
        glossary_rows=glossary_rows,
        filename_stem="hachimimt",
        summary_prefix="Đã dịch",
        source_kind="text",
        session=_session_key(request),
    )


def translate_file_ui(
    file_obj,
    model_key: str,
    backend: str,
    beam_size: float,
    chunk_mode: str,
    normalize_mode: str,
    honorific_kinship: bool,
    honorific_pronouns: bool,
    pronoun_harmonizer_v9: bool,
    auto_batch: bool,
    manual_batch: float,
    glossary_rows=None,
    request: gr.Request | None = None,
) -> Iterator[tuple]:
    if file_obj is None:
        raise gr.Error("Chọn file .txt cần dịch.")

    path = Path(file_obj)
    if path.suffix.lower() != ".txt":
        raise gr.Error("Chỉ hỗ trợ file .txt")

    source = read_text_file(path)
    if not source.strip():
        raise gr.Error("File trống.")

    yield from _translate_run(
        source,
        model_key,
        backend,
        beam_size,
        chunk_mode,
        normalize_mode,
        honorific_kinship,
        honorific_pronouns,
        pronoun_harmonizer_v9,
        auto_batch,
        manual_batch,
        glossary_rows=glossary_rows,
        filename_stem=path.stem,
        summary_prefix=f"Đã dịch từ `{path.name}` —",
        source_kind="file",
        session=_session_key(request),
    )


def _find_row(idx, rows):
    for r in rows:
        if r[0] == idx:
            return r
    return None


def _load_sentence(idx, context) -> tuple[str, str, str, str]:
    """Nạp câu theo idx từ context snapshot vào panel."""
    rows = (context or {}).get("rows") or []
    try:
        idx = int(idx)
    except (TypeError, ValueError):
        return "", "", "", "⚠️ Số thứ tự không hợp lệ."
    row = _find_row(idx, rows)
    if row is None:
        return "", "", "", f"⚠️ Không có câu #{idx} trong bản dịch hiện tại."
    _, zh, vi = row
    return zh, vi, vi, f"Đã nạp câu #{idx}. Sửa rồi bấm lưu."


def _save_feedback(idx, corrected, category, rating, context, *, require_correction: bool = False) -> str:
    """Ghi 1 feedback. Metadata lấy TỪ CONTEXT (không từ control hiện tại).

    require_correction=True: chặn ghi khi ô sửa rỗng (dùng cho nút 💾 và Lưu & câu tiếp).
    require_correction=False (mặc định): cho phép ghi không có bản sửa (dùng cho nút 👎).
    """
    from translation.core.feedback_log import FeedbackEntry, SCHEMA_VERSION, append_feedback

    ctx = context or {}
    rows = ctx.get("rows") or []
    try:
        idx = int(idx)
    except (TypeError, ValueError):
        return "⚠️ Hãy chọn câu trước (số thứ tự không hợp lệ)."
    row = _find_row(idx, rows)
    if row is None:
        return "⚠️ Hãy chọn câu hợp lệ trước khi lưu."
    _, zh, vi = row

    if rating == "good":
        corrected_val = None
        category_val = None        # 👍 → category vô nghĩa, ép None (tránh nhiễu)
    else:
        corrected_val = (corrected or "").strip() or None
        category_val = category or None
        if require_correction and corrected_val is None:
            return "⚠️ Ô sửa trống — hãy sửa câu hoặc dùng 👎 nếu chỉ muốn báo lỗi."
        if require_correction and corrected_val == (vi or "").strip():
            return "⚠️ Bản sửa chưa khác bản dịch hiện tại — hãy sửa câu trước khi lưu."

    try:
        append_feedback(FeedbackEntry(
            schema_version=SCHEMA_VERSION,
            ts=datetime.now().astimezone().isoformat(timespec="seconds"),
            run_id=ctx.get("run_id", ""),
            source_kind=ctx.get("source_kind", ""),
            model=ctx.get("model", ""),
            backend=ctx.get("backend", ""),
            chunk_mode=ctx.get("chunk_mode", ""),
            normalize_mode=ctx.get("normalize_mode", ""),
            honorific=ctx.get("honorific", "none"),
            pronoun_v9=bool(ctx.get("pronoun_v9", False)),
            category=category_val,
            idx=idx,
            source=zh,
            mt_final=vi,
            corrected=corrected_val,
            rating=rating,
        ))
    except Exception as exc:  # ghi lỗi không làm sập app
        return f"⚠️ Lỗi ghi feedback: {exc}"
    verb = "👍 Tốt" if rating == "good" else "Đã lưu"
    return f"✓ {verb} câu #{idx}."


def _save_and_next(idx, corrected, category, context) -> tuple:
    """Lưu (rating=bad, yêu cầu có sửa) rồi nạp câu kế. Lưu lỗi/trống → không tiến."""
    status = _save_feedback(idx, corrected, category, "bad", context, require_correction=True)
    if status.startswith("⚠️"):
        # Lưu không thành (ô trống hoặc lỗi) → giữ nguyên câu, không nhảy
        rows = (context or {}).get("rows") or []
        try:
            cur = int(idx)
        except (TypeError, ValueError):
            row = None
        else:
            row = _find_row(cur, rows)
        if row is None:
            return idx, "", "", "", status
        _, zh, vi = row
        return idx, zh, vi, corrected, status
    rows = (context or {}).get("rows") or []
    try:
        cur = int(idx)
    except (TypeError, ValueError):
        return idx, "", "", "", status
    nxt = cur + 1
    if _find_row(nxt, rows) is None:
        return cur, "", "", "", status + " Đã hết câu."
    zh, vi, edit, load_status = _load_sentence(nxt, context)
    return nxt, zh, vi, edit, status + f" → {load_status}"


def build_result_outputs(base_outputs: list, feedback_context_state) -> list:
    """result_outputs LUÔN gồm feedback_context_state ở cuối (khớp 7-tuple của
    _build_results) dù panel feedback có hiện hay không."""
    return [*base_outputs, feedback_context_state]


def build_ui() -> gr.Blocks:
    model_choices = [(cfg.label, key) for key, cfg in MODELS.items()]

    with gr.Blocks(title="HachimiMT — Dịch Trung Việt") as demo:
        # ── Header ────────────────────────────────────────────────────
        with gr.Column(elem_id="app-header"):
            gr.Markdown("# HachimiMT", elem_id="app-title")
        gr.HTML('<div id="app-rule"></div>')

        # ── Banner demo (chỉ trên Space) ──────────────────────────────
        if IS_HF_SPACE:
            gr.HTML(
                '<div id="demo-banner">'
                'Đây là <b>bản demo chạy CPU</b> — phù hợp dịch thử đoạn ngắn. '
                'Cần <b>GPU</b>, dịch <b>file/chương dài</b> hay chạy <b>offline</b>? '
                f'<a href="{COLAB_URL}" target="_blank" rel="noopener">☁️ chạy trên Google Colab</a> '
                f'/ <a href="{KAGGLE_NOTEBOOK_URL}" target="_blank" rel="noopener">Kaggle T4×2</a> '
                f'hoặc <a href="{LOCAL_ZIP_URL}">⬇ tải bản cài máy</a> '
                '(chi tiết ở mục “Dùng nhanh/mạnh hơn” cuối trang).'
                "</div>"
            )

        # ── Khu cấu hình ──────────────────────────────────────────────
        with gr.Group(elem_id="settings-card"):
            gr.Markdown("Cấu hình dịch", elem_classes=["section-label"])
            with gr.Row():
                model_select = gr.Dropdown(
                    choices=model_choices, value="HachimiMT-60", label="Model dịch", scale=3,
                )
                backend_select = gr.Radio(
                    [("CTranslate2 — nhanh", Backend.CT2.value), ("PyTorch", Backend.TRANSFORMERS.value)],
                    value=Backend.CT2.value,
                    label="Engine",
                    scale=3,
                )
                # Space (CPU): default beam=1 (nhanh hơn rõ, demo ưu tiên tốc độ);
                # local: beam=2 (chất lượng nhỉnh hơn, máy mạnh). User vẫn kéo được.
                beam_size = gr.Slider(1, 4, value=(1 if IS_HF_SPACE else 2), step=1,
                                      label="Beam (1–4)", scale=2, elem_id="beam-slider",
                                      info="Cao hơn = dịch kỹ hơn, chậm hơn")
                chunk_mode = gr.Radio(
                    [("Theo câu", "sentence"), ("Theo đoạn", "paragraph")],
                    value="sentence",
                    label="Chia chunk",
                    scale=2,
                    info="Theo câu: bám sát từng dòng. Theo đoạn: gom dòng cùng đoạn "
                    "để thêm ngữ cảnh, tự dịch lại từng dòng khi restore rủi ro.",
                )
                normalize_mode = gr.Dropdown(
                    [
                        ("Tự động phồn → giản", NORMALIZE_AUTO),
                        ("Ép phồn → giản", NORMALIZE_T2S),
                        ("Giữ nguyên", NORMALIZE_NONE),
                    ],
                    value=NORMALIZE_AUTO,
                    label="Chuẩn hóa chữ Hán",
                    scale=2,
                )
            with gr.Row():
                auto_batch = gr.Checkbox(value=True, label="Tự động batch theo CPU/GPU", scale=2)
                manual_batch = gr.Slider(
                    4, 128, value=HW_PROFILE.batch_size, step=4,
                    label="Batch size (chunk/lần)", interactive=False, scale=3,
                )

            model_badge = gr.HTML(
                render_model_badge("HachimiMT-60", Backend.CT2.value),
                elem_id="model-badge",
            )
            engine_hint = gr.Markdown(_engine_hint_text(Backend.CT2.value))
            status = gr.Textbox(
                label="Trạng thái", value="Sẵn sàng — chọn cấu hình rồi bắt đầu dịch.",
                interactive=False, elem_classes=["status-box"],
            )

            _gpu_idle = gpu_available_but_idle()
            with gr.Group(visible=_gpu_idle, elem_id="gpu-hint-box") as gpu_hint_group:
                gpu_hint = gr.HTML(render_gpu_hint_html())
                gpu_install_btn = gr.Button(
                    "⚡ Cài torch để bật GPU (tải ~2–3 GB, cần ~5 GB trống)",
                    variant="primary",
                )
                gpu_install_log = gr.Textbox(
                    label="Tiến trình cài đặt",
                    value="",
                    interactive=False,
                    lines=6,
                    visible=False,
                    elem_classes=["status-box"],
                )

        with gr.Accordion("🧪 Tuỳ chọn chuẩn hóa xưng hô (nâng cao · thử nghiệm)", open=False,
                          elem_id="honorific-accordion"):
            with gr.Row():
                honorific_kinship = gr.Checkbox(
                    value=False, label="Thân tộc (tỷ / muội / ca ca…)", scale=1,
                )
                honorific_pronouns = gr.Checkbox(
                    value=False, label="Đại từ (ngươi / hắn / nàng / ta)", scale=1,
                )
                pronoun_harmonizer_v9 = gr.Checkbox(
                    value=False, label="Ổn định ngôi hiện đại", scale=1,
                )
            gr.Markdown(
                "<span class=\"exp-badge\">🧪 Thử nghiệm</span> Hậu kỳ chỉnh xưng hô "
                "ngoài model — bản dịch gốc thường đã ổn, đây là lớp tinh chỉnh tuỳ chọn "
                "nên **mặc định tắt**; bật khi muốn ép phong cách, và nên rà lại kết quả.\n\n"
                "Ép xưng hô về Hán-Việt khi nguồn có từ tương ứng · **Đại từ** chỉ áp "
                "khi route cấp chương là văn cổ trang · **Ổn định ngôi hiện đại** chỉ "
                "rewrite khi route hiện đại, ví dụ thầy/em, mẹ/con, anh/em. Mixed/unknown "
                "sẽ guard để tránh sửa quá tay.",
                elem_classes=["honorific-hint"],
            )

        with gr.Accordion("📚 Tên riêng & thuật ngữ (glossary)", open=False,
                          elem_id="glossary-accordion"):
            gr.Markdown(
                "Glossary thay đúng `source_zh` bằng **placeholder đã kiểm định** trước khi "
                "Marian dịch, rồi khôi phục thành `target_vi`; vì vậy tên hiếm không phụ "
                "thuộc vào cách model tự phiên âm. Nếu placeholder bị mất/đổi/lặp, dòng đó "
                "được dịch lại từ nguồn gốc và mới dùng alias làm fallback. "
                "`Loại` chỉ để quản lý và **không bắt buộc**.",
                elem_classes=["honorific-hint"],
            )
            glossary_table = gr.Dataframe(
                value=[["", "", "", "", True]],
                headers=[
                    "Nguồn Trung *",
                    "Đích Việt *",
                    "Loại (tùy chọn)",
                    "Alias fallback (tùy chọn, ngăn bằng |)",
                    "Bật",
                ],
                datatype=["str", "str", "str", "str", "bool"],
                type="array",
                row_count=3,
                column_count=5,
                column_widths=["20%", "22%", "16%", "32%", "10%"],
                max_height=360,
                interactive=True,
                show_row_numbers=True,
                label="Glossary của phiên hiện tại",
                elem_id="glossary-table",
            )
            with gr.Row():
                glossary_add_row_btn = gr.Button(
                    "＋ Thêm hàng",
                    variant="secondary",
                    size="sm",
                    scale=0,
                    min_width=140,
                    elem_id="glossary-add-row",
                )
            with gr.Row():
                glossary_file = gr.File(
                    label="Nhập glossary (.tsv / .json)",
                    file_types=[".tsv", ".json"],
                    type="filepath",
                    scale=3,
                )
                glossary_format = gr.Radio(
                    [("TSV", "tsv"), ("JSON", "json")],
                    value="tsv",
                    label="Định dạng xuất",
                    scale=1,
                )
            with gr.Row():
                glossary_import_btn = gr.Button("Nạp vào bảng", variant="secondary")
                glossary_export_btn = gr.Button("Xuất glossary", variant="secondary")
            glossary_download = gr.File(label="Tải glossary")
            glossary_status = gr.Markdown()

        if IS_HF_SPACE:
            with gr.Accordion("🚀 Dùng nhanh/mạnh hơn — Google Colab/Kaggle (GPU) hoặc cài máy (offline)", open=False):
                gr.Markdown(
                    f"""Bản Space này chạy **CPU** nên hợp dịch thử. Ba cách dùng nhanh/mạnh hơn:

### ☁️ Cách 1 — Chạy trên Google Colab (CPU/GPU miễn phí, không cài gì)

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)]({COLAB_URL})

Bấm nút trên → đăng nhập Google → `Runtime → Run all` → mở link `*.gradio.live` hiện
ra để dịch. Muốn nhanh: chọn `Runtime → Change runtime type → T4 GPU` trước (Colab tiếng
Việt: `Thời gian chạy → Thay đổi loại thời gian chạy → T4 GPU → Lưu`). ⚠️ Chọn **T4 GPU**,
KHÔNG chọn **TPU** — app chỉ chạy GPU NVIDIA/CPU, không dùng được TPU.

> ⚡ **Tốc độ trên Colab T4** (đo thật, notebook đã tối ưu window): **~40.000 chữ Hán/giây**
> ở beam 1 hoặc **~28.000 chữ/giây** ở beam 2; cả một bộ truyện dài **2,4 triệu chữ
> khoảng 1–1,5 phút**. Nhanh hơn CPU nhiều lần.

### ☁️ Cách 2 — Chạy trên Kaggle (T4×2 miễn phí, hợp dịch file dài)

[![Open in Kaggle](https://kaggle.com/static/images/open-in-kaggle.svg)]({KAGGLE_NOTEBOOK_URL})

Bấm nút trên → đăng nhập Kaggle → bấm **Create / Edit** (Kaggle tạo notebook từ
GitHub) → bật `Settings → Accelerator → GPU T4 x2` và `Settings → Internet → on`
→ `Run All`. Cell cuối hiện link `*.gradio.live` để mở giao diện dịch. Notebook đã
bật `HACHIMIMT_AUTO_ALL_GPUS=1` và window tối ưu để dùng cả 2 GPU T4 khi Kaggle cấp đủ.

> ⚡ **Tốc độ trên T4 x2** (đo mới nhất): **~81.000 chữ Hán/giây** (beam 1) hoặc
> **~54.000 chữ Hán/giây** (beam 2) — file **2,84 triệu chữ ~35 giây** ở beam 1,
> hoặc **~52 giây** ở beam 2. Nhanh hơn Colab T4 x1 beam 2 khoảng 1,9× trên file dài.

### 💻 Cách 3 — Cài bản chạy trên máy (offline, dịch file lớn)

**1. Tải về** — [⬇ Tải bản cài (.zip, ~60 KB)]({LOCAL_ZIP_URL}) rồi giải nén
(ra thư mục `hachimimt/`).

**2. Windows** (cần [Python 3.10+](https://www.python.org/downloads/)): trong thư
mục `hachimimt`, chạy `setup.bat` (cài thư viện + tải model mặc định, một lần) rồi
`start.bat` — trình duyệt tự mở `http://127.0.0.1:7860`.

**3. macOS / Linux**: `./setup_macos.sh` rồi `./start_macos.sh` (xem `README.md`).

- **GPU NVIDIA**: app mặc định chạy CPU; có nút **“Cài torch để bật GPU”** ngay trong
  app (tải ~2–3 GB, một lần) → nhanh hơn nhiều lần với văn bản dài.
- Các model tự tải từ Hugging Face lần đầu, sau đó chạy **offline**.
- Bản local mở khoá: chọn 8 model, dịch file `.txt`, không giới hạn CPU như Space.""",
                    elem_classes=["info-card"],
                )

        with gr.Accordion("Thông tin máy & hướng dẫn", open=False):
            _startup_line = (
                ""  # Space: không có start.bat / 127.0.0.1 → bỏ dòng vô nghĩa
                if IS_HF_SPACE
                else f"\n\n**Khởi động / tắt:** `start.bat` / `stop.bat` · http://127.0.0.1:{APP_PORT}"
            )
            gr.Markdown(
                f"**Cấu hình tự động:** {HW_PROFILE.summary}\n\n"
                f"**GPU inference:** {HW_PROFILE.gpu_name or 'CPU'}"
                f"{_startup_line}",
                elem_classes=["info-card"],
            )

        model_select.change(
            on_model_change,
            inputs=[model_select, backend_select],
            outputs=[beam_size, model_badge],
        )
        backend_select.change(
            on_backend_change,
            inputs=[backend_select, model_select],
            outputs=[engine_hint, model_badge],
        )
        auto_batch.change(on_auto_batch_toggle, inputs=[auto_batch], outputs=[manual_batch])
        glossary_add_row_event = glossary_add_row_btn.click(
            add_glossary_row_ui,
            inputs=[glossary_table],
            outputs=[glossary_table],
            queue=False,
        )
        glossary_add_row_event.then(
            fn=None,
            js="() => window.__hachimimtRefreshGlossaryTable?.()",
            queue=False,
            api_name=False,
        )
        glossary_import_btn.click(
            import_glossary_ui,
            inputs=[glossary_file],
            outputs=[glossary_table, glossary_status],
            queue=False,
        )
        glossary_export_btn.click(
            export_glossary_ui,
            inputs=[glossary_table, glossary_format],
            outputs=[glossary_download, glossary_status],
            queue=False,
        )

        gpu_install_btn.click(
            lambda: gr.update(visible=True),
            outputs=[gpu_install_log],
        ).then(
            install_gpu_torch_ui,
            outputs=[gpu_install_btn, gpu_install_log],
        )

        # ── Nhập liệu (tiểu thuyết / văn bản / file) ──────────────────
        with gr.Tabs():
            build_novel_tab(
                translator,
                model_select,
                backend_select,
                beam_size,
                chunk_mode,
                normalize_mode,
                honorific_kinship,
                honorific_pronouns,
                pronoun_harmonizer_v9,
                auto_batch,
                manual_batch,
                glossary_table,
            )
            with gr.Tab("📝 Dịch văn bản"):
                source = gr.Textbox(
                    label="Văn bản gốc (Tiếng Trung)",
                    placeholder="粘贴中文原文…",
                    lines=10,
                    elem_classes=["source-input"],
                )
                text_btn = gr.Button("Dịch văn bản", variant="primary", size="lg")

            with gr.Tab("📄 Dịch file .txt"):
                gr.Markdown("Upload file `.txt` tiếng Trung → dịch toàn bộ → tải file `.txt` tiếng Việt.")
                file_input = gr.File(label="Chọn file .txt đầu vào", file_types=[".txt"], type="filepath")
                file_preview = gr.Textbox(
                    label="Xem trước nội dung file", lines=8, interactive=False, elem_classes=["file-preview"],
                )
                file_btn = gr.Button("Dịch file & xuất .txt", variant="primary", size="lg")

                def preview_file(file_obj) -> str:
                    if not file_obj:
                        return ""
                    return build_file_preview(read_text_file(Path(file_obj)), max_chars=8000)

                file_input.change(preview_file, inputs=[file_input], outputs=[file_preview])

        # ── Tiến trình (một thanh duy nhất) ───────────────────────────
        progress_html = gr.HTML(render_progress_html(0, "Sẵn sàng.", False))
        progress_active_state = gr.State(False)

        # ── Kết quả ───────────────────────────────────────────────────
        result_summary = gr.Markdown(elem_id="result-summary")

        with gr.Accordion("Đối chiếu song song (bản gốc · bản dịch)", open=True):
            compare_view = gr.HTML(render_compare_html([]), elem_id="compare-view")

        with gr.Accordion("Bản dịch đầy đủ & xuất file", open=True):
            full_output = gr.Textbox(
                label="Bản dịch đầy đủ", lines=10, interactive=False,
                elem_id="full-output",
            )
            # Giữ bản dịch ĐẦY ĐỦ (không bị cap hiển thị) để nút Xuất .txt dùng.
            full_text_state = gr.State("")
            # Snapshot ngữ cảnh bản dịch cho panel feedback (luôn tạo, kể cả khi
            # panel ẩn — để result_outputs khớp 7-tuple của _build_results).
            feedback_context_state = gr.State({})
            with gr.Row():
                export_btn = gr.Button("💾 Xuất bản dịch .txt", variant="secondary")
                download_file = gr.File(label="Tải file bản dịch (.txt)")

        if feedback_panel_enabled(DEV_FEEDBACK, IS_HF_SPACE):
            with gr.Accordion("📝 Góp ý / sửa câu dịch (dev)", open=False):
                fb_idx = gr.Number(label="Số thứ tự câu", precision=0, value=1)
                fb_source = gr.Textbox(label="Câu gốc (Trung)", interactive=False, lines=2)
                fb_mt = gr.Textbox(label="Bản dịch hiện tại", interactive=False, lines=2)
                fb_edit = gr.Textbox(label="Bản sửa của bạn", lines=2)
                fb_category = gr.Dropdown(
                    label="Loại lỗi (tùy chọn)",
                    choices=["name", "pronoun", "punctuation", "line_break",
                             "missing", "hallucination", "style", "other"],
                    value=None, allow_custom_value=False,
                )
                with gr.Row():
                    fb_good = gr.Button("👍 Tốt")
                    fb_bad = gr.Button("👎 Chưa đạt")
                    fb_save = gr.Button("💾 Lưu bản sửa", variant="primary")
                    fb_next = gr.Button("⏭ Lưu & câu tiếp")
                fb_status = gr.Markdown()

            fb_idx.change(
                _load_sentence,
                inputs=[fb_idx, feedback_context_state],
                outputs=[fb_source, fb_mt, fb_edit, fb_status],
            )
            fb_good.click(
                lambda idx, ctx: _save_feedback(idx, "", None, "good", ctx),
                inputs=[fb_idx, feedback_context_state], outputs=[fb_status],
            )
            fb_bad.click(
                lambda idx, cat, ctx: _save_feedback(idx, "", cat, "bad", ctx),
                inputs=[fb_idx, fb_category, feedback_context_state], outputs=[fb_status],
            )
            fb_save.click(
                lambda idx, corr, cat, ctx: _save_feedback(idx, corr, cat, "bad", ctx, require_correction=True),
                inputs=[fb_idx, fb_edit, fb_category, feedback_context_state],
                outputs=[fb_status],
            )
            fb_next.click(
                _save_and_next,
                inputs=[fb_idx, fb_edit, fb_category, feedback_context_state],
                outputs=[fb_idx, fb_source, fb_mt, fb_edit, fb_status],
            )

        result_outputs = build_result_outputs([
            compare_view,
            full_output,
            status,
            download_file,
            result_summary,
            full_text_state,
        ], feedback_context_state)
        translate_outputs = [progress_html, progress_active_state, *result_outputs]

        translate_inputs = [
            model_select, backend_select, beam_size, chunk_mode, normalize_mode,
            honorific_kinship, honorific_pronouns, pronoun_harmonizer_v9,
            auto_batch, manual_batch, glossary_table,
        ]

        text_event = text_btn.click(
            prepare_text_progress_ui,
            inputs=[source],
            outputs=[progress_html, progress_active_state],
            scroll_to_output=True,
            show_progress="hidden",
            queue=False,
        )
        text_event.then(
            translate_text_ui,
            inputs=[source, *translate_inputs],
            outputs=translate_outputs,
            scroll_to_output=True,
            show_progress="hidden",
            concurrency_limit=1,
            concurrency_id="translate",
        )

        file_event = file_btn.click(
            prepare_file_progress_ui,
            inputs=[file_input],
            outputs=[progress_html, progress_active_state],
            scroll_to_output=True,
            show_progress="hidden",
            queue=False,
        )
        file_event.then(
            translate_file_ui,
            inputs=[file_input, *translate_inputs],
            outputs=translate_outputs,
            scroll_to_output=True,
            show_progress="hidden",
            concurrency_limit=1,
            concurrency_id="translate",
        )

        export_btn.click(
            export_translation_ui,
            inputs=[full_text_state], outputs=[download_file],
        )

        progress_timer = gr.Timer(0.5, active=True)
        progress_timer.tick(
            poll_progress_ui,
            inputs=[progress_active_state],
            outputs=[progress_html],
            show_progress=False,
            queue=False,
        )

    return demo


def main() -> None:
    if not IS_HF_SPACE:           # Space: process do HF quản, không cần PID
        write_pid_file()
        atexit.register(remove_pid_file)
    else:
        # Trên Space: cache + warmup model mặc định (HachimiMT-60 CT2) lúc KHỞI ĐỘNG
        # (startup runtime, trong main() — KHÔNG phải build-time) → user mở lên dịch
        # được NGAY, không chờ tải lần đầu. Hiệu quả vì Space giữ process chạy lâu.
        # Lỗi (mạng) KHÔNG chặn app — fallback lazy-download khi dịch.
        try:
            print(f"[Space] cpu_count={os.cpu_count()} threads={os.environ.get('HACHIMIMT_THREADS')} "
                  f"batch={os.environ.get('HACHIMIMT_BATCH_SIZE')} — cache + warmup {DEFAULT_MODEL_KEY}...",
                  flush=True)
            ensure_model_files(MODELS[DEFAULT_MODEL_KEY], Backend.CT2)
            # load() đã tự warmup (dịch 1 câu) → user dịch là nhanh ngay.
            translator.load(DEFAULT_MODEL_KEY, Backend.CT2)
            print(f"[Space] Đã cache + warmup {DEFAULT_MODEL_KEY}.", flush=True)
        except Exception as exc:  # noqa: BLE001 — preload best-effort, không fatal
            print(f"[Space] Preload/warmup lỗi (sẽ lazy khi dịch): {exc}", flush=True)
    reset_progress()

    demo = build_ui()
    demo.queue(default_concurrency_limit=8)
    # Gradio 6: theme/css/head truyền ở launch() (không còn ở Blocks()).
    favicon = Path(__file__).resolve().parent / "assets" / "favicon.svg"
    launch_kwargs = dict(
        theme=gr.themes.Soft(primary_hue="orange", neutral_hue="stone"),
        css=CUSTOM_CSS,
        head=HEAD_HTML,
        favicon_path=str(favicon) if favicon.exists() else None,
        allowed_paths=[str(EXPORTS_DIR), tempfile.gettempdir()],
    )
    # HACHIMIMT_SHARE=1 (Google Colab / máy từ xa): tạo link share công khai
    # (gradio.live), bind 0.0.0.0 để truy cập từ ngoài.
    share = os.environ.get("HACHIMIMT_SHARE", "").strip() == "1"
    if share:
        launch_kwargs["share"] = True
        launch_kwargs["server_name"] = "0.0.0.0"
    elif not IS_HF_SPACE:         # local: bind localhost cố định; Space: HF tự lo
        launch_kwargs["server_name"] = "127.0.0.1"
        launch_kwargs["server_port"] = APP_PORT
    demo.launch(**launch_kwargs)


if __name__ == "__main__":
    main()
