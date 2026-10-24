"""Piper TTS audio synthesis module: Piper/VieNeu, sampling control, format conversion, and chapter grouping."""
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

from monitoring.tasks import audio_report, characters

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
from paths import voice_models
VOICE_DIR = voice_models()

_voice_lock = threading.Lock()
_voice_instances = {}


def ensure_voice_downloaded(voice_id: str) -> bool:
    """Tự động tải model giọng đọc và file config nếu chưa có trên máy."""
    voice_id = (voice_id or "ngochuyennew").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", voice_id):
        raise ValueError("ID giọng đọc không hợp lệ")
    model_path = VOICE_DIR / f"{voice_id}.onnx"
    config_path = VOICE_DIR / f"{voice_id}.onnx.json"

    from scripts.download_voices import valid_config
    if model_path.is_file() and model_path.stat().st_size > 10 * 1024 * 1024 and valid_config(config_path):
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
        is_config = out_file.name.endswith('.onnx.json')
        if out_file.is_file() and out_file.stat().st_size >= min_size and (not is_config or valid_config(out_file)):
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
                if tmp_file.stat().st_size >= min_size and (not is_config or valid_config(tmp_file)):
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

    # Always show the full bundled catalog on a fresh Molab/runtime.
    try:
        bundled = json.loads((BASE_DIR.parent / 'tts/voices_catalog.json').read_text('utf-8'))
        existing = {it.get('id') for it in manifest_items if isinstance(it, dict)}
        manifest_items.extend(it for it in bundled if it['id'] not in existing)
    except (OSError, ValueError):
        pass
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
    return {'ort_version': version, 'available_providers': available,
            'loaded_voices': loaded, 'requested_device': os.getenv('PIPER_DEVICE', 'auto'),
            'require_cuda': os.getenv('PIPER_REQUIRE_CUDA', '0') == '1'}


def get_voice(voice_id: str = "ngochuyennew"):
    """Nạp và cache PiperVoice theo voice_id (tự động kích hoạt GPU CUDA nếu có)."""
    voice_id = (voice_id or "ngochuyennew").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", voice_id):
        raise ValueError("ID giọng đọc không hợp lệ")
    # Separate Piper/phonemizer/ORT state per consumer; never serialize inference
    # behind the model-loading lock. Cache slots are released after queue shutdown.
    worker = threading.current_thread().name
    cache_key = f"{voice_id}@{worker}" if worker.startswith('chapter-audio-') else voice_id
    if cache_key in _voice_instances:
        return _voice_instances[cache_key]
    with _voice_lock:
        if cache_key in _voice_instances:
            return _voice_instances[cache_key]

        model_path = VOICE_DIR / f"{voice_id}.onnx"
        config_path = VOICE_DIR / f"{voice_id}.onnx.json"

        if not (model_path.is_file() and config_path.is_file()):
            ensure_voice_downloaded(voice_id)

        if not model_path.is_file() or not config_path.is_file():
            raise FileNotFoundError(f"Không tải được model/config giọng '{voice_id}'. Kiểm tra kết nối hoặc chạy scripts/download_voices.py --voice {voice_id}. Không tự đổi sang giọng khác.")

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
                inst = PiperVoice.load(
                    str(model_path),
                    config_path=str(config_path) if config_path.is_file() else None,
                    use_cuda=True)
                from tts.cuda_session import configure_cuda_session
                configure_cuda_session(inst.session)
                providers = inst.session.get_providers()
                if 'CUDAExecutionProvider' not in providers:
                    raise RuntimeError(f'Piper session không dùng CUDA: {providers}')
            except Exception as exc:
                if require_cuda:
                    raise RuntimeError('Piper khởi tạo CUDA thất bại; không chuyển sang CPU. Kiểm tra lib CUDA/cuDNN và log ORT.') from exc
                log.warning('Piper CUDA thất bại (%s), dùng CPU; đặt PIPER_REQUIRE_CUDA=1 để dừng thay vì fallback.', exc)
                inst = None
        if inst is None:
            inst = PiperVoice.load(
                str(model_path),
                config_path=str(config_path) if config_path.is_file() else None,
                use_cuda=False)

        _voice_instances[cache_key] = inst
        active_providers = getattr(inst.session, "get_providers", lambda: [])() if hasattr(inst, "session") else []
        device_label = "GPU (CUDA)" if any("CUDA" in str(p) for p in active_providers) else "CPU"
        log.info("Đã nạp xong model TTS %s [Thiết bị: %s]", voice_id, device_label)
        return inst


