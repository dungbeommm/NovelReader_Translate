"""Full voice catalog/config JSON or all ONNX models. Safe to rerun after failure."""
import argparse
import json
import os
import re
import sys
import tempfile
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from paths import voice_models
VOICE_DIR = voice_models()
GITHUB_API = 'https://api.github.com/repos/dungbeommm/NovelReader_voices/contents/voices/low'
HEADERS = {'User-Agent': 'NovelReader/4.4'}


def valid_config(path):
    try:
        data = json.loads(path.read_text('utf-8-sig'))
        return isinstance(data, dict) and isinstance(data.get('audio'), dict) and isinstance(data.get('phoneme_id_map'), dict)
    except (OSError, ValueError):
        return False


def download_file(url, out_path, min_size=1024, retries=3):
    out_path = Path(out_path)
    is_config = out_path.name.endswith('.onnx.json')
    if out_path.is_file() and out_path.stat().st_size >= min_size and (not is_config or valid_config(out_path)):
        return True, f'Đã có: {out_path.name}'
    out_path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(retries):
        fd, name = tempfile.mkstemp(dir=out_path.parent, prefix='.voice-')
        temp = Path(name)
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with os.fdopen(fd, 'wb') as out, urllib.request.urlopen(req, timeout=90) as response:
                while chunk := response.read(1024 * 1024):
                    out.write(chunk)
            if temp.stat().st_size < min_size or (is_config and not valid_config(temp)):
                raise ValueError('File thiếu hoặc JSON không phải cấu hình Piper.')
            os.replace(temp, out_path)
            return True, f'Đã tải: {out_path.name}'
        except Exception as exc:
            error = str(exc)
            time.sleep(min(attempt + 1, 3))
        finally:
            temp.unlink(missing_ok=True)
    return False, f'Lỗi {out_path.name}: {error}'


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.manifest-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            json.dump(data, out, ensure_ascii=False, indent=2)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def load_catalog(refresh=True):
    bundled = json.loads((ROOT / 'tts/voices_catalog.json').read_text('utf-8'))
    by_id = {v['id']: dict(v) for v in bundled}
    if refresh:
        try:
            req = urllib.request.Request(GITHUB_API, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=20) as response:
                folders = json.load(response)
            for folder in folders:
                if folder.get('type') != 'dir':
                    continue
                vid = folder['name'].removeprefix('low-')
                if re.fullmatch(r'[A-Za-z0-9_-]{1,100}', vid):
                    by_id.setdefault(vid, {'id': vid, 'name': vid, 'folder': folder['name']})
        except Exception as exc:
            print(f'Không tải được danh mục GitHub; dùng {len(by_id)} giọng tích hợp: {exc}')
    return list(by_id.values())


def process_voice(item, config_only=False):
    item = dict(item)
    vid = item['id']
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', vid):
        raise ValueError('ID giọng không hợp lệ')
    folder = item.get('folder', f'low-{vid}')
    base = f'https://raw.githubusercontent.com/dungbeommm/NovelReader_voices/main/voices/low/{folder}'
    # metadata improves display names and includes canonical CDN URLs.
    try:
        with urllib.request.urlopen(urllib.request.Request(base + '/voice_info.json', headers=HEADERS), timeout=15) as response:
            meta = json.loads(response.read().decode('utf-8-sig'))
        item['name'] = meta.get('displayName') or item.get('name', vid)
        for field in ('onnxUrl', 'jsonUrl', 'gender'):
            if meta.get(field):
                item[field] = meta[field]
        write_json(VOICE_DIR / f'{vid}.info.json', meta)
    except Exception:
        pass
    onnx, cfg = VOICE_DIR / f'{vid}.onnx', VOICE_DIR / f'{vid}.onnx.json'
    def fetch(suffix, target, min_size):
        urls = [item.get('jsonUrl' if suffix.endswith('json') else 'onnxUrl'),
                f'https://cdn.ainovelreader.com/tts_model/{vid}{suffix}', f'{base}/{vid}{suffix}']
        for url in dict.fromkeys(u for u in urls if u):
            ok, message = download_file(url, target, min_size, retries=2)
            if ok:
                return True
        print(message)
        return False
    json_ok = fetch('.onnx.json', cfg, 50)
    model_ok = onnx.is_file() and onnx.stat().st_size >= 10 * 1024**2
    if not config_only:
        model_ok = fetch('.onnx', onnx, 10 * 1024**2)
    item.update(onnx_file=onnx.name, json_file=cfg.name, config_downloaded=json_ok,
                downloaded=bool(model_ok and json_ok),
                status='done' if json_ok and (config_only or model_ok) else 'failed',
                size_mb=round(onnx.stat().st_size / 1024**2, 1) if model_ok else 0)
    return item


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--catalog-only', action='store_true', help='Tải đầy đủ JSON/config, không tải ONNX.')
    mode.add_argument('--all', action='store_true', help='Tải tất cả JSON và model ONNX.')
    mode.add_argument('--default-only', action='store_true')
    mode.add_argument('--voice', help='Tải một giọng theo ID.')
    parser.add_argument('--offline-catalog', action='store_true', help='Không truy vấn danh mục GitHub; vẫn tải file.')
    parser.add_argument('--workers', type=int, choices=range(1, 9), default=3)
    args = parser.parse_args(argv)
    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    catalog = load_catalog(not args.offline_catalog)
    selected_id = 'ngochuyennew' if args.default_only else args.voice
    if selected_id and selected_id not in {v['id'] for v in catalog}:
        parser.error('Giọng không có trong danh mục.')
    # Preserve the entire catalog, including not-yet-installed voices.
    by_id = {v['id']: v for v in catalog}
    tasks = [v for v in catalog if not selected_id or v['id'] == selected_id]
    failed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(process_voice, v, args.catalog_only) for v in tasks]
        for future in as_completed(futures):
            result = future.result()
            by_id[result['id']] = result
            failed += result['status'] == 'failed'
            print(f"{result['id']}: {result['status']}", flush=True)
            manifest = sorted(by_id.values(), key=lambda v: v['id'])
            write_json(VOICE_DIR / 'voices_manifest.json', manifest)
            write_json(VOICE_DIR / 'available_voices.json', manifest)
    print(f'Danh mục đầy đủ: {len(by_id)} giọng. Lỗi tải: {failed}.')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
