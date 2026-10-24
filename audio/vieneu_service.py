"""Official VieNeu v3 SDK adapter + Vbook speaker references (not GGUF inference)."""
import hashlib
import io
import json
import logging
import os
import re
import shutil
import tempfile
import threading
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from paths import ROOT, voice_models

log = logging.getLogger(__name__)
_download_lock = threading.RLock()
_load_lock = threading.Lock()
_infer_lock = threading.Lock()
_runtime = None
_runtime_key = None


def model_spec():
    return json.loads((ROOT / 'tts/model_sources.json').read_text('utf-8'))['vieneu']


def model_dir():
    return Path(os.getenv('VIENEU_MODEL_DIR', str(voice_models().parent / 'vieneu'))).expanduser().resolve()


def catalog():
    return json.loads((ROOT / 'tts/vieneu_catalog.json').read_text('utf-8'))


def read_references(archive):
    """Parse bounded text/JSON only. Never execute anything from an archive."""
    with zipfile.ZipFile(archive) as z:
        items = z.infolist()
        names = [it.filename for it in items]
        if len(names) != len(set(names)) or len(names) > 200:
            raise ValueError('Gói giọng có tên trùng/quá nhiều file.')
        for it in items:
            path = PurePosixPath(it.filename)
            if path.is_absolute() or '..' in path.parts or '\\' in it.filename:
                raise ValueError('Đường dẫn ZIP không hợp lệ.')
        if z.getinfo('config.json').file_size > 1024 * 1024:
            raise ValueError('Config quá lớn.')
        config = json.loads(z.read('config.json'))
        ids = config.get('voices', [])
        if len(ids) != 25 or config.get('model_type') != 'vieneu':
            raise ValueError('Không đúng gói VieNeu 25 giọng.')
        names_by_id = {config['voices'][idx]: name for name, idx in config['speaker_id_map'].items()}
        voices = {}
        for vid in ids:
            if not re.fullmatch(r'[a-z0-9_-]{1,100}', vid):
                raise ValueError('ID giọng không hợp lệ.')
            files = [f'voices/{vid}/speaker.emb.txt', f'voices/{vid}/ref_codes.txt']
            if any(z.getinfo(n).file_size > 2 * 1024 * 1024 for n in files):
                raise ValueError('Dữ liệu giọng quá lớn.')
            emb = [float(v) for v in re.split(r'[,\s]+', z.read(files[0]).decode().strip()) if v]
            codes = [[int(v) for v in line.split()] for line in z.read(files[1]).decode().strip().splitlines() if line.strip()]
            import math
            if len(emb) != 192 or not all(math.isfinite(v) for v in emb) or not codes or len(codes) > 2000 or any(len(row) != 16 or any(v < 0 or v > 1024 for v in row) for row in codes):
                raise ValueError(f'Embedding/ref codes không hợp lệ: {vid}')
            voices[vid] = {'id': vid, 'name': names_by_id[vid], 'speaker_emb': emb, 'codes': codes}
        return {'schema_version': 1, 'sample_rate': 48000, 'source': model_spec()['archive_url'], 'voices': voices}


def ensure_references():
    with _download_lock:
        directory = model_dir()
        target = directory / 'voices.json'
        if target.is_file():
            try:
                data = json.loads(target.read_text('utf-8'))
                if data.get('schema_version') == 1 and set(data['voices']) == {v['id'] for v in catalog()}:
                    return data
            except (OSError, ValueError, KeyError, TypeError):
                pass
        directory.mkdir(parents=True, exist_ok=True)
        spec = model_spec()
        archive = directory / 'vbook-vieneu-v3-turbo.zip'
        def valid_archive(path):
            if not path.is_file() or path.stat().st_size != spec['archive_size']:
                return False
            with path.open('rb') as f:
                return hashlib.file_digest(f, 'sha256').hexdigest() == spec['sha256']
        if not valid_archive(archive):
            fd, name = tempfile.mkstemp(prefix='.download-', dir=directory)
            temp = Path(name)
            try:
                req = urllib.request.Request(spec['archive_url'], headers={'User-Agent': 'NovelReader/4.5'})
                total = 0
                with os.fdopen(fd, 'wb') as out, urllib.request.urlopen(req, timeout=180) as response:
                    while chunk := response.read(1024 * 1024):
                        total += len(chunk)
                        if total > spec['archive_size']:
                            raise ValueError('Model vượt dung lượng manifest.')
                        out.write(chunk)
                if not valid_archive(temp):
                    raise ValueError('SHA256/dung lượng gói VieNeu không khớp manifest. Không dùng file lỗi.')
                os.replace(temp, archive)
            finally:
                temp.unlink(missing_ok=True)
        data = read_references(archive)
        from scripts.download_voices import write_json
        write_json(target, data)
        return data


