"""Startup-safe CTranslate2 import helpers.

CTranslate2 imports optional converter/spec modules at package import time. Those
modules may try to import torch even when the app only needs CT2 inference. On
Windows, a broken or oversized CUDA torch install can block app startup before
Gradio has a chance to launch. This helper lets startup treat torch as absent for
that optional import path.
"""

from __future__ import annotations

import importlib
import importlib.abc
import sys
from contextlib import contextmanager
from types import ModuleType
from typing import Iterator


class _OptionalTorchBlocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname: str, path=None, target=None):
        del path, target
        if fullname == "torch" or fullname.startswith("torch."):
            raise ImportError("Blocked optional torch import during CTranslate2 startup.")
        return None


@contextmanager
def block_optional_torch_import() -> Iterator[None]:
    """Temporarily make torch look unavailable to optional imports."""
    if "torch" in sys.modules:
        yield
        return

    blocker = _OptionalTorchBlocker()
    sys.meta_path.insert(0, blocker)
    try:
        yield
    finally:
        try:
            sys.meta_path.remove(blocker)
        except ValueError:
            pass


def preload_cuda_libraries() -> None:
    """Preload NVIDIA CUDA runtime libraries (libcublas, libcudnn, etc.) if available.
    
    Prevents 'RuntimeError: Library libcublas.so.12 is not found or cannot be loaded'
    on Linux (Google Colab / Kaggle / Linux) by preloading libcublas.so.12 and libcublasLt.so.12
    with RTLD_GLOBAL before CTranslate2 requests them.
    """
    import os
    import sys
    import ctypes
    import site
    from pathlib import Path

    search_dirs: list[Path] = []

    try:
        import nvidia
        nvidia_root = Path(nvidia.__file__).resolve().parent
        for sub in ["cublas", "cudnn", "cuda_runtime", "cuda_nvrtc"]:
            lib_dir = nvidia_root / sub / "lib"
            if lib_dir.is_dir() and lib_dir not in search_dirs:
                search_dirs.append(lib_dir)
    except Exception:
        pass

    try:
        for site_pkg in site.getsitepackages():
            p = Path(site_pkg) / "nvidia"
            if p.is_dir():
                for sub in ["cublas", "cudnn", "cuda_runtime", "cuda_nvrtc"]:
                    lib_dir = p / sub / "lib"
                    if lib_dir.is_dir() and lib_dir not in search_dirs:
                        search_dirs.append(lib_dir)
    except Exception:
        pass

    try:
        import torch
        t_lib = Path(torch.__file__).resolve().parent / "lib"
        if t_lib.is_dir() and t_lib not in search_dirs:
            search_dirs.append(t_lib)
    except Exception:
        pass

    for p_str in ["/usr/local/cuda/lib64", "/usr/local/cuda-12/lib64", "/usr/lib/x86_64-linux-gnu"]:
        d = Path(p_str)
        if d.is_dir() and d not in search_dirs:
            search_dirs.append(d)

    if search_dirs:
        dir_strs = [str(d) for d in search_dirs]
        cur_ld = os.environ.get("LD_LIBRARY_PATH", "")
        new_ld = ":".join(dir_strs + ([cur_ld] if cur_ld else []))
        os.environ["LD_LIBRARY_PATH"] = new_ld

    if sys.platform.startswith("linux"):
        lib_candidates = [
            ["libcudart.so.12", "libcudart.so"],
            ["libcublasLt.so.12", "libcublasLt.so"],
            ["libcublas.so.12", "libcublas.so"],
            ["libcudnn.so.9", "libcudnn.so.8", "libcudnn.so"],
        ]
        mode = getattr(ctypes, "RTLD_GLOBAL", 0)
        for group in lib_candidates:
            loaded = False
            for lib_dir in search_dirs:
                if loaded:
                    break
                for name in group:
                    target = lib_dir / name
                    if target.is_file():
                        try:
                            ctypes.CDLL(str(target), mode=mode)
                            loaded = True
                            break
                        except Exception:
                            pass


def import_ctranslate2(*, block_torch: bool = True) -> ModuleType:
    """Import ctranslate2 without letting optional torch stall startup."""
    preload_cuda_libraries()

    existing = sys.modules.get("ctranslate2")
    if existing is not None:
        return existing

    if not block_torch:
        return importlib.import_module("ctranslate2")

    with block_optional_torch_import():
        return importlib.import_module("ctranslate2")
