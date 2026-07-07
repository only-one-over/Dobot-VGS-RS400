"""Windows Service deployment helpers for the Dobot Runtime."""

from .service_config import (
    RUNTIME_SERVICE_ID,
    WATCHDOG_SERVICE_ID,
    build_runtime_service_xml,
    build_watchdog_service_xml,
    verify_winsw_binary,
)

__all__ = [
    "RUNTIME_SERVICE_ID",
    "WATCHDOG_SERVICE_ID",
    "build_runtime_service_xml",
    "build_watchdog_service_xml",
    "verify_winsw_binary",
]
