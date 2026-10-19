"""Piper TTS audio synthesis module: multi-voice, emotion control, format conversion, and chapter grouping."""
import io
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import wave
from pathlib import Path

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
from paths import voice_models
VOICE_DIR = voice_models()

_voice_lock = threading.Lock()
_voice_instances = {}


def ensure_voice_downloaded(voice_id: str) -> bool:
    """Tự động tải model giọng đọc và file config nếu chưa có trên máy."""
    voice_id = (voice_id or "ngochuyennew").strip()
    model_path = VOICE_DIR / f"{voice_id}.onnx"
    config_path = VOICE_DIR / f"{voice_id}.onnx.json"

    if model_path.is_file() and model_path.stat().st_size > 10 * 1024 * 1024 and config_path.is_file():
        return True

    log.info("Đang tự động tải model giọng đọc: %s...", voice_id)
    VOICE_DIR.mkdir(parents=True, exist_ok=True)

    onnx_urls = [
        f"https://cdn.ainovelreader.com/tts_model/{voice_id}.onnx",
        f"https://raw.githubusercontent.com/dungbeommm/NovelReader_voices/main/voices/low/low-{voice_id}/{voice_id}.onnx",
    ]
    json_urls = [
        f"https://cdn.ainovelreader.com/tts_model/{voice_id}.onnx.json",
        f"https://raw.githubusercontent.com/dungbeommm/NovelReader_voices/main/voices/low/low-{voice_id}/{voice_id}.onnx.json",
    ]

    import urllib.request
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

    def _dl(urls, out_file, min_size=50):
        if out_file.is_file() and out_file.stat().st_size >= min_size:
            return True
        tmp_file = out_file.with_suffix(".tmp")
        for u in urls:
            try:
                req = urllib.request.Request(u, headers=headers)
                with urllib.request.urlopen(req, timeout=30) as resp, open(tmp_file, "wb") as f:
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        f.write(chunk)
                if tmp_file.stat().st_size >= min_size:
                    tmp_file.replace(out_file)
                    return True
                tmp_file.unlink(missing_ok=True)
            except Exception:
                tmp_file.unlink(missing_ok=True)
        return False

    json_ok = _dl(json_urls, config_path, min_size=50)
    onnx_ok = _dl(onnx_urls, model_path, min_size=10 * 1024 * 1024)
    return onnx_ok and json_ok


def list_available_voices() -> list[dict]:
    """Danh sách tất cả các giọng đọc khả dụng trên máy (và có thể tự động tải)."""
    manifest_file = VOICE_DIR / "voices_manifest.json"
    manifest_items = []
    if manifest_file.is_file():
        try:
            manifest_items = json.loads(manifest_file.read_text(encoding="utf-8"))
        except Exception:
            manifest_items = []

    voices = []
    seen_ids = set()

    # 1. Quét tất cả các file .onnx đã có sẵn trong thư mục voice
    for onnx in sorted(VOICE_DIR.glob("*.onnx")):
        vid = onnx.stem
        cfg = onnx.with_suffix(".onnx.json")
        if not cfg.is_file():
            continue

        meta = next((it for it in manifest_items if it.get("id") == vid), {})
        display_name = meta.get("name")
        gender = meta.get("gender")
        if not gender:
            gender = "female" if vid in [
                "ngochuyennew", "ngochuyen", "banmai", "calmwoman3688",
                "maiphuong", "phuongtrang", "thanhphuong2", "vunga",
                "lacphi", "vais1000medium"
            ] else "male"

        if not display_name:
            info_file = VOICE_DIR / f"{vid}.info.json"
            if info_file.is_file():
                try:
                    info = json.loads(info_file.read_text(encoding="utf-8-sig"))
                    display_name = info.get("displayName", vid)
                except Exception:
                    display_name = vid
            else:
                display_name = "Ngọc Huyền (Mới)" if vid == "ngochuyennew" else vid

        seen_ids.add(vid)
        voices.append({
            "id": vid,
            "name": display_name,
            "gender": gender,
            "is_default": (vid == "ngochuyennew"),
            "size_mb": round(onnx.stat().st_size / (1024 * 1024), 1),
            "onnx_file": str(onnx.name),
            "json_file": str(cfg.name),
            "downloaded": True
        })

    # 2. Đưa thêm các giọng trong manifest (nếu chưa tải) để luôn hiển thị đầy đủ
    for it in manifest_items:
        vid = it.get("id")
        if not vid or vid in seen_ids:
            continue
        display_name = it.get("name", vid)
        gender = it.get("gender")
        if not gender:
            gender = "female" if vid in [
                "ngochuyennew", "ngochuyen", "banmai", "calmwoman3688",
                "maiphuong", "phuongtrang", "thanhphuong2", "vunga",
                "lacphi", "vais1000medium"
            ] else "male"

        seen_ids.add(vid)
        voices.append({
            "id": vid,
            "name": display_name,
            "gender": gender,
            "is_default": (vid == "ngochuyennew"),
            "size_mb": it.get("size_mb", 60.6),
            "onnx_file": it.get("onnx_file", f"{vid}.onnx"),
            "json_file": it.get("json_file", f"{vid}.onnx.json"),
            "downloaded": False
        })

    # Đưa giọng mặc định lên đầu, sau đó sắp xếp theo giới tính rồi đến tên
    voices.sort(key=lambda x: (not x["is_default"], x["gender"] != "female", x["name"]))
    return voices


