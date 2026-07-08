"""PR-C Task 7.4 — Runtime handler tests for the 10 new IPC handlers.

Each handler is invoked through ``DobotRuntimeAgent._handle_ipc_command``
so the schema-validation layer is exercised end-to-end. The fake
controller exposes the hardware-facing methods (``enable_robot`` /
``disable_robot`` / ``clear_error`` / ``set_collision_level`` /
``set_robot_ip`` / ``connect`` / ``start_modbus`` / ``stop_modbus``) and
an ``alarm_history`` stub so the handlers can be verified without real
hardware.
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
from unittest.mock import MagicMock  # noqa: E402

import pytest  # noqa: E402

from dobot_move.runtime.runtime_agent import DobotRuntimeAgent  # noqa: E402
from dobot_move.runtime.runtime_ipc import IpcCommandError  # noqa: E402


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeDashboard:
    def __init__(self):
        self.stop_calls = 0

    def Stop(self):
        self.stop_calls += 1
        return "0,0,0;"


class _FakeAlarmHistory:
    """Minimal stand-in for :class:`AlarmHistory`."""

    def __init__(self):
        self.clear_calls = 0

    def clear(self) -> None:
        self.clear_calls += 1


class _FakeController:
    """Controller stub exposing every hardware-facing method the new
    handlers call. Each method records its invocation for assertions.
    """

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
        self.alarm_history = _FakeAlarmHistory()

        # Call counters / argument captures.
        self.enable_calls = 0
        self.disable_calls = 0
        self.clear_error_calls = 0
        self.connect_calls = 0
        self.set_robot_ip_calls: list[str] = []
        self.collision_level_calls: list[int] = []
        self.start_modbus_calls: list[tuple[int, int]] = []
        self.stop_modbus_calls = 0

    # -- Hardware-facing methods ----------------------------------------

    def enable_robot(self):
        self.enable_calls += 1
        self.is_enabled = True

    def disable_robot(self):
        self.disable_calls += 1
        self.is_enabled = False

    def clear_error(self):
        self.clear_error_calls += 1

    def set_robot_ip(self, ip: str):
        self.set_robot_ip_calls.append(str(ip))
        self.robot_ip = str(ip)

    def connect(self):
        self.connect_calls += 1
        self.is_connected = True
        self.last_error = ""
        return True

    def set_collision_level(self, level: int):
        self.collision_level_calls.append(int(level))

    def start_modbus(self, port=502, slave_id=5):
        self.start_modbus_calls.append((int(port), int(slave_id)))
        self.modbus_running = True
        return True

    def stop_modbus(self):
        self.stop_modbus_calls += 1
        self.modbus_running = False

    # -- Misc plumbing used by DobotRuntimeAgent ----------------------

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
    temp_dir = Path.cwd() / f"_runtime_handlers_test_{uuid.uuid4().hex}"
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
# Task 2 handlers — robot control
# ---------------------------------------------------------------------------


def test_ipc_enable_robot_calls_controller_and_returns_enabled_true():
    with _runtime_agent_fixture() as (agent, controller):
        result = agent._handle_ipc_command("enable_robot", None)
        assert result == {"enabled": True}
        assert controller.enable_calls == 1


def test_ipc_disable_robot_calls_controller_and_returns_enabled_false():
    with _runtime_agent_fixture() as (agent, controller):
        result = agent._handle_ipc_command("disable_robot", None)
        assert result == {"enabled": False}
        assert controller.disable_calls == 1


def test_ipc_clear_alarms_calls_controller_clear_error():
    with _runtime_agent_fixture() as (agent, controller):
        result = agent._handle_ipc_command("clear_alarms", None)
        assert result == {"cleared": True}
        assert controller.clear_error_calls == 1


def test_ipc_connect_robot_sets_ip_and_connects():
    with _runtime_agent_fixture() as (agent, controller):
        result = agent._handle_ipc_command(
            "connect_robot", {"ip": "192.168.10.20"}
        )
        assert result == {"connected": True}
        assert controller.set_robot_ip_calls == ["192.168.10.20"]
        assert controller.connect_calls == 1


def test_ipc_connect_robot_without_ip_still_connects():
    """Schema rejects missing ip, but the handler itself tolerates empty ip."""
    with _runtime_agent_fixture() as (agent, controller):
        # Bypass schema by calling the handler directly.
        result = agent._ipc_connect_robot({"ip": ""})
        assert result == {"connected": True}
        assert controller.set_robot_ip_calls == []
        assert controller.connect_calls == 1


def test_ipc_connect_robot_failure_raises_robot_not_connected():
    with _runtime_agent_fixture() as (agent, controller):
        controller.connect_calls = 0  # ensure connect returns False
        # Replace connect with a failing stub.
        controller.connect = lambda: False  # type: ignore[assignment]
        controller.last_error = "boom"
        with pytest.raises(IpcCommandError) as exc_info:
            agent._ipc_connect_robot({"ip": "10.0.0.1"})
        assert exc_info.value.code == "ROBOT_NOT_CONNECTED"
        assert "boom" in exc_info.value.message


def test_ipc_set_collision_level_calls_controller_with_int():
    with _runtime_agent_fixture() as (agent, controller):
        result = agent._handle_ipc_command(
            "set_collision_level", {"level": 3}
        )
        assert result == {"level": 3}
        assert controller.collision_level_calls == [3]


# ---------------------------------------------------------------------------
# Task 2 handlers — camera
# ---------------------------------------------------------------------------


def test_ipc_connect_camera_d435i_uses_program_runner_ensure_camera():
    with _runtime_agent_fixture() as (agent, _controller):
        ensure_calls: list[str] = []
        agent.program_runner._ensure_camera = lambda ct: (  # type: ignore[assignment]
            ensure_calls.append(ct) or True
        )
        result = agent._handle_ipc_command(
            "connect_camera", {"camera_type": "D435i"}
        )
        assert result == {"connected": True, "camera_type": "D435i"}
        assert ensure_calls == ["D435i"]


def test_ipc_connect_camera_d405_uses_program_runner_ensure_camera():
    with _runtime_agent_fixture() as (agent, _controller):
        agent.program_runner._ensure_camera = lambda ct: True  # type: ignore[assignment]
        result = agent._handle_ipc_command(
            "connect_camera", {"camera_type": "D405"}
        )
        assert result == {"connected": True, "camera_type": "D405"}


def test_ipc_connect_camera_unsupported_type_raises_invalid_config():
    with _runtime_agent_fixture() as (agent, _controller):
        # Bypass schema (which only checks camera_type is str) by calling
        # the handler directly with an unsupported value.
        with pytest.raises(IpcCommandError) as exc_info:
            agent._ipc_connect_camera({"camera_type": "D999"})
        assert exc_info.value.code == "INVALID_CONFIG"


def test_ipc_connect_camera_ensure_failure_raises_camera_not_ready():
    with _runtime_agent_fixture() as (agent, _controller):
        agent.program_runner._ensure_camera = lambda ct: False  # type: ignore[assignment]
        with pytest.raises(IpcCommandError) as exc_info:
            agent._ipc_connect_camera({"camera_type": "D435i"})
        assert exc_info.value.code == "CAMERA_NOT_READY"


def test_ipc_disconnect_camera_closes_vision_instance():
    with _runtime_agent_fixture() as (agent, _controller):
        closed: list[str] = []
        fake_vision = MagicMock()
        fake_vision.close.side_effect = lambda: closed.append("D435i")
        # Program runner exposes ``vision_d435i`` / ``vision_d405`` attrs.
        agent.program_runner.vision_d435i = fake_vision
        result = agent._handle_ipc_command(
            "disconnect_camera", {"camera_type": "D435i"}
        )
        assert result == {"disconnected": True, "camera_type": "D435i"}
        fake_vision.close.assert_called_once()
        # The vision attribute should be cleared after disconnect.
        assert agent.program_runner.vision_d435i is None
        assert closed == ["D435i"]


def test_ipc_disconnect_camera_when_no_vision_returns_disconnected_true():
    """Disconnecting a camera that was never connected is a no-op success."""
    with _runtime_agent_fixture() as (agent, _controller):
        # program_runner.vision_d405 is None by default.
        assert agent.program_runner.vision_d405 is None
        result = agent._handle_ipc_command(
            "disconnect_camera", {"camera_type": "D405"}
        )
        assert result == {"disconnected": True, "camera_type": "D405"}


def test_ipc_disconnect_camera_unsupported_type_raises_invalid_config():
    with _runtime_agent_fixture() as (agent, _controller):
        with pytest.raises(IpcCommandError) as exc_info:
            agent._ipc_disconnect_camera({"camera_type": "D999"})
        assert exc_info.value.code == "INVALID_CONFIG"


# ---------------------------------------------------------------------------
# Task 2 handlers — Modbus
# ---------------------------------------------------------------------------


def test_ipc_start_modbus_calls_controller_start_modbus_with_port_and_slave():
    with _runtime_agent_fixture() as (agent, controller):
        result = agent._handle_ipc_command("start_modbus", None)
        assert result == {"running": True}
        assert controller.start_modbus_calls == [
            (agent.modbus_port, agent.modbus_slave_id)
        ]


def test_ipc_start_modbus_failure_raises_internal_error():
    with _runtime_agent_fixture() as (agent, controller):
        controller.start_modbus = lambda port=502, slave_id=5: False  # type: ignore[assignment]
        with pytest.raises(IpcCommandError) as exc_info:
            agent._ipc_start_modbus(None)
        assert exc_info.value.code == "INTERNAL_ERROR"


def test_ipc_stop_modbus_calls_controller_stop_modbus():
    with _runtime_agent_fixture() as (agent, controller):
        controller.modbus_running = True
        result = agent._handle_ipc_command("stop_modbus", None)
        assert result == {"running": False}
        assert controller.stop_modbus_calls == 1
        assert controller.modbus_running is False


def test_ipc_stop_modbus_exception_raises_internal_error():
    with _runtime_agent_fixture() as (agent, controller):
        def _boom():
            raise RuntimeError("modbus stop failed")
        controller.stop_modbus = _boom  # type: ignore[assignment]
        with pytest.raises(IpcCommandError) as exc_info:
            agent._ipc_stop_modbus(None)
        assert exc_info.value.code == "INTERNAL_ERROR"
        assert "modbus stop failed" in exc_info.value.message


# ---------------------------------------------------------------------------
# Task 2 handlers — alarm history
# ---------------------------------------------------------------------------


def test_ipc_clear_alarm_history_calls_alarm_history_clear():
    with _runtime_agent_fixture() as (agent, controller):
        result = agent._handle_ipc_command("clear_alarm_history", None)
        assert result == {"cleared": True}
        assert controller.alarm_history.clear_calls == 1


def test_ipc_clear_alarm_history_without_alarm_history_attribute_still_succeeds():
    """When ``alarm_history`` is None the handler must not raise."""
    with _runtime_agent_fixture() as (agent, _controller):
        agent.alarm_history = None
        result = agent._handle_ipc_command("clear_alarm_history", None)
        assert result == {"cleared": True}


# ---------------------------------------------------------------------------
# Handler registration — all 10 must be in the handlers dict
# ---------------------------------------------------------------------------


def test_all_ten_new_handlers_are_registered():
    """The handlers dict must expose all 10 new commands from Task 2."""
    required = {
        "enable_robot",
        "disable_robot",
        "clear_alarms",
        "connect_robot",
        "set_collision_level",
        "connect_camera",
        "disconnect_camera",
        "start_modbus",
        "stop_modbus",
        "clear_alarm_history",
    }
    with _runtime_agent_fixture() as (agent, _controller):
        registered = set(agent._handlers.keys())
        missing = required - registered
        assert not missing, f"Handlers missing from registry: {sorted(missing)}"
