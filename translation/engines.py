"""Translation engines with multi-model local CTranslate2 and HF Space support."""
from abc import ABC, abstractmethod
from pathlib import Path
import os
import re
import time
import logging
from .glossary import translate_with_glossary

from paths import ROOT, translation_models
SPACE = 'ngocdang83/HachimiMT-demo'
SPECIAL = {0: '<pad>', 1: '<s>', 2: '</s>', 3: '<unk>'}
log = logging.getLogger(__name__)

MODELS = {
    'HachimiMT-60-QT': {
        'repo': 'ngocdang83/HachimiMT-60-QT',
        'name': 'HachimiMT-60-QT (Cổ trang / Tiên hiệp)',
        'size_mb': 58,
        'beam_size': 2,
        'repetition_penalty': 1.2,
        'max_tokens': 160,
        'desc': 'Tối ưu truyện tiên hiệp, kiếm hiệp, xưng hô ta/ngươi/hắn/nàng.',
    },
    'HachimiMT-60': {
        'repo': 'ngocdang83/HachimiMT-60-zh-vi',
        'name': 'HachimiMT-60 (Hiện đại / Đô thị)',
        'size_mb': 57,
        'beam_size': 2,
        'repetition_penalty': 1.2,
        'max_tokens': 160,
        'desc': 'Văn phong tự nhiên, phù hợp truyện đô thị, hiện đại, học đường.',
    },
    'HachimiMT-40-QT': {
        'repo': 'ngocdang83/HachimiMT-40-QT',
        'name': 'HachimiMT-40-QT (Nhanh & nhẹ ~43MB)',
        'size_mb': 43,
        'beam_size': 1,
        'repetition_penalty': 1.05,
        'max_tokens': 160,
        'desc': 'Model gọn nhẹ, tốc độ cao, tiết kiệm RAM.',
    },
    'HachimiMT-30': {
        'repo': 'ngocdang83/HachimiMT-30-zh-vi',
        'name': 'HachimiMT-30 (Siêu nhẹ ~35MB)',
        'size_mb': 35,
        'beam_size': 1,
        'repetition_penalty': 1.2,
        'max_tokens': 160,
        'desc': 'Model siêu nhẹ, tốc độ nhanh nhất cho máy cấu hình yếu.',
    },
    'MoxhiMT-60': {
        'repo': 'DanVP/MoxhiMT-60',
        'name': 'MoxhiMT-60 (Cổ trang / Kiếm hiệp ~58MB)',
        'size_mb': 58,
        'beam_size': 2,
        'repetition_penalty': 1.2,
        'max_tokens': 160,
        'desc': 'Model dịch kiếm hiệp cổ điển, xưng hô ổn định.',
    },
    'MoxhiMT-30': {
        'repo': 'DanVP/MoxhiMT-30',
        'name': 'MoxhiMT-30 (Gọn nhẹ ~38MB)',
        'size_mb': 38,
        'beam_size': 2,
        'repetition_penalty': 1.2,
        'max_tokens': 160,
        'desc': 'Model 38MB gọn nhẹ, dịch nhanh, cân bằng.',
    },
    'MoxhiMT-30-QT': {
        'repo': 'DanVP/MoxhiMT-30-QT',
        'name': 'MoxhiMT-30-QT (Cổ trang nhẹ ~38MB)',
        'size_mb': 38,
        'beam_size': 1,
        'repetition_penalty': 1.2,
        'max_tokens': 160,
        'desc': 'Model cổ trang ta/ngươi/hắn/nàng tối ưu nhẹ và nhanh.',
    },
    'HirashibaMT-Medium': {
        'repo': 'Moleys/hirashiba-mt-medium',
        'name': 'HirashibaMT-Medium (Chất lượng cao ~62MB)',
        'size_mb': 62,
        'beam_size': 4,
        'repetition_penalty': 1.0,
        'max_tokens': 128,
        'desc': 'Model Hirashiba Marian chất lượng dịch chuẩn xác.',
    },
    'HirashibaMT-Tiny': {
        'repo': 'chi-vi/hirashiba-mt-tiny-zh-vi',
        'name': 'HirashibaMT-Tiny (Siêu tốc ~17MB)',
        'size_mb': 17,
        'beam_size': 1,
        'repetition_penalty': 1.0,
        'max_tokens': 160,
        'desc': 'Model Marian siêu nhỏ chỉ 17MB, tốc độ dịch cực nhanh.',
    },
}

