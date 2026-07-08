"""PR 5 — 暴露生产遥测数据 (现场接口和 Telemetry) tests.

Covers Tasks 1-6 of the expose-production-telemetry spec:
* Task 1: Health JSON ``production`` field (RUNNING + IDLE scenarios).
* Task 2: GUI Dashboard 生产上下文 display (mock Health JSON).
* Task 3: ProductionState transition log format (from/to/reason/task_id).
* Task 4: PLC diagnostic logs for 40001/40002/40004 changes.
* Task 5: task_id consistency across logs + Health JSON.
* Task 6: winsound.Beep preserved as auxiliary alarm (110/111/112).
"""
from __future__ import annotations

import asyncio
import importlib
import logging
import sys
import types
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Install a minimal modbus_server stub BEFORE importing runtime_agent,
# mirroring the pattern in test_production_state_machine.py.
if "pyrealsense2" not in sys.modules:
    sys.modules["pyrealsense2"] = types.ModuleType("pyrealsense2")


def _install_modbus_stub() -> None:
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

from dobot_move.runtime.production_context import ProductionTaskContext  # noqa: E402
from dobot_move.runtime.production_flow_router import ProductionFlowRouter  # noqa: E402
from dobot_move.runtime.production_state import ProductionState  # noqa: E402
from dobot_move.runtime.runtime_agent import (  # noqa: E402
    DobotRuntimeAgent,
    RuntimeExecutionRequest,
)
from dobot_move.ui.gui_app import DobotMainWindow  # noqa: E402


# ===========================================================================
# Shared fixture (mirrors test_production_state_machine.py)
# ===========================================================================


class _FakeDashboard:
    def __init__(self):
        self.stop_calls = 0

    def Stop(self):
        self.stop_calls += 1
        return "0,0,0;"


class _FakeController:
    """Controller stub supporting PR 3 delegate + mode/hook callbacks."""

    def __init__(self):
        self.is_connected = True
        self.is_enabled = True
        self.dashboard = _FakeDashboard()
        self.robot_ip = "192.168.1.50"
        self.last_error = ""
        self.modbus_running = False
        self.feed_thread = None
        self._active_flow_thread = None
        self.runtime_maintenance = False
        self.runtime_recovery_required = None
        self.written_statuses: list[tuple[int, int]] = []
        self.pause_calls = 0
        self.continue_calls = 0
        self.clear_error_calls = 0
        self.enable_calls = 0
        self.move_to_initial_calls = 0
        self.move_to_initial_return = True
        self.enable_return = True
        self.close_transport_calls = 0
        self._command_delegate = None
        self._mode_changed_callback = None
        self._hook_type_changed_callback = None

    def get_feedback_health(self, max_age=0.3):
        return {"health": "ok"}

    def get_modbus_stats(self):
        return {"is_running": self.modbus_running}

    def set_modbus_program_runner(
        self, runner, readiness_checker=None, command_delegate=None
    ):
        self._command_delegate = command_delegate

    def set_modbus_mode_changed_callback(self, callback):
        self._mode_changed_callback = callback

    def set_modbus_hook_type_changed_callback(self, callback):
        self._hook_type_changed_callback = callback

    def close_robot_transport(self):
        self.close_transport_calls += 1

    def abort_active_flow_for_disconnect(self, reason, source="flow"):
        pass

    def _write_modbus_status(self, status, mode=0):
        self.written_statuses.append((int(status), int(mode)))

    def record_alarm(self, *args, **kwargs):
        pass

    def mark_modbus_program_finished(self, success, mode=0, failure_status=None):
        pass

    def set_runtime_recovery_required(self, required=True, on_cleared=None):
        pass

    def set_runtime_maintenance(self, active=True):
        self.runtime_maintenance = bool(active)

    def pause(self):
        self.pause_calls += 1

    def continue_motion(self):
        self.continue_calls += 1

    def clear_error(self):
        self.clear_error_calls += 1

    def enable_robot(self):
        self.enable_calls += 1
        return self.enable_return

    def move_to_initial_position(
        self, verify_start_pose=True, verify_end_pose=True, **kwargs
    ):
        self.move_to_initial_calls += 1
        return self.move_to_initial_return


