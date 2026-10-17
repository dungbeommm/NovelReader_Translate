import json
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

VOICE_DIR = Path(__file__).resolve().parent.parent / 'models' / 'voices'
VOICE_DIR.mkdir(parents=True, exist_ok=True)

GITHUB_API = 'https://api.github.com/repos/dungbeommm/NovelReader_voices/contents/voices/low'
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

def download_file(url, out_path, min_size=1024, retries=3):
    if out_path.is_file() and out_path.stat().st_size >= min_size:
        return True, f"Da co: {out_path.name}"
    
    tmp_path = out_path.with_suffix('.tmp')
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as resp, open(tmp_path, 'wb') as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
            
            if tmp_path.stat().st_size < min_size:
                tmp_path.unlink(missing_ok=True)
                raise ValueError(f"File qua nho: {tmp_path.stat().st_size} bytes")
                
            tmp_path.replace(out_path)
            return True, f"Tai thanh cong: {out_path.name} ({out_path.stat().st_size // 1024} KB)"
        except Exception as e:
            tmp_path.unlink(missing_ok=True)
            if attempt == retries:
                return False, f"Loi tai {url}: {e}"
            time.sleep(1)
    return False, "That bai"

def process_voice(folder_name):
    # Lay voice_info.json
    info_url = f'https://raw.githubusercontent.com/dungbeommm/NovelReader_voices/main/voices/low/{folder_name}/voice_info.json'
    try:
        req = urllib.request.Request(info_url, headers=HEADERS)
        info_data = urllib.request.urlopen(req, timeout=10).read().decode('utf-8-sig')
        info = json.loads(info_data)
    except Exception as e:
        return {'folder': folder_name, 'status': 'error', 'error': f"Loi info: {e}"}

    vid = info.get('original_id', folder_name.replace('low-', ''))
    display_name = info.get('displayName', vid)
    
    onnx_file = VOICE_DIR / f"{vid}.onnx"
    json_file = VOICE_DIR / f"{vid}.onnx.json"
    meta_file = VOICE_DIR / f"{vid}.info.json"
    
    # Luu meta
    meta_file.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding='utf-8')
    
    # 1. Download json config
    json_urls = [
        info.get('jsonUrl'),
        f'https://raw.githubusercontent.com/dungbeommm/NovelReader_voices/main/voices/low/{folder_name}/{vid}.onnx.json'
    ]
    json_ok = False
    for ju in [u for u in json_urls if u]:
        ok, msg = download_file(ju, json_file, min_size=50)
        if ok:
            json_ok = True
            break
            
    # 2. Download onnx model (~60MB)
    onnx_urls = [
        info.get('onnxUrl'),
        f'https://raw.githubusercontent.com/dungbeommm/NovelReader_voices/main/voices/low/{folder_name}/{vid}.onnx'
    ]
    onnx_ok = False
    for ou in [u for u in onnx_urls if u]:
        ok, msg = download_file(ou, onnx_file, min_size=10 * 1024 * 1024)
        if ok:
            onnx_ok = True
            break
            
    status = 'done' if (onnx_ok and json_ok) else 'failed'
    return {
        'id': vid,
        'folder': folder_name,
        'name': display_name,
        'status': status,
        'onnx_file': str(onnx_file.name),
        'json_file': str(json_file.name),
        'size_mb': round(onnx_file.stat().st_size / (1024*1024), 1) if onnx_file.is_file() else 0
    }

def main():
    print("Dang ket noi GitHub de lay danh sach giong doc...")
    req = urllib.request.Request(GITHUB_API, headers=HEADERS)
    items = json.loads(urllib.request.urlopen(req, timeout=15).read().decode('utf-8'))
    
    # Loai tru ngochuyennew vi da co san
    folders = [it['name'] for it in items if it['name'] != 'low-ngochuyennew']
    print(f"Tim thay {len(folders)} giong can tai. Bat dau tai song song (3 luong)...")
    
    results = []
    # Them ngochuyennew vao danh sach manifest
    ngoc_huyen_onnx = VOICE_DIR / "ngochuyennew.onnx"
    results.append({
        'id': 'ngochuyennew',
        'name': 'Ngọc Huyền (Nữ) - Mặc định',
        'status': 'done' if ngoc_huyen_onnx.is_file() else 'missing',
        'onnx_file': 'ngochuyennew.onnx',
        'json_file': 'ngochuyennew.onnx.json',
        'size_mb': round(ngoc_huyen_onnx.stat().st_size / (1024*1024), 1) if ngoc_huyen_onnx.is_file() else 0
    })
    
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(process_voice, f): f for f in folders}
        for future in as_completed(futures):
            res = future.result()
            results.append(res)
            print(f"[{len(results)-1}/{len(folders)}] {res.get('name', res.get('id'))}: {res.get('status')} ({res.get('size_mb', 0)} MB)")
            
            # Luu manifest lien tuc
            manifest_file = VOICE_DIR / 'voices_manifest.json'
            manifest_file.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')

    print(f"\nHoan tat! Tong cong co {len(results)} giong doc da cap nhat trong manifest.")

if __name__ == '__main__':
    main()
