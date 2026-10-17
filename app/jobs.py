import asyncio
import threading
import json
import time
import logging
from .engines import create_engine, invert_opener_spacing
from .text import make_plan, assemble, postprocess
from .glossary import parse_glossary
from .honorific_normalize import normalize_honorifics
from .pronoun_harmonizer_v9 import harmonize_pronouns_v9
from .postprocess_policy import classify_genre, v9_route_for_decision
from .text_preprocess import normalize_chinese_text

log = logging.getLogger(__name__)

def apply_postprocess(title, paras, source_title, source_paras, config):
    """Full postprocessing pipeline: quotes spacing, honorific normalization, and V9 pronoun harmonizer."""
    title = invert_opener_spacing(postprocess(title))
    paras = [invert_opener_spacing(postprocess(p)) for p in paras]

    honorific_mode = config.get('honorific_mode', 'safe')
    pronoun_harmonizer = config.get('pronoun_harmonizer', True)

    if honorific_mode != 'off' or pronoun_harmonizer:
        try:
            rows = [(0, source_title or '', title)] + [
                (i + 1, s, t) for i, (s, t) in enumerate(zip(source_paras, paras))
            ]
            policy_rows = [(idx, normalize_chinese_text(zh, 't2s'), vi) for idx, zh, vi in rows]
            genre_decision = classify_genre(policy_rows) if policy_rows else None

            # 1. Honorific normalization
            if honorific_mode in ('safe', 'xianxia_strict'):
                apply_pronouns = (honorific_mode == 'xianxia_strict' and genre_decision and genre_decision.is_classical)
                new_rows = []
                for (idx, zh, vi), (_, pol_zh, _) in zip(rows, policy_rows):
                    fixed = normalize_honorifics(
                        pol_zh, vi,
                        apply_kinship=True,
                        apply_pronouns=bool(apply_pronouns),
                        classical_context=genre_decision.is_classical if genre_decision else None
                    )
                    new_rows.append((idx, zh, fixed))
                rows = new_rows

            # 2. Pronoun Harmonizer V9
            if pronoun_harmonizer and rows:
                v9_policy_rows = [(idx, normalize_chinese_text(zh, 't2s'), vi) for idx, zh, vi in rows]
                v9_rows, _ = harmonize_pronouns_v9(
                    v9_policy_rows,
                    route=v9_route_for_decision(genre_decision) if genre_decision else "unknown_copy_guard"
                )
                rows = [(idx, zh, fvi) for (idx, zh, _), (_, _, fvi) in zip(rows, v9_rows)]

            title = rows[0][2]
            paras = [r[2] for r in rows[1:]]
        except Exception:
            log.exception('Lỗi hậu kỳ xưng hô/đại từ; giữ nguyên bản dịch thô')

    title = postprocess(title)
    paras = [postprocess(p) for p in paras]
    return title, paras

