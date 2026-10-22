"""Internal TTS service. No host ports; never expose this without authentication."""
import os
import subprocess
import tempfile
import threading
from functools import lru_cache
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask
from tts.pipeline.batch_tts import load_voice, synth_chapter

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
lock = threading.Lock()
from paths import voice_models
ROOT = Path(__file__).resolve().parent
VOICE_DIR = voice_models()
MODEL = Path(os.getenv("TTS_MODEL", str(VOICE_DIR / "ngochuyennew.onnx")))
CONFIG = Path(os.getenv("TTS_CONFIG", str(VOICE_DIR / "ngochuyennew.onnx.json")))

class Input(BaseModel):
    text: str = Field(min_length=1, max_length=250000)

@lru_cache(maxsize=1)
def voice():
    return load_voice(str(MODEL), str(CONFIG))

@app.get('/health')
def health():
    return {'ok': True, 'voice_present': MODEL.is_file()}

@app.post('/synthesize')
def synth(payload: Input):
    temp = tempfile.TemporaryDirectory()
    try:
        root = Path(temp.name)
        wav = root / 'audio.wav'
        mp3 = root / 'audio.mp3'
        with lock:
            synth_chapter(voice(), payload.text, str(wav), str(root), 1500, length_scale=1.0)
        subprocess.run(['ffmpeg','-v','error','-y','-i',str(wav),'-b:a','96k',str(mp3)],
                       check=True, timeout=1800)
        wav.unlink()
        return FileResponse(mp3, media_type='audio/mpeg', background=BackgroundTask(temp.cleanup))
    except BaseException:
        temp.cleanup()
        raise
