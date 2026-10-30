"""Benchmark the same local Marian checkpoint with CT2 CPU and PyTorch XPU.

Uses local model files only. Writes translations for manual quality inspection.
"""
import argparse
import gc
import json
import statistics
import sys
import time
from pathlib import Path


TEXTS = [
    '少年推开房门，看见师父正站在院子里。',
    '山风吹过竹林，远处传来清脆的钟声。',
    '他停下脚步，低声说道：“我们明天再出发。”',
    '少女抬起头，望着夜空中的星星，久久没有说话。',
    '城门外人来人往，商贩的叫卖声此起彼伏。',
    '老人放下手中的茶杯，脸上露出一丝笑容。',
    '这件事情没有那么简单，你最好再想一想。',
    '经过三天的赶路，他们终于来到了那座古老的城市。',
]


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, default=Path(__file__).resolve().parents[1] / 'models/translation/HachimiMT-60-QT')
    parser.add_argument('--batch-size', type=int, default=8)
    parser.add_argument('--beam', type=int, default=2)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--backends', nargs='+', choices=['ct2_cpu', 'xpu_fp32', 'xpu_fp16'], default=['ct2_cpu', 'xpu_fp16'])
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1] / 'output_text/intel-benchmark')
    args = parser.parse_args()
    if min(args.batch_size, args.beam, args.repeats) < 1:
        parser.error('batch-size, beam and repeats must be positive')

    import torch
    from transformers import MarianMTModel, MarianTokenizer

    tokenizer = MarianTokenizer.from_pretrained(args.model, local_files_only=True)
    report = {'torch': torch.__version__, 'xpu_available': torch.xpu.is_available(),
              'model': str(args.model), 'texts': TEXTS, 'batch_size': args.batch_size,
              'beam': args.beam, 'results': {}}
    if report['xpu_available']:
        report['device'] = torch.xpu.get_device_name(0)
    print(json.dumps({k: v for k, v in report.items() if k != 'texts'}, ensure_ascii=False), flush=True)
    if any(b.startswith('xpu') for b in args.backends) and not report['xpu_available']:
        raise RuntimeError('PyTorch XPU does not see an Intel GPU')
    args.output.mkdir(parents=True, exist_ok=True)
    for backend in args.backends:
        print(f'Loading {backend}...', flush=True)
        start = time.perf_counter()
        if backend == 'ct2_cpu':
            import ctranslate2
            model = ctranslate2.Translator(str(args.model / 'ct2-int8_float32'), device='cpu', compute_type='int8')
            report['ctranslate2'] = ctranslate2.__version__
        else:
            dtype = torch.float16 if backend == 'xpu_fp16' else torch.float32
            model = MarianMTModel.from_pretrained(args.model, local_files_only=True, dtype=dtype).to('xpu').eval()
            torch.xpu.synchronize()
        load_seconds = time.perf_counter() - start

        def translate():
            outputs = []
            for pos in range(0, len(TEXTS), args.batch_size):
                texts = TEXTS[pos:pos + args.batch_size]
                if backend == 'ct2_cpu':
                    encoded = tokenizer(texts, truncation=True, max_length=160)['input_ids']
                    tokens = [tokenizer.convert_ids_to_tokens(ids) for ids in encoded]
                    results = model.translate_batch(tokens, beam_size=args.beam, max_decoding_length=300, repetition_penalty=1.2)
                    outputs.extend(tokenizer.decode(tokenizer.convert_tokens_to_ids(r.hypotheses[0]), skip_special_tokens=True) for r in results)
                else:
                    inputs = tokenizer(texts, return_tensors='pt', padding=True, truncation=True, max_length=160).to('xpu')
                    with torch.inference_mode():
                        result = model.generate(**inputs, num_beams=args.beam, max_new_tokens=300,
                                                repetition_penalty=1.2, early_stopping=args.beam > 1)
                    torch.xpu.synchronize()
                    outputs.extend(tokenizer.batch_decode(result.cpu(), skip_special_tokens=True))
            if len(outputs) != len(TEXTS) or any(not t.strip() for t in outputs):
                raise RuntimeError(f'{backend}: empty or missing translation')
            return outputs

        start = time.perf_counter()
        translate()
        warmup_seconds = time.perf_counter() - start
        print(f'{backend}: warm-up {warmup_seconds:.3f}s', flush=True)
        elapsed = []
        for repeat in range(args.repeats):
            start = time.perf_counter()
            outputs = translate()
            elapsed.append(time.perf_counter() - start)
            print(f'{backend}: run {repeat + 1}/{args.repeats} {elapsed[-1]:.3f}s', flush=True)
        execution = model.device if backend == 'ct2_cpu' else str(next(model.parameters()).device)
        result = {'execution': execution, 'load_seconds': load_seconds, 'warmup_seconds': warmup_seconds, 'runs_seconds': elapsed,
                  'median_seconds': statistics.median(elapsed), 'translations': outputs}
        report['results'][backend] = result
        (args.output / 'translation-results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({backend: result}, ensure_ascii=False), flush=True)
        del model
        gc.collect()
        if backend.startswith('xpu'):
            torch.xpu.empty_cache()
    print(f'Saved {args.output / "translation-results.json"}', flush=True)


if __name__ == '__main__':
    main()