class _FakeIpcServer:
    def __init__(self):
        self.last_error = ""

    def start(self):
        return True

    def stop(self):
        pass

    def snapshot(self):
        return {
            "running": True,
            "host": "127.0.0.1",
            "port": 8765,
            "clients": 0,
            "queue_depth": 0,
            "last_error": self.last_error,
        }


def _make_fake_request(flow_id="test-flow", mode="production"):
    return RuntimeExecutionRequest(
        mode=mode,
        flow_id=flow_id,
        flow_name="Test Flow",
        modules=[],
        config={"robot_ip": "127.0.0.1"},
        revision="test-rev",
    )


@contextmanager
def _runtime_agent_fixture():
    """Create a DobotRuntimeAgent with PR 3 + PR 5 wiring intact."""
    temp_dir = Path.cwd() / f"_prod_tel_test_{uuid.uuid4().hex}"
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
        agent.flow_router = ProductionFlowRouter(
            {
                "low_hook": "flow-low",
                "high_hook": "flow-high",
                "error_recovery": "flow-recovery",
            }
        )
        agent.program_runner.build_production_request = MagicMock(
            side_effect=lambda flow_id, task_id="": _make_fake_request(flow_id)
        )
        agent.program_runner.start_request = MagicMock(return_value=True)
        agent.program_runner.pause = MagicMock(return_value=True)
        agent.program_runner.resume = MagicMock(return_value=True)
        agent.program_runner.stop = MagicMock(return_value=True)
        agent.program_runner.current_module_index = 2
        agent.program_runner.task_mode = None
        yield agent, controller
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _start_running_task(agent, hook_type=0):
    """Helper: drive the agent into RUNNING with a production task."""
    agent._set_production_state(ProductionState.STANDBY)
    agent._dispatch_command(cmd=3, mode=0, hook_type=hook_type)
    assert agent.production_state == ProductionState.RUNNING
    assert agent.production_task is not None


# ===========================================================================
# Task 1 — Health JSON production field
# ===========================================================================


class TestHealthJsonProductionField:
    def test_running_state_contains_complete_production_field(self):
        """RUNNING state Health JSON production field has all fields populated."""
        with _runtime_agent_fixture() as (agent, _controller):
            _start_running_task(agent, hook_type=0)
            payload = agent.build_health_payload()
            production = payload["production"]
            assert production["state"] == "running"
            assert production["task_id"] == agent.production_task.task_id
            assert production["hook_type"] == 0
            assert production["hook_name"] == "低钩子"
            assert production["flow_role"] == "low_hook"
            assert production["flow_id"] == "flow-low"
            assert production["recovery_started"] is False
            assert production["failure_code"] is None

    def test_high_hook_running_state_uses_high_hook_name(self):
        with _runtime_agent_fixture() as (agent, _controller):
            _start_running_task(agent, hook_type=1)
            production = agent.build_health_payload()["production"]
            assert production["hook_type"] == 1
            assert production["hook_name"] == "高钩子"
            assert production["flow_role"] == "high_hook"
            assert production["flow_id"] == "flow-high"

    def test_idle_state_task_id_is_null(self):
        """IDLE state: production field state='idle', task_id=null."""
        with _runtime_agent_fixture() as (agent, _controller):
            # Default state is IDLE, no task
            assert agent.production_state == ProductionState.IDLE
            assert agent.production_task is None
            production = agent.build_health_payload()["production"]
            assert production["state"] == "idle"
            assert production["task_id"] is None
            assert production["hook_type"] is None
            assert production["hook_name"] is None
            assert production["flow_role"] is None
            assert production["flow_id"] is None
            assert production["recovery_started"] is None
            assert production["failure_code"] is None

    def test_recovery_started_uses_recovery_flow_role(self):
        """When recovery_started=True, flow_role='error_recovery'."""
        with _runtime_agent_fixture() as (agent, _controller):
            _start_running_task(agent, hook_type=0)
            task = agent.production_task
            task.recovery_started = True
            production = agent.build_health_payload()["production"]
            assert production["flow_role"] == "error_recovery"
            assert production["flow_id"] == "flow-recovery"
            assert production["recovery_started"] is True

    def test_health_json_preserves_existing_fields(self):
        """Backward compat: robot/camera/modbus/flow fields still present."""
        with _runtime_agent_fixture() as (agent, _controller):
            payload = agent.build_health_payload()
            for key in ("robot", "modbus", "flow", "runtime", "startup_connection"):
                assert key in payload, f"missing existing field: {key}"
            assert "production" in payload


