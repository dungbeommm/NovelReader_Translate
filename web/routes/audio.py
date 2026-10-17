from urllib.parse import quote
import io
import json
import zipfile
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response
from audio import audio_service, merge_service
from web import runtime
from web.schemas import MergeAudioInput, AutoGroupInput, MergeRangeInput, MergeSelectedInput

router = APIRouter()

@router.get('/api/voices')
def get_voices():
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
    return FileResponse(path, media_type=media_type, filename=f"chuong_{chapter['position']:04d}{ext}")


@router.post('/api/chapters/{id}/audio')
def generate_single_audio(id: int):
    chapter = runtime.store.get(id)
    if not chapter:
        raise HTTPException(404, 'Không tìm thấy chương.')
    if chapter['status'] != 'done':
        raise HTTPException(400, 'Chương này chưa được dịch xong.')
    
    book = runtime.store.book()
    b_cfg = json.loads(book['config']) if (book and book.get('config')) else {}
    voice_id = b_cfg.get('voice_id', 'ngochuyennew')
    speed = float(b_cfg.get('audio_speed', 1.0))
    noise_scale = float(b_cfg.get('noise_scale', 0.667))
    noise_w_scale = float(b_cfg.get('noise_w_scale', 0.8))
    fmt = b_cfg.get('audio_format', 'mp3')
    bitrate = b_cfg.get('audio_bitrate', '96k')

    try:
        runtime.store.update(id, audio_status='generating')
        runtime.job.emit('chapter_audio_started', chapter_id=id)
        path = audio_service.generate_chapter_audio(
            id, chapter['position'],
            chapter['translated_title'] or chapter['title'],
            chapter['translated'],
            runtime.store.audio_dir,
            voice_id=voice_id,
            speed=speed,
            noise_scale=noise_scale,
            noise_w_scale=noise_w_scale,
            fmt=fmt,
            bitrate=bitrate
        )
        runtime.store.update(id, audio_status='done')
        runtime.job.emit('chapter_audio_done', chapter_id=id, audio_url=f'/api/chapters/{id}/audio')
        return {'ok': True, 'audio_url': f'/api/chapters/{id}/audio'}
    except Exception as exc:
        runtime.store.update(id, audio_status='error')
        runtime.job.emit('chapter_audio_error', chapter_id=id, error=str(exc))
        raise HTTPException(500, f'Lỗi tạo audio: {exc}')


@router.post('/api/audio/merge')
def merge_audio_endpoint(payload: MergeAudioInput):
    runtime.ensure_idle()
    groups = merge_service.group_and_merge_chapters(runtime.store, group_size=payload.group_size, fmt=payload.format)
    return {'ok': True, 'groups': groups, 'count': len(groups)}


@router.post('/api/audio/auto-group')
def auto_group_audio_endpoint(payload: AutoGroupInput):
    runtime.ensure_idle()
    try:
        groups = merge_service.group_and_merge_chapters(runtime.store, group_size=payload.group_size, fmt=payload.format)
        return {'ok': True, 'groups': groups, 'count': len(groups)}
    except Exception as exc:
        raise HTTPException(500, f"Lỗi tự động gộp audio: {exc}")


@router.post('/api/audio/merge-range')
def merge_audio_range_endpoint(payload: MergeRangeInput):
    runtime.ensure_idle()
    try:
        return merge_service.merge_chapter_range(
            runtime.store,
            start_pos=payload.start_pos,
            end_pos=payload.end_pos,
            fmt=payload.format,
            bitrate=payload.bitrate
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(500, f"Lỗi gộp audio: {exc}")


@router.post('/api/audio/merge-selected')
def merge_audio_selected_endpoint(payload: MergeSelectedInput):
    runtime.ensure_idle()
    try:
        return merge_service.merge_selected_chapters(
            runtime.store,
            chapter_ids=payload.chapter_ids,
            fmt=payload.format,
            bitrate=payload.bitrate
        )
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
    # Cũng quét các file gộp chuong_XXXX_YYYY.* ở thư mục gốc nếu chưa có trong list
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


@router.get('/api/export/audio')
def export_audio_zip():
    book = runtime.store.book()
    if not book:
        raise HTTPException(400, 'Chưa có truyện.')
    audio_files = [f for f in sorted(runtime.store.audio_dir.rglob('*.*')) if f.is_file() and f.suffix in ('.mp3', '.m4b', '.m4a', '.wav', '.opus')]
    if not audio_files:
        raise HTTPException(404, 'Chưa có file audio nào để xuất.')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for f in audio_files:
            z.write(f, arcname=str(f.relative_to(runtime.store.audio_dir)))
    title = (book.get('title') or 'novel').replace('"', '')
    return Response(buf.getvalue(), media_type='application/zip',
                    headers={'Content-Disposition': "attachment; filename=audio.zip; filename*=UTF-8''" + quote(title + '_audio.zip')})

