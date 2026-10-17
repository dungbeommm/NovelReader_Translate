"""Run multiple benchmark_file.py configurations and summarize throughput."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def parse_int_list(raw: str, *, name: str) -> list[int]:
    values: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            value = int(part)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"{name} phải là danh sách số: {raw!r}") from exc
        if value <= 0:
            raise argparse.ArgumentTypeError(f"{name} chỉ nhận số dương: {raw!r}")
        values.append(value)
    if not values:
        raise argparse.ArgumentTypeError(f"{name} không được rỗng")
    return values


def parse_kv_line(line: str) -> dict[str, str]:
    data: dict[str, str] = {}
    for part in line.split()[1:]:
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        data[key] = value
    return data


def float_or_zero(value: str | None) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except ValueError:
        return 0.0


def set_or_unset(env: dict[str, str], key: str, value: str | None) -> None:
    value = (value or "").strip()
    if value:
        env[key] = value
    else:
        env.pop(key, None)


def build_env(args: argparse.Namespace, *, batch: int, window: int) -> dict[str, str]:
    env = os.environ.copy()
    if args.single_gpu:
        env["HACHIMIMT_GPU_INDICES"] = args.gpu_indices
        env["HACHIMIMT_AUTO_ALL_GPUS"] = "0"
    elif args.auto_all_gpus:
        env.pop("HACHIMIMT_GPU_INDICES", None)
        env["HACHIMIMT_AUTO_ALL_GPUS"] = "1"
    else:
        env.pop("HACHIMIMT_GPU_INDICES", None)
        env.pop("HACHIMIMT_AUTO_ALL_GPUS", None)

    env["HACHIMIMT_BATCH_SIZE"] = str(batch)
    env["HACHIMIMT_CT2_WINDOW_MULTIPLIER"] = str(window)
    set_or_unset(env, "HACHIMIMT_CT2_BATCH_TYPE", args.ct2_batch_type)
    set_or_unset(env, "HACHIMIMT_INTER_THREADS", args.inter_threads)
    set_or_unset(env, "HACHIMIMT_TOKENIZE_WORKERS", args.tokenize_workers)
    set_or_unset(env, "HACHIMIMT_TOKENIZE_JOB_SIZE", args.tokenize_job_size)
    set_or_unset(env, "HACHIMIMT_THREADS", args.ct2_threads)
    return env


def build_command(args: argparse.Namespace, *, beam: int) -> list[str]:
    script = Path(__file__).with_name("benchmark_file.py")
    return [
        sys.executable,
        str(script),
        str(args.path),
        "--model",
        args.model,
        "--backend",
        args.backend,
        "--beam",
        str(beam),
        "--chunk-mode",
        args.chunk_mode,
        "--normalize",
        args.normalize,
        "--progress-seconds",
        str(args.progress_seconds),
    ]


def run_one(
    args: argparse.Namespace,
    *,
    label: str,
    beam: int,
    batch: int,
    window: int,
) -> dict[str, object]:
    env = build_env(args, batch=batch, window=window)
    cmd = build_command(args, beam=beam)

    print(f"SWEEP_RUN label={label} beam={beam} batch={batch} window={window}", flush=True)
    print("SWEEP_CMD " + " ".join(cmd), flush=True)
    if args.dry_run:
        return {
            "label": label,
            "beam": beam,
            "batch": batch,
            "window": window,
            "done": {},
            "profile": {},
            "runtime": {},
            "packages": {},
            "env": {},
            "returncode": 0,
        }

    lines: list[str] = []
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
    )
    assert process.stdout is not None
    for line in process.stdout:
        print(line, end="")
        lines.append(line.rstrip("\n"))
    returncode = process.wait()
    if returncode != 0:
        raise subprocess.CalledProcessError(returncode, cmd)

    profile_lines = [line for line in lines if line.startswith("BENCH_PROFILE")]
    done_lines = [line for line in lines if line.startswith("BENCH_DONE")]
    runtime_lines = [line for line in lines if line.startswith("BENCH_RUNTIME")]
    package_lines = [line for line in lines if line.startswith("BENCH_PACKAGES")]
    env_lines = [line for line in lines if line.startswith("BENCH_ENV")]

    result = {
        "label": label,
        "beam": beam,
        "batch": batch,
        "window": window,
        "done": parse_kv_line(done_lines[-1]) if done_lines else {},
        "profile": parse_kv_line(profile_lines[-1]) if profile_lines else {},
        "runtime": parse_kv_line(runtime_lines[-1]) if runtime_lines else {},
        "packages": parse_kv_line(package_lines[-1]) if package_lines else {},
        "env": parse_kv_line(env_lines[-1]) if env_lines else {},
        "returncode": returncode,
    }
    print(format_sweep_result(result), flush=True)
    return result


def format_sweep_result(result: dict[str, object], *, prefix: str = "SWEEP_RESULT") -> str:
    done = result["done"]
    profile = result["profile"]
    assert isinstance(done, dict)
    assert isinstance(profile, dict)
    fields = [
        f"label={result['label']}",
        f"beam={result['beam']}",
        f"batch={result['batch']}",
        f"window={result['window']}",
        f"translate_s={done.get('translate_s', '')}",
        f"chars_s={done.get('chars_s', '')}",
        f"chunks_s={done.get('chunks_s', '')}",
        f"ct2_infer_s={profile.get('ct2_infer_s', '')}",
        f"decode_s={profile.get('decode_s', '')}",
        f"chunk_s={profile.get('chunk_s', '')}",
        f"tokenize_wait_s={profile.get('tokenize_wait_s', '')}",
    ]
    return prefix + " " + " ".join(fields)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="Input .txt file")
    parser.add_argument("--model", default="HachimiMT-60")
    parser.add_argument("--backend", choices=["ct2", "transformers"], default="ct2")
    parser.add_argument("--chunk-mode", choices=["sentence", "paragraph"], default="sentence")
    parser.add_argument("--normalize", choices=["auto", "none", "t2s"], default="auto")
    parser.add_argument("--beams", default="1,2", help="Comma-separated beam sizes")
    parser.add_argument("--batches", default="96", help="Comma-separated batch sizes")
    parser.add_argument("--windows", default="4,8,16", help="Comma-separated CT2 window multipliers")
    parser.add_argument("--single-gpu", action="store_true", help="Force HACHIMIMT_GPU_INDICES to one GPU")
    parser.add_argument("--auto-all-gpus", action="store_true", help="Force HACHIMIMT_AUTO_ALL_GPUS=1")
    parser.add_argument("--gpu-indices", default="0")
    parser.add_argument("--ct2-batch-type", default="tokens")
    parser.add_argument("--inter-threads", default="1")
    parser.add_argument("--tokenize-workers", default="")
    parser.add_argument("--tokenize-job-size", default="")
    parser.add_argument("--ct2-threads", default="")
    parser.add_argument("--progress-seconds", type=float, default=999999.0)
    parser.add_argument("--max-runs", type=int, default=0, help="Optional cap for quick smoke tests")
    parser.add_argument("--dry-run", action="store_true", help="Print planned runs without translating")
    args = parser.parse_args()
    args.beams_list = parse_int_list(args.beams, name="--beams")
    args.batches_list = parse_int_list(args.batches, name="--batches")
    args.windows_list = parse_int_list(args.windows, name="--windows")
    if args.single_gpu and args.auto_all_gpus:
        parser.error("--single-gpu và --auto-all-gpus không dùng cùng lúc")
    if not args.dry_run and not args.path.exists():
        parser.error(f"Input file không tồn tại: {args.path}")
    return args


def main() -> None:
    args = parse_args()
    results: list[dict[str, object]] = []
    planned = 0
    for beam in args.beams_list:
        for batch in args.batches_list:
            for window in args.windows_list:
                planned += 1
                if args.max_runs and len(results) >= args.max_runs:
                    break
                mode = "1gpu" if args.single_gpu else "allgpu" if args.auto_all_gpus else "auto"
                label = f"beam{beam}-batch{batch}-window{window}-{mode}"
                results.append(run_one(args, label=label, beam=beam, batch=batch, window=window))
            if args.max_runs and len(results) >= args.max_runs:
                break
        if args.max_runs and len(results) >= args.max_runs:
            break

    print(f"SWEEP_DONE planned={planned} ran={len(results)}", flush=True)
    if args.dry_run or not results:
        return

    ranked = sorted(
        results,
        key=lambda result: float_or_zero(result["done"].get("chars_s") if isinstance(result["done"], dict) else None),
        reverse=True,
    )
    print("\n--- sweep summary (best first) ---", flush=True)
    for result in ranked:
        print(format_sweep_result(result), flush=True)
    print(format_sweep_result(ranked[0], prefix="SWEEP_BEST"), flush=True)


if __name__ == "__main__":
    main()
