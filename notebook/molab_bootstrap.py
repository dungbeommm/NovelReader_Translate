"""Repair source assets lost when MoLab persists Python sources only."""
from __future__ import annotations
import io
import os
from pathlib import Path, PurePosixPath
import tempfile
import shutil
import subprocess
import urllib.request
import zipfile

SOURCE_DIRS = {'audio', 'core', 'monitoring', 'notebook', 'scripts', 'server',
               'storage', 'translation', 'tts', 'web', 'workflows'}
SOURCE_ROOT = {'requirements.txt', 'requirements-vieneu.txt', 'main.py', 'paths.py'}
CRITICAL = ('main.py', 'paths.py', 'requirements.txt', 'notebook/molab_native.py')


def restore_missing(root, source_ref):
    root = Path(root).resolve()
    if all((root / name).is_file() for name in CRITICAL):
        return []
    url = 'https://github.com/dungbeommm/NovelReader_Translate/archive/' + source_ref + '.zip'
    with urllib.request.urlopen(url, timeout=120) as response:
        payload = response.read(64 * 1024**2 + 1)
    if len(payload) > 64 * 1024**2:
        raise ValueError('Gói mã nguồn vượt giới hạn 64 MiB.')
    restored = []
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        if sum(item.file_size for item in archive.infolist()) > 128 * 1024**2:
            raise ValueError('Gói mã nguồn giải nén vượt giới hạn 128 MiB.')
        for item in archive.infolist():
            parts = PurePosixPath(item.filename).parts[1:]
            if not parts or item.is_dir():
                continue
            if '..' in parts or '\\' in item.filename or PurePosixPath(item.filename).is_absolute():
                raise ValueError('Đường dẫn ZIP không hợp lệ.')
            if not (parts[0] in SOURCE_DIRS or (len(parts) == 1 and parts[0] in SOURCE_ROOT)):
                continue
            destination = root.joinpath(*parts)
            if not destination.resolve().is_relative_to(root):
                raise ValueError('Đường dẫn mã nguồn nằm ngoài thư mục dự án.')
            if destination.exists():
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            # Fully write before exposing the file; never replace user modifications.
            fd, temporary = tempfile.mkstemp(dir=destination.parent, prefix='.source-')
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(archive.read(item))
                try:
                    os.link(temporary, destination)
                    restored.append('/'.join(parts))
                except FileExistsError:
                    pass
            finally:
                Path(temporary).unlink(missing_ok=True)
    missing = [name for name in CRITICAL if not (root / name).is_file()]
    if missing:
        raise RuntimeError('Mã nguồn chưa đủ: ' + ', '.join(missing))
    return restored


def prepare_environment(root):
    root = Path(root).resolve()
    for key, relative in {'NOVEL_DATA': 'data', 'NOVEL_MODELS': 'models/translation',
                          'TTS_VOICE_DIR': 'models/voices', 'NOVEL_OUTPUT_TEXT': 'output_text',
                          'NOVEL_OUTPUT_AUDIO': 'output_audio', 'VIENEU_MODEL_DIR': 'models/vieneu'}.items():
        path = root / relative
        path.mkdir(parents=True, exist_ok=True)
        os.environ[key] = str(path)
    os.environ['ALLOW_TUNNEL'] = '0'
    os.environ['NOVEL_RUNTIME_KIND'] = 'molab-native'
    os.environ.setdefault('OMP_NUM_THREADS', '2')
    os.environ.setdefault('AUDIO_WORKERS', '1')


def ensure_tools():
    absent = [name for name in ('ffmpeg', 'espeak-ng') if not shutil.which(name)]
    if not absent:
        return
    if not (hasattr(os, 'geteuid') and os.geteuid() == 0 and shutil.which('apt-get')):
        raise RuntimeError('Thiếu công cụ hệ thống: ' + ', '.join(absent))
    print('Cài công cụ audio: ' + ', '.join(absent), flush=True)
    subprocess.run(['apt-get', 'update', '-qq'], check=True, timeout=150)
    subprocess.run(['apt-get', 'install', '-y', '-qq', *absent], check=True, timeout=300)