# ===========================================================================
# Task 2 — GUI Dashboard production context display
# ===========================================================================


class _FakeLabel:
    """Minimal QLabel stub recording setText / setStyleSheet calls."""

    def __init__(self):
        self.text = ""
        self.style = ""

    def setText(self, text):
        self.text = text

    def setStyleSheet(self, style):
        self.style = style

    def setMinimumWidth(self, width):
        pass


class _DashboardStub:
    """Stub exposing only the prod_*_label attributes used by
    ``_refresh_production_display`` so the method can run without Qt.

    The method reads the class-level dicts ``_PRODUCTION_STATE_CN`` and
    ``_PLC_CMD_CN`` via ``self``; mirror them onto the stub so attribute
    lookups succeed.
    """

    _PRODUCTION_STATE_CN = DobotMainWindow._PRODUCTION_STATE_CN
    _PLC_CMD_CN = DobotMainWindow._PLC_CMD_CN

    def __init__(self):
        self.prod_state_label = _FakeLabel()
        self.prod_hook_label = _FakeLabel()
        self.prod_flow_label = _FakeLabel()
        self.prod_step_label = _FakeLabel()
        self.prod_plc_label = _FakeLabel()
        self.prod_mode_label = _FakeLabel()
        self.prod_task_id_label = _FakeLabel()


class _SnapshotStub:
    """Minimal RuntimeHealthSnapshot stub carrying a ``raw`` dict."""

    def __init__(self, raw):
        self.raw = raw


def _build_health_raw(state="running", task_id="abc123", hook_type=0,
                      hook_name="低钩子", flow_role="low_hook",
                      flow_id="flow-low", recovery_started=False,
                      failure_code=None, flow_name="低钩子提钩",
                      step_name="视觉伺服", cmd_value=4):
    return {
        "production": {
            "state": state,
            "task_id": task_id,
            "hook_type": hook_type,
            "hook_name": hook_name,
            "flow_role": flow_role,
            "flow_id": flow_id,
            "recovery_started": recovery_started,
            "failure_code": failure_code,
        },
        "flow": {
            "main_flow_name": flow_name,
            "module_name": step_name,
        },
        "modbus": {"is_running": True},
        "last_command": {"value": cmd_value, "timestamp": 0.0},
    }


