"""Explicit CUDA convolution policy and runtime-fallback control for Piper."""
import os


def strict_cuda():
    return os.getenv('PIPER_DEVICE', 'auto').lower() == 'cuda' or os.getenv('PIPER_REQUIRE_CUDA') == '1'


def configure_cuda_session(session):
    options = {
        'device_id': '0',
        'cudnn_conv_algo_search': os.getenv('PIPER_CUDNN_ALGO', 'DEFAULT'),
        'cudnn_conv1d_pad_to_nc1d': '1',
        'cudnn_conv_use_max_workspace': '1',
        'do_copy_in_default_stream': '1',
    }
    session.set_providers([('CUDAExecutionProvider', options), 'CPUExecutionProvider'])
    if strict_cuda():
        session.disable_fallback()
    if 'CUDAExecutionProvider' not in session.get_providers():
        raise RuntimeError('Piper CUDA provider không khởi tạo được sau cấu hình Conv1D')
    return session


def guard_cuda_session(voice):
    """Provider presence at load is not enough: enforce it for every inference."""
    if not strict_cuda():
        return
    session = getattr(voice, 'session', None)
    if session is None:
        raise RuntimeError('Không có Piper ONNX session để xác minh CUDA')
    session.disable_fallback()
    if 'CUDAExecutionProvider' not in session.get_providers():
        raise RuntimeError('Piper session đã mất CUDA provider; dừng thay vì tạo audio trên CPU')
