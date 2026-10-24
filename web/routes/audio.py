from urllib.parse import quote
import io
import json
import zipfile
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response
from audio import audio_service, merge_service
from web import runtime
from web.schemas import MergeAudioInput, AutoGroupInput, MergeRangeInput, MergeSelectedInput, AudioSettingsPatch, Config

router = APIRouter()

@router.get('/api/tts/status')
def tts_status():
    from audio.vieneu_service import runtime_status
    return {**audio_service.tts_runtime_status(), 'vieneu': runtime_status()}


@router.get('/api/voices')
def get_voices(tts_engine: str = 'piper'):
    if tts_engine == 'vieneu':
        from audio.vieneu_service import list_voices
        return list_voices()
    if tts_engine != 'piper':
        raise HTTPException(400, 'Engine TTS không hợp lệ.')
    return audio_service.list_available_voices()


@router.get('/api/chapters/{id}/audio')
def get_chapter_audio(id: int):
    chapter = runtime.store.get(id)
    if not chapter:
        raise HTTPException(404, 'Không tìm thấy chương.')
    path = audio_service.get_chapter_audio_path(runtime.store.audio_dir, chapter['id'], chapter['position'])
    if not path or not path.is_file():
        path = runtime.store.audio_dir / f"chuong_{chapter['position']:04d}.mp3"
    if not path or not path.is_file():
        raise HTTPException(404, 'Chương này chưa có file audio.')
    
    ext = path.suffix.lower()
    media_map = {'.mp3': 'audio/mpeg', '.m4b': 'audio/mp4', '.m4a': 'audio/mp4', '.wav': 'audio/wav', '.opus': 'audio/ogg', '.ogg': 'audio/ogg'}
    media_type = media_map.get(ext, 'audio/mpeg')
    return FileResponse(path, media_type=media_type, filename=f"chuong_{chapter['position']:04d}{ext}", headers={"Cache-Control": "no-store"})


def resolved_settings(saved, patch):
    data = patch.model_dump(exclude_unset=True, exclude_none=True) if patch else {}
    if 'tts_engine' in data and data['tts_engine'] != saved.get('tts_engine', 'piper') and 'voice_id' not in data:
        data['voice_id'] = 'truc_ly' if data['tts_engine'] == 'vieneu' else 'ngochuyennew'
    return Config.model_validate({**saved, **data}).model_dump()


@router.get('/api/settings/audio')
def get_audio_settings():
    from storage.checkpoints import load_draft
    book=runtime.store.book()
    saved=json.loads(book['config'] or '{}') if book else (load_draft() or {})
    cfg=Config.model_validate(saved).model_dump()
    return {'settings':{k:cfg[k] for k in audio_service.AUDIO_CONFIG_KEYS}}


@router.post('/api/settings/audio')
def save_audio_settings(payload: AudioSettingsPatch):
    with runtime.job.lock:
        runtime.ensure_idle()
        book = runtime.store.book()
        old = json.loads(book['config'] or '{}') if book else {}
        try:
            cfg = resolved_settings(old, payload)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        from storage.checkpoints import load_draft, save_draft
        save_draft({**(load_draft() or cfg), **{k: cfg[k] for k in audio_service.AUDIO_CONFIG_KEYS}})
        if book:
            changed = any(old.get(k) != cfg[k] for k in audio_service.AUDIO_CONFIG_KEYS)
            runtime.store.configure(cfg, reset=False)
            if changed:
                with runtime.store.connect() as db:
                    db.execute("UPDATE chapter SET audio_status='none' WHERE audio_status='done'")
                runtime.store._invalidate_groups()
        return {'ok': True, 'settings': {k: cfg[k] for k in audio_service.AUDIO_CONFIG_KEYS}}


@router.post('/api/chapters/{id}/audio')
def generate_single_audio(id: int, payload: AudioSettingsPatch | None = None):
    with runtime.job.lock:
        runtime.ensure_idle()
        chapter = runtime.store.get(id)
        if not chapter:
            raise HTTPException(404, 'Không tìm thấy chương.')
        if chapter['status'] != 'done':
            raise HTTPException(400, 'Chương này chưa được dịch xong.')
        book = runtime.store.book()
        saved = json.loads(book['config'] or '{}') if book else {}
        try:
            cfg = resolved_settings(saved, payload)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        try:
            runtime.store.update(id, audio_status='generating')
            runtime.job.emit('chapter_audio_started', chapter_id=id)
            runtime.job.telemetry.book(book.get('output_folder') or book['filename'])
            with runtime.job.telemetry.audio_task(id, chapter['position'], chapter['translated_title'] or chapter['title']):
                audio_path = audio_service.generate_chapter_audio(
                    id, chapter['position'], chapter['translated_title'] or chapter['title'],
                    chapter['translated'], runtime.store.audio_dir, **audio_service.generation_kwargs(cfg))
            runtime.store.update(id, audio_status='done')
            runtime.job.queue_cloud_artifact(audio_path, 'audio')
            runtime.store._invalidate_groups([chapter['position']])
            runtime.job.emit('chapter_audio_done', chapter_id=id, audio_url=f'/api/chapters/{id}/audio')
            return {'ok': True, 'audio_url': f'/api/chapters/{id}/audio',
                    'settings': {k: cfg[k] for k in audio_service.AUDIO_CONFIG_KEYS}}
        except Exception as exc:
            runtime.store.update(id, audio_status='error')
            runtime.job.emit('chapter_audio_error', chapter_id=id, error=str(exc))
            raise HTTPException(500, f'Lỗi tạo audio: {exc}')


