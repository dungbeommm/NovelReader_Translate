"""Central paths, independent of the current working directory."""
import os
from pathlib import Path
ROOT = Path(__file__).resolve().parent

def data_dir():
    return Path(os.getenv('NOVEL_DATA', str(ROOT / 'data'))).expanduser().resolve()

def translation_models():
    custom = os.getenv('NOVEL_MODELS') or os.getenv('HACHIMIMT_MODELS_DIR')
    if custom:
        return Path(custom).expanduser().resolve()
    default_dir = (ROOT / 'models/translation').resolve()
    sibling_dir = (ROOT.parent.parent / 'NovelReader_Translate' / 'models').resolve()
    if sibling_dir.is_dir() and (not default_dir.exists() or not any(default_dir.iterdir())):
        return sibling_dir
    return default_dir

def voice_models():
    return Path(os.getenv('TTS_VOICE_DIR', str(ROOT / 'models/voices'))).expanduser().resolve()
