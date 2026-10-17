"""Run from the project root: python scripts/probe_space.py [--translate]."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gradio_client import Client
c=Client('ngocdang83/HachimiMT-demo',httpx_kwargs={'timeout':30})
api=c.view_api(return_format='dict',print_info=False)
p=Path('docs/space-api.json');p.write_text(json.dumps(api,ensure_ascii=False,indent=2),encoding='utf-8')
print('Saved',p)
if '--translate' in sys.argv:
    from app.engines import SpaceEngine
    engine=SpaceEngine();engine.load()
    print(engine.translate(['林羽站在山门前。'],{'林羽':'Lâm Vũ'}))