def split_text_for_tts(text: str, max_chars: int = 4000) -> list[str]:
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
    """Tổng hợp văn bản ra WAV với tham số biến thiên và thời lượng."""
    default_chunk = 4000 if is_cuda_available_for_piper() else 2500
    chunk_limit = int(os.getenv('TTS_CHUNK_MAX_CHARS', default_chunk))
    chunks = split_text_for_tts(text, max_chars=chunk_limit)
    if not chunks:
        with wave.open(str(out_wav), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(22050)
        return

    from tts.synthesis import synthesize_wav
    settings = dict(length_scale=length_scale, noise_scale=noise_scale, noise_w_scale=noise_w_scale)

    total=sum(characters(chunk) for chunk in chunks);completed=0
    audio_report(total=total,completed=0,stage='synthesizing')
    with wave.open(str(out_wav), "wb") as w:
        for i, chunk in enumerate(chunks):
            synthesize_wav(voice, chunk, w, set_wav_format=(i == 0), **settings)
            completed+=characters(chunk)
            audio_report(completed=completed,audio_seconds=w.tell()/w.getframerate(),stage='synthesizing')


def convert_wav(in_wav: Path, out_file: Path, fmt: str = "mp3", bitrate: str = "96k", sample_rate: int = 0, speed: float = 1.0):
    """Chuyển đổi WAV sang các định dạng mp3, m4b, m4a, opus, wav bằng ffmpeg đa luồng."""
    fmt = fmt.lower().strip()
    cmd = ["ffmpeg", "-v", "error", "-y", "-threads", "0", "-i", str(in_wav)]

    if not 0.4 <= speed <= 2.5 or sample_rate not in (0, 22050, 24000, 44100, 48000):
        raise ValueError('Tốc độ/tần số xuất không hợp lệ.')
    if speed != 1.0:
        # Keep each atempo stage within 0.5–2 for older FFmpeg builds.
        filters = []
        remaining = speed
        while remaining < 0.5:
            filters.append('atempo=0.5'); remaining /= 0.5
        while remaining > 2:
            filters.append('atempo=2'); remaining /= 2
        filters.append(f'atempo={remaining:.6f}')
        cmd.extend(['-af', ','.join(filters)])
    if fmt == 'mp3' and bitrate == '192k':
        effective_rate=sample_rate
        if not effective_rate:
            with wave.open(str(in_wav),'rb') as source: effective_rate=source.getframerate()
        if effective_rate<=24000:
            raise ValueError('MP3 192 kbps cần 44.1 hoặc 48 kHz. Chọn 128 kbps hoặc đổi tần số xuất để tránh hạ âm thầm xuống 160 kbps.')
    if fmt in ('opus', 'ogg'):
        sample_rate = 48000  # Opus decoder clock; never imply 22.05 kHz Opus.
    if sample_rate:
        cmd.extend(['-ar', str(sample_rate)])
    if fmt == "mp3":
        cmd.extend(["-c:a", "libmp3lame", "-threads", "0", "-b:a", bitrate, str(out_file)])
    elif fmt in ("m4b", "m4a", "aac"):
        cmd.extend(["-c:a", "aac", "-threads", "0", "-b:a", bitrate, str(out_file)])
    elif fmt in ("opus", "ogg"):
        cmd.extend(["-c:a", "libopus", "-threads", "0", "-b:a", bitrate, str(out_file)])
    elif fmt == "wav":
        cmd.extend(["-c:a", "pcm_s16le", str(out_file)])
    else:
        # Mặc định mp3
        cmd.extend(["-c:a", "libmp3lame", "-threads", "0", "-b:a", bitrate, str(out_file)])

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
    bitrate: str = "96k",
    tts_engine: str = "piper",
    sample_rate: int = 0,
    vieneu_temperature: float = 0.8,
    vieneu_top_p: float = 0.95,
    vieneu_batch_size: int = 8,
) -> Path:
    """Tạo file audio cho một chương truyện với engine và tham số lấy mẫu tùy chọn."""
    audio_dir.mkdir(parents=True, exist_ok=True)
    out_file = audio_dir / f"chuong_{position:04d}.{fmt}"

    clean_title = (title or "").strip()
    clean_paras = [p.strip() for p in paras if p and p.strip() and not p.strip().startswith("(")]
    full_text = clean_title + "\n\n" + "\n\n".join(clean_paras)

    if not full_text.strip():
        raise ValueError("Chương không có nội dung chữ để tạo audio.")

    if tts_engine not in ('piper', 'vieneu'):
        raise ValueError('Engine TTS không được hỗ trợ.')
    audio_report(total=characters(full_text),completed=0,stage='loading')
    voice = get_voice(voice_id) if tts_engine == 'piper' else None
    length_scale = 1.0 / max(0.4, min(2.5, speed))

    # Same filesystem for atomic publication; partial MP3s are never visible.
    with tempfile.TemporaryDirectory(prefix=".audio-", dir=audio_dir) as tmp_dir:
        tmp_path = Path(tmp_dir)
        raw_wav = tmp_path / "chapter.wav"
        if tts_engine == 'piper':
            synth_text_to_wav(voice, full_text, raw_wav, tmp_path,
                              length_scale=length_scale, noise_scale=noise_scale, noise_w_scale=noise_w_scale)
        else:
            from audio.vieneu_service import synthesize_to_wav
            synthesize_to_wav(full_text, voice_id, raw_wav, temperature=vieneu_temperature,
                              top_p=vieneu_top_p, batch_size=vieneu_batch_size)
        with wave.open(str(raw_wav),'rb') as wav:
            audio_seconds=wav.getnframes()/wav.getframerate()
        if tts_engine=='vieneu':audio_seconds/=speed
        audio_report(stage='encoding',audio_seconds=audio_seconds)
        temp_target = tmp_path / f"converted.{fmt}"
        convert_options = {'fmt': fmt, 'bitrate': bitrate}
        if sample_rate:
            convert_options['sample_rate'] = sample_rate
        if tts_engine == 'vieneu' and speed != 1:
            convert_options['speed'] = speed
        convert_wav(raw_wav, temp_target, **convert_options)

        os.replace(temp_target, out_file)
        # Remove stale alternatives only after successful atomic publication.
        for ext in ('mp3','m4b','m4a','opus','wav'):
            for old in (audio_dir/f'chuong_{position:04d}.{ext}',audio_dir/f'chapter_{chapter_id}.{ext}',audio_dir/f'chuong_{position}.{ext}'):
                if old!=out_file: old.unlink(missing_ok=True)

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




