"""Remote API configuration accessor (delegates to config_manager)."""

from __future__ import annotations

from ..config import config_manager

DEFAULT_REMOTE_API_CONFIG = config_manager.DEFAULT_REMOTE_API_CONFIG
REMOTE_API_HEALTH_FILE = config_manager.REMOTE_API_HEALTH_FILE


def get_remote_api_config() -> dict:
    """Return merged remote_api config (defaults + user overlay)."""
    return config_manager.get_remote_api_config()
