"""Shared runtime flags. Private tokens must never be stored here."""
import os


def env_enabled(key: str, default: bool = False) -> bool:
    value = os.getenv(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def tunnel_allowed() -> bool:
    return (
        os.getenv("ALLOWED_HOSTS", "").strip() == "*"
        or env_enabled("ALLOW_TUNNEL")
        or env_enabled("COLAB_GPU")
    )
