"""Stable router registration; current URLs remain unchanged."""
from web.routes import audio, translation, system, progress, huggingface, checkpoints, books

ROUTERS = (audio, translation, system, progress, huggingface, checkpoints, books)
