"""Real CT2 translation + Piper CUDA session and short synthesis smoke check."""
import argparse
import io
import json
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', default='HachimiMT-60-QT')
    parser.add_argument('--voice', default='ngochuyennew')
    args = parser.parse_args()
    from translation.core.ct2_safe_import import import_ctranslate2
    ct2 = import_ctranslate2()
    if ct2.get_cuda_device_count() < 1:
        raise RuntimeError('CT2 không thấy GPU. Chọn runtime T4 và kiểm tra nvidia-smi.')
    from translation.engines import LocalEngine
    engine = LocalEngine(args.model, backend='ct2')
    engine.load()
    output = engine.translate_raw(['你好世界。'], beam_size=2)
    device = engine.translator.device if engine.translator is not None else engine.model.device
    if device != 'cuda':
        raise RuntimeError(f'CT2 đang chạy {device}, không phải CUDA')
    # Release translation model before checking voice to keep smoke-test simple.
    del engine
    from audio.audio_service import get_voice, tts_runtime_status
    from tts.synthesis import synthesize_wav
    voice = get_voice(args.voice)
    providers = voice.session.get_providers()
    if 'CUDAExecutionProvider' not in providers:
        raise RuntimeError(f'Piper session không dùng CUDA: {providers}')
    buffer = io.BytesIO()
    before = time.perf_counter()
    with wave.open(buffer, 'wb') as wav:
        synthesize_wav(voice, 'Xin chào, kiểm tra giọng đọc trên GPU.', wav)
    with wave.open(io.BytesIO(buffer.getvalue()), 'rb') as wav:
        duration = wav.getnframes() / wav.getframerate()
    print(json.dumps({'ct2_device': device, 'translation_sample': output,
                      'tts': tts_runtime_status(), 'audio_seconds': duration,
                      'synthesis_seconds': round(time.perf_counter() - before, 3)},
                     ensure_ascii=False, indent=2))
    if duration <= 0:
        raise RuntimeError('Piper trả về audio rỗng')


if __name__ == '__main__':
    main()
