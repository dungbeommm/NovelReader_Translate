"""Explicit two-GPU replicas and deterministic, bounded work distribution."""
import logging
import math
import os
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger(__name__)


def enabled():
    return os.getenv('NOVEL_BALANCE_GPUS', '0').lower() in {'1', 'true', 'yes'}


def choose_two_devices(count):
    return list(range(min(2, max(0, int(count)))))


def selected_devices(count, env_name='HACHIMIMT_GPU_INDICES'):
    raw = os.getenv(env_name, '').strip()
    indices = [int(x.strip()) for x in raw.split(',')] if raw else choose_two_devices(count)
    indices = list(dict.fromkeys(indices))
    if len(indices) > 2 or any(i < 0 or i >= count for i in indices):
        raise ValueError(f'{env_name}={raw!r}: cần 1–2 GPU hợp lệ; khả dụng={count}')
    return indices


def balanced_indices(weights, workers):
    """Equal item counts (difference <= 1), then greedily balance token/char cost."""
    if workers < 1:
        raise ValueError('workers must be positive')
    groups = [[] for _ in range(workers)]
    loads = [0] * workers
    capacities = [len(weights)//workers + (i < len(weights)%workers) for i in range(workers)]
    for index in sorted(range(len(weights)), key=lambda i: (-max(1, weights[i]), i)):
        choices = [i for i in range(workers) if len(groups[i]) < capacities[i]]
        target = min(choices, key=lambda i: (loads[i], len(groups[i]), i))
        groups[target].append(index)
        loads[target] += max(1, weights[index])
    return [sorted(group) for group in groups]


class BalancedTranslator:
    """One CT2 model per device, explicit concurrent calls, original output order."""
    device = 'cuda'

    def __init__(self, model_path, factory, **kwargs):
        indices = kwargs.pop('device_index')
        self.device_index = list(indices)
        kwargs.pop('device', None)
        kwargs['inter_threads'] = 1
        self.models = [factory(model_path, device='cuda', device_index=i, **kwargs)
                       for i in self.device_index]
        log.info('BALANCE CT2: GPUs=%s, one replica/device', self.device_index)

    def translate_batch(self, source, **kwargs):
        if not source:
            return []
        weights = [len(tokens) for tokens in source]
        groups = balanced_indices(weights, len(self.models))
        outputs = [None] * len(source)

        def run(worker):
            indices = groups[worker]
            if not indices:
                return []
            options = dict(kwargs)
            if options.get('asynchronous'):
                raise ValueError('BalancedTranslator expects synchronous results')
            # Original limit is a total budget, not multiplied by device count.
            if options.get('max_batch_size', 0):
                options['max_batch_size'] = max(1, math.ceil(options['max_batch_size']/len(self.models)))
            results = self.models[worker].translate_batch([source[i] for i in indices], **options)
            if len(results) != len(indices):
                raise RuntimeError('CT2 trả thiếu kết quả; không xuất bản dịch không đầy đủ')
            return list(zip(indices, results))

        with ThreadPoolExecutor(max_workers=len(self.models), thread_name_prefix='ct2-gpu') as pool:
            for result in pool.map(run, range(len(self.models))):
                for index, value in result:
                    outputs[index] = value
        log.info('BALANCE CT2: %s', {gpu: {'segments': len(group), 'tokens': sum(weights[i] for i in group)}
                 for gpu, group in zip(self.device_index, groups)})
        return outputs


def gpu_status():
    try:
        from translation.ct2_safe_import import import_ctranslate2
        count = import_ctranslate2().get_cuda_device_count()
        indices = selected_devices(count) if enabled() and count else []
        return {'cuda_device_count': count, 'balanced_gpu_indices': indices,
                'two_gpu_balance': len(indices) == 2}
    except Exception as exc:
        return {'cuda_device_count': 0, 'balanced_gpu_indices': [],
                'two_gpu_balance': False, 'gpu_probe_error': str(exc)}