def list_voices():
    ready = (model_dir() / 'voices.json').is_file()
    return [{**v, 'downloaded': ready, 'runtime_ready': _runtime is not None,
             'note': '25 giọng Vbook; backbone chính thức tải riêng, không chạy GGUF.'} for v in catalog()]


def runtime_status():
    return {'engine': 'vieneu', 'loaded': _runtime is not None,
            'backend': getattr(_runtime, 'backend', None),
            'device': os.getenv('VIENEU_DEVICE', 'auto'), 'sample_rate': 48000,
            'references_ready': (model_dir() / 'voices.json').is_file(),
            'gguf_inference_supported': False, 'backbone_repo': model_spec()['backbone_repo']}


def get_runtime():
    global _runtime, _runtime_key
    device = os.getenv('VIENEU_DEVICE', 'auto')
    if device not in ('auto', 'cpu', 'cuda'):
        raise ValueError('VIENEU_DEVICE phải là auto/cpu/cuda.')
    if device == 'auto':
        try:
            import torch
            device = 'cuda' if torch.cuda.is_available() else 'cpu'
        except ImportError:
            device = 'cpu'
    key = device
    with _load_lock:
        if _runtime is not None and _runtime_key == key:
            return _runtime
        try:
            from vieneu import Vieneu
        except ImportError as exc:
            raise RuntimeError('Chưa cài VieNeu. Chạy python scripts/setup_tts.py --engine vieneu --install --preload.') from exc
        spec = model_spec()
        # SDK resolves/caches BOTH backbone and MOSS codec; do not pass GGUF here.
        runtime = Vieneu(mode='v3turbo', backbone_repo=spec['backbone_repo'],
                         model_subfolder=spec['model_subfolder'], moss_tokenizer=spec['moss_tokenizer'],
                         onnx_subfolder=spec['onnx_subfolder'], device=device,
                         backend='pytorch' if device == 'cuda' else 'onnx', max_batch_size=64)
        if device == 'cuda' and getattr(runtime, 'backend', None) != 'pytorch':
            raise RuntimeError('VieNeu không khởi tạo backend CUDA/PyTorch theo yêu cầu.')
        _runtime, _runtime_key = runtime, key
        return runtime


def synthesize_to_wav(text, voice_id, destination, temperature=0.8, top_p=0.95, batch_size=8):
    import numpy as np
    import soundfile as sf
    references = ensure_references()
    if voice_id not in references['voices']:
        raise ValueError(f'Không có giọng VieNeu {voice_id}; không tự đổi giọng.')
    ref = references['voices'][voice_id]
    # Public SDK accepts a voice dict. No private SDK fields or monkey-patching.
    voice = {'speaker_emb': np.asarray(ref['speaker_emb'], dtype=np.float32),
             'codes': np.asarray(ref['codes'], dtype=np.int64)}
    from monitoring.tasks import audio_report, characters
    from audio.audio_service import split_text_for_tts
    # Observable outer groups; SDK still batches inner segments on the same runtime.
    chunks=split_text_for_tts(text,max_chars=4000)
    total=sum(characters(c) for c in chunks);completed=0;duration=0.
    audio_report(stage='waiting',total=total,completed=0)
    with _infer_lock:
        audio_report(stage='loading')
        runtime = get_runtime()
        audio_report(stage='synthesizing')
        with sf.SoundFile(str(destination),mode='w',samplerate=48000,channels=1,subtype='PCM_16') as output:
            for chunk in chunks:
                audio=runtime.infer(text=chunk,voice=voice,temperature=temperature,top_p=top_p,batch_size=batch_size)
                samples=np.asarray(audio,dtype=np.float32).reshape(-1)
                if samples.size==0 or not np.all(np.isfinite(samples)):
                    raise RuntimeError('VieNeu trả về audio rỗng/không hợp lệ.')
                output.write(samples);completed+=characters(chunk);duration+=samples.size/48000
                audio_report(completed=completed,audio_seconds=duration,stage='synthesizing')
