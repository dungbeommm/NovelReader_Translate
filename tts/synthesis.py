"""Shared Piper >=1.3 adapter for Web UI and the standalone TTS service."""
def synthesize_wav(voice, text, wav_file, length_scale=1.0, noise_scale=0.667, noise_w_scale=0.8):
    from piper.config import SynthesisConfig
    config = SynthesisConfig(length_scale=float(length_scale), noise_scale=float(noise_scale), noise_w_scale=float(noise_w_scale))
    voice.synthesize_wav(text, wav_file, syn_config=config)
