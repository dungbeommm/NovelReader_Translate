"""Explicit CUDA convolution policy and runtime-fallback control for Piper."""
import os


def strict_cuda():
    return os.getenv('PIPER_DEVICE', 'auto').lower() == 'cuda' or os.getenv('PIPER_REQUIRE_CUDA') == '1'


def configure_cuda_session(session, device_id=0):
    # Equivalent 1D padding, but a different cuDNN engine selection problem.
    # [N,C,D,1] -> [N,C,1,D], avoiding the failing shape in the reported T4 log.
    options = {
        'device_id': str(int(device_id)),
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
    if hasattr(session, 'get_provider_options'):
        actual = session.get_provider_options().get('CUDAExecutionProvider', {}).get('device_id')
        if actual is None or int(actual) != int(device_id):
            raise RuntimeError(f'Piper không dùng đúng GPU {device_id}; ORT báo device_id={actual}')
    return session


def guard_cuda_session(voice):
    """Provider presence at load is not enough: enforce it for every inference."""
    if not strict_cuda():
        return
    session = getattr(voice, 'session', None)
    if session is None:
        raise RuntimeError('Không có Piper ONNX session để xác minh CUDA')
    session.disable_fallback()  # ORT otherwise retries EPFail entirely on CPU.
    if 'CUDAExecutionProvider' not in session.get_providers():
        raise RuntimeError('Piper session đã mất CUDA provider; dừng thay vì tạo audio trên CPU')
