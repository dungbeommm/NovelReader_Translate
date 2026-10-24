from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import socket
import sys
from pathlib import Path


def _package_version(name: str) -> str | None:
    try:
        from importlib.metadata import version
        return version(name)
    except Exception:
        return None


def inspect_environment(root: Path | None = None) -> dict:
    root = Path(root or Path.cwd())
    total_ram = available_ram = None
    try:
        import psutil
        memory = psutil.virtual_memory()
        total_ram, available_ram = memory.total, memory.available
    except Exception:
        pass
    gpu = {"available": False, "name": None, "vram_bytes": None, "cuda": None}
    try:
        import torch
        gpu["available"] = bool(torch.cuda.is_available())
        gpu["cuda"] = getattr(torch.version, "cuda", None)
        if gpu["available"]:
            gpu["name"] = torch.cuda.get_device_name(0)
            gpu["vram_bytes"] = torch.cuda.get_device_properties(0).total_memory
    except Exception:
        pass
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "architecture": platform.machine(),
        "cpu_count": os.cpu_count() or 1,
        "ram_bytes": total_ram,
        "available_ram_bytes": available_ram,
        "gpu": gpu,
        "packages": {name: _package_version(name) for name in ("torch", "ctranslate2", "onnxruntime", "piper-tts", "huggingface-hub")},
        "executables": {name: shutil.which(name) for name in ("ffmpeg", "espeak-ng", "cloudflared")},
        "disk_free_bytes": shutil.disk_usage(root).free,
        "network": _network_status(),
    }


def _network_status() -> bool:
    try:
        with socket.create_connection(("huggingface.co", 443), timeout=2):
            return True
    except OSError:
        return False