class TestGuiDashboardProductionDisplay:
    """Verify ``_refresh_production_display`` renders the right fields."""

    def _refresh(self, raw):
        stub = _DashboardStub()
        # Bind the stub's method to the real implementation.
        DobotMainWindow._refresh_production_display(stub, _SnapshotStub(raw))
        return stub

    def test_running_state_displays_all_fields(self):
        raw = _build_health_raw(
            state="running", task_id="abc123", hook_type=0,
            hook_name="低钩子", flow_role="low_hook", flow_id="flow-low",
            flow_name="低钩子提钩", step_name="视觉伺服", cmd_value=4,
        )
        stub = self._refresh(raw)
        assert stub.prod_state_label.text == "运行中"
        assert stub.prod_hook_label.text == "低钩子"
        assert stub.prod_flow_label.text == "低钩子提钩"
        assert stub.prod_step_label.text == "视觉伺服"
        assert "40001=4" in stub.prod_plc_label.text
        assert "运行中" in stub.prod_plc_label.text
        assert stub.prod_mode_label.text == "自动"
        assert stub.prod_task_id_label.text == "abc123"

    def test_idle_state_displays_idle(self):
        raw = _build_health_raw(
            state="idle", task_id=None, hook_type=None, hook_name=None,
            flow_role=None, flow_id=None, flow_name=None, step_name=None,
            cmd_value=0,
        )
        stub = self._refresh(raw)
        assert stub.prod_state_label.text == "空闲"
        assert stub.prod_hook_label.text == "---"
        assert stub.prod_task_id_label.text == "---"

    def test_paused_state_displays_paused(self):
        raw = _build_health_raw(state="paused", cmd_value=0)
        stub = self._refresh(raw)
        assert stub.prod_state_label.text == "已暂停"

    def test_flow_error_state_displays_error(self):
        raw = _build_health_raw(state="flow_error", cmd_value=110)
        stub = self._refresh(raw)
        assert stub.prod_state_label.text == "流程错误"
        assert "40001=110" in stub.prod_plc_label.text

    def test_manual_offline_displays_manual_mode(self):
        raw = _build_health_raw(state="manual_offline", cmd_value=0)
        stub = self._refresh(raw)
        assert stub.prod_state_label.text == "手动下线"
        assert stub.prod_mode_label.text == "手动"

    def test_state_color_coding(self):
        """running → green, paused → amber, flow_error → red."""
        running = self._refresh(_build_health_raw(state="running"))
        assert "#22c55e" in running.prod_state_label.style
        paused = self._refresh(_build_health_raw(state="paused"))
        assert "#f59e0b" in paused.prod_state_label.style
        error = self._refresh(_build_health_raw(state="flow_error"))
        assert "#ef4444" in error.prod_state_label.style


# ===========================================================================
# Task 3 — State transition log
# ===========================================================================


class TestStateTransitionLog:
    def test_transition_log_includes_from_to_reason_task_id(self, caplog):
        """Log format: ProductionState transition: {old} → {new} (reason=..., task_id=...)"""
        with _runtime_agent_fixture() as (agent, _controller):
            agent._set_production_state(ProductionState.STANDBY)
            _start_running_task(agent, hook_type=0)
            task_id = agent.production_task.task_id
            with caplog.at_level(logging.INFO, logger="dobot_move.runtime.runtime_agent"):
                agent._set_production_state(
                    ProductionState.PAUSED, reason="test pause"
                )
            # Find the transition log line
            transition_logs = [
                r for r in caplog.records
                if "ProductionState transition" in r.getMessage()
            ]
            assert len(transition_logs) >= 1
            msg = transition_logs[-1].getMessage()
            assert "running" in msg
            assert "paused" in msg
            assert "test pause" in msg
            assert task_id in msg

    def test_transition_log_shows_none_task_id_when_idle(self, caplog):
        with _runtime_agent_fixture() as (agent, _controller):
            assert agent.production_task is None
            with caplog.at_level(logging.INFO, logger="dobot_move.runtime.runtime_agent"):
                agent._set_production_state(
                    ProductionState.STANDBY, reason="init"
                )
            transition_logs = [
                r for r in caplog.records
                if "ProductionState transition" in r.getMessage()
            ]
            assert len(transition_logs) >= 1
            msg = transition_logs[-1].getMessage()
            assert "task_id=None" in msg

    def test_no_log_when_state_unchanged(self, caplog):
        with _runtime_agent_fixture() as (agent, _controller):
            agent._set_production_state(ProductionState.STANDBY)
            caplog.clear()
            with caplog.at_level(logging.INFO, logger="dobot_move.runtime.runtime_agent"):
                agent._set_production_state(ProductionState.STANDBY)
            transition_logs = [
                r for r in caplog.records
                if "ProductionState transition" in r.getMessage()
            ]
            assert len(transition_logs) == 0


