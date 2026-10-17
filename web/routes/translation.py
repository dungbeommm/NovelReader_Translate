from fastapi import APIRouter, HTTPException
from translation.engines import list_available_models
from translation.hardware import detect_hardware_profile
from web import runtime
from web.schemas import Config

router = APIRouter()

@router.get('/api/models')
def models():
    return list_available_models()


@router.get('/api/hardware')
def hardware():
    profile = detect_hardware_profile()
    if profile:
        return {
            'cpu_count': profile.cpu_logical,
            'intra_threads': profile.ct2_threads,
            'is_gpu': profile.has_cuda,
            'device': profile.gpu_name or 'cpu',
            'vram_gb': profile.vram_gb or 0,
            'batch_size': profile.batch_size,
            'summary': profile.summary,
        }
    return {
        'cpu_count': os.cpu_count() or 2,
        'intra_threads': max(1, min(8, (os.cpu_count() or 2) - 1)),
        'is_gpu': False,
        'device': 'cpu',
        'vram_gb': 0,
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