class Job:
    def __init__(self, store):
        self.store = store
        self.status = 'ready'
        self.message = ''
        self.thread = None
        self.stop_flag = threading.Event()
        self.gate = threading.Event()
        self.gate.set()
        self.clients = set()
        self.loop = None
        self.lock = threading.RLock()

    @property
    def active(self):
        return self.thread is not None and self.thread.is_alive()

    def summary(self):
        chapters = self.store.list()
        done = sum(c['status'] == 'done' for c in chapters)
        return {
            'status': self.status,
            'message': self.message,
            'done': done,
            'total': len(chapters),
            'active': self.active
        }

    async def broadcast(self, event):
        async def send(client):
            try:
                await asyncio.wait_for(client.send_json(event), 2)
            except Exception:
                self.clients.discard(client)
        await asyncio.gather(*(send(c) for c in list(self.clients)))

    def emit(self, type, **data):
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self.broadcast({'type': type, **data, 'progress': self.summary()}),
                self.loop
            )

    def checkpoint(self):
        while not self.stop_flag.is_set():
            if self.gate.wait(.2):
                return True
        return False

    def start(self, config, reset=False):
        with self.lock:
            if self.active:
                raise ValueError('Job trước vẫn đang xử lý. Đợi batch hiện tại kết thúc.')
            book = self.store.book()
            if not book:
                raise ValueError('Hãy nạp truyện trước.')
            glossary = parse_glossary(config['glossary'])
            old = json.loads(book['config']) if book.get('config') else {}
            changed = old and any(
                old.get(k) != config.get(k)
                for k in ('engine', 'glossary', 'honorific_mode', 'pronoun_harmonizer', 'beam_size', 'chunk_mode', 'normalize_mode')
            )
            if changed and not reset and any(c['status'] != 'pending' for c in self.store.list()):
                raise ValueError('Cấu hình dịch đã thay đổi. Chọn “Dịch lại từ đầu” để tránh trộn cấu hình.')
            self.store.configure(config, reset)
            self.stop_flag.clear()
            self.gate.set()
            self.status = 'loading'
            self.message = 'Đang nạp engine…'
            self.thread = threading.Thread(target=self.run, args=(config, glossary), daemon=True, name='translator')
            self.thread.start()

    def pause(self):
        with self.lock:
            if not self.active or self.status not in ('running', 'loading'):
                raise ValueError('Không có job đang dịch.')
            self.gate.clear()
            self.status = 'paused'
            self.message = 'Tạm dừng sau batch hiện tại'
            self.emit('status')

    def resume(self):
        with self.lock:
            if not self.active or self.status != 'paused':
                raise ValueError('Không có job đang tạm dừng.')
            self.gate.set()
            self.status = 'running'
            self.message = ''
            self.emit('status')

    def stop(self):
        with self.lock:
            if not self.active:
                raise ValueError('Không có job đang chạy.')
            self.stop_flag.set()
            self.gate.set()
            self.status = 'stopping'
            self.message = 'Đang hủy; đợi lời gọi engine hiện tại kết thúc'
            self.emit('status')

    def run(self, config, glossary):
        current = None
        try:
            engine = create_engine(config.get('engine', 'HachimiMT-60-QT'))
            engine.load()
            if not self.checkpoint():
                return
            with self.lock:
                if self.status != 'paused':
                    self.status = 'running'
                    self.message = ''
            self.emit('status')
            for row in self.store.list():
                if row['status'] == 'done':
                    continue
                if not self.checkpoint():
                    break
                current = row['id']
                chapter = self.store.get(current)
                chunk_mode = config.get('chunk_mode', 'sentence')
                beam_size = config.get('beam_size', 2)
                normalize_mode = config.get('normalize_mode', 'auto')

                plan = chapter['plan'] or make_plan(chapter['title'], chapter['source'], glossary, chunk_mode=chunk_mode)
                values = chapter['outputs'] or [None] * len(plan)
                self.store.update(current, status='translating', plan=plan, outputs=values, error='')
                self.emit('chapter_started', chapter_id=current)
                for attempt in range(3):
                    try:
                        pending = [i for i, v in enumerate(values) if v is None]
                        batch_size = config.get('batch_size', 8)
                        for offset in range(0, len(pending), batch_size):
                            if not self.checkpoint():
                                return
                            ids = pending[offset:offset + batch_size]
                            try:
                                translated = engine.translate(
                                    [plan[i][1] for i in ids],
                                    glossary,
                                    beam_size=beam_size,
                                    chunk_mode=chunk_mode,
                                    normalize_mode=normalize_mode
                                )
                            except TypeError:
                                translated = engine.translate([plan[i][1] for i in ids], glossary)


                            if len(translated) != len(ids):
                                raise RuntimeError('Sai số lượng segment')
                            if self.stop_flag.is_set():
                                return
                            for i, text in zip(ids, translated):
                                values[i] = text
                            title, paras = assemble(plan, values, len(chapter['source']))
                            title = postprocess(title)
                            paras = [postprocess(p) for p in paras]
                            self.store.update(current, outputs=values, translated_title=title, translated=paras)
                            self.emit('segment_done', chapter_id=current, completed=sum(v is not None for v in values), segments=len(plan))

                        # Apply full postprocessing upon chapter completion
                        title, paras = assemble(plan, values, len(chapter['source']))
                        title, paras = apply_postprocess(title, paras, chapter['title'], chapter['source'], config)
                        self.store.update(current, status='done', outputs=values, translated_title=title, translated=paras, error='')
                        self.emit('chapter_done', chapter_id=current)
                        break
                    except Exception as exc:
                        log.exception('Chapter %s attempt %s/3', current, attempt + 1)
                        if self.stop_flag.is_set():
                            return
                        if attempt == 2:
                            self.store.update(current, status='error', error=str(exc)[:500])
                            self.emit('error', chapter_id=current, message=str(exc)[:500])
                        elif self.stop_flag.wait(2 ** attempt):
                            return
                current = None
        except Exception as exc:
            log.exception('Job failed')
            self.status = 'error'
            self.message = str(exc)[:500]
            self.emit('error', message=self.message)
        finally:
            if current:
                chapter = self.store.get(current)
                if chapter and chapter['status'] == 'translating':
                    self.store.update(current, status='pending')
            with self.lock:
                if self.status != 'error':
                    errors = any(c['status'] == 'error' for c in self.store.list())
                    self.status = 'error' if errors and not self.stop_flag.is_set() else 'ready'
                    self.message = 'Có chương lỗi. Bắt đầu để thử lại.' if self.status == 'error' else ''
            self.emit('job_finished')
