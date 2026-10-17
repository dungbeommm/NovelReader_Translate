"""One subprocess per book: isolated SQLite checkpoints and resumable MP3 files."""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from storage.files import parse_file, export_txt, export_epub
from storage.store import Store
from workflows.jobs import Job

def write_json(path, data):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    tmp.replace(path)

def progress(folder, stage, **kw):
    write_json(folder / 'progress.json', {'stage': stage, **kw})

def run(folder):
    request = json.loads((folder / 'request.json').read_text())
    output = folder / 'output'
    output.mkdir(exist_ok=True)
    store = Store(folder / 'book.sqlite3', text_dir=folder/'output_text', audio_dir=folder/'output_audio')
    if not store.book():
        chapters, enc = parse_file(request['input'], (folder / request['input']).read_bytes())
        if not chapters or len(chapters) > 10000 or sum(len(t)+len(b) for t,b in chapters) > 2000000:
            raise ValueError('Mỗi truyện tối đa 10.000 chương / 2 triệu ký tự. Hãy chia tập.')
        if any(len(t)+len(b) > 200000 for t,b in chapters):
            raise ValueError('Một chương quá 200.000 ký tự. Hãy chia nhỏ.')
        store.replace(request['input'], enc, chapters)
    if request['mode'] != 'audio':
        job = Job(store)
        config = {'engine': 'HachimiMT-60-QT', 'glossary': '', 'batch_size': 8,
                  'honorific_mode': 'safe', 'pronoun_harmonizer': True,
                  'beam_size': 2, 'chunk_mode': 'sentence', 'normalize_mode': 'auto', 'generate_audio': False, 'auto_group_audio': False}
        if any(c['status'] != 'done' for c in store.list()):
            job.start(config)
        while job.active:
            progress(folder, 'đang dịch', **job.summary())
            time.sleep(2)
        if job.status == 'error' or any(c['status'] != 'done' for c in store.list()):
            raise RuntimeError(job.message or 'Có chương dịch lỗi; dùng /retry để thử lại.')
        chapters = [store.get(c['id']) for c in store.list()]
        (output / 'ban_dich.txt').write_bytes(export_txt(store.book(), chapters))
        (output / 'ban_dich.epub').write_bytes(export_epub(store.book(), chapters))
    if request['mode'] != 'translate':
        rows = store.list()
        for i, row in enumerate(rows, 1):
            progress(folder, 'đang tạo audio', done=i-1, total=len(rows))
            marker = folder / f'audio_{i:05}.json'
            if marker.exists() and all((output / n).is_file() for n in json.loads(marker.read_text())):
                continue
            if shutil.disk_usage(folder).free < 1024**3:
                raise RuntimeError('Ổ đĩa còn dưới 1 GB. Dọn dữ liệu trước khi tiếp tục.')
            ch = store.get(row['id'])
            text = '\n\n'.join([ch['title'], *ch['source']]) if request['mode'] == 'audio' else '\n\n'.join([ch['translated_title'], *ch['translated']])
            response = requests.post(os.getenv('TTS_URL', 'http://tts:8010') + '/synthesize',
                                     json={'text': text}, timeout=(15, 7200), stream=True)
            response.raise_for_status()
            tmp = folder / 'chapter.mp3'
            size = 0
            with tmp.open('wb') as f:
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > 100 * 1024**2:
                        raise RuntimeError('Audio một chương quá 100 MB. Hãy chia chương.')
                    f.write(chunk)
            response.close()
            # Each ~10-minute part at 96 kbps is well below Telegram's upload limit.
            for old in output.glob(f'chuong_{i:05}_*.mp3'):
                old.unlink()
            subprocess.run(['ffmpeg','-v','error','-y','-i',str(tmp),'-c','copy',
                            '-f','segment','-segment_time','600','-reset_timestamps','1',
                            str(output / f'chuong_{i:05}_%03d.mp3')], check=True, timeout=300)
            parts = sorted(output.glob(f'chuong_{i:05}_*.mp3'))
            if not parts or any(p.stat().st_size > 48*1024**2 for p in parts):
                raise RuntimeError('Không thể chia audio theo giới hạn gửi Telegram.')
            write_json(marker, [p.name for p in parts])
            tmp.unlink(missing_ok=True)
    progress(folder, 'xử lý xong', done=len(store.list()), total=len(store.list()))

if __name__ == '__main__':
    try:
        run(Path(sys.argv[1]).resolve())
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
