import json
from pathlib import Path
import urllib.request

req = urllib.request.Request(
    'https://api.github.com/repos/dungbeommm/NovelReader_voices/contents/voices/low',
    headers={'User-Agent': 'Mozilla/5.0'}
)
items = json.loads(urllib.request.urlopen(req).read().decode('utf-8'))
voices = [it['name'] for it in items if it['name'] != 'low-ngochuyennew']
print(f"Total voices: {len(voices)}")

results = []
for v in voices:
    try:
        url = f'https://raw.githubusercontent.com/dungbeommm/NovelReader_voices/main/voices/low/{v}/voice_info.json'
        info = json.loads(urllib.request.urlopen(url, timeout=10).read().decode('utf-8-sig'))
        results.append({
            'folder': v,
            'id': info.get('original_id', v.replace('low-', '')),
            'name': info.get('displayName', v),
            'onnxUrl': info.get('onnxUrl'),
            'jsonUrl': info.get('jsonUrl'),
            'rawOnnx': f'https://raw.githubusercontent.com/dungbeommm/NovelReader_voices/main/voices/low/{v}/{info.get("original_id")}.onnx',
            'rawJson': f'https://raw.githubusercontent.com/dungbeommm/NovelReader_voices/main/voices/low/{v}/{info.get("original_id")}.onnx.json',
        })
        print(f"OK: {v} -> {info.get('displayName')} ({info.get('original_id')})")
    except Exception as e:
        print(f"ERR {v}: {e}")

with open(Path(__file__).resolve().parents[1] / 'models/voices/available_voices.json', 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print("Saved available_voices.json")
