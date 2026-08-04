"""Read-only Runtime health snapshots for the engineering GUI."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..runtime.runtime_resilience import RuntimeState


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_RUNTIME_HEALTH_PATH = PROJECT_ROOT / "user_data" / "runtime_health.json"


# ---------------------------------------------------------------------------
# Runtime state i18n + colour mapping (Task 4: maintenance display)
# ---------------------------------------------------------------------------

RUNTIME_STATE_CN: dict[str, str] = {
    "STARTING": "启动中",
    "READY": "就绪",
    "RUNNING": "运行中",
    "WAITING_DELAY": "等待延时",
    "MAINTENANCE_REQUESTED": "维护请求中",
    "MAINTENANCE": "维护中",
    "DEGRADED": "降级",
    "RECOVERY_REQUIRED": "需恢复",
    "STOPPING": "停止中",
    "OFFLINE": "离线",
    "UNKNOWN": "未知",
}


# Pre-populate with every RuntimeState enum value so the mapping stays in sync
# even if the enum grows. Non-enum pseudo-states (OFFLINE/UNKNOWN) are kept
# above for readability.
for _state_member in RuntimeState:
    RUNTIME_STATE_CN.setdefault(_state_member.value, _state_member.value)


def translate_runtime_state(state: str) -> str:
    """Return the Chinese display name for a Runtime state string.

    Unknown state values are returned verbatim so callers can still render
    something meaningful if the runtime emits a new state we have not mapped.
    """
    if not state:
        return "未知"
    return RUNTIME_STATE_CN.get(state, state)


def runtime_state_color(state: str) -> str:
    """Return the hex colour for a Runtime state indicator."""
    if state in {"READY"}:
        return "#4caf50"
    if state in {"RUNNING", "STARTING", "WAITING_DELAY"}:
        return "#2196f3"
    if state in {"MAINTENANCE"}:
        return "#ffc107"
    if state in {"MAINTENANCE_REQUESTED"}:
        return "#ff9800"
    if state in {"DEGRADED", "RECOVERY_REQUIRED"}:
        return "#f44336"
    if state in {"STOPPING", "OFFLINE", "UNKNOWN"}:
        return "#9e9e9e"
    return "#9e9e9e"


@dataclass(frozen=True)
class RuntimeHealthSnapshot:
    online: bool = False
    timestamp: float = 0.0
    age_s: float | None = None
    runtime_state: str = "OFFLINE"
    robot_connected: bool = False
    robot_enabled: bool = False
    software_emergency_active: bool = False
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
            software_emergency_active=online and bool(
                robot.get("software_emergency_active", False)
            ),
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