@router.post('/api/audio/merge')
def merge_audio_endpoint(payload: MergeAudioInput):
    runtime.ensure_idle()
    groups = merge_service.group_and_merge_chapters(runtime.store, group_size=payload.group_size, fmt=payload.format)
    for group in groups:
        runtime.job.queue_cloud_artifact(runtime.store.audio_dir / 'audio_gop' / group['filename'], 'audio')
    return {'ok': True, 'groups': groups, 'count': len(groups)}


@router.post('/api/audio/auto-group')
def auto_group_audio_endpoint(payload: AutoGroupInput):
    runtime.ensure_idle()
    try:
        groups = merge_service.group_and_merge_chapters(runtime.store, group_size=payload.group_size, fmt=payload.format)
        for group in groups:
            runtime.job.queue_cloud_artifact(runtime.store.audio_dir / 'audio_gop' / group['filename'], 'audio')
        return {'ok': True, 'groups': groups, 'count': len(groups)}
    except Exception as exc:
        raise HTTPException(500, f"Lỗi tự động gộp audio: {exc}")


@router.post('/api/audio/merge-range')
def merge_audio_range_endpoint(payload: MergeRangeInput):
    runtime.ensure_idle()
    try:
        result = merge_service.merge_chapter_range(
            runtime.store,
            start_pos=payload.start_pos,
            end_pos=payload.end_pos,
            fmt=payload.format,
            bitrate=payload.bitrate
        )
        runtime.job.queue_cloud_artifact(runtime.store.audio_dir / 'audio_gop' / result['filename'], 'audio')
        return result
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(500, f"Lỗi gộp audio: {exc}")


@router.post('/api/audio/merge-selected')
def merge_audio_selected_endpoint(payload: MergeSelectedInput):
    runtime.ensure_idle()
    try:
        result = merge_service.merge_selected_chapters(
            runtime.store,
            chapter_ids=payload.chapter_ids,
            fmt=payload.format,
            bitrate=payload.bitrate
        )
        runtime.job.queue_cloud_artifact(runtime.store.audio_dir / 'audio_gop' / result['filename'], 'audio')
        return result
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(500, f"Lỗi gộp audio: {exc}")


@router.get('/api/audio/merged/{filename}')
def get_merged_audio_file(filename: str):
    p0 = (runtime.store.audio_dir / filename).resolve()
    if p0.is_file() and (runtime.store.audio_dir == p0.parent or runtime.store.audio_dir in p0.parents):
        return FileResponse(p0, filename=filename)
    p = (runtime.store.audio_dir / 'audio_gop' / filename).resolve()
    if p.is_file() and runtime.store.audio_dir in p.parents:
        return FileResponse(p, filename=filename)
    raise HTTPException(404, 'Không tìm thấy file audio đã gộp.')


@router.get('/api/audio/groups')
def list_audio_groups():
    groups_dir = runtime.store.audio_dir / 'audio_gop'
    items = []
    seen = set()
    if groups_dir.exists():
        for f in sorted(groups_dir.iterdir()):
            if f.is_file() and f.suffix.lower() in ('.mp3', '.m4b', '.m4a', '.opus', '.wav'):
                items.append({
                    'filename': f.name,
                    'size_mb': round(f.stat().st_size / (1024 * 1024), 2),
                    'url': f'/api/audio/groups/{f.name}'
                })
                seen.add(f.name)
    for f in sorted(runtime.store.audio_dir.glob('chuong_*_*.*')):
        if f.is_file() and f.name not in seen and not f.name.endswith('.tmp'):
            items.append({
                'filename': f.name,
                'size_mb': round(f.stat().st_size / (1024 * 1024), 2),
                'url': f'/api/audio/groups/{f.name}'
            })
            seen.add(f.name)
    return items


@router.get('/api/audio/groups/{filename}')
def get_audio_group_file(filename: str):
    p0 = (runtime.store.audio_dir / filename).resolve()
    if p0.is_file() and (runtime.store.audio_dir == p0.parent or runtime.store.audio_dir in p0.parents):
        return FileResponse(p0, filename=filename)
    p = (runtime.store.audio_dir / 'audio_gop' / filename).resolve()
    if p.is_file() and runtime.store.audio_dir in p.parents:
        return FileResponse(p, filename=filename)
    raise HTTPException(404, 'Không tìm thấy file nhóm.')


@router.get('/api/export/options')
def export_options():
    book=runtime.store.book()
    rows=runtime.store.list() if book else []
    files=audio_service.exportable_audio_files(runtime.store.audio_dir) if book else []
    return {'book_title':book['title'] if book else None,'chapters':len(rows),
            'translated':sum(c['status']=='done' for c in rows),
            'audio_files':len(files),'audio_bytes':sum(p.stat().st_size for p in files),
            'busy':runtime.job.active}


@router.get('/api/export/audio')
def export_audio_zip():
    book = runtime.store.book()
    if not book:
        raise HTTPException(400, 'Chưa có truyện.')
    audio_files = audio_service.exportable_audio_files(runtime.store.audio_dir)
    if not audio_files:
        raise HTTPException(404, 'Chưa có file audio nào để xuất.')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for f in audio_files:
            z.write(f, arcname=str(f.relative_to(runtime.store.audio_dir)))
    title = (book.get('title') or 'novel').replace('"', '')
    return Response(buf.getvalue(), media_type='application/zip',
                    headers={'Content-Disposition': "attachment; filename=audio.zip; filename*=UTF-8''" + quote(title + '_audio.zip')})