# ===========================================================================
# Task 4 — PLC diagnostic logs (40001 / 40002 / 40004)
# ===========================================================================


class TestPLCDiagnosticLogs:
    def test_40001_command_emits_diagnostic_log(self, caplog):
        """40001=3 → 'PLC diagnostic: 40001=3 (cmd=start_hook, mode=auto, ...)'"""
        with _runtime_agent_fixture() as (agent, _controller):
            agent._set_production_state(ProductionState.STANDBY)
            with caplog.at_level(logging.INFO, logger="dobot_move.runtime.runtime_agent"):
                agent._on_modbus_command_delegate(cmd=3, mode=0, hook_type=0)
            diagnostic_logs = [
                r for r in caplog.records
                if "PLC diagnostic: 40001=" in r.getMessage()
            ]
            assert len(diagnostic_logs) >= 1
            msg = diagnostic_logs[-1].getMessage()
            assert "40001=3" in msg
            assert "cmd=start_hook" in msg
            assert "mode=auto" in msg
            assert "hook_type=low_hook" in msg

    def test_40001_command_includes_task_id_when_running(self, caplog):
        with _runtime_agent_fixture() as (agent, _controller):
            _start_running_task(agent, hook_type=0)
            task_id = agent.production_task.task_id
            with caplog.at_level(logging.INFO, logger="dobot_move.runtime.runtime_agent"):
                agent._on_modbus_command_delegate(cmd=0, mode=0, hook_type=0)
            diagnostic_logs = [
                r for r in caplog.records
                if "PLC diagnostic: 40001=" in r.getMessage()
            ]
            assert len(diagnostic_logs) >= 1
            assert task_id in diagnostic_logs[-1].getMessage()

    def test_40002_mode_change_emits_diagnostic_log(self, caplog):
        """40002 0→1 → 'PLC diagnostic: 40002 mode auto → manual ...'"""
        with _runtime_agent_fixture() as (agent, _controller):
            agent._set_production_state(ProductionState.STANDBY)
            with caplog.at_level(logging.INFO, logger="dobot_move.runtime.runtime_agent"):
                agent._on_mode_changed(old_mode=0, new_mode=1)
            mode_logs = [
                r for r in caplog.records
                if "PLC diagnostic: 40002" in r.getMessage()
            ]
            assert len(mode_logs) >= 1
            msg = mode_logs[-1].getMessage()
            assert "auto" in msg
            assert "manual" in msg

    def test_40004_hook_type_change_emits_diagnostic_log(self, caplog):
        """40004 change → 'PLC diagnostic: 40004 hook_type low_hook → high_hook ...'"""
        with _runtime_agent_fixture() as (agent, _controller):
            with caplog.at_level(logging.INFO, logger="dobot_move.runtime.runtime_agent"):
                agent._on_hook_type_changed(old_hook=0, new_hook=1)
            hook_logs = [
                r for r in caplog.records
                if "PLC diagnostic: 40004" in r.getMessage()
            ]
            assert len(hook_logs) >= 1
            msg = hook_logs[-1].getMessage()
            assert "low_hook" in msg
            assert "high_hook" in msg

    def test_40004_change_does_not_modify_running_task(self, caplog):
        """40004 change logs even when a task is running; task.hook_type stays latched."""
        with _runtime_agent_fixture() as (agent, _controller):
            _start_running_task(agent, hook_type=0)
            original_hook = agent.production_task.hook_type
            with caplog.at_level(logging.INFO, logger="dobot_move.runtime.runtime_agent"):
                agent._on_hook_type_changed(old_hook=0, new_hook=1)
            # Task hook_type must NOT change
            assert agent.production_task.hook_type == original_hook
            hook_logs = [
                r for r in caplog.records
                if "PLC diagnostic: 40004" in r.getMessage()
            ]
            assert len(hook_logs) >= 1

    def test_40004_callback_registered_on_controller(self):
        """The runtime agent wires _on_hook_type_changed via the controller."""
        with _runtime_agent_fixture() as (_agent, controller):
            assert controller._hook_type_changed_callback is not None


