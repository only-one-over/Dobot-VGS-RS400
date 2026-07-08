"""PR-C Task 7.3 — schema validation tests for ``runtime_contract``.

Covers:
- ``COMMAND_SPECS`` covers all existing + new commands.
- ``validate_payload`` accepts valid payloads.
- ``validate_payload`` rejects ``run_step`` missing ``step_index`` /
  ``flow_id`` with ``INVALID_CONFIG``-compatible reason strings.
- Schema is enforced by ``DobotRuntimeAgent._handle_ipc_command`` before
  the handler runs (returns ``INVALID_CONFIG`` error code).
"""
from __future__ import annotations

import sys
import types

if "pyrealsense2" not in sys.modules:
    sys.modules["pyrealsense2"] = types.ModuleType("pyrealsense2")


def _install_modbus_stub():
    module = types.ModuleType("dobot_move.communication.modbus_server")

    class DobotModbusServer:
        pass

    module.DobotModbusServer = DobotModbusServer
    module.REG_CMD_STATUS = 40001
    module.REG_MODE = 40002
    module.STATUS_IDLE = 0
    module.STATUS_STANDBY = 2
    module.STATUS_RUNNING = 4
    module.STATUS_HOOK_OK = 5
    module.STATUS_HOOK_ERR = 110
    module.STATUS_ROBOT_ERR = 111
    module.STATUS_CAMERA_ERR = 112
    module.MODE_AUTO = 0
    module.MODE_MANUAL = 1
    module.CMD_STOP = 0
    module.CMD_RESET = 1
    module.CMD_HOOK = 3
    sys.modules["dobot_move.communication.modbus_server"] = module


_install_modbus_stub()

import shutil  # noqa: E402
import uuid  # noqa: E402
from contextlib import contextmanager  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

from dobot_move.runtime.runtime_contract import (  # noqa: E402
    COMMAND_SPECS,
    CommandSpec,
    validate_payload,
)
from dobot_move.runtime.runtime_agent import DobotRuntimeAgent  # noqa: E402
from dobot_move.runtime.runtime_ipc import IpcCommandError  # noqa: E402
from dobot_move.runtime.runtime_resilience import RuntimeState  # noqa: E402


# ---------------------------------------------------------------------------
# Reuse the _FakeController / _FakeIpcServer pattern from test_runtime_agent
# ---------------------------------------------------------------------------


class _FakeDashboard:
    def __init__(self):
        self.stop_calls = 0

    def Stop(self):
        self.stop_calls += 1
        return "0,0,0;"


class _FakeController:
    def __init__(self):
        self.is_connected = False
        self.is_enabled = False
        self.dashboard = _FakeDashboard()
        self.robot_ip = "192.168.1.50"
        self.last_error = ""
        self.modbus_running = False
        self.feed_thread = None
        self._active_flow_thread = None
        self.runtime_maintenance = False
        self.runtime_recovery_required = None

    def get_feedback_health(self, max_age=0.3):
        return {"health": "ok"}

    def get_modbus_stats(self):
        return {"is_running": self.modbus_running}

    def set_modbus_program_runner(self, runner, readiness_checker=None):
        pass

    def close_robot_transport(self):
        pass

    def abort_active_flow_for_disconnect(self, reason):
        pass

    def _write_modbus_status(self, status, mode=0):
        pass

    def record_alarm(self, *args, **kwargs):
        pass

    def mark_modbus_program_finished(self, success, mode=0, failure_status=None):
        pass

    def set_runtime_recovery_required(self, required=True, on_cleared=None):
        pass

    def set_runtime_maintenance(self, active=True):
        self.runtime_maintenance = bool(active)


class _FakeIpcServer:
    def __init__(self):
        self.last_error = ""

    def start(self):
        return True

    def stop(self):
        pass

    def snapshot(self):
        return {"running": True, "host": "127.0.0.1", "port": 8765,
                "clients": 0, "queue_depth": 0, "last_error": self.last_error}


@contextmanager
def _runtime_agent_fixture():
    temp_dir = Path.cwd() / f"_runtime_contract_test_{uuid.uuid4().hex}"
    temp_dir.mkdir()
    try:
        controller = _FakeController()
        agent = DobotRuntimeAgent(
            controller=controller,
            health_path=temp_dir / "health.json",
            state_path=temp_dir / "state.json",
            startup_delay=0,
            poll_interval=0.1,
            ipc_server=_FakeIpcServer(),
        )
        agent.state_store.begin_boot()
        agent._state_initialized = True
        yield agent, controller
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# CommandSpec / COMMAND_SPECS
# ---------------------------------------------------------------------------


