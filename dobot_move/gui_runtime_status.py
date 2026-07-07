"""Read-only Runtime health snapshots for the engineering GUI."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RUNTIME_HEALTH_PATH = PROJECT_ROOT / "runtime_health.json"


@dataclass(frozen=True)
class RuntimeHealthSnapshot:
    online: bool = False
    timestamp: float = 0.0
    age_s: float | None = None
    runtime_state: str = "OFFLINE"
    robot_connected: bool = False
    robot_enabled: bool = False
    d405_connected: bool = False
    d435i_connected: bool = False
    modbus_running: bool = False
    modbus_port: int = 502
    flow_running: bool = False
    current_flow: str | None = None
    current_step: str | None = None
    last_error: str = ""
    read_error: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


class RuntimeHealthReader:
    """Load Runtime health without opening hardware or blocking on IPC."""

    def __init__(
        self,
        path: Path | str = DEFAULT_RUNTIME_HEALTH_PATH,
        *,
        stale_after_s: float = 3.0,
    ):
        self.path = Path(path)
        self.stale_after_s = max(0.1, float(stale_after_s))

    def read(self, *, now: float | None = None) -> RuntimeHealthSnapshot:
        current_time = time.time() if now is None else float(now)
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            if not isinstance(payload, dict):
                raise ValueError("健康文件根节点必须是对象")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return RuntimeHealthSnapshot(read_error=str(exc))

        timestamp = _as_float(payload.get("timestamp"), 0.0)
        age_s = max(0.0, current_time - timestamp) if timestamp > 0 else None
        online = age_s is not None and age_s <= self.stale_after_s

        runtime = _mapping(payload.get("runtime"))
        robot = _mapping(payload.get("robot"))
        modbus = _mapping(payload.get("modbus"))
        flow = _mapping(payload.get("flow"))
        startup = _mapping(payload.get("startup_connection"))
        startup_cameras = _mapping(startup.get("camera_connected"))
        flow_cameras = _mapping(flow.get("cameras"))

        runtime_state = str(runtime.get("state") or "UNKNOWN")
        if not online:
            runtime_state = "OFFLINE"

        return RuntimeHealthSnapshot(
            online=online,
            timestamp=timestamp,
            age_s=age_s,
            runtime_state=runtime_state,
            robot_connected=online and bool(robot.get("connected", False)),
            robot_enabled=online and bool(robot.get("enabled", False)),
            d405_connected=online
            and bool(flow_cameras.get("D405", startup_cameras.get("D405", False))),
            d435i_connected=online
            and bool(flow_cameras.get("D435i", startup_cameras.get("D435i", False))),
            modbus_running=online and bool(modbus.get("is_running", False)),
            modbus_port=_as_int(modbus.get("port"), 502),
            flow_running=online and bool(flow.get("running", False)),
            current_flow=_optional_text(
                flow.get("main_flow_name") or flow.get("flow_id")
            ),
            current_step=_optional_text(
                flow.get("module_name")
                if flow.get("module_name") is not None
                else flow.get("module_index")
            ),
            last_error=str(
                runtime.get("last_error") or robot.get("last_error") or ""
            ),
            raw=payload,
        )


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
