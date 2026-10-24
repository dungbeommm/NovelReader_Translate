from pathlib import Path
import json
from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import Response
from storage.files import export_txt, export_epub, MAX_FILE
from web import runtime
from web.schemas import PathInput, ChapterIdsInput

router = APIRouter()

@router.post('/api/upload')
def upload(file:UploadFile):
    runtime.ensure_idle();data=file.file.read(MAX_FILE+1)
    if len(data)>MAX_FILE:raise HTTPException(413,'File tối đa 50 MB.')
    return runtime.import_book(Path((file.filename or 'novel.txt').replace('\\','/')).name,data)


@router.post('/api/load-path')
def load_path(payload:PathInput):
    runtime.ensure_idle();p=Path(payload.path).expanduser()
    if p.suffix.lower() not in ('.txt','.epub'):raise HTTPException(400,'Chỉ hỗ trợ .txt/.epub.')
    try:
        with p.open('rb') as f:data=f.read(MAX_FILE+1)
    except OSError as exc:raise HTTPException(400,f'Không đọc được đường dẫn trên máy chạy backend: {exc}')
    return runtime.import_book(p.name,data)


@router.get('/api/state')
def state():return {'book':runtime.store.book(),'progress':runtime.job.summary()}


@router.get('/api/chapters')
def chapters():return runtime.store.list()


@router.get('/api/chapters/{id}')
def chapter(id:int):
    value=runtime.store.get(id)
    if not value:raise HTTPException(404,'Không tìm thấy chương.')
    return value


@router.post('/api/book/delete')
def delete_book():
    runtime.ensure_idle()
    with runtime.job.lock:
        runtime.store.clear()
        runtime.job.status='ready';runtime.job.message=''
        runtime.job.target_chapter_ids = None
        runtime.job.scope_label = ''
    runtime.job.emit('book_deleted')
    return {'ok':True,'book':None,'chapters':[]}


@router.post('/api/chapters/reset')
def reset_chapters_endpoint(payload:ChapterIdsInput):
    runtime.ensure_idle()
    if not payload.ids:raise HTTPException(400,'Danh sách chương rỗng.')
    with runtime.job.lock:
        runtime.store.reset_chapters(payload.ids)
    runtime.job.emit('chapters_updated')
    return {'ok':True,'reset_count':len(payload.ids)}


@router.post('/api/chapters/delete')
def delete_chapters_endpoint(payload:ChapterIdsInput):
    runtime.ensure_idle()
    if not payload.ids:raise HTTPException(400,'Danh sách chương rỗng.')
    with runtime.job.lock:
        runtime.store.delete_chapters(payload.ids)
    runtime.job.emit('chapters_updated')
    return {'ok':True,'deleted_count':len(payload.ids),'chapters':runtime.store.list()}


@router.post('/api/chapters/{id}/reset')
def reset_single_chapter(id:int):
    runtime.ensure_idle()
    with runtime.job.lock:
        runtime.store.reset_chapters([id])
    runtime.job.emit('chapters_updated')
    return {'ok':True,'reset_id':id}


@router.post('/api/chapters/{id}/delete')
def delete_single_chapter(id:int):
    runtime.ensure_idle()
    with runtime.job.lock:
        runtime.store.delete_chapters([id])
    runtime.job.emit('chapters_updated')
    return {'ok':True,'deleted_id':id}


@router.post('/api/chapters/purge-empty')
def purge_empty_chapters_endpoint():
    runtime.ensure_idle()
    with runtime.job.lock:
        count = runtime.store.purge_empty_chapters()
    runtime.job.emit('chapters_updated')
    return {'ok': True, 'purged_count': count, 'message': f'Đã xóa {count} chương rỗng.', 'chapters': runtime.store.list()}


@router.get('/api/export/{format}')
def export(format:str):
    if format not in ('txt','epub'):raise HTTPException(404,'Định dạng không hợp lệ.')
    with runtime.store.connect() as c:
        # Atomic snapshot: do not combine chapter states from different batches.
        c.execute('BEGIN')
        b=c.execute('SELECT * FROM book LIMIT 1').fetchone()
        rows=c.execute('SELECT * FROM chapter ORDER BY position').fetchall()
    if not b:raise HTTPException(400,'Chưa có truyện.')
    cs=[]
    for r in rows:
        d=dict(r);d['translated']=json.loads(d['translated']);cs.append(d)
    data=export_txt(dict(b),cs) if format=='txt' else export_epub(dict(b),cs)
    return Response(data,media_type='text/plain; charset=utf-8' if format=='txt' else 'application/epub+zip',
                    headers={'Content-Disposition':f'attachment; filename="translated.{format}"'})


from web.schemas import BookTitleInput

@router.post('/api/book/title')
def set_book_title(payload: BookTitleInput):
    runtime.ensure_idle()
    with runtime.job.lock:
        try:
            book = runtime.store.set_title(payload.title)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
    runtime.job.emit('book_updated')
    return {'ok': True, 'book': book}
