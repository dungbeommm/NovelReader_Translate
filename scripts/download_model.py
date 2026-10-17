import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.engines import LocalEngine
engine=LocalEngine();engine.load()
print('Model cached. Smoke:',engine.translate(['你好。'],{}))