def _prepare_ort():
    import onnxruntime as ort
    # ORT >=1.21 knows the pip NVIDIA runtime layout. Also support older ORT.
    preload = getattr(ort, 'preload_dlls', None)
    if preload:
        try:
            preload(directory='')
        except Exception as exc:
            log.warning('ORT preload: %s', exc)
    try:
        from translation.core.ct2_safe_import import preload_cuda_libraries
        preload_cuda_libraries()
    except Exception as exc:
        log.debug('CUDA preload: %s', exc)
    return ort


def is_cuda_available_for_piper() -> bool:
    try:
        return 'CUDAExecutionProvider' in _prepare_ort().get_available_providers()
    except Exception:
        return False


def tts_runtime_status():
    try:
        import onnxruntime as ort
        available = ort.get_available_providers()
        version = ort.__version__
    except ImportError:
        available, version = [], None
    with _voice_lock:
        loaded = {key: voice.session.get_providers() for key, voice in _voice_instances.items()}
        devices = {key: getattr(voice, 'device_indices', [0]) for key, voice in _voice_instances.items()}
    return {'ort_version': version, 'available_providers': available,
            'loaded_voices': loaded, 'voice_gpu_indices': devices, 'requested_device': os.getenv('PIPER_DEVICE', 'auto'),
            'require_cuda': os.getenv('PIPER_REQUIRE_CUDA', '0') == '1'}


def get_voice(voice_id: str = "ngochuyennew"):
    """Nạp và cache PiperVoice theo voice_id (tự động kích hoạt GPU CUDA nếu có)."""
    voice_id = (voice_id or "ngochuyennew").strip()
    if voice_id in _voice_instances:
        return _voice_instances[voice_id]

    with _voice_lock:
        if voice_id in _voice_instances:
            return _voice_instances[voice_id]

        model_path = VOICE_DIR / f"{voice_id}.onnx"
        config_path = VOICE_DIR / f"{voice_id}.onnx.json"

        if not (model_path.is_file() and config_path.is_file()):
            ensure_voice_downloaded(voice_id)

        if not model_path.is_file():
            # Fallback về ngochuyennew nếu giọng yêu cầu tải thất bại
            if voice_id != "ngochuyennew":
                ensure_voice_downloaded("ngochuyennew")
            model_path = VOICE_DIR / "ngochuyennew.onnx"
            config_path = VOICE_DIR / "ngochuyennew.onnx.json"

        if not model_path.is_file():
            raise FileNotFoundError(f"Không tìm thấy model giọng TTS: {voice_id}")

        log.info("Đang nạp Piper voice model: %s", model_path.name)
        from piper import PiperVoice

        device = os.getenv('PIPER_DEVICE', 'auto').strip().lower()
        if device not in {'auto', 'cpu', 'cuda'}:
            raise ValueError('PIPER_DEVICE phải là auto, cpu hoặc cuda')
        require_cuda = device == 'cuda' or os.getenv('PIPER_REQUIRE_CUDA') == '1'
        if device == 'cpu' and require_cuda:
            raise ValueError('PIPER_DEVICE=cpu xung đột PIPER_REQUIRE_CUDA=1')
        use_cuda = device != 'cpu' and is_cuda_available_for_piper()
        if require_cuda and not use_cuda:
            raise RuntimeError('Piper không có CUDAExecutionProvider. Chạy lại cell cài GPU, restart runtime rồi kiểm tra CUDA/cuDNN.')
        inst = None
        if use_cuda:
            try:
                from translation.gpu_balance import enabled, selected_devices
                if enabled():
                    from translation.ct2_safe_import import import_ctranslate2
                    indices = selected_devices(import_ctranslate2().get_cuda_device_count(), 'PIPER_GPU_INDICES')
                    if not indices:
                        raise RuntimeError('Không có GPU cho Piper')
                else:
                    indices = [0]
                from tts.cuda_session import configure_cuda_session
                replicas = []
                for device_index in indices:
                    replica = PiperVoice.load(
                        str(model_path),
                        config_path=str(config_path) if config_path.is_file() else None,
                        use_cuda=True)
                    configure_cuda_session(replica.session, device_id=device_index)
                    providers = replica.session.get_providers()
                    if 'CUDAExecutionProvider' not in providers:
                        raise RuntimeError(f'Piper GPU {device_index} không dùng CUDA: {providers}')
                    replicas.append(replica)
                if len(replicas) > 1:
                    from tts.replicas import VoiceReplicas
                    inst = VoiceReplicas(replicas, indices)
                    log.info('BALANCE Piper: GPUs=%s, one replica/device', indices)
                else:
                    inst = replicas[0]
            except Exception as exc:
                if require_cuda or os.getenv('NOVEL_BALANCE_GPUS') == '1':
                    raise RuntimeError('Piper khởi tạo CUDA thất bại; không chuyển sang CPU. Kiểm tra lib CUDA/cuDNN và log ORT.') from exc
                log.warning('Piper CUDA thất bại (%s), dùng CPU; đặt PIPER_REQUIRE_CUDA=1 để dừng thay vì fallback.', exc)
                inst = None
        if inst is None:
            inst = PiperVoice.load(
                str(model_path),
                config_path=str(config_path) if config_path.is_file() else None,
                use_cuda=False)

        _voice_instances[voice_id] = inst
        active_providers = getattr(inst.session, "get_providers", lambda: [])() if hasattr(inst, "session") else []
        device_label = "GPU (CUDA)" if any("CUDA" in str(p) for p in active_providers) else "CPU"
        log.info("Đã nạp xong model TTS %s [Thiết bị: %s]", voice_id, device_label)
        return inst


