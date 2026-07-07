import xml.etree.ElementTree as ET
from pathlib import Path

from dobot_move.windows_service.service_config import (
    RUNTIME_SERVICE_ID,
    WATCHDOG_SERVICE_ID,
    WINSW_X64_SHA256,
    build_runtime_service_xml,
    build_watchdog_service_xml,
    verify_winsw_binary,
)


def _root(xml_text):
    return ET.fromstring(xml_text)


def test_runtime_winsw_xml_is_service_safe():
    root = _root(
        build_runtime_service_xml(
            r"C:\DobotRuntime",
            r"C:\DobotRuntime\.venv\Scripts\python.exe",
            r"C:\DobotRuntime\runtime_ipc.token",
        )
    )

    assert root.findtext("id") == RUNTIME_SERVICE_ID
    assert root.findtext("delayedAutoStart") == "true"
    assert root.findtext("stoptimeout") == "30 sec"
    assert root.findtext("preshutdownTimeout") == "3 min"
    assert root.findtext("workingdirectory").endswith("DobotRuntime")
    assert root.find("serviceaccount") is None
    assert "password" not in ET.tostring(root, encoding="unicode").lower()
    env = {node.attrib["name"]: node.attrib["value"] for node in root.findall("env")}
    assert env["DOBOT_SERVICE_MODE"] == "1"
    assert env["DOBOT_IPC_TOKEN_FILE"].endswith("runtime_ipc.token")


def test_watchdog_winsw_xml_uses_localsystem_and_service_backend():
    root = _root(
        build_watchdog_service_xml(
            r"C:\DobotRuntime",
            r"C:\DobotRuntime\.venv\Scripts\python.exe",
        )
    )

    assert root.findtext("id") == WATCHDOG_SERVICE_ID
    assert root.findtext("serviceaccount/username") == "LocalSystem"
    arguments = root.findtext("arguments")
    assert "--restart-mode service" in arguments
    assert f"--service-name {RUNTIME_SERVICE_ID}" in arguments


def test_vendored_winsw_binary_matches_pinned_hash():
    binary = (
        Path(__file__).resolve().parents[1]
        / "dobot_move"
        / "windows_service"
        / "vendor"
        / "WinSW-x64.exe"
    )
    assert len(WINSW_X64_SHA256) == 64
    assert verify_winsw_binary(binary)