def release_worker_voices():
    """Called only after all chapter consumers have stopped."""
    with _voice_lock:
        for key in list(_voice_instances):
            if '@chapter-audio-' in key:
                del _voice_instances[key]


AUDIO_CONFIG_KEYS = ('tts_engine','voice_id','audio_speed','noise_scale','noise_w_scale',
                     'audio_format','audio_bitrate','audio_sample_rate','vieneu_temperature',
                     'vieneu_top_p','vieneu_batch_size')


def generation_kwargs(config):
    """The ONE settings mapper used by both job and single-chapter routes."""
    return dict(voice_id=config.get('voice_id', 'ngochuyennew'), speed=config.get('audio_speed', 1.0),
                noise_scale=config.get('noise_scale', 0.667), noise_w_scale=config.get('noise_w_scale', 0.8),
                fmt=config.get('audio_format', 'mp3'), bitrate=config.get('audio_bitrate', '96k'),
                tts_engine=config.get('tts_engine','piper'), sample_rate=config.get('audio_sample_rate',0),
                vieneu_temperature=config.get('vieneu_temperature',0.8), vieneu_top_p=config.get('vieneu_top_p',0.95),
                vieneu_batch_size=config.get('vieneu_batch_size',8))


def exportable_audio_files(directory):
    """Only completed public audio paths; exclude temporary synthesis workdirs."""
    return [p for p in sorted(directory.rglob('*')) if p.is_file() and not p.is_symlink()
            and p.suffix.lower() in {'.mp3','.m4b','.m4a','.wav','.opus','.aac','.ogg'}
            and not any(part.startswith('.') for part in p.relative_to(directory).parts)
            and not any(parent.is_symlink() for parent in p.parents if parent.is_relative_to(directory))]
