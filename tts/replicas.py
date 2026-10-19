"""Piper replicas, one lock per CUDA session (no global inference lock)."""
import threading


class VoiceReplicas:
    def __init__(self, voices, devices):
        self.replicas = list(voices)
        self.device_indices = list(devices)
        self.locks = [threading.Lock() for _ in voices]
        self.session = voices[0].session  # compatibility with existing status/checks

    def synthesize_wav(self, text, wav_file, **kwargs):
        # Legacy direct calls remain single-WAV compatible.
        with self.locks[0]:
            return self.replicas[0].synthesize_wav(text, wav_file, **kwargs)
