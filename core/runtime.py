"""Shared application state. Routes access this module, not copied globals."""
from pathlib import Path
import logging
from fastapi import HTTPException
from storage.store import Store
from storage.files import parse_file
from core.job_manager import ManagedJob
from core.state_manager import JobLease
from paths import ROOT, data_dir

store = None
job = None
resources = None

def initialize():
    global store, job, resources
    directory = data_dir()
    directory.mkdir(parents=True, exist_ok=True)
    logs = directory / 'logs'
    logs.mkdir(parents=True, exist_ok=True)
    log_path = logs / 'app.log'
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    if not any(isinstance(h, logging.FileHandler) and Path(h.baseFilename) == log_path for h in logger.handlers):
        handler = logging.FileHandler(log_path, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s'))
        logger.addHandler(handler)
    from monitoring.resources import ResourceSampler
    if resources is not None:resources.close()
    resources=ResourceSampler([('Dữ liệu',directory),('Audio',Path(__import__('os').getenv('NOVEL_OUTPUT_AUDIO',ROOT/'output_audio'))),('Văn bản',Path(__import__('os').getenv('NOVEL_OUTPUT_TEXT',ROOT/'output_text')))])
    db_path = directory / 'novel.sqlite3'
    recover = not JobLease(directory / 'job.lock').held_by_another()
    store = Store(db_path, recover_incomplete=recover)
    job = ManagedJob(store)

def ensure_idle():
    if job.active:raise HTTPException(409,'Hãy dừng job dịch trước khi thực hiện thao tác này.')


def import_book(name,data):
    with job.lock:
        ensure_idle()
        try:
            chapters,encoding=parse_file(name,data)
            store.replace(name,encoding,chapters);job.status='ready';job.message=''
            job.target_chapter_ids = None
            job.scope_label = ''
        except Exception as exc:
            logging.exception('Import failed');raise HTTPException(400,f'Không nạp được tệp: {exc}')
    job.emit('book_loaded');return {'book':store.book(),'chapters':store.list()}


