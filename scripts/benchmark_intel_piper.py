"""Compare local Piper ONNX CPU with native OpenVINO on an Intel GPU.

Run with the optional OpenVINO environment; never downloads voice models.
"""
import argparse
import io
import json
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tts.openvino_session import OpenVINOSession


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--voice', type=Path, default=Path(__file__).resolve().parents[1] / 'models/voices/ngochuyennew.onnx')
    parser.add_argument('--device', default='GPU')
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1] / 'output_audio/intel-benchmark')
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error('--repeats must be positive')
    if not args.device.startswith('GPU'):
        parser.error('--device must be GPU or GPU.<index>')
    if not args.voice.is_file():
        parser.error(f'Missing local voice: {args.voice}')

    import numpy as np
    import openvino as ov
    from piper import PiperVoice
    from piper.config import PiperConfig, SynthesisConfig

    args.output.mkdir(parents=True, exist_ok=True)
    core = ov.Core()
    report = {'openvino': ov.__version__, 'hardware': {d: core.get_property(d, 'FULL_DEVICE_NAME') for d in core.available_devices}, 'results': {}}
    texts = [
        'Xin chào, đây là phép thử giọng đọc tiếng Việt trên máy tính.',
        'Người lữ hành bước qua khu rừng và nhìn về phía chân trời. ' * 8,
    ]
    # Disable model noise so lengths and output validity can be compared.
    config = SynthesisConfig(noise_scale=0.0, noise_w_scale=0.0)
    for backend in ('ort_cpu', 'openvino_gpu'):
        print(f'Loading {backend}...', flush=True)
        start = time.perf_counter()
        if backend == 'ort_cpu':
            voice = PiperVoice.load(args.voice, use_cuda=False)
            execution = voice.session.get_providers()
        else:
            session = OpenVINOSession(args.voice, args.device)
            with Path(str(args.voice) + '.json').open(encoding='utf-8') as f:
                voice = PiperVoice(session=session, config=PiperConfig.from_dict(json.load(f)))
            execution = session.devices
        load_seconds = time.perf_counter() - start

        def synthesize(text):
            buf = io.BytesIO()
            with wave.open(buf, 'wb') as wav:
                voice.synthesize_wav(text, wav, syn_config=config)
            data = buf.getvalue()
            with wave.open(io.BytesIO(data), 'rb') as wav:
                samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)
                duration = len(samples) / wav.getframerate()
                if not samples.size or not np.any(samples) or duration <= 0:
                    raise RuntimeError(f'{backend}: empty or silent audio')
            return data, duration

        start = time.perf_counter()
        for text in texts:
            synthesize(text)
        warmup_seconds = time.perf_counter() - start
        durations, elapsed = [], []
        for repeat in range(args.repeats):
            start = time.perf_counter()
            audio_seconds = 0.0
            for index, text in enumerate(texts):
                data, duration = synthesize(text)
                audio_seconds += duration
                if repeat == 0:
                    (args.output / f'{backend}-{index}.wav').write_bytes(data)
            elapsed.append(time.perf_counter() - start)
            durations.append(audio_seconds)
        seconds = float(np.median(elapsed))
        result = {'execution': execution, 'load_seconds': load_seconds, 'warmup_seconds': warmup_seconds,
                  'runs_seconds': elapsed, 'median_seconds': seconds, 'audio_seconds': durations,
                  'rtf': seconds / float(np.median(durations))}
        report['results'][backend] = result
        print(json.dumps({backend: result}, ensure_ascii=False), flush=True)
    report['gpu_speedup'] = report['results']['ort_cpu']['median_seconds'] / report['results']['openvino_gpu']['median_seconds']
    path = args.output / 'results.json'
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    print(f'Saved {path}', flush=True)


if __name__ == '__main__':
    main()