_OPENER_SPACING_OPENERS = "“‘«「『【《([{（［｛"
_OPENER_SPACING_INVERSE = re.compile(
    "([" + re.escape(_OPENER_SPACING_OPENERS) + r"]) (?=[^\W\d_])"
)

def invert_opener_spacing(text: str) -> str:
    if not text or not any(ch in _OPENER_SPACING_OPENERS for ch in text):
        return text
    return _OPENER_SPACING_INVERSE.sub(r"\1", text)

def is_model_downloaded(model_key: str, backend: str = 'ct2') -> bool:
    if model_key not in MODELS:
        return False
    try:
        from translation.core.translator import is_model_downloaded as h_is_downloaded, Backend
        b = Backend.TRANSFORMERS if backend in ('transformers', 'pytorch', 'torch') else Backend.CT2
        return h_is_downloaded(model_key, b)
    except Exception:
        pass
    model_dir = translation_models() / model_key
    if backend in ('transformers', 'pytorch', 'torch'):
        needed = [model_dir / n for n in ('model.safetensors', 'pytorch_model.bin')]
        has_weights = any(p.is_file() for p in needed)
        has_tok = (model_dir / 'source.spm').is_file() or (model_dir / 'tokenizer.json').is_file()
        return has_weights and has_tok
    needed = [model_dir / 'ct2-int8_float32' / n for n in ('model.bin', 'config.json', 'shared_vocabulary.json')]
    needed += [model_dir / n for n in ('source.spm', 'target.spm')]
    return all(p.is_file() for p in needed)

def list_available_models(backend: str = 'ct2') -> list[dict]:
    items = []
    for key, cfg in MODELS.items():
        items.append({
            'id': key,
            'name': cfg['name'],
            'size_mb': cfg['size_mb'],
            'desc': cfg['desc'],
            'downloaded': is_model_downloaded(key, backend=backend),
            'recommended': key == 'HachimiMT-60-QT',
        })
    items.append({
        'id': 'space',
        'name': '🌐 Trực tuyến: HachimiMT-60-QT (HF Space API)',
        'size_mb': 0,
        'desc': 'Dịch trực tuyến qua HF Space (ngocdang83/HachimiMT-demo), không tốn RAM/CPU máy.',
        'downloaded': True,
        'recommended': False,
    })
    items.append({
        'id': 'space:HachimiMT-60',
        'name': '🌐 Trực tuyến: HachimiMT-60 Đô thị (HF Space API)',
        'size_mb': 0,
        'desc': 'Dịch trực tuyến model Đô thị qua HF Space, không cần tải.',
        'downloaded': True,
        'recommended': False,
    })
    items.append({
        'id': 'space:MoxhiMT-60',
        'name': '🌐 Trực tuyến: MoxhiMT-60 Kiếm hiệp (HF Space API)',
        'size_mb': 0,
        'desc': 'Dịch trực tuyến model Kiếm hiệp qua HF Space, không cần tải.',
        'downloaded': True,
        'recommended': False,
    })
    return items

class TranslatorEngine(ABC):
    @abstractmethod
    def load(self): ...

    def translate(self, texts: list[str], glossary, beam_size: int | None = None, chunk_mode: str = 'sentence', normalize_mode: str = 'auto') -> list[str]:
        return translate_with_glossary(texts, glossary, lambda xs: self.translate_raw(xs, beam_size=beam_size, chunk_mode=chunk_mode, normalize_mode=normalize_mode))

    @abstractmethod
    def translate_raw(self, texts: list[str], beam_size: int | None = None, chunk_mode: str = 'sentence', normalize_mode: str = 'auto') -> list[str]: ...