def split_text_for_tts(text: str, max_chars: int = 1500) -> list[str]:
    """Chia nhỏ văn bản tránh tràn bộ nhớ khi đọc chương dài."""
    if not text:
        return []
    if max_chars <= 0 or len(text) <= max_chars:
        return [text]

    parts = re.split(r"(?<=[.!?\u2026\n])\s+", text)
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

        if cur and (len(cur) + len(p) + 1 > max_chars):
            chunks.append(cur)
            cur = p
        else:
            cur = (cur + " " + p).strip() if cur else p

    if cur:
        chunks.append(cur)
    return chunks


def concat_wavs(part_paths: list[Path], out_wav: Path):
    """Nối nhiều file WAV cùng thông số."""
    if not part_paths:
        return
    with wave.open(str(part_paths[0]), "rb") as w0:
        params = w0.getparams()

    with wave.open(str(out_wav), "wb") as out:
        out.setparams(params)
        for p in part_paths:
            with wave.open(str(p), "rb") as w:
                out.writeframes(w.readframes(w.getnframes()))


def synth_text_to_wav(
    voice,
    text: str,
    out_wav: Path,
    work_dir: Path,
    length_scale: float = 1.0,
    noise_scale: float = 0.667,
    noise_w_scale: float = 0.8
):
    """Tổng hợp văn bản ra WAV với đầy đủ tham số cảm xúc và ngắt nghỉ."""
    chunks = split_text_for_tts(text, max_chars=1500)
    if not chunks:
        with wave.open(str(out_wav), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(22050)
        return

    from tts.synthesis import synthesize_wav
    settings = dict(length_scale=length_scale, noise_scale=noise_scale, noise_w_scale=noise_w_scale)

    replicas = getattr(voice, 'replicas', None)
    if replicas and len(replicas) > 1:
        from concurrent.futures import ThreadPoolExecutor
        from translation.gpu_balance import balanced_indices
        # A short chapter may originally fit one chunk: split it so both devices
        # have work when there are at least two characters. Each WAV is separate.
        if len(chunks) < len(replicas) and len(text) > 1:
            chunks = split_text_for_tts(text, max_chars=max(1, (len(text)+len(replicas)-1)//len(replicas)))
        groups = balanced_indices([len(chunk) for chunk in chunks], len(replicas))
        part_paths = [work_dir / f"chunk_{i:04d}.wav" for i in range(len(chunks))]

        def synth_group(worker):
            with voice.locks[worker]:
                for index in groups[worker]:
                    with wave.open(str(part_paths[index]), 'wb') as wav:
                        synthesize_wav(replicas[worker], chunks[index], wav, **settings)

        with ThreadPoolExecutor(max_workers=len(replicas), thread_name_prefix='piper-gpu') as pool:
            list(pool.map(synth_group, range(len(replicas))))
        concat_wavs(part_paths, out_wav)
        log.info('BALANCE Piper: %s', {device: {'chunks': len(group), 'chars': sum(len(chunks[i]) for i in group)}
                 for device, group in zip(voice.device_indices, groups)})
        return

    if len(chunks) == 1:
        with _voice_lock:
            with wave.open(str(out_wav), "wb") as w:
                synthesize_wav(voice, chunks[0], w, **settings)
        return

    part_paths = []
    for i, chunk in enumerate(chunks):
        p = work_dir / f"chunk_{i:04d}.wav"
        with _voice_lock:
            with wave.open(str(p), "wb") as w:
                synthesize_wav(voice, chunk, w, **settings)
        part_paths.append(p)

    concat_wavs(part_paths, out_wav)


def convert_wav(in_wav: Path, out_file: Path, fmt: str = "mp3", bitrate: str = "96k"):
    """Chuyển đổi WAV sang các định dạng mp3, m4b, m4a, opus, wav bằng ffmpeg."""
    fmt = fmt.lower().strip()
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(in_wav)]

    if fmt == "mp3":
        cmd.extend(["-c:a", "libmp3lame", "-b:a", bitrate, str(out_file)])
    elif fmt in ("m4b", "m4a", "aac"):
        cmd.extend(["-c:a", "aac", "-b:a", bitrate, str(out_file)])
    elif fmt in ("opus", "ogg"):
        cmd.extend(["-c:a", "libopus", "-b:a", bitrate, str(out_file)])
    elif fmt == "wav":
        cmd.extend(["-c:a", "pcm_s16le", str(out_file)])
    else:
        # Mặc định mp3
        cmd.extend(["-c:a", "libmp3lame", "-b:a", bitrate, str(out_file)])

    subprocess.run(cmd, check=True, timeout=600)


def generate_chapter_audio(
    chapter_id: int,
    position: int,
    title: str,
    paras: list[str],
    audio_dir: Path,
    voice_id: str = "ngochuyennew",
    speed: float = 1.0,
    noise_scale: float = 0.667,
    noise_w_scale: float = 0.8,
    fmt: str = "mp3",
    bitrate: str = "96k"
) -> Path:
    """Tạo file audio cho một chương truyện với giọng đọc và cảm xúc tùy chọn."""
    audio_dir.mkdir(parents=True, exist_ok=True)
    out_file = audio_dir / f"chuong_{position:04d}.{fmt}"

    clean_title = (title or "").strip()
    clean_paras = [p.strip() for p in paras if p and p.strip() and not p.strip().startswith("(")]
    full_text = clean_title + "\n\n" + "\n\n".join(clean_paras)

    if not full_text.strip():
        raise ValueError("Chương không có nội dung chữ để tạo audio.")

    voice = get_voice(voice_id)
    length_scale = 1.0 / max(0.4, min(2.5, speed))

    # Same filesystem for atomic publication; partial MP3s are never visible.
    with tempfile.TemporaryDirectory(prefix=".audio-", dir=audio_dir) as tmp_dir:
        tmp_path = Path(tmp_dir)
        raw_wav = tmp_path / "chapter.wav"
        synth_text_to_wav(
            voice, full_text, raw_wav, tmp_path,
            length_scale=length_scale,
            noise_scale=noise_scale,
            noise_w_scale=noise_w_scale
        )

        temp_target = tmp_path / f"converted.{fmt}"
        convert_wav(raw_wav, temp_target, fmt=fmt, bitrate=bitrate)

        os.replace(temp_target, out_file)

    log.info("Tạo audio chương %d thành công [%s, %s]: %s (%d bytes)",
             position, voice_id, fmt, out_file.name, out_file.stat().st_size)
    return out_file


def get_chapter_audio_path(audio_dir: Path, chapter_id: int, position: int | None = None) -> Path | None:
    """Tìm file audio của chương (hỗ trợ các định dạng mp3, m4b, m4a, opus, wav)."""
    for ext in ("mp3", "m4b", "m4a", "opus", "wav"):
        p = audio_dir / f"chapter_{chapter_id}.{ext}"
        if p.is_file() and p.stat().st_size > 0:
            return p
        if position is not None:
            p2 = audio_dir / f"chuong_{position:04d}.{ext}"
            if p2.is_file() and p2.stat().st_size > 0:
                return p2
            p3 = audio_dir / f"chuong_{position}.{ext}"
            if p3.is_file() and p3.stat().st_size > 0:
                return p3
    return None


