import asyncio
import threading
import json
import time
import logging
import inspect
import os
from workflows.audio_queue import AudioQueue
from monitoring.tasks import TaskTelemetry, characters
from translation.engines import create_engine, invert_opener_spacing
from translation.text import make_plan, assemble, postprocess
from translation.glossary import parse_glossary
from translation.core.honorific_normalize import normalize_honorifics
from translation.core.pronoun_harmonizer_v9 import harmonize_pronouns_v9
from translation.core.postprocess_policy import classify_genre, v9_route_for_decision
from translation.core.text_preprocess import normalize_chinese_text
from audio import audio_service, merge_service
from storage import bucket_service
from storage.bucket_service import BucketSyncWorker

log = logging.getLogger(__name__)

def translate_with_options(engine, texts, glossary, **options):
    """Inspect compatibility BEFORE calling; never hide TypeError from engine code."""
    parameters=inspect.signature(engine.translate).parameters
    variadic=any(p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters.values())
    accepted=options if variadic else {k:v for k,v in options.items() if k in parameters}
    ignored=set(options)-set(accepted)
    if ignored:
        log.warning('Engine %s không hỗ trợ tùy chọn: %s',type(engine).__name__,', '.join(sorted(ignored)))
    return engine.translate(texts,glossary,**accepted)


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
        self.target_chapter_ids = None
        self.scope_label = ''
        self.telemetry = TaskTelemetry()
        self.bucket_sync = BucketSyncWorker(store)
        try:
            budget_minutes = max(0, int(os.getenv('NOVEL_SESSION_BUDGET_MINUTES', '0')))
        except ValueError:
            budget_minutes = 0
        self.session_deadline = time.monotonic() + budget_minutes * 60 if budget_minutes else None

    @property
    def active(self):
        return self.thread is not None and self.thread.is_alive()

    def summary(self):
        chapters = self.store.list()
        if self.target_chapter_ids is not None:
            target_set = set(self.target_chapter_ids)
            scoped_chapters = [c for c in chapters if c['id'] in target_set]
            done = sum(c['status'] == 'done' for c in scoped_chapters)
            total = len(scoped_chapters)
        else:
            done = sum(c['status'] == 'done' for c in chapters)
            total = len(chapters)

        return {
            'status': self.status,
            'message': self.message,
            'done': done,
            'total': total,
            'active': self.active,
            'scope': self.scope_label,
            'cloud_sync': self.bucket_sync.snapshot_status(),
            'session_seconds_remaining': max(0, int(self.session_deadline - time.monotonic())) if self.session_deadline else None,
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

    def queue_cloud_artifact(self, path, kind):
        try:
            self.bucket_sync.enqueue_artifact(path, kind)
        except Exception as exc:
            log.warning('Không xếp hàng được artifact Bucket (%s): %s', kind, exc)
            self.emit('cloud_checkpoint_error', error=str(exc)[:240])

    def queue_cloud_snapshot(self, include_audio=False):
        try:
            return self.bucket_sync.enqueue_snapshot(include_audio)
        except Exception as exc:
            log.warning('Không xếp hàng được checkpoint Bucket: %s', exc)
            self.emit('cloud_checkpoint_error', error=str(exc)[:240])
            return False

    def checkpoint(self):
        if self.session_deadline is not None and time.monotonic() >= self.session_deadline:
            self.stop_flag.set()
            self.gate.set()
            self.status = 'stopping'
            self.message = 'Đã hết ngân sách phiên; đang lưu trạng thái và dừng sau batch hiện tại.'
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
            self.telemetry.book(book.get('output_folder') or book['filename'])
            glossary = parse_glossary(config['glossary'])
            old = json.loads(book['config']) if book.get('config') else {}
            changed = old and any(
                old.get(k) != config.get(k)
                for k in ('backend', 'engine', 'glossary', 'honorific_mode', 'pronoun_harmonizer', 'beam_size', 'chunk_mode', 'normalize_mode')
            )

            all_chapters = self.store.list()
            start_pos = config.get('start_pos')
            end_pos = config.get('end_pos')
            chapter_ids = config.get('chapter_ids')
            force_retranslate = config.get('force_retranslate', False)

            max_pos = max((c.get('position', 0) for c in all_chapters), default=1)
            if start_pos is not None and end_pos is None:
                end_pos = max_pos
            elif start_pos is None and end_pos is not None:
                start_pos = 1

            if start_pos is not None and (start_pos < 1 or end_pos < start_pos):
                raise ValueError('Dải chương không hợp lệ.')
            if chapter_ids is not None and (not chapter_ids or start_pos is not None):
                raise ValueError('Danh sách chương rỗng hoặc xung đột với dải chương.')

            if start_pos is not None and end_pos is not None:
                s = min(int(start_pos), int(end_pos))
                e = max(int(start_pos), int(end_pos))
                target_chapters = [c for c in all_chapters if s <= c.get('position', 0) <= e]
                self.scope_label = f"Chương {s} - {e}"
            elif chapter_ids:
                target_set = set(chapter_ids)
                target_chapters = [c for c in all_chapters if c['id'] in target_set]
                self.scope_label = f"{len(target_chapters)} chương đã chọn"
            else:
                target_chapters = all_chapters
                self.scope_label = ""

            if not target_chapters:
                raise ValueError(f"Không tìm thấy chương nào trong phạm vi: {self.scope_label or 'Toàn bộ'}")

            if changed and not reset and not force_retranslate and any(c['status'] != 'pending' for c in target_chapters):
                raise ValueError('Cấu hình dịch đã thay đổi. Hãy chọn dịch lại/reset để tránh trộn bản dịch cũ và mới.')

            self.target_chapter_ids = [c['id'] for c in target_chapters] if (start_pos is not None or chapter_ids is not None) else None
            if not config.get('generate_audio', True):
                config = {**config, 'generate_audio': False, 'auto_group_audio': False}

            if reset:
                if self.target_chapter_ids:
                    self.store.reset_chapters(self.target_chapter_ids)
                    self.store.configure(config, reset=False)
                else:
                    self.store.configure(config, reset=True)
            elif force_retranslate:
                if self.target_chapter_ids:
                    self.store.reset_chapters(self.target_chapter_ids)
                self.store.configure(config, reset=False)
            else:
                if self.target_chapter_ids and all(c['status'] == 'done' for c in target_chapters):
                    self.store.reset_chapters(self.target_chapter_ids)
                if changed and any(c['status'] != 'pending' for c in target_chapters):
                    log.info("Cấu hình thay đổi trên dải mục tiêu.")
                self.store.configure(config, reset=False)

            audio_changed = old and any(old.get(k) != config.get(k) for k in audio_service.AUDIO_CONFIG_KEYS)
            if audio_changed and config.get('generate_audio', True):
                for chapter in target_chapters:
                    self.store.update(chapter['id'], audio_status='none')
                self.store._invalidate_groups([c['position'] for c in target_chapters])
            self.stop_flag.clear()
            self.gate.set()
            self.status = 'loading'
            self.message = f'Đang nạp engine…{f" ({self.scope_label})" if self.scope_label else ""}'
            self.thread = threading.Thread(
                target=self.run,
                args=(config, glossary, self.target_chapter_ids),
                daemon=True,
                name='translator'
            )
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

    def _generate_audio(self, item, config):
        cid, position, title, paras = item
        if not self.checkpoint():
            self.telemetry.cancel_queued(cid)
            self.store.update(cid, audio_status='none')
            return
        try:
            self.store.update(cid, audio_status='generating')
            self.emit('chapter_audio_started', chapter_id=cid)
            started = time.perf_counter()
            with self.telemetry.audio_task(cid, position, title):
                audio_path = audio_service.generate_chapter_audio(
                    cid, position, title, paras, self.store.audio_dir,
                    **audio_service.generation_kwargs(config))
            self.store.update(cid, audio_status='done')
            self.queue_cloud_artifact(audio_path, 'audio')
            log.info('TIMING audio chapter=%s seconds=%.3f', position, time.perf_counter() - started)
            self.emit('chapter_audio_done', chapter_id=cid, audio_url=f'/api/chapters/{cid}/audio')
            try:
                from gdrive import gdrive_service
                if gdrive_service.get_gdrive_config().get('auto_upload'):
                    threading.Thread(target=gdrive_service.upload_audio_file, args=(audio_path,), daemon=True).start()
            except Exception:
                log.exception('Không thể khởi tạo upload Drive')
        except Exception as exc:
            log.exception('Lỗi tạo audio cho chương %s', cid)
            self.store.update(cid, audio_status='error')
            self.emit('chapter_audio_error', chapter_id=cid, error=str(exc)[:300])

    def run(self, config, glossary, target_chapter_ids=None):
        current = None
        group_failed = False
        audio_queue = None
        export_dirty = False
        next_cloud_snapshot = time.monotonic() + 60
        target_id_set = set(target_chapter_ids) if target_chapter_ids else None
        try:
            backend = config.get('backend', 'ct2')
            try:
                engine = create_engine(config.get('engine', 'HachimiMT-60-QT'), backend=backend)
            except TypeError:
                engine = create_engine(config.get('engine', 'HachimiMT-60-QT'))
            engine.load()
            if not self.checkpoint():
                return
            with self.lock:
                if self.status != 'paused':
                    self.status = 'running'
                    self.message = ''
            self.emit('status')
            if config.get('generate_audio', True) and config.get('audio_pipeline', True):
                default_workers = 2 if (os.getenv('COLAB_GPU') or os.getenv('KAGGLE_KERNEL_RUN_TYPE')) else 1
                audio_workers = max(1, min(8, int(config.get('audio_workers', os.getenv('AUDIO_WORKERS', default_workers)))))
                if config.get('tts_engine') == 'vieneu':
                    audio_workers = 1
                audio_queue = AudioQueue(
                    lambda item: self._generate_audio(item, config), self.checkpoint,
                    lambda item: (self.store.update(item[0], audio_status='none'), self.telemetry.cancel_queued(item[0])),
                    maxsize=max(1, min(32, int(config.get('audio_queue_size', 4 if default_workers > 1 else 2)))),
                    workers=audio_workers)

            def queue_audio(item):
                self.telemetry.queued(item[0], item[1], item[2])
                if audio_queue is not None:
                    self.store.update(item[0], audio_status='queued')
                    audio_queue.submit(item)
                else:
                    self._generate_audio(item, config)

            for row in self.store.list():
                if target_id_set is not None and row['id'] not in target_id_set:
                    continue
                if row['status'] == 'done':
                    if config.get('generate_audio', True) and not self.stop_flag.is_set():
                        chapter = self.store.get(row['id'])
                        exists = audio_service.get_chapter_audio_path(self.store.audio_dir, row['id'], row['position'])
                        if chapter.get('audio_status') != 'done' or not exists:
                            queue_audio((row['id'], row['position'], chapter['translated_title'] or chapter['title'], chapter['translated']))
                    continue
                if not self.checkpoint():
                    break
                current = row['id']
                chapter = self.store.get(current)
                chunk_mode = config.get('chunk_mode', 'sentence')
                beam_size = config.get('beam_size', 2)
                normalize_mode = config.get('normalize_mode', 'auto' if config.get('normalize_t2s', True) else 'none')

                plan = chapter['plan'] or make_plan(chapter['title'], chapter['source'], glossary, chunk_mode=chunk_mode)
                values = chapter['outputs'] or [None] * len(plan)
                self.store.update(current, status='translating', plan=plan, outputs=values, error='')
                self.telemetry.translation_start(current, chapter['position'], chapter['title'], plan, values)
                self.emit('chapter_started', chapter_id=current)
                chapter_started = time.perf_counter()
                for attempt in range(3):
                    try:
                        pending = [i for i, v in enumerate(values) if v is None]
                        batch_size = max(1, int(config.get('batch_size', 96 if os.getenv('COLAB_GPU') else 8)))
                        offset = 0
                        while offset < len(pending):
                            if not self.checkpoint():
                                return
                            ids = pending[offset:offset + batch_size]
                            try:
                                batch_started=time.perf_counter()
                                translated = translate_with_options(
                                    engine, [plan[i][1] for i in ids], glossary,
                                    beam_size=beam_size, chunk_mode=chunk_mode,
                                    normalize_mode=normalize_mode)
                            except RuntimeError as exc:
                                oom = any(word in str(exc).lower() for word in ('out of memory', 'cuda_error_out_of_memory', 'cudaerrormemoryallocation', 'cublas_status_alloc_failed'))
                                reduced = False
                                if oom:
                                    reduce = getattr(engine, 'reduce_batch_size', None)
                                    reduced = bool(reduce()) if reduce else False
                                if oom and (batch_size > 1 or reduced):
                                    batch_size = max(1, batch_size // 2)
                                    log.warning('GPU OOM: giảm Web batch xuống %s, thử lại cùng đoạn', batch_size)
                                    self.emit('batch_reduced', batch_size=batch_size, reason='GPU OOM')
                                    continue
                                raise


                            if len(translated) != len(ids):
                                raise RuntimeError('Sai số lượng segment')
                            if self.stop_flag.is_set():
                                return
                            self.telemetry.translation_batch(sum(characters(plan[i][1]) for i in ids), time.perf_counter()-batch_started)
                            offset += len(ids)
                            for i, text in zip(ids, translated):
                                values[i] = text
                            title, paras = assemble(plan, values, len(chapter['source']))
                            title = postprocess(title)
                            paras = [postprocess(p) for p in paras]
                            self.store.update(current, outputs=values, translated_title=title, translated=paras)
                            self.emit('segment_done', chapter_id=current, completed=sum(v is not None for v in values), segments=len(plan))
                            if config.get('cloud_checkpoint', bucket_service.write_enabled()) and time.monotonic() >= next_cloud_snapshot:
                                self.queue_cloud_snapshot(config.get('checkpoint_include_audio', False))
                                next_cloud_snapshot = time.monotonic() + 60

                        title, paras = assemble(plan, values, len(chapter['source']))
                        title, paras = apply_postprocess(title, paras, chapter['title'], chapter['source'], config)
                        self.store.update(current, status='done', outputs=values, translated_title=title, translated=paras, error='')
                        export_dirty = True
                        try:
                            text_path = self.store.export_chapter_text(current, title, paras, chapter['position'])
                            self.queue_cloud_artifact(text_path, 'text')
                        except Exception as e:
                            log.error("Lỗi xuất file text chương %d: %s", chapter['position'], e)
                        log.info('TIMING translation chapter=%s seconds=%.3f', chapter['position'], time.perf_counter() - chapter_started)
                        self.telemetry.translation_end('done')
                        self.emit('chapter_done', chapter_id=current)

                        if config.get('generate_audio', True) and not self.stop_flag.is_set():
                            queue_audio((current, chapter['position'], title, paras))

                        break
                    except Exception as exc:
                        log.exception('Chapter %s attempt %s/3', current, attempt + 1)
                        if self.stop_flag.is_set():
                            return
                        if attempt == 2:
                            self.telemetry.translation_end('error')
                            self.store.update(current, status='error', error=str(exc)[:500])
                            self.emit('error', chapter_id=current, message=str(exc)[:500])
                        elif self.stop_flag.wait(2 ** attempt):
                            return
                current = None

            if audio_queue is not None:
                audio_queue.close()
            if config.get('auto_group_audio') and not self.stop_flag.is_set():
                try:
                    final_groups = merge_service.group_and_merge_chapters(
                        self.store, int(config.get('group_size', 50)),
                        config.get('audio_format', 'mp3'),
                        chapter_ids=target_chapter_ids,
                        bitrate=config.get('audio_bitrate', '96k'))
                    if final_groups:
                        self.emit('audio_groups_updated', groups=final_groups, group_size=int(config.get('group_size', 50)))
                except Exception as merge_exc:
                    group_failed = True
                    self.emit('audio_group_error', error=str(merge_exc)[:300])
                    log.warning('Lỗi gộp audio ở cuối job: %s', merge_exc)
        except Exception as exc:
            log.exception('Job failed')
            self.status = 'error'
            self.message = str(exc)[:500]
            self.emit('error', message=self.message)
        finally:
            if audio_queue is not None:
                try:
                    if self.status == 'error':
                        self.stop_flag.set()
                        self.gate.set()
                    audio_queue.close()
                except Exception as exc:
                    log.exception('Lỗi dừng audio worker')
                    self.status = 'error'
                    self.message = str(exc)[:500]
            self.telemetry.translation_end('stopped' if self.stop_flag.is_set() else 'error')
            audio_service.release_worker_voices()
            if export_dirty:
                try:
                    self.store.export_full_book_text()
                except Exception as exc:
                    log.exception('Lỗi xuất toàn bộ truyện')
                    self.status = 'error'
                    self.message = str(exc)[:500]
            if current:
                chapter = self.store.get(current)
                if chapter and chapter['status'] == 'translating':
                    self.store.update(current, status='pending')

            with self.lock:
                if self.status != 'error':
                    if target_id_set:
                        target_rows = [c for c in self.store.list() if c['id'] in target_id_set]
                        errors = group_failed or any(c['status'] == 'error' or c.get('audio_status') == 'error' for c in target_rows)
                    else:
                        errors = group_failed or any(c['status'] == 'error' or c.get('audio_status') == 'error' for c in self.store.list())
                    self.status = 'error' if errors and not self.stop_flag.is_set() else 'ready'
                    self.message = 'Có lỗi dịch hoặc audio. Kiểm tra chương lỗi và thông báo audio.' if self.status == 'error' else ''
            if config.get('cloud_checkpoint', bucket_service.write_enabled()):
                if self.queue_cloud_snapshot(config.get('checkpoint_include_audio', False)):
                    self.emit('cloud_checkpoint_queued')
                elif not bucket_service.write_enabled():
                    self.emit('cloud_checkpoint_error', error='Chưa cấu hình HF_TOKEN để ghi vào Bucket.')
            self.emit('job_finished')
