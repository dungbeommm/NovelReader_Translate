"""Batch TTS theo chuong bang Piper (giong Ngoc Huyen) + convert + dong goi.

Doc:
  <chapters_dir>/manifest.json  (do parse_ebook.py tao)
  job.json                       (option nguoi dung, tuy chon)

Quy trinh:
  1. Load PiperVoice 1 lan.
  2. Voi moi chuong -> synthesize WAV.
  3. Convert sang dinh dang dich (mp3/wav/m4b) bang ffmpeg.
  4. Dong goi:
       - format == m4b: gop tat ca thanh 1 audiobook co chapter marks.
       - package == zip (va nhieu file): nen .zip.
       - package == single (1 chuong): giu file don.

Output: cac file cuoi cung nam trong <out_dir> (mac dinh: release/).

Vi du:
    python batch_tts.py --chapters-dir chapters --out-dir release \\
        --title "Ten Truyen" --format mp3 --length-scale 1.0 --package zip
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import wave
import zipfile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MODEL = os.path.join(BASE_DIR, "..", "..", "models", "voices", "ngochuyennew.onnx")
DEFAULT_CONFIG = os.path.join(BASE_DIR, "..", "..", "models", "voices", "ngochuyennew.onnx.json")


# ------------------------------------------------------------ piper synth

def load_voice(model, config):
    from piper import PiperVoice
    print("Dang tai model Piper: %s" % model, flush=True)
    return PiperVoice.load(model, config_path=config)


def synth_to_wav(voice, text, out_wav, length_scale=None, noise_scale=None, noise_w=None):
    from tts.synthesis import synthesize_wav
    with wave.open(out_wav, 'wb') as wav_file:
        synthesize_wav(voice, text, wav_file,
                       length_scale=1.0 if length_scale is None else length_scale,
                       noise_scale=0.667 if noise_scale is None else noise_scale,
                       noise_w_scale=0.8 if noise_w is None else noise_w)


# --- helper moi: chia nho van ban + gom WAV (chong tran bo nho voi chuong dai) ---

def split_text(text, max_chars):
    """Chia van ban dai thanh cac doan <= max_chars, uu tien cat theo cau/dong."""
    if max_chars <= 0 or len(text) <= max_chars:
        return [text]
    parts = re.split(r"(?<=[.!?\u2026])\s+|\n+", text)
    chunks, cur = [], ""
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if len(p) > max_chars:
            if cur:
                chunks.append(cur)
                cur = ""
            for i in range(0, len(p), max_chars):
                chunks.append(p[i:i + max_chars])
            continue
        if cur and len(cur) + len(p) + 1 > max_chars:
            chunks.append(cur)
            cur = p
        else:
            cur = (cur + " " + p).strip() if cur else p
    if cur:
        chunks.append(cur)
    return chunks


def concat_wavs(parts, out_path):
    """Noi nhieu file WAV cung dinh dang thanh 1 (khong re-encode)."""
    with wave.open(parts[0], "rb") as w0:
        params = w0.getparams()
    with wave.open(out_path, "wb") as out:
        out.setparams(params)
        for p in parts:
            with wave.open(p, "rb") as w:
                out.writeframes(w.readframes(w.getnframes()))


def synth_chapter(voice, text, out_wav, work_dir, chunk_chars,
                  length_scale=None, noise_scale=None, noise_w=None):
    """Tong hop 1 chuong; neu qua dai thi chia nho roi gom lai de tranh OOM."""
    chunks = split_text(text, chunk_chars)
    if len(chunks) <= 1:
        synth_to_wav(voice, text, out_wav, length_scale, noise_scale, noise_w)
        return
    base = os.path.splitext(os.path.basename(out_wav))[0]
    parts = []
    for i, ch in enumerate(chunks):
        pp = os.path.join(work_dir, "%s__p%04d.wav" % (base, i))
        synth_to_wav(voice, ch, pp, length_scale, noise_scale, noise_w)
        parts.append(pp)
    concat_wavs(parts, out_wav)
    for pp in parts:
        try:
            os.remove(pp)
        except OSError:
            pass


def audio_duration(path):
    """Do dai audio (giay); ho tro ca WAV lan dinh dang khac qua ffprobe."""
    try:
        with wave.open(path, "rb") as w:
            return w.getnframes() / float(w.getframerate())
    except Exception:
        try:
            out = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=nw=1:nk=1", path],
                capture_output=True, text=True, check=True,
            )
            return float(out.stdout.strip())
        except Exception:
            return 0.0


# ------------------------------------------------------------ ffmpeg utils

def ensure_ffmpeg():
    if not shutil.which("ffmpeg"):
        raise RuntimeError("Thieu ffmpeg. Hay cai ffmpeg trong moi truong chay.")


def wav_duration(path):
    with wave.open(path, "rb") as w:
        return w.getnframes() / float(w.getframerate())


def convert_audio(in_wav, out_path, fmt):
    """Convert WAV -> mp3/ogg/opus/wav bang ffmpeg."""
    if fmt == "wav":
        shutil.copyfile(in_wav, out_path)
        return
    codec = {
        "mp3": ["-codec:a", "libmp3lame", "-qscale:a", "3"],
        "ogg": ["-codec:a", "libvorbis", "-qscale:a", "4"],
        "opus": ["-codec:a", "libopus", "-b:a", "48k"],
        "m4a": ["-codec:a", "aac", "-b:a", "128k"],
    }.get(fmt, ["-codec:a", "libmp3lame", "-qscale:a", "3"])
    subprocess.run(
        ["ffmpeg", "-y", "-i", in_wav, *codec, out_path],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def concat_audio(files, out_path, fmt):
    """Noi (ghep) nhieu file audio cung dinh dang thanh 1 file lien tuc.

    Giu dung thu tu chuong. Re-encode de tranh loi param khong dong nhat.
    """
    if not files:
        raise RuntimeError("Khong co file de ghep")
    if len(files) == 1:
        shutil.copyfile(files[0], out_path)
        return
    if fmt == "wav":
        concat_wavs(files, out_path)
        return
    workdir = os.path.dirname(os.path.abspath(out_path)) or "."
    list_path = os.path.join(workdir, "_merge_%d.txt" % os.getpid())
    with open(list_path, "w", encoding="utf-8") as f:
        for fp in files:
            f.write("file '%s'\n" % os.path.abspath(fp).replace("'", r"'\''"))
    codec = {
        "mp3": ["-codec:a", "libmp3lame", "-qscale:a", "3"],
        "ogg": ["-codec:a", "libvorbis", "-qscale:a", "4"],
        "opus": ["-codec:a", "libopus", "-b:a", "48k"],
        "m4a": ["-codec:a", "aac", "-b:a", "128k"],
    }.get(fmt, ["-codec:a", "libmp3lame", "-qscale:a", "3"])
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path,
             *codec, out_path],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    finally:
        try:
            os.remove(list_path)
        except OSError:
            pass


def build_m4b(wav_files, titles, out_path, title):
    """Gop nhieu WAV thanh 1 file .m4b co chapter marks."""
    # 1. Tao FFMETADATA voi moc chuong.
    meta_lines = [";FFMETADATA1", "title=%s" % _clean(title)]
    start_ms = 0
    concat_list = []
    for wav, chap_title in zip(wav_files, titles):
        dur_ms = int(audio_duration(wav) * 1000)
        end_ms = start_ms + dur_ms
        meta_lines += [
            "[CHAPTER]",
            "TIMEBASE=1/1000",
            "START=%d" % start_ms,
            "END=%d" % end_ms,
            "title=%s" % _clean(chap_title),
        ]
        start_ms = end_ms
        concat_list.append("file '%s'" % os.path.abspath(wav).replace("'", r"'\''"))

    workdir = os.path.dirname(os.path.abspath(out_path)) or "."
    meta_path = os.path.join(workdir, "_chapters.txt")
    list_path = os.path.join(workdir, "_concat.txt")
    with open(meta_path, "w", encoding="utf-8") as f:
        f.write("\n".join(meta_lines))
    with open(list_path, "w", encoding="utf-8") as f:
        f.write("\n".join(concat_list))

    # 2. Concat + mux metadata -> m4b (aac).
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", list_path,
            "-i", meta_path, "-map_metadata", "1",
            "-codec:a", "aac", "-b:a", "128k",
            out_path,
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    os.remove(meta_path)
    os.remove(list_path)


def _clean(s):
    return re.sub(r"[\r\n=;]", " ", str(s)).strip()


# ------------------------------------------------------------ job options

def load_job_options(job_path):
    """Doc job.json neu co. Tra ve dict option da chuan hoa."""
    opts = {}
    if job_path and os.path.isfile(job_path):
        with open(job_path, "r", encoding="utf-8") as f:
            opts = json.load(f)
    return opts


def pick(cli_val, opts, key, default):
    if cli_val is not None:
        return cli_val
    if key in opts and opts[key] not in (None, ""):
        return opts[key]
    return default


# ------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser(description="Batch TTS theo chuong bang Piper")
    ap.add_argument("--chapters-dir", default="chapters")
    ap.add_argument("--out-dir", default="release")
    ap.add_argument("--work-dir", default="work_audio", help="Thu muc WAV tam")
    ap.add_argument("--job", default=None, help="File job.json chua option")
    ap.add_argument("--title", default=None, help="Ten truyen")
    ap.add_argument("--format", default=None, choices=["mp3", "wav", "m4b", "ogg", "opus", "m4a"])
    ap.add_argument("--package", default=None,
                    choices=["auto", "zip", "single", "files", "merge"])
    ap.add_argument("--merge-name", default=None,
                    help="Ten file goc khi package=merge (mac dinh = slug tieu de)")
    ap.add_argument("--batch-size", type=int,
                    default=int(os.environ.get("TTS_BATCH_SIZE", "0") or "0"),
                    help="Lam ca bo: chia thanh nhieu zip, moi zip toi da N chuong (0 = 1 zip)")
    ap.add_argument("--length-scale", type=float, default=None)
    ap.add_argument("--noise-scale", type=float, default=None)
    ap.add_argument("--noise-w", type=float, default=None)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--config", default=DEFAULT_CONFIG)
    ap.add_argument("--chunk-chars", type=int,
                    default=int(os.environ.get("TTS_CHUNK_CHARS", "2500")),
                    help="Chia nho chuong dai hon N ky tu khi tong hop (chong OOM)")
    ap.add_argument("--max-runtime-sec", type=int,
                    default=int(os.environ.get("TTS_MAX_RUNTIME_SEC", "0")),
                    help="Ngan sach thoi gian: dung tam va giu tien do (0 = khong gioi han)")
    args = ap.parse_args()

    opts = load_job_options(args.job)
    title = pick(args.title, opts, "title", "audiobook")
    fmt = pick(args.format, opts, "format", "mp3")
    package = pick(args.package, opts, "package", "auto")
    batch_size = args.batch_size or 0
    length_scale = pick(args.length_scale, opts, "length_scale", None)
    if length_scale is not None:
        length_scale = float(length_scale)
    noise_scale = pick(args.noise_scale, opts, "noise_scale", None)
    noise_w = pick(args.noise_w, opts, "noise_w", None)

    manifest_path = os.path.join(args.chapters_dir, "manifest.json")
    if not os.path.isfile(manifest_path):
        print("Loi: khong tim thay %s" % manifest_path, file=sys.stderr)
        sys.exit(1)
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    if not manifest:
        print("Loi: manifest rong", file=sys.stderr)
        sys.exit(2)

    ensure_ffmpeg()
    os.makedirs(args.work_dir, exist_ok=True)
    os.makedirs(args.out_dir, exist_ok=True)
    voice = load_voice(args.model, args.config)

    title_slug = re.sub(r"[^A-Za-z0-9]+", "_", title).strip("_").lower() or "audiobook"
    per_chapter_fmt = "mp3" if fmt == "m4b" else fmt
    budget = args.max_runtime_sec
    start_ts = time.time()

    # Tieu de cac muc khong can doc (muc luc...).
    SKIP_TITLES = {"table of contents", "contents", "muc luc",
                   "m\u1ee5c l\u1ee5c", "m\u1ee5c l\u1ee5c."}

    total = len(manifest)
    done = 0
    produced_now = 0
    stopped_early = False

    for m in manifest:
        idx = m["index"]
        stem = os.path.splitext(m["file"])[0]
        out_path = os.path.join(args.out_dir, stem + "." + per_chapter_fmt)

        # Ngan sach thoi gian: dung truoc khi runner bi kill, giu lai tien do.
        if budget > 0 and (time.time() - start_ts) >= budget:
            stopped_early = True
            print("\n[!] Het ngan sach thoi gian (%ds) o chuong %d/%d - se tiep tuc o luot sau."
                  % (budget, idx, total), flush=True)
            break

        # Bo qua muc luc / muc khong co noi dung.
        if m["title"].strip().lower() in SKIP_TITLES:
            print("[%d/%d] Bo qua (muc luc): %s" % (idx, total, m["title"]), flush=True)
            done += 1
            continue

        txt_path = os.path.join(args.chapters_dir, m["file"])
        with open(txt_path, "r", encoding="utf-8") as f:
            text = f.read().strip()
        if not text:
            done += 1
            continue

        fingerprint = hashlib.sha256(json.dumps({
            "text": text, "format": per_chapter_fmt,
            "length_scale": length_scale, "noise_scale": noise_scale,
            "noise_w": noise_w,
        }, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        fingerprint_path = out_path + ".sha256"
        old_fingerprint = ""
        if os.path.isfile(fingerprint_path):
            with open(fingerprint_path, "r", encoding="ascii") as f:
                old_fingerprint = f.read().strip()
        if (old_fingerprint == fingerprint and os.path.exists(out_path)
                and os.path.getsize(out_path) > 0):
            done += 1
            continue

        wav_path = os.path.join(args.work_dir, stem + ".wav")
        print("[%d/%d] TTS: %s (%d ky tu)"
              % (idx, total, m["title"][:40], len(text)), flush=True)
        synth_chapter(voice, text, wav_path, args.work_dir, args.chunk_chars,
                      length_scale, noise_scale, noise_w)
        convert_audio(wav_path, out_path, per_chapter_fmt)
        with open(fingerprint_path, "w", encoding="ascii") as f:
            f.write(fingerprint)
        try:
            os.remove(wav_path)
        except OSError:
            pass
        produced_now += 1
        done += 1

    # Tat ca file chuong hien co trong out-dir.
    chapter_entries = []
    for m in manifest:
        if m["title"].strip().lower() in SKIP_TITLES:
            continue
        stem = os.path.splitext(m["file"])[0]
        path = os.path.join(args.out_dir, stem + "." + per_chapter_fmt)
        if os.path.isfile(path) and os.path.getsize(path) > 0:
            chapter_entries.append((path, m["title"]))
    chapter_files = [entry[0] for entry in chapter_entries]
    if not chapter_files:
        print("Loi: khong tao duoc audio nao", file=sys.stderr)
        sys.exit(3)

    # Chua chay het manifest -> con chuong de lam o luot sau: chi ghi tien do.
    if stopped_early:
        summary = {
            "title": title,
            "format": per_chapter_fmt,
            "package": "files",
            "done": False,
            "chapters_done": len(chapter_files),
            "chapters_total": total,
            "artifacts": [os.path.basename(p) for p in chapter_files],
        }
        with open(os.path.join(args.out_dir, "summary.json"), "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        print("\nTien do: %d/%d chuong. Chua hoan tat - chay lai de tiep tuc."
              % (len(chapter_files), total), flush=True)
        sys.exit(0)

    # ---- Da xong toan bo: dong goi ket qua ----
    merge_name = args.merge_name or title_slug
    final_artifacts = []
    if fmt == "m4b":
        titles = [entry[1] for entry in chapter_entries]
        out_path = os.path.join(args.out_dir, merge_name + ".m4b")
        print("Dang gop %d chuong thanh m4b..." % len(chapter_files), flush=True)
        build_m4b(chapter_files, titles, out_path, title)
        final_artifacts.append(out_path)
    elif package == "merge":
        # GHEP tat ca chuong cua batch thanh 1 file audio lien tuc.
        out_path = os.path.join(args.out_dir, merge_name + "." + fmt)
        print("Dang ghep %d chuong thanh 1 file: %s"
              % (len(chapter_files), os.path.basename(out_path)), flush=True)
        concat_audio(chapter_files, out_path, fmt)
        for fp in chapter_files:
            for extra in (fp, fp + ".sha256"):
                try:
                    os.remove(extra)
                except OSError:
                    pass
        final_artifacts.append(out_path)
    else:
        multiple = len(chapter_files) > 1
        want_zip = package == "zip" or (package == "auto" and multiple)
        if want_zip and batch_size and batch_size > 0 and len(chapter_files) > batch_size:
            # Lam ca bo: chia thanh nhieu zip, moi zip toi da batch_size chuong.
            n = len(chapter_files)
            for s0 in range(0, n, batch_size):
                group = chapter_files[s0:s0 + batch_size]
                a, b = s0 + 1, s0 + len(group)
                zip_path = os.path.join(
                    args.out_dir, "%s_chuong_%03d-%03d.zip" % (title_slug, a, b))
                print("Dang nen chuong %d-%d thanh zip (%d file)..."
                      % (a, b, len(group)), flush=True)
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    for fp in group:
                        zf.write(fp, os.path.basename(fp))
                final_artifacts.append(zip_path)
            for fp in chapter_files:
                try:
                    os.remove(fp)
                except OSError:
                    pass
                try:
                    os.remove(fp + ".sha256")
                except OSError:
                    pass
        elif want_zip:
            zip_path = os.path.join(args.out_dir, title_slug + ".zip")
            print("Dang nen %d file thanh zip..." % len(chapter_files), flush=True)
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for fp in chapter_files:
                    zf.write(fp, os.path.basename(fp))
            for fp in chapter_files:
                try:
                    os.remove(fp)
                except OSError:
                    pass
                try:
                    os.remove(fp + ".sha256")
                except OSError:
                    pass
            final_artifacts.append(zip_path)
        else:
            final_artifacts.extend(chapter_files)

    summary = {
        "title": title,
        "chapters": len(chapter_files),
        "format": fmt,
        "package": package,
        "batch_size": batch_size,
        "done": True,
        "artifacts": [os.path.basename(p) for p in final_artifacts],
    }
    with open(os.path.join(args.out_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("\nHoan tat!")
    print("  Chuong : %d" % summary["chapters"])
    print("  File   : %s" % ", ".join(summary["artifacts"]))


if __name__ == "__main__":
    main()