# ===========================================================================
# Task 5 — task_id consistency (logs + Health JSON)
# ===========================================================================


class TestTaskIdConsistency:
    def test_health_json_task_id_matches_production_task(self):
        with _runtime_agent_fixture() as (agent, _controller):
            _start_running_task(agent, hook_type=0)
            expected = agent.production_task.task_id
            production = agent.build_health_payload()["production"]
            assert production["task_id"] == expected

    def test_transition_log_task_id_matches_health_json(self, caplog):
        with _runtime_agent_fixture() as (agent, _controller):
            _start_running_task(agent, hook_type=0)
            expected = agent.production_task.task_id
            with caplog.at_level(logging.INFO, logger="dobot_move.runtime.runtime_agent"):
                agent._set_production_state(
                    ProductionState.PAUSED, reason="consistency check"
                )
            transition_logs = [
                r for r in caplog.records
                if "ProductionState transition" in r.getMessage()
            ]
            assert len(transition_logs) >= 1
            assert expected in transition_logs[-1].getMessage()
            # Health JSON should carry the same task_id
            assert agent.build_health_payload()["production"]["task_id"] == expected

    def test_plc_diagnostic_log_task_id_matches_health_json(self, caplog):
        with _runtime_agent_fixture() as (agent, _controller):
            _start_running_task(agent, hook_type=0)
            expected = agent.production_task.task_id
            with caplog.at_level(logging.INFO, logger="dobot_move.runtime.runtime_agent"):
                agent._on_modbus_command_delegate(cmd=0, mode=0, hook_type=0)
            diagnostic_logs = [
                r for r in caplog.records
                if "PLC diagnostic: 40001=" in r.getMessage()
            ]
            assert len(diagnostic_logs) >= 1
            assert expected in diagnostic_logs[-1].getMessage()


# ===========================================================================
# Task 6 — winsound.Beep preserved as auxiliary alarm
# ===========================================================================


def _install_pymodbus_stub():
    """Stub pymodbus so the real modbus_server module can be imported."""
    pymodbus = types.ModuleType("pymodbus")

    class ModbusDeviceIdentification:
        pass

    pymodbus.ModbusDeviceIdentification = ModbusDeviceIdentification

    server = types.ModuleType("pymodbus.server")

    class ModbusTcpServer:
        pass

    server.ModbusTcpServer = ModbusTcpServer

    simulator = types.ModuleType("pymodbus.simulator")

    class SimData:
        def __init__(self, *args, **kwargs):
            pass

    class SimDevice:
        def __init__(self, *args, **kwargs):
            pass

    class DataType:
        REGISTERS = "registers"

    simulator.SimData = SimData
    simulator.SimDevice = SimDevice
    simulator.DataType = DataType

    sys.modules["pymodbus"] = pymodbus
    sys.modules["pymodbus.server"] = server
    sys.modules["pymodbus.simulator"] = simulator


def _real_modbus_server():
    """Import the real modbus_server module (with pymodbus stubbed)."""
    sys.modules.pop("dobot_move.communication.modbus_server", None)
    try:
        modbus_server = importlib.import_module(
            "dobot_move.communication.modbus_server"
        )
    except ImportError as exc:
        if "pymodbus" not in str(exc):
            raise
        _install_pymodbus_stub()
        sys.modules.pop("dobot_move.communication.modbus_server", None)
        modbus_server = importlib.import_module(
            "dobot_move.communication.modbus_server"
        )
    return modbus_server