class LocalEngine(TranslatorEngine):
    def __init__(self, model_key: str = 'HachimiMT-60-QT', backend: str = 'ct2'):
        self.model_key = model_key if model_key in MODELS else 'HachimiMT-60-QT'
        self.backend = backend.lower() if backend else 'ct2'
        self.config = MODELS.get(self.model_key, {})
        self.translator = None
        self.source = None
        self.target = None
        self.model = None
        self.to_simplified = None
        self._fallback_batch_size = max(1, int(os.getenv('HACHIMIMT_BATCH_SIZE', '8')))

    def load(self):
        try:
            import sys
            from translation.core.translator import HachimiTranslator, Backend
            self.translator = HachimiTranslator()
            target_backend = Backend.TRANSFORMERS if self.backend in ('transformers', 'pytorch', 'torch') else Backend.CT2
            self.translator.load(self.model_key, target_backend)
            if target_backend == Backend.CT2 and os.getenv('HACHIMIMT_FORCE_CT2_CUDA') == '1' and self.translator.device != 'cuda':
                raise RuntimeError('CT2 core không dùng CUDA trong khi FORCE_CT2_CUDA=1')
            log.info("Loaded official HachimiTranslator core for %s with backend %s", self.model_key, target_backend.value)
            return
        except Exception as exc:
            self.translator = None
            log.warning("HachimiTranslator core load failed (%s), using fallback CT2 loader: %s", self.model_key, exc)

        from .ct2_safe_import import import_ctranslate2
        ctranslate2 = import_ctranslate2()
        import sentencepiece as spm
        from huggingface_hub import snapshot_download

        model_dir = translation_models() / self.model_key
        needed = [model_dir / 'ct2-int8_float32' / n for n in ('model.bin', 'config.json', 'shared_vocabulary.json')]
        needed += [model_dir / n for n in ('source.spm', 'target.spm')]
        if not all(p.is_file() for p in needed):
            log.info("Downloading model %s from %s...", self.model_key, self.config['repo'])
            snapshot_download(
                self.config['repo'],
                local_dir=model_dir,
                allow_patterns=['source.spm', 'target.spm', 'ct2-int8_float32/*'],
                local_files_only=os.getenv('HF_HUB_OFFLINE') == '1'
            )
        self.source = spm.SentencePieceProcessor(model_file=str(model_dir / 'source.spm'))
        self.target = spm.SentencePieceProcessor(model_file=str(model_dir / 'target.spm'))

        has_cuda = False
        try:
            from translation.core.hardware import detect_hardware_profile
            profile = detect_hardware_profile()
            intra_threads = profile.ct2_threads if profile else max(1, min(8, (os.cpu_count() or 2) - 1))
            has_cuda = profile.has_cuda if profile else False
        except Exception:
            intra_threads = max(1, min(8, (os.cpu_count() or 2) - 1))
            try:
                has_cuda = ctranslate2.get_cuda_device_count() > 0
            except Exception:
                has_cuda = False

        if os.getenv('HACHIMIMT_FORCE_CT2_CUDA') == '1' and not has_cuda:
            raise RuntimeError('CT2 chưa dùng được CUDA. Kiểm tra runtime T4 và thư viện CUDA; không chuyển âm thầm sang CPU.')
        device = 'cuda' if has_cuda else 'cpu'
        compute_type = os.getenv('HACHIMIMT_COMPUTE_TYPE') or ('int8_float16' if has_cuda else 'int8')

        self.model = ctranslate2.Translator(
            str(model_dir / 'ct2-int8_float32'),
            device=device,
            compute_type=compute_type,
            inter_threads=1,
            intra_threads=intra_threads
        )
        from opencc import OpenCC
        self.to_simplified = OpenCC('t2s')

    def reduce_batch_size(self):
        """Halve the inference budget after OOM, without dropping any segments."""
        if self.translator is not None:
            old = self.translator._batch_size
            self.translator._batch_size = max(1, old // 2)
            return self.translator._batch_size < old
        old = self._fallback_batch_size
        self._fallback_batch_size = max(1, old // 2)
        return self._fallback_batch_size < old

    def translate_raw(self, texts: list[str], beam_size: int | None = None, chunk_mode: str = 'sentence', normalize_mode: str = 'auto') -> list[str]:
        if not texts:
            return []

        beam = (
            self.translator.clamp_beam(beam_size)
            if (self.translator and beam_size)
            else (beam_size if (beam_size and 1 <= beam_size <= 4) else self.config.get('beam_size', 2))
        )
        mode = 'paragraph' if chunk_mode == 'paragraph' else 'sentence'

        # 1. Primary path: Official HachimiTranslator core
        if self.translator is not None:
            from .text_preprocess import normalize_chinese_text
            all_chunks = []
            mapping = []

            for t in texts:
                norm_text = normalize_chinese_text(t, normalize_mode)
                if not norm_text.strip():
                    mapping.append((len(all_chunks), len(all_chunks)))
                    continue

                sub_chunks = self.translator._chunk_text(norm_text, chunk_mode=mode)
                start_idx = len(all_chunks)
                all_chunks.extend(sub_chunks if sub_chunks else [norm_text])
                mapping.append((start_idx, len(all_chunks)))

            if not all_chunks:
                return ['' for _ in texts]

            # Batch translation with clamped beam_size
            from translation.core.translator import Backend
            if getattr(self.translator, '_backend', Backend.CT2) == Backend.TRANSFORMERS:
                translated_chunks = self.translator._translate_torch_batch(all_chunks, beam_size=beam)
            else:
                translated_chunks = self.translator._translate_chunks_ct2(all_chunks, beam_size=beam)

            outputs = []
            for start, end in mapping:
                if start == end:
                    outputs.append('')
                else:
                    outputs.append(' '.join(translated_chunks[start:end]).strip())
            return outputs

        # 2. Fallback path
        from .text_preprocess import normalize_chinese_text
        from .core.chunker import split_chunks
        jobs = []
        groups = []
        def encode(text: str):
            ids = self.source.encode(text, out_type=int)
            if len(ids) + 1 > self.config.get('max_tokens', 160) and len(text) > 1:
                middle = len(text) // 2
                encode(text[:middle])
                encode(text[middle:])
                return
            jobs.append([SPECIAL[i] if i in SPECIAL else self.source.id_to_piece(i) for i in ids] + ['</s>'])

        for text in texts:
            first = len(jobs)
            normalized = normalize_chinese_text(text, normalize_mode)
            for chunk in split_chunks(normalized, mode=mode):
                encode(chunk)
            groups.append((first, len(jobs)))

        if not jobs:
            return []

        repetition_penalty = self.config.get('repetition_penalty', 1.2)
        results = self.model.translate_batch(
            jobs,
            beam_size=beam,
            max_batch_size=self._fallback_batch_size,
            max_decoding_length=300,
            repetition_penalty=repetition_penalty
        )
        decoded = [
            invert_opener_spacing(
                self.target.decode([t for t in r.hypotheses[0] if t not in SPECIAL.values()]).strip()
            )
            for r in results
        ]
        return [' '.join(decoded[a:b]) for a, b in groups]

class SpaceEngine(TranslatorEngine):
    def __init__(self, model_key: str = 'HachimiMT-60-QT', timeout=180, interval=0.5):
        self.model_key = model_key if model_key in MODELS else 'HachimiMT-60-QT'
        self.timeout = timeout
        self.interval = interval
        self.last = 0
        self.client = None

    def load(self):
        from gradio_client import Client
        self.client = Client(SPACE, verbose=False, httpx_kwargs={'timeout': 45})

    def _translate_batch(self, batch_texts: list[str], beam: int, chunk_mode: str, normalize_mode: str) -> list[str]:
        if not batch_texts:
            return []
        non_empty = [i for i, t in enumerate(batch_texts) if t.strip()]
        if not non_empty:
            return ['' for _ in batch_texts]

        formatted = '\n\n'.join(f'§{i}§ {batch_texts[i]}' for i in non_empty)

        for attempt in range(3):
            try:
                time.sleep(max(0, self.interval - (time.monotonic() - self.last)))
                self.last = time.monotonic()
                res = self.client.predict(
                    source=formatted,
                    model_key=self.model_key,
                    backend='ct2',
                    beam_size=beam,
                    chunk_mode=chunk_mode or 'sentence',
                    normalize_mode=normalize_mode or 'auto',
                    honorific_kinship=True,
                    honorific_pronouns=True,
                    pronoun_harmonizer_v9=False,
                    auto_batch=False,
                    manual_batch=8,
                    glossary_rows={'headers': ['Nguồn Trung *', 'Đích Việt *', 'Loại (tùy chọn)', 'Alias fallback (tùy chọn, ngăn bằng |)', 'Bật'], 'data': [], 'metadata': None},
                    api_name='/translate_text_ui'
                )
                if not isinstance(res, (tuple, list)) or len(res) < 3 or not isinstance(res[2], str):
                    raise RuntimeError('Space không trả bản dịch hợp lệ.')
                full_text = res[2]
                extracted = {}
                for m in re.finditer(r'§(\d+)§\s*([\s\S]*?)(?=(?:§\d+§|\Z))', full_text):
                    extracted[int(m.group(1))] = invert_opener_spacing(m.group(2).strip())

                if len(extracted) == len(non_empty):
                    return [extracted.get(i, '') if batch_texts[i].strip() else '' for i in range(len(batch_texts))]

                # Fallback: split on \n\n if markers missing
                splits = [invert_opener_spacing(re.sub(r'^§\d+§\s*', '', s).strip()) for s in full_text.split('\n\n') if s.strip()]
                if len(splits) == len(non_empty):
                    res_map = {idx: splits[pos] for pos, idx in enumerate(non_empty)}
                    return [res_map.get(i, '') if batch_texts[i].strip() else '' for i in range(len(batch_texts))]

                return [extracted.get(i, '') if batch_texts[i].strip() else '' for i in range(len(batch_texts))]
            except Exception as exc:
                if attempt == 2:
                    log.error('Space translation failed after 3 attempts: %s', exc)
                    raise
                log.warning('Space retry %d/3: %s', attempt + 1, exc)
                time.sleep(2 ** (attempt + 1))
        return ['' for _ in batch_texts]

    def translate_raw(self, texts: list[str], beam_size: int | None = None, chunk_mode: str = 'sentence', normalize_mode: str = 'auto') -> list[str]:
        if not texts:
            return []
        beam = beam_size if (beam_size and 1 <= beam_size <= 4) else 2
        outputs = []

        batch = []
        batch_chars = 0
        for text in texts:
            t_len = len(text)
            if batch and (len(batch) >= 25 or batch_chars + t_len > 10000):
                outputs.extend(self._translate_batch(batch, beam, chunk_mode, normalize_mode))
                batch = []
                batch_chars = 0
            batch.append(text)
            batch_chars += t_len

        if batch:
            outputs.extend(self._translate_batch(batch, beam, chunk_mode, normalize_mode))

        return outputs

def create_engine(name: str, backend: str = 'ct2', *args, **kwargs):
    if name == 'local':
        return LocalEngine(model_key='HachimiMT-60-QT', backend=backend)
    if name == 'space' or name.startswith('space:'):
        model_key = name.split(':', 1)[1] if ':' in name else 'HachimiMT-60-QT'
        return SpaceEngine(model_key=model_key)
    if name in MODELS:
        return LocalEngine(model_key=name, backend=backend)
    return LocalEngine(model_key='HachimiMT-60-QT', backend=backend)
