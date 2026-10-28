"""Idempotent logging setup for one runtime."""
import logging
from pathlib import Path


def configure_logging(path):
    log_path = Path(path).resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    if not any(
        isinstance(h, logging.FileHandler) and Path(h.baseFilename).resolve() == log_path
        for h in logger.handlers
    ):
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
    return logger
