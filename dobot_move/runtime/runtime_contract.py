"""GUI ↔ Runtime IPC command contract.

Defines :class:`CommandSpec` and the :data:`COMMAND_SPECS` mapping that
serves as the single source of truth for IPC command payloads exchanged
between the GUI (via :class:`~dobot_move.ui.runtime_facade.RuntimeFacade`)
and the headless :class:`~dobot_move.runtime.runtime_agent.DobotRuntimeAgent`.

The schema intentionally uses plain ``dict`` objects mapping field names
to expected Python types — this avoids pulling in ``jsonschema`` and keeps
validation trivial. Both sides may import :data:`COMMAND_SPECS` for
documentation; the Runtime side enforces validation in
:meth:`~dobot_move.runtime.runtime_agent.DobotRuntimeAgent._handle_ipc_command`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class CommandSpec:
    """Declarative description of a single IPC command.

    Attributes
    ----------
    name:
        Canonical command name (matches the key in :data:`COMMAND_SPECS`).
    data_schema:
        Mapping of required payload field name → expected Python type.
        ``None`` means the command takes no payload (or accepts any).
    response_schema:
        Mapping of expected response field name → expected Python type.
        Used for documentation only; not enforced at runtime.
    required_capability:
        Optional capability flag the Runtime must expose for this command
        to be available. ``None`` means always available.
    """

    name: str
    data_schema: Optional[dict[str, type]] = None
    response_schema: Optional[dict[str, Any]] = None
    required_capability: Optional[str] = None


def _spec(
    name: str,
    *,
    data_schema: Optional[dict[str, type]] = None,
    response_schema: Optional[dict[str, Any]] = None,
    required_capability: Optional[str] = None,
) -> CommandSpec:
    return CommandSpec(
        name=name,
        data_schema=data_schema,
        response_schema=response_schema,
        required_capability=required_capability,
    )


# ---------------------------------------------------------------------------
# Command catalogue
# ---------------------------------------------------------------------------
# Grouped by category. ``data_schema`` is ``None`` for commands that accept
# either no payload or a free-form payload (validated by the handler itself).
COMMAND_SPECS: dict[str, CommandSpec] = {
    # -- Lifecycle / status -------------------------------------------------
    "ping": _spec("ping", response_schema={"pong": bool}),
    "get_status": _spec("get_status", response_schema={"runtime_state": str}),
    "enter_maintenance": _spec(
        "enter_maintenance", response_schema={"runtime_state": str}
    ),
    "exit_maintenance": _spec(
        "exit_maintenance", response_schema={"runtime_state": str}
    ),
    "reload_config": _spec("reload_config", response_schema={"reloaded": bool}),
    "publish_config": _spec("publish_config", response_schema={"published": bool}),
    "get_publication_status": _spec("get_publication_status"),
    "validate_flow": _spec(
        "validate_flow",
        data_schema=None,
        response_schema={"valid": bool},
    ),

    # -- Robot control (PR-C Task 2) ---------------------------------------
    "enable_robot": _spec("enable_robot", response_schema={"enabled": bool}),
    "disable_robot": _spec("disable_robot", response_schema={"enabled": bool}),
    "clear_alarms": _spec("clear_alarms", response_schema={"cleared": bool}),
    "connect_robot": _spec(
        "connect_robot",
        data_schema={"ip": str},
        response_schema={"connected": bool},
    ),
    "set_collision_level": _spec(
        "set_collision_level",
        data_schema={"level": int},
        response_schema={"level": int},
    ),

    # -- Camera (PR-C Task 2) ----------------------------------------------
    "connect_camera": _spec(
        "connect_camera",
        data_schema={"camera_type": str},
        response_schema={"connected": bool},
    ),
    "disconnect_camera": _spec(
        "disconnect_camera",
        data_schema={"camera_type": str},
        response_schema={"disconnected": bool},
    ),

    # -- Modbus (PR-C Task 2) ----------------------------------------------
    "start_modbus": _spec("start_modbus", response_schema={"running": bool}),
    "stop_modbus": _spec("stop_modbus", response_schema={"running": bool}),

    # -- Alarm history (PR-C Task 2) ---------------------------------------
    "clear_alarm_history": _spec(
        "clear_alarm_history", response_schema={"cleared": bool}
    ),

    # -- Motion / debug flow ------------------------------------------------
    "get_current_pose": _spec(
        "get_current_pose", response_schema={"pose": list}
    ),
    "get_runtime_logs": _spec(
        "get_runtime_logs",
        data_schema=None,
        response_schema={"lines": list},
    ),
    "start_debug_flow": _spec(
        "start_debug_flow",
        data_schema=None,
        response_schema={"accepted": bool},
    ),
    "start_production_flow": _spec(
        "start_production_flow",
        data_schema=None,
        response_schema={"accepted": bool},
    ),
    "run_step": _spec(
        "run_step",
        data_schema={"flow_id": str, "step_index": int},
        response_schema={"accepted": bool},
    ),
    "move_to_point": _spec(
        "move_to_point",
        data_schema={"point_name": str},
        response_schema={"accepted": bool},
    ),
    "pause_debug_flow": _spec(
        "pause_debug_flow", response_schema={"paused": bool}
    ),
    "resume_debug_flow": _spec(
        "resume_debug_flow", response_schema={"paused": bool}
    ),
    "stop_debug_flow": _spec("stop_debug_flow"),
    "get_debug_task_status": _spec("get_debug_task_status"),
    "stop_current_task": _spec("stop_current_task"),
    "safe_stop": _spec("safe_stop"),

    # -- Vision diagnostics -------------------------------------------------
    "test_d405": _spec("test_d405"),
    "test_d435i": _spec("test_d435i"),
    "test_detection": _spec("test_detection"),
    "get_vision_snapshot": _spec("get_vision_snapshot"),
    "get_visual_servo_telemetry": _spec("get_visual_servo_telemetry"),
}


def validate_payload(command: str, data: Optional[dict[str, Any]]) -> tuple[bool, str]:
    """Validate ``data`` against the command's ``data_schema``.

    Returns ``(True, "")`` when the payload satisfies the schema, otherwise
    ``(False, reason)``. Commands without a schema (or unknown commands)
    pass through unchanged so the handler can decide.
    """
    spec = COMMAND_SPECS.get(command)
    if spec is None or spec.data_schema is None:
        return True, ""
    if data is None:
        data = {}
    for key, expected_type in spec.data_schema.items():
        if key not in data:
            return False, f"missing required field: {key}"
        value = data[key]
        # ``bool`` is a subclass of ``int`` — accept it for ``int`` fields
        # only when the schema explicitly asks for ``bool``.
        if expected_type is int and isinstance(value, bool):
            return False, (
                f"field {key} expected int, got bool"
            )
        if not isinstance(value, expected_type):
            return False, (
                f"field {key} expected {expected_type.__name__}, "
                f"got {type(value).__name__}"
            )
    return True, ""
