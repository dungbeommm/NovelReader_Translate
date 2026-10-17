"""Benchmark local file translation throughput."""

from __future__ import annotations

import argparse
import importlib.metadata
import os
import platform
import time
from pathlib import Path

from translation.core.app import read_text_file
from translation.core.ct2_safe_import import import_ctranslate2
from translation.core.hardware import detect_hardware_profile
from translation.core.text_preprocess import (
    NORMALIZE_AUTO,
    NORMALIZE_MODES,
    normalization_message,
    normalize_chinese_text,
)
from translation.core.translator import Backend, HachimiTranslator


TRACKED_ENV_KEYS = (
    "CUDA_VISIBLE_DEVICES",
    "HACHIMIMT_GPU_INDICES",
    "HACHIMIMT_AUTO_ALL_GPUS",
    "HACHIMIMT_BATCH_SIZE",
    "HACHIMIMT_THREADS",
    "HACHIMIMT_TOKENIZE_WORKERS",
    "HACHIMIMT_TOKENIZE_JOB_SIZE",
    "HACHIMIMT_CT2_BATCH_TYPE",
    "HACHIMIMT_CT2_WINDOW_MULTIPLIER",
    "HACHIMIMT_INTER_THREADS",
    "HACHIMIMT_COMPUTE_TYPE",
)


TRACKED_PACKAGES = (
    "ctranslate2",
    "sentencepiece",
    "tokenizers",
    "huggingface_hub",
    "torch",
    "transformers",
    "gradio",
)


def _safe_field(value: object) -> str:
    text = str(value)
    return text.replace("\\", "/").replace(" ", "_").replace("\n", "_")


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "missing"


def _ct2_cuda_device_count() -> int | str:
    try:
        ctranslate2 = import_ctranslate2()

        return ctranslate2.get_cuda_device_count()
    except Exception as exc:
        return f"error:{type(exc).__name__}"


def _print_runtime_context() -> None:
    runtime_parts = [
        f"python={_safe_field(platform.python_version())}",
        f"platform={_safe_field(platform.platform())}",
        f"processor={_safe_field(platform.processor() or 'unknown')}",
        f"ct2_cuda_devices={_ct2_cuda_device_count()}",
    ]
    print("BENCH_RUNTIME " + " ".join(runtime_parts), flush=True)

    package_parts = [f"{name}={_safe_field(_package_version(name))}" for name in TRACKED_PACKAGES]
    print("BENCH_PACKAGES " + " ".join(package_parts), flush=True)

    env_parts = [f"{key}={_safe_field(os.environ.get(key, '<unset>'))}" for key in TRACKED_ENV_KEYS]
    print("BENCH_ENV " + " ".join(env_parts), flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="Input .txt file")
    parser.add_argument("--model", default="HachimiMT-60")
    parser.add_argument("--backend", choices=[Backend.CT2.value, Backend.TRANSFORMERS.value], default=Backend.CT2.value)
    parser.add_argument("--beam", type=int, default=2)
    parser.add_argument("--chunk-mode", choices=["sentence", "paragraph"], default="sentence")
    parser.add_argument("--normalize", choices=sorted(NORMALIZE_MODES), default=NORMALIZE_AUTO)
    parser.add_argument("--progress-seconds", type=float, default=15.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    total_start = time.perf_counter()

    profile = detect_hardware_profile()
    print(f"BENCH_START file={args.path}", flush=True)
    print(f"PROFILE {profile.summary}", flush=True)
    _print_runtime_context()

    read_start = time.perf_counter()
    text = read_text_file(args.path)
    read_s = time.perf_counter() - read_start
    original_chars = len(text)
    normalize_start = time.perf_counter()
    normalized_text = normalize_chinese_text(text, args.normalize)
    normalize_s = time.perf_counter() - normalize_start
    normalize_msg = normalization_message(text, normalized_text, args.normalize)
    text = normalized_text
    print(
        f"INPUT chars={len(text)} original_chars={original_chars} "
        f"lines={text.count(chr(10)) + 1 if text else 0} read_s={read_s:.3f} "
        f"normalize_s={normalize_s:.3f} normalize={args.normalize} "
        f"normalize_msg={normalize_msg}",
        flush=True,
    )

    translator = HachimiTranslator(profile)
    load_start = time.perf_counter()
    status = translator.load(args.model, backend=args.backend)
    load_s = time.perf_counter() - load_start
    print(f"LOAD seconds={load_s:.3f} status={status}", flush=True)

    translate_start = time.perf_counter()
    last_print = 0.0
    rows = []
    full_text = ""

    for done, total, message, result_rows, result_text in translator.translate_text_iter(
        text,
        chunk_mode=args.chunk_mode,
        beam_size=args.beam,
    ):
        now = time.perf_counter()
        if result_rows is not None and result_text is not None:
            rows = result_rows
            full_text = result_text

        if done == 0 or done == total or now - last_print >= args.progress_seconds:
            elapsed = now - translate_start
            rate = done / elapsed if elapsed > 0 else 0.0
            eta = (total - done) / rate if rate > 0 else 0.0
            pct = done / total * 100 if total else 100.0
            print(
                "PROGRESS "
                f"done={done} total={total} pct={pct:.2f} elapsed_s={elapsed:.1f} "
                f"rate_chunks_s={rate:.2f} eta_s={eta:.1f} message={message}",
                flush=True,
            )
            last_print = now

    translate_s = time.perf_counter() - translate_start
    total_s = time.perf_counter() - total_start
    profile = translator.last_profile
    if profile:
        profile_parts = []
        for key in sorted(profile):
            value = profile[key]
            if isinstance(value, float):
                profile_parts.append(f"{key}={value:.6f}")
            else:
                profile_parts.append(f"{key}={value}")
        print("BENCH_PROFILE " + " ".join(profile_parts), flush=True)
    print(
        "BENCH_DONE "
        f"total_s={total_s:.3f} translate_s={translate_s:.3f} minutes={total_s / 60:.3f} "
        f"chunks={len(rows)} chars_in={len(text)} chars_out={len(full_text)} "
        f"chunks_s={(len(rows) / translate_s) if translate_s > 0 else 0:.3f} "
        f"chars_s={(len(text) / translate_s) if translate_s > 0 else 0:.1f}",
        flush=True,
    )


if __name__ == "__main__":
    main()
