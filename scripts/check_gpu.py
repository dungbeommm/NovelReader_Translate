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
    parser.add_argument('--tts-engine',choices=['piper','vieneu'],default='piper')
    args = parser.parse_args()
    from translation.core.ct2_safe_import import import_ctranslate2
    ct2 = import_ctranslate2()
    import importlib.metadata
    import ctypes
    for package in ('onnxruntime-gpu', 'nvidia-cudnn-cu12', 'ctranslate2', 'piper-tts'):
        try:
            print(f'{package}={importlib.metadata.version(package)}', flush=True)
        except importlib.metadata.PackageNotFoundError:
            print(f'{package}=not-installed', flush=True)
    try:
        cudnn = ctypes.CDLL('libcudnn.so.9')
        cudnn.cudnnGetVersion.restype = ctypes.c_size_t
        print(f'loaded_cudnn_version={cudnn.cudnnGetVersion()}', flush=True)
    except OSError as exc:
        print(f'cuDNN load check: {exc}', flush=True)
    if ct2.get_cuda_device_count() < 1:
        raise RuntimeError('CT2 không thấy GPU. Chọn runtime T4 và kiểm tra nvidia-smi.')
    from translation.engines import LocalEngine
    engine = LocalEngine(args.model, backend='ct2')
    engine.load()
    output = engine.translate_raw(['你好世界。'], beam_size=2)
    device = engine.translator.device if engine.translator is not None else engine.model.device
    if device != 'cuda':
        raise RuntimeError(f'CT2 đang chạy {device}, không phải CUDA')
    del engine
    if args.tts_engine=='vieneu':
        import tempfile,os
        import soundfile as sf
        from audio.vieneu_service import synthesize_to_wav,get_runtime,runtime_status
        os.environ['VIENEU_DEVICE']='cuda';before=time.perf_counter()
        with tempfile.TemporaryDirectory() as work:
            path=Path(work)/'smoke.wav'
            synthesize_to_wav('Xin chào, kiểm tra giọng đọc trên GPU.',args.voice,path)
            samples,rate=sf.read(path)
        if get_runtime().backend!='pytorch' or len(samples)==0 or rate!=48000:
            raise RuntimeError('VieNeu GPU không trả về WAV 48 kHz hợp lệ.')
        print(json.dumps({'ct2_device':device,'translation_sample':output,'tts':runtime_status(),'audio_seconds':len(samples)/rate,'synthesis_seconds':time.perf_counter()-before},ensure_ascii=False))
        return
    from audio.audio_service import get_voice, tts_runtime_status
    from tts.synthesis import synthesize_wav
    voice = get_voice(args.voice)
    providers = voice.session.get_providers()
    if 'CUDAExecutionProvider' not in providers:
        raise RuntimeError(f'Piper session không dùng CUDA: {providers}')
    before = time.perf_counter()
    durations = []
    for text in ('Xin chào, kiểm tra giọng đọc trên GPU.',
                 ('người lữ hành bước qua khu rừng và nhìn về phía chân trời ' * 20).strip()):
        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as wav:
            synthesize_wav(voice, text, wav)
        with wave.open(io.BytesIO(buffer.getvalue()), 'rb') as wav:
            durations.append(wav.getnframes() / wav.getframerate())
    duration = sum(durations)
    if 'CUDAExecutionProvider' not in voice.session.get_providers():
        raise RuntimeError('Piper rơi về CPU sau inference')
    print(json.dumps({'ct2_device': device, 'translation_sample': output,
                      'tts': tts_runtime_status(), 'audio_seconds': duration,
                      'synthesis_seconds': round(time.perf_counter() - before, 3)},
                     ensure_ascii=False, indent=2))
    if any(value <= 0 for value in durations):
        raise RuntimeError('Piper trả về audio rỗng')


if __name__ == '__main__':
    main()
