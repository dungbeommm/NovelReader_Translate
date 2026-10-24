from fastapi import APIRouter, HTTPException
import os
from translation.engines import list_available_models
from translation.hardware import detect_hardware_profile
from web import runtime
from web.schemas import Config, ModelDownloadInput

router = APIRouter()

@router.get('/api/models')
def models(backend: str = 'ct2'):
    return list_available_models(backend=backend)


@router.post('/api/models/download')
def download_model(payload: ModelDownloadInput):
    from translation.core.translator import ensure_model_files, MODELS, Backend
    if payload.model_id not in MODELS:
        raise HTTPException(404, f"Mô hình '{payload.model_id}' không tồn tại trong danh mục.")
    config = MODELS[payload.model_id]
    target_backend = Backend.TRANSFORMERS if payload.backend in ('transformers', 'pytorch', 'torch') else Backend.CT2
    backend_label = 'PyTorch' if target_backend == Backend.TRANSFORMERS else 'CTranslate2'
    try:
        path = ensure_model_files(config, target_backend)
        return {
            'status': 'success',
            'message': f"Đã tải thành công model {config.label} cho {backend_label}!",
            'model_id': payload.model_id,
            'backend': target_backend.value,
            'path': str(path),
        }
    except Exception as exc:
        raise HTTPException(500, f"Lỗi khi tải model {payload.model_id}: {exc}")


@router.get('/api/hardware')
def hardware():
    profile = detect_hardware_profile()
    from translation.core.hardware import PHYSICAL_NVIDIA_GPU, PHYSICAL_GPU_NAME, PHYSICAL_GPU_VRAM_GB

    gpu_name = profile.gpu_name if profile else None
    has_cuda = profile.has_cuda if profile else False
    vram_gb = profile.vram_gb if profile else None

    try:
        import torch
        if torch.cuda.is_available():
            has_cuda = True
            if not gpu_name:
                gpu_name = torch.cuda.get_device_name(0)
            if not vram_gb:
                vram_gb = round(torch.cuda.get_device_properties(0).total_memory / (1024**3), 1)
    except Exception:
        pass

    has_discrete_gpu = bool(PHYSICAL_NVIDIA_GPU or has_cuda)
    final_gpu_name = gpu_name or PHYSICAL_GPU_NAME or ('NVIDIA GPU' if has_discrete_gpu else None)

    if profile:
        return {
            'cpu_count': profile.cpu_logical,
            'intra_threads': profile.ct2_threads,
            'is_gpu': has_cuda,
            'has_discrete_gpu': has_discrete_gpu,
            'device': final_gpu_name or 'cpu',
            'gpu_name': final_gpu_name,
            'vram_gb': vram_gb or PHYSICAL_GPU_VRAM_GB or 0,
            'batch_size': profile.batch_size,
            'summary': profile.summary,
        }
    return {
        'cpu_count': os.cpu_count() or 2,
        'intra_threads': max(1, min(8, (os.cpu_count() or 2) - 1)),
        'is_gpu': has_cuda,
        'has_discrete_gpu': has_discrete_gpu,
        'device': final_gpu_name or 'cpu',
        'gpu_name': final_gpu_name,
        'vram_gb': vram_gb or PHYSICAL_GPU_VRAM_GB or 0,
        'batch_size': 8,
        'summary': f'CPU {os.cpu_count() or 2} luồng',
    }


@router.post('/api/translate/start')
async def start(config:Config):
    try:
        runtime.job.start(config.model_dump(exclude={'reset'}),config.reset)
    except ValueError as exc:raise HTTPException(409,str(exc))
    return runtime.job.summary()


@router.post('/api/translate/{action}')
async def control(action:str):
    if action not in ('pause','resume','stop'):raise HTTPException(404,'Lệnh không hợp lệ.')
    try:getattr(runtime.job,action)()
    except ValueError as exc:raise HTTPException(409,str(exc))
    return runtime.job.summary()