class TestWinsoundBeepPreserved:
    def test_110_triggers_winsound_beep(self):
        """40001=110 (flow_error) triggers winsound.Beep when available."""
        modbus_server = _real_modbus_server()
        fake_winsound = MagicMock()
        # Inject the mock winsound module + flag
        modbus_server.winsound = fake_winsound
        modbus_server._HAS_WINSOUND = True
        try:
            server = modbus_server.DobotModbusServer()
            # current_registers: [40001=0 (old), 40002=0, 40003=0]
            asyncio.run(
                server._action_callback(
                    function_code=16,
                    start_address=0,
                    address=0,
                    count=1,
                    current_registers=[0, modbus_server.MODE_AUTO, 0],
                    set_values=[110],
                )
            )
            assert fake_winsound.Beep.called
            call_args = fake_winsound.Beep.call_args
            assert call_args[0] == (1000, 500)
        finally:
            # Restore module state
            modbus_server._HAS_WINSOUND = False
            if hasattr(modbus_server, "winsound"):
                del modbus_server.winsound

    def test_111_triggers_winsound_beep(self):
        modbus_server = _real_modbus_server()
        fake_winsound = MagicMock()
        modbus_server.winsound = fake_winsound
        modbus_server._HAS_WINSOUND = True
        try:
            server = modbus_server.DobotModbusServer()
            asyncio.run(
                server._action_callback(
                    function_code=16,
                    start_address=0,
                    address=0,
                    count=1,
                    current_registers=[0, modbus_server.MODE_AUTO, 0],
                    set_values=[111],
                )
            )
            assert fake_winsound.Beep.called
        finally:
            modbus_server._HAS_WINSOUND = False
            if hasattr(modbus_server, "winsound"):
                del modbus_server.winsound

    def test_112_triggers_winsound_beep(self):
        modbus_server = _real_modbus_server()
        fake_winsound = MagicMock()
        modbus_server.winsound = fake_winsound
        modbus_server._HAS_WINSOUND = True
        try:
            server = modbus_server.DobotModbusServer()
            asyncio.run(
                server._action_callback(
                    function_code=16,
                    start_address=0,
                    address=0,
                    count=1,
                    current_registers=[0, modbus_server.MODE_AUTO, 0],
                    set_values=[112],
                )
            )
            assert fake_winsound.Beep.called
        finally:
            modbus_server._HAS_WINSOUND = False
            if hasattr(modbus_server, "winsound"):
                del modbus_server.winsound

    def test_non_alarm_value_does_not_trigger_beep(self):
        """40001=4 (running) must NOT trigger winsound.Beep."""
        modbus_server = _real_modbus_server()
        fake_winsound = MagicMock()
        modbus_server.winsound = fake_winsound
        modbus_server._HAS_WINSOUND = True
        try:
            server = modbus_server.DobotModbusServer()
            asyncio.run(
                server._action_callback(
                    function_code=16,
                    start_address=0,
                    address=0,
                    count=1,
                    current_registers=[0, modbus_server.MODE_AUTO, 0],
                    set_values=[4],
                )
            )
            assert not fake_winsound.Beep.called
        finally:
            modbus_server._HAS_WINSOUND = False
            if hasattr(modbus_server, "winsound"):
                del modbus_server.winsound

    def test_beep_silent_when_winsound_unavailable(self):
        """When _HAS_WINSOUND is False, 110 does not raise and no beep fires."""
        modbus_server = _real_modbus_server()
        fake_winsound = MagicMock()
        modbus_server.winsound = fake_winsound
        modbus_server._HAS_WINSOUND = False
        try:
            server = modbus_server.DobotModbusServer()
            # Should not raise even though winsound is unavailable
            asyncio.run(
                server._action_callback(
                    function_code=16,
                    start_address=0,
                    address=0,
                    count=1,
                    current_registers=[0, modbus_server.MODE_AUTO, 0],
                    set_values=[110],
                )
            )
            assert not fake_winsound.Beep.called
        finally:
            if hasattr(modbus_server, "winsound"):
                del modbus_server.winsound

    def test_source_contains_auxiliary_alarm_comment(self):
        """The winsound.Beep block documents that production alarms don't
        depend on the Windows audio system (PR 5 Task 6)."""
        modbus_server = _real_modbus_server()
        import inspect
        source = inspect.getsource(modbus_server)
        assert "生产报警不依赖 Windows 音频系统" in source
        assert "PLC 侧通过" in source
