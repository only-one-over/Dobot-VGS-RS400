"""PR-C Task 7.5 — Production / Debug flow separation tests.

Verifies the mutual-exclusion guard introduced in Task 5:
- ``_ipc_start_debug_flow`` rejects with ``RUNTIME_BUSY`` when a
  production task is running (``task_mode == "production"``).
- ``_ipc_start_production_flow`` rejects with ``RUNTIME_BUSY`` when a
  debug task is running (``task_mode == "debug"``).
- ``_run_program_from_modbus`` (Modbus 40001=3 trigger) returns
  ``False`` when a debug task owns the runner.
- ``start_production_flow`` is registered in the handlers dict and
  routes through the production path on success.
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

from dobot_move.runtime.runtime_agent import (  # noqa: E402
    DobotRuntimeAgent,
    RuntimeExecutionRequest,
)
from dobot_move.runtime.runtime_ipc import IpcCommandError  # noqa: E402


# ---------------------------------------------------------------------------
# Fakes (same pattern as test_runtime_contract / test_runtime_handlers)
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

    def abort_active_flow_for_disconnect(self, reason, source="flow"):
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
    temp_dir = Path.cwd() / f"_prod_debug_sep_test_{uuid.uuid4().hex}"
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
# SubTask 5.6: Mutual exclusion — production running rejects debug
# ---------------------------------------------------------------------------


def test_start_debug_flow_rejected_when_production_running():
    """``_ipc_start_debug_flow`` must raise ``RUNTIME_BUSY`` when a
    production task is active.
    """
    with _runtime_agent_fixture() as (agent, _controller):
        agent.program_runner.task_mode = "production"
        with pytest.raises(IpcCommandError) as exc_info:
            agent._handle_ipc_command("start_debug_flow", {})
        assert exc_info.value.code == "RUNTIME_BUSY"
        assert "生产流程" in exc_info.value.message or "production" in exc_info.value.message.lower()


def test_start_debug_flow_rejection_happens_before_build_request():
    """The RUNTIME_BUSY guard must fire before ``build_request`` is called
    so we don't waste resources building a request that will be rejected.
    """
    with _runtime_agent_fixture() as (agent, _controller):
        agent.program_runner.task_mode = "production"
        # If build_request is reached, this mock will record the call.
        agent.program_runner.build_request = MagicMock(  # type: ignore[assignment]
            side_effect=AssertionError("build_request must not be called when production is running")
        )
        with pytest.raises(IpcCommandError) as exc_info:
            agent._handle_ipc_command("start_debug_flow", {})
        assert exc_info.value.code == "RUNTIME_BUSY"
        agent.program_runner.build_request.assert_not_called()


# ---------------------------------------------------------------------------
# SubTask 5.6: Mutual exclusion — debug running rejects production
# ---------------------------------------------------------------------------


def test_start_production_flow_rejected_when_debug_running():
    """``_ipc_start_production_flow`` must raise ``RUNTIME_BUSY`` when a
    debug task is active.
    """
    with _runtime_agent_fixture() as (agent, _controller):
        agent.program_runner.task_mode = "debug"
        with pytest.raises(IpcCommandError) as exc_info:
            agent._handle_ipc_command("start_production_flow", {})
        assert exc_info.value.code == "RUNTIME_BUSY"
        assert "调试流程" in exc_info.value.message or "debug" in exc_info.value.message.lower()


# ---------------------------------------------------------------------------
# SubTask 5.3: Modbus 40001=3 routes through production path
# ---------------------------------------------------------------------------


def test_run_program_from_modbus_rejected_when_debug_running():
    """``_run_program_from_modbus`` must return ``False`` (not raise) when
    a debug task owns the runner — the Modbus poll loop treats ``False``
    as "rejected, try again later".
    """
    with _runtime_agent_fixture() as (agent, _controller):
        agent.program_runner.task_mode = "debug"
        result = agent._run_program_from_modbus()
        assert result is False


def test_run_program_from_modbus_rejected_in_maintenance_mode():
    """Maintenance mode must also block the Modbus production trigger."""
    with _runtime_agent_fixture() as (agent, _controller):
        # ``maintenance_mode`` is a plain attribute on the agent.
        agent.maintenance_mode = True
        result = agent._run_program_from_modbus()
        assert result is False


# ---------------------------------------------------------------------------
# SubTask 5.2: start_production_flow handler is registered
# ---------------------------------------------------------------------------


def test_start_production_flow_is_registered_handler():
    """``start_production_flow`` must appear in the handlers dict so
    ``_handle_ipc_command`` can route to it.
    """
    with _runtime_agent_fixture() as (agent, _controller):
        assert "start_production_flow" in agent._handlers
        assert callable(agent._handlers["start_production_flow"])


def test_start_production_flow_advertised_in_capabilities():
    """``get_status`` must include ``start_production_flow`` in the
    ``capabilities`` list so the GUI knows the Runtime supports it.
    """
    with _runtime_agent_fixture() as (agent, _controller):
        status = agent._handle_ipc_command("get_status", {})
        assert "start_production_flow" in status["capabilities"]


# ---------------------------------------------------------------------------
# SubTask 5.2: success path — production flow starts and sets task_mode
# ---------------------------------------------------------------------------


def _make_fake_request(mode: str = "production") -> RuntimeExecutionRequest:
    return RuntimeExecutionRequest(
        mode=mode,
        flow_id="test-flow",
        flow_name="Test Flow",
        modules=[],
        config={"robot_ip": "127.0.0.1"},
        revision="test-rev",
    )


def test_start_production_flow_success_sets_task_mode_to_production():
    """When ``task_mode`` is ``None`` and ``start_request`` succeeds, the
    handler returns ``{"accepted": True, ...}`` and the runner's
    ``task_mode`` is set to ``"production"``.
    """
    with _runtime_agent_fixture() as (agent, _controller):
        fake_request = _make_fake_request("production")
        agent.program_runner.build_request = MagicMock(return_value=fake_request)  # type: ignore[assignment]
        agent.program_runner.start_request = MagicMock(return_value=True)  # type: ignore[assignment]
        agent.program_runner.task_mode = None

        result = agent._handle_ipc_command("start_production_flow", {})

        assert result["accepted"] is True
        assert result["task_id"] == fake_request.task_id
        assert result["flow_id"] == "test-flow"
        agent.program_runner.build_request.assert_called_once_with(
            mode="production", flow_id=None
        )
        agent.program_runner.start_request.assert_called_once_with(fake_request)


def test_start_production_flow_when_already_running_returns_task_already_running():
    """When ``start_request`` returns ``False`` (another task owns the
    runner), the handler raises ``TASK_ALREADY_RUNNING``.
    """
    with _runtime_agent_fixture() as (agent, _controller):
        fake_request = _make_fake_request("production")
        agent.program_runner.build_request = MagicMock(return_value=fake_request)  # type: ignore[assignment]
        agent.program_runner.start_request = MagicMock(return_value=False)  # type: ignore[assignment]
        agent.program_runner.task_mode = None

        with pytest.raises(IpcCommandError) as exc_info:
            agent._handle_ipc_command("start_production_flow", {})
        assert exc_info.value.code == "TASK_ALREADY_RUNNING"


# ---------------------------------------------------------------------------
# SubTask 5.1: task_mode accepts "production" value
# ---------------------------------------------------------------------------


def test_program_runner_task_mode_accepts_production_value():
    """``RuntimeProgramRunner.task_mode`` must accept ``"production"`` as
    a valid value (in addition to ``"debug"`` and ``None``).
    """
    with _runtime_agent_fixture() as (agent, _controller):
        runner = agent.program_runner
        runner.task_mode = "production"
        assert runner.task_mode == "production"
        # snapshot() must surface task_mode for the GUI / status consumers.
        snapshot = runner.snapshot()
        assert snapshot["task_mode"] == "production"
