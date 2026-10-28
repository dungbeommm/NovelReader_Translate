"""Compatibility entrypoint for older imports."""
from server.app import create_app, lifespan, local_guard

__all__ = ["create_app", "lifespan", "local_guard"]
