"""Generate deterministic WinSW 2.12 service configuration."""

from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from pathlib import Path


RUNTIME_SERVICE_ID = "DobotRuntimeService"
WATCHDOG_SERVICE_ID = "DobotRuntimeWatchdog"
WINSW_VERSION = "2.12.0"
WINSW_X64_SHA256 = (
    "05b82d46ad331cc16bdc00de5c6332c1ef818df8ceefcd49c726553209b3a0da"
)


def _add_text(parent, name, value):
    node = ET.SubElement(parent, name)
    node.text = str(value)
    return node


def _add_environment(root, values):
    for name, value in values.items():
        ET.SubElement(root, "env", name=str(name), value=str(value))


def _serialize(root) -> str:
    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(
        root,
        encoding="unicode",
    )


def _base_service(
    service_id,
    display_name,
    description,
    python_exe,
    project_root,
    arguments,
    log_path,
):
    root = ET.Element("service")
    _add_text(root, "id", service_id)
    _add_text(root, "name", display_name)
    _add_text(root, "description", description)
    _add_text(root, "executable", Path(python_exe).resolve())
    _add_text(root, "arguments", arguments)
    _add_text(root, "workingdirectory", Path(project_root).resolve())
    _add_text(root, "startmode", "Automatic")
    _add_text(root, "delayedAutoStart", "true")
    _add_text(root, "hidewindow", "true")
    _add_text(root, "stoptimeout", "30 sec")
    _add_text(root, "stopparentprocessfirst", "true")
    _add_text(root, "preshutdown", "true")
    _add_text(root, "preshutdownTimeout", "3 min")
    _add_text(root, "logpath", Path(log_path).resolve())
    ET.SubElement(root, "log", mode="roll")
    return root


def build_runtime_service_xml(
    project_root,
    python_exe,
    token_path,
    *,
    service_id=RUNTIME_SERVICE_ID,
) -> str:
    project_root = Path(project_root).resolve()
    root = _base_service(
        service_id,
        "Dobot Runtime Service",
        "Owns Dobot, RealSense, Modbus and production flow execution.",
        python_exe,
        project_root,
        "-m dobot_move.runtime.runtime_agent --startup-delay 0",
        project_root / "logs" / "winsw-runtime",
    )
    _add_environment(
        root,
        {
            "DOBOT_SERVICE_MODE": "1",
            "DOBOT_SERVICE_NAME": service_id,
            "DOBOT_IPC_TOKEN_FILE": Path(token_path).resolve(),
            "PYTHONUNBUFFERED": "1",
        },
    )
    ET.SubElement(root, "onfailure", action="restart", delay="10 sec")
    ET.SubElement(root, "onfailure", action="none")
    _add_text(root, "resetfailure", "10 min")
    _add_text(root, "autoRefresh", "false")
    return _serialize(root)


def build_watchdog_service_xml(
    project_root,
    python_exe,
    *,
    runtime_service_id=RUNTIME_SERVICE_ID,
    service_id=WATCHDOG_SERVICE_ID,
) -> str:
    project_root = Path(project_root).resolve()
    arguments = (
        "-m dobot_move.runtime.runtime_watchdog "
        f"--restart-mode service --service-name {runtime_service_id}"
    )
    root = _base_service(
        service_id,
        "Dobot Runtime Watchdog",
        "Detects a stalled Runtime, stops motion and restarts its service.",
        python_exe,
        project_root,
        arguments,
        project_root / "logs" / "winsw-watchdog",
    )
    _add_text(root, "depend", runtime_service_id)
    _add_environment(
        root,
        {
            "DOBOT_SERVICE_MODE": "1",
            "DOBOT_SERVICE_NAME": service_id,
            "PYTHONUNBUFFERED": "1",
        },
    )
    account = ET.SubElement(root, "serviceaccount")
    _add_text(account, "username", "LocalSystem")
    ET.SubElement(root, "onfailure", action="restart", delay="30 sec")
    ET.SubElement(root, "onfailure", action="none")
    _add_text(root, "resetfailure", "10 min")
    _add_text(root, "autoRefresh", "false")
    return _serialize(root)


def verify_winsw_binary(path) -> bool:
    binary_path = Path(path)
    if not binary_path.is_file():
        return False
    digest = hashlib.sha256(binary_path.read_bytes()).hexdigest()
    return digest.lower() == WINSW_X64_SHA256
