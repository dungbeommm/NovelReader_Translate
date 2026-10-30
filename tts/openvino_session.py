"""Native OpenVINO session adapter for Piper's session.run interface."""
import threading


class OpenVINOSession:
    def __init__(self, model_path, device='GPU'):
        try:
            import openvino as ov
        except ImportError as exc:
            raise RuntimeError('Piper OpenVINO cần cài openvino trong môi trường đang chạy.') from exc
        if not device.startswith('GPU'):
            raise ValueError('Piper OpenVINO yêu cầu thiết bị GPU hoặc GPU.<index>.')
        self.core = ov.Core()
        self.model_path = str(model_path)
        self.compiled = self.core.compile_model(str(model_path), device)
        self.devices = list(self.compiled.get_property('EXECUTION_DEVICES'))
        if not self.devices or any(not d.startswith('GPU') for d in self.devices):
            raise RuntimeError(f'Piper OpenVINO không chạy GPU: {self.devices}')
        self._lock = threading.Lock()
        self._cpu_session = None
        self.cpu_fallback_count = 0

    def run(self, output_names, inputs):
        # CompiledModel.__call__ shares an infer request; serialize access and
        # copy results before the next call can reuse its output buffers.
        with self._lock:
            try:
                result = self.compiled(inputs)
            except RuntimeError as exc:
                # OpenVINO's GPU plugin rejects a rare zero-sized internal
                # reshape in this Piper ONNX graph. ORT CPU handles that shape;
                # route only this known graph error to CPU so the chapter can
                # finish. Keep all normal phoneme inference on the Intel GPU.
                message = str(exc)
                if 'dimension is out of range' not in message or 'Reshape' not in message:
                    raise
                if self._cpu_session is None:
                    try:
                        import onnxruntime as ort
                    except ImportError as import_exc:
                        raise RuntimeError('Piper gặp reshape rỗng trên Intel GPU và cần ONNX Runtime CPU cho đoạn này.') from import_exc
                    self._cpu_session = ort.InferenceSession(self.model_path, providers=['CPUExecutionProvider'])
                self.cpu_fallback_count += 1
                return self._cpu_session.run(output_names, inputs)
            ports = self.compiled.outputs if output_names is None else [self.compiled.output(n) for n in output_names]
            return [result[port].copy() for port in ports]

    def get_providers(self):
        # Diagnostic tags for our native adapter, not ONNX Runtime EP names.
        providers = [f'OpenVINO:{device}' for device in self.devices]
        if self.cpu_fallback_count:
            providers.append('CPU fallback for empty Reshape')
        return providers