def test_command_specs_cover_existing_and_new_commands():
    """COMMAND_SPECS must cover every registered handler + new commands."""
    required = {
        # existing
        "ping", "get_status", "enter_maintenance", "exit_maintenance",
        "reload_config", "publish_config", "get_publication_status",
        "validate_flow", "get_current_pose", "get_runtime_logs",
        "start_debug_flow", "run_step", "move_to_point",
        "pause_debug_flow", "resume_debug_flow", "stop_debug_flow",
        "get_debug_task_status", "test_d405", "test_d435i",
        "test_detection", "get_vision_snapshot",
        "get_visual_servo_telemetry", "stop_current_task", "safe_stop",
        # PR-C new handlers
        "enable_robot", "disable_robot", "clear_alarms", "connect_robot",
        "set_collision_level", "connect_camera", "disconnect_camera",
        "start_modbus", "stop_modbus", "clear_alarm_history",
        "start_production_flow",
    }
    missing = required - set(COMMAND_SPECS.keys())
    assert not missing, f"COMMAND_SPECS missing: {sorted(missing)}"


def test_command_spec_is_frozen_dataclass():
    spec = COMMAND_SPECS["ping"]
    assert isinstance(spec, CommandSpec)
    assert spec.name == "ping"
    with pytest.raises(Exception):
        spec.name = "tampered"  # type: ignore[misc]


def test_run_step_schema_requires_flow_id_and_step_index():
    spec = COMMAND_SPECS["run_step"]
    assert spec.data_schema == {"flow_id": str, "step_index": int}


# ---------------------------------------------------------------------------
# validate_payload
# ---------------------------------------------------------------------------


def test_validate_payload_accepts_valid_run_step():
    ok, reason = validate_payload(
        "run_step", {"flow_id": "flow1", "step_index": 2}
    )
    assert ok is True
    assert reason == ""


def test_validate_payload_rejects_missing_step_index():
    ok, reason = validate_payload("run_step", {"flow_id": "flow1"})
    assert ok is False
    assert "step_index" in reason


def test_validate_payload_rejects_missing_flow_id():
    ok, reason = validate_payload("run_step", {"step_index": 0})
    assert ok is False
    assert "flow_id" in reason


def test_validate_payload_rejects_wrong_type_for_step_index():
    ok, reason = validate_payload(
        "run_step", {"flow_id": "flow1", "step_index": "two"}
    )
    assert ok is False
    assert "step_index" in reason
    assert "int" in reason


def test_validate_payload_rejects_bool_for_int_field():
    """``bool`` is a subclass of ``int`` but should be rejected for int fields."""
    ok, reason = validate_payload(
        "run_step", {"flow_id": "flow1", "step_index": True}
    )
    assert ok is False
    assert "step_index" in reason


def test_validate_payload_passes_unknown_commands():
    ok, reason = validate_payload("does_not_exist", {"any": "thing"})
    assert ok is True
    assert reason == ""


def test_validate_payload_passes_commands_without_schema():
    ok, reason = validate_payload("get_status", None)
    assert ok is True
    assert reason == ""


def test_validate_payload_connect_robot_requires_ip():
    ok, reason = validate_payload("connect_robot", {"ip": "192.168.1.50"})
    assert ok is True
    ok, reason = validate_payload("connect_robot", {})
    assert ok is False
    assert "ip" in reason


def test_validate_payload_connect_camera_requires_camera_type():
    ok, reason = validate_payload("connect_camera", {"camera_type": "D435i"})
    assert ok is True
    ok, reason = validate_payload("connect_camera", {})
    assert ok is False
    assert "camera_type" in reason


# ---------------------------------------------------------------------------
# Runtime-side enforcement (INVALID_CONFIG on schema failure)
# ---------------------------------------------------------------------------


def test_run_step_missing_step_index_returns_invalid_config():
    """Runtime must reject ``run_step`` without ``step_index``."""
    with _runtime_agent_fixture() as (agent, _controller):
        with pytest.raises(IpcCommandError) as exc_info:
            agent._handle_ipc_command(
                "run_step", {"flow_id": "flow1"}
            )
        assert exc_info.value.code == "INVALID_CONFIG"
        assert "step_index" in exc_info.value.message


def test_run_step_missing_flow_id_returns_invalid_config():
    with _runtime_agent_fixture() as (agent, _controller):
        with pytest.raises(IpcCommandError) as exc_info:
            agent._handle_ipc_command(
                "run_step", {"step_index": 0}
            )
        assert exc_info.value.code == "INVALID_CONFIG"
        assert "flow_id" in exc_info.value.message


def test_set_collision_level_missing_level_returns_invalid_config():
    with _runtime_agent_fixture() as (agent, _controller):
        with pytest.raises(IpcCommandError) as exc_info:
            agent._handle_ipc_command("set_collision_level", {})
        assert exc_info.value.code == "INVALID_CONFIG"


def test_get_status_advertises_capabilities():
    """``_ipc_get_status`` must include a ``capabilities`` list."""
    with _runtime_agent_fixture() as (agent, _controller):
        status = agent._handle_ipc_command("get_status", {})
        assert "capabilities" in status
        assert isinstance(status["capabilities"], list)
        # capabilities should include the new handlers
        for command in (
            "enable_robot", "disable_robot", "clear_alarms",
            "connect_robot", "set_collision_level",
            "connect_camera", "disconnect_camera",
            "start_modbus", "stop_modbus", "clear_alarm_history",
            "start_production_flow",
        ):
            assert command in status["capabilities"]
