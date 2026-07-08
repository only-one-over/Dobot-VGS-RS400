"""PR 3 — Production state machine tests.

Covers Tasks 1-13 of the implement-production-state-machine spec:
* Unit tests for production_state / production_context /
  production_flow_router / reset_strategy (Tasks 1-4).
* Unit test for RuntimeProgramRunner.build_production_request (Task 5).
* Integration tests for the runtime_agent state machine (Tasks 6-13),
  mapped to the 10 acceptance scenarios:
    Test 1  — 低钩选择 (low hook selection)
    Test 2  — 高钩选择 (high hook selection)
    Test 3  — 非法40004 (invalid hook type)
    Test 4  — 类型锁存 (hook type latching)
    Test 5  — 自动暂停 (auto pause)
    Test 6  — 恢复流程 (resume)
    Test 7  — 手动模式 (manual offline)
    Test 8  — 重新上线 (re-online)
    Test 9  — 扶钩状态 (holding hook)
    Test 10 — 扶钩后复位 (reset after holding hook)
"""
from __future__ import annotations

import sys
import types

# Install a minimal modbus_server stub BEFORE importing runtime_agent,
# mirroring the pattern in test_production_debug_flow_separation.py.
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
from contextlib import contextmanager  # noqa: E402
from pathlib import Path  # noqa: E402
from unittest.mock import MagicMock  # noqa: E402

import pytest  # noqa: E402

from dobot_move.runtime.production_context import ProductionTaskContext  # noqa: E402
from dobot_move.runtime.production_flow_router import ProductionFlowRouter  # noqa: E402
from dobot_move.flow.flow_result import FlowResult  # noqa: E402
from dobot_move.runtime.production_state import (  # noqa: E402
    ERROR_STATES,
    MODBUS_STATUS_MAP,
    ProductionState,
)
from dobot_move.runtime.reset_strategy import ResetStrategy  # noqa: E402
from dobot_move.runtime.runtime_agent import (  # noqa: E402
    DobotRuntimeAgent,
    RuntimeExecutionRequest,
    RuntimeProgramRunner,
)


# ===========================================================================
# Task 1.4 — production_state unit tests
# ===========================================================================


class TestProductionState:
    def test_enum_has_all_states(self):
        expected = {
            "manual_offline",
            "idle",
            "standby",
            "starting",
            "running",
            "paused",
            "holding_hook",
            "resetting",
            "error_recovery",
            "flow_error",
            "robot_error",
            "camera_error",
        }
        actual = {s.value for s in ProductionState}
        assert actual == expected

    def test_modbus_status_map_covers_mapped_states(self):
        assert MODBUS_STATUS_MAP[ProductionState.IDLE] == 0
        assert MODBUS_STATUS_MAP[ProductionState.STANDBY] == 2
        assert MODBUS_STATUS_MAP[ProductionState.RUNNING] == 4
        assert MODBUS_STATUS_MAP[ProductionState.PAUSED] == 0
        assert MODBUS_STATUS_MAP[ProductionState.HOLDING_HOOK] == 5
        assert MODBUS_STATUS_MAP[ProductionState.FLOW_ERROR] == 110
        assert MODBUS_STATUS_MAP[ProductionState.ROBOT_ERROR] == 111
        assert MODBUS_STATUS_MAP[ProductionState.CAMERA_ERROR] == 112

    def test_error_states_frozenset(self):
        assert ERROR_STATES == frozenset(
            {
                ProductionState.FLOW_ERROR,
                ProductionState.ROBOT_ERROR,
                ProductionState.CAMERA_ERROR,
            }
        )
        # MANUAL_OFFLINE / RESETTING / ERROR_RECOVERY are intentionally
        # absent from MODBUS_STATUS_MAP (no PLC-facing code).
        assert ProductionState.MANUAL_OFFLINE not in MODBUS_STATUS_MAP
        assert ProductionState.RESETTING not in MODBUS_STATUS_MAP
        assert ProductionState.ERROR_RECOVERY not in MODBUS_STATUS_MAP


# ===========================================================================
# Task 2.3 — production_context unit tests
# ===========================================================================


class TestProductionTaskContext:
    def test_create_factory_generates_task_id_and_started_at(self):
        ctx = ProductionTaskContext.create(
            hook_type=0,
            primary_flow_id="flow-low",
            recovery_flow_id="flow-recovery",
            state="running",
        )
        assert isinstance(ctx.task_id, str) and len(ctx.task_id) > 0
        assert ctx.hook_type == 0
        assert ctx.primary_flow_id == "flow-low"
        assert ctx.recovery_flow_id == "flow-recovery"
        assert ctx.state == "running"
        assert ctx.started_at > 0

    def test_default_field_values(self):
        ctx = ProductionTaskContext(
            task_id="abc",
            hook_type=1,
            primary_flow_id="f1",
            recovery_flow_id="f2",
            state="running",
            started_at=1.0,
        )
        assert ctx.paused_at_step is None
        assert ctx.failure_code is None
        assert ctx.failure_kind is None
        assert ctx.recovery_started is False

    def test_task_id_is_unique(self):
        ctx1 = ProductionTaskContext.create(
            hook_type=0,
            primary_flow_id="a",
            recovery_flow_id="b",
            state="running",
        )
        ctx2 = ProductionTaskContext.create(
            hook_type=0,
            primary_flow_id="a",
            recovery_flow_id="b",
            state="running",
        )
        assert ctx1.task_id != ctx2.task_id


# ===========================================================================
# Task 3.6 — production_flow_router unit tests
# ===========================================================================


class TestProductionFlowRouter:
    def _make_router(self):
        return ProductionFlowRouter(
            {
                "low_hook": "flow-low",
                "high_hook": "flow-high",
                "error_recovery": "flow-recovery",
            }
        )

    def test_resolve_primary_low_hook(self):
        assert self._make_router().resolve_primary(0) == "flow-low"

    def test_resolve_primary_high_hook(self):
        assert self._make_router().resolve_primary(1) == "flow-high"

    def test_resolve_primary_invalid_hook_type_raises(self):
        with pytest.raises(ValueError):
            self._make_router().resolve_primary(2)

    def test_resolve_primary_negative_raises(self):
        with pytest.raises(ValueError):
            self._make_router().resolve_primary(-1)

    def test_resolve_recovery(self):
        assert self._make_router().resolve_recovery() == "flow-recovery"

    def test_resolve_primary_missing_role_raises(self):
        router = ProductionFlowRouter({"low_hook": "f1"})  # no high_hook
        with pytest.raises(ValueError):
            router.resolve_primary(1)

    def test_resolve_recovery_missing_role_raises(self):
        router = ProductionFlowRouter({"low_hook": "f1"})
        with pytest.raises(ValueError):
            router.resolve_recovery()


# ===========================================================================
# Task 4.6 — reset_strategy unit tests
# ===========================================================================


class TestResetStrategy:
    def _make_mocks(self, connected=True):
        controller = MagicMock()
        controller.is_connected = connected
        controller.dashboard = MagicMock()
        controller.move_to_initial_position.return_value = True
        controller.clear_error.return_value = None
        controller.enable_robot.return_value = True
        program_runner = MagicMock()
        program_runner.stop.return_value = True
        return controller, program_runner

    def test_holding_hook_path_calls_move_to_initial(self):
        controller, program_runner = self._make_mocks()
        ok = ResetStrategy().execute(
            ProductionState.HOLDING_HOOK, controller, program_runner
        )
        assert ok is True
        program_runner.stop.assert_called_once()
        controller.move_to_initial_position.assert_called_once()
        # Should NOT call clear_error / enable_robot for HOLDING_HOOK path
        controller.clear_error.assert_not_called()

    def test_paused_path_calls_stop_and_move_to_initial(self):
        controller, program_runner = self._make_mocks()
        ok = ResetStrategy().execute(
            ProductionState.PAUSED, controller, program_runner
        )
        assert ok is True
        program_runner.stop.assert_called_once()
        controller.dashboard.Stop.assert_called_once()
        controller.move_to_initial_position.assert_called_once()

    def test_error_path_clears_and_enables(self):
        controller, program_runner = self._make_mocks()
        ok = ResetStrategy().execute(
            ProductionState.FLOW_ERROR, controller, program_runner
        )
        assert ok is True
        controller.clear_error.assert_called_once()
        controller.enable_robot.assert_called_once()
        controller.move_to_initial_position.assert_called_once()

    def test_error_path_fails_when_enable_returns_false(self):
        controller, program_runner = self._make_mocks()
        controller.enable_robot.return_value = False
        ok = ResetStrategy().execute(
            ProductionState.ROBOT_ERROR, controller, program_runner
        )
        assert ok is False

    def test_manual_offline_uses_error_path(self):
        controller, program_runner = self._make_mocks()
        ok = ResetStrategy().execute(
            ProductionState.MANUAL_OFFLINE, controller, program_runner
        )
        assert ok is True
        controller.clear_error.assert_called_once()
        controller.enable_robot.assert_called_once()

    def test_move_failure_returns_false(self):
        controller, program_runner = self._make_mocks()
        controller.move_to_initial_position.return_value = False
        ok = ResetStrategy().execute(
            ProductionState.HOLDING_HOOK, controller, program_runner
        )
        assert ok is False


# ===========================================================================
# Task 5.3 — RuntimeProgramRunner.build_production_request unit test
# ===========================================================================
# build_production_request delegates to build_request(mode="production",
# flow_id=flow_id). We verify the delegation by mocking build_request.


class TestBuildProductionRequest:
    def test_build_production_request_sets_mode_production(self):
        runner = RuntimeProgramRunner.__new__(RuntimeProgramRunner)
        captured: dict = {}

        def fake_build_request(*, mode, flow_id=None, **kwargs):
            captured["mode"] = mode
            captured["flow_id"] = flow_id
            return RuntimeExecutionRequest(
                mode=mode,
                flow_id=flow_id or "test",
                flow_name="Test",
                modules=[],
                config={},
                revision="rev",
            )

        runner.build_request = fake_build_request  # type: ignore[assignment]
        runner.build_production_request("flow-low")
        assert captured["mode"] == "production"
        assert captured["flow_id"] == "flow-low"


# ===========================================================================
# Integration tests — runtime_agent state machine (Tasks 6-13, Test 1-10)
# ===========================================================================


class _FakeDashboard:
    def __init__(self):
        self.stop_calls = 0

    def Stop(self):
        self.stop_calls += 1
        return "0,0,0;"


class _FakeController:
    """Controller stub supporting PR 3 delegate + mode-changed callbacks."""

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
        # PR 3 tracking
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

    # PR 3 motion primitives
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
    """Create a DobotRuntimeAgent with PR 3 wiring intact.

    The _FakeController accepts the 3-arg set_modbus_program_runner
    signature so command_delegate + mode_changed_callback are registered.
    """
    temp_dir = Path.cwd() / f"_prod_sm_test_{uuid.uuid4().hex}"
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
        # Install a real ProductionFlowRouter with known role mappings.
        agent.flow_router = ProductionFlowRouter(
            {
                "low_hook": "flow-low",
                "high_hook": "flow-high",
                "error_recovery": "flow-recovery",
            }
        )
        # Mock program_runner heavy methods; keep pause/resume/stop as
        # real no-ops by replacing them with MagicMock(return_value=True).
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


# ---------------------------------------------------------------------------
# Test 1 — 低钩选择 (low hook selection)
# ---------------------------------------------------------------------------


class TestLowHookSelection:
    def test_standby_plus_hook_3_low_hook_starts_low_flow(self):
        """STANDBY + 40001=3 + 40004=0 → starts low_hook flow, state=RUNNING."""
        with _runtime_agent_fixture() as (agent, controller):
            agent._set_production_state(ProductionState.STANDBY)
            controller.written_statuses.clear()
            # Dispatch 40001=3, mode=AUTO, hook_type=0 (low)
            agent._dispatch_command(cmd=3, mode=0, hook_type=0)
            assert agent.production_state == ProductionState.RUNNING
            assert agent.production_task is not None
            assert agent.production_task.hook_type == 0
            assert agent.production_task.primary_flow_id == "flow-low"
            agent.program_runner.build_production_request.assert_called_once_with(
                "flow-low", task_id=agent.production_task.task_id
            )
            # 40001 should be written to 4 (RUNNING)
            assert (4, 0) in controller.written_statuses


# ---------------------------------------------------------------------------
# Test 2 — 高钩选择 (high hook selection)
# ---------------------------------------------------------------------------


class TestHighHookSelection:
    def test_standby_plus_hook_3_high_hook_starts_high_flow(self):
        """STANDBY + 40001=3 + 40004=1 → starts high_hook flow."""
        with _runtime_agent_fixture() as (agent, controller):
            agent._set_production_state(ProductionState.STANDBY)
            controller.written_statuses.clear()
            agent._dispatch_command(cmd=3, mode=0, hook_type=1)
            assert agent.production_state == ProductionState.RUNNING
            assert agent.production_task is not None
            assert agent.production_task.hook_type == 1
            assert agent.production_task.primary_flow_id == "flow-high"
            agent.program_runner.build_production_request.assert_called_once_with(
                "flow-high", task_id=agent.production_task.task_id
            )


# ---------------------------------------------------------------------------
# Test 3 — 非法40004 (invalid hook type)
# ---------------------------------------------------------------------------


class TestInvalidHookType:
    def test_invalid_hook_type_transitions_to_flow_error(self):
        """STANDBY + 40001=3 + 40004=2 → FLOW_ERROR (ValueError from router)."""
        with _runtime_agent_fixture() as (agent, controller):
            agent._set_production_state(ProductionState.STANDBY)
            controller.written_statuses.clear()
            # hook_type=2 is invalid; flow_router.resolve_primary raises ValueError
            agent._dispatch_command(cmd=3, mode=0, hook_type=2)
            assert agent.production_state == ProductionState.FLOW_ERROR
            assert agent.production_task is None
            # 40001 should be written to 110 (FLOW_ERROR)
            assert (110, 0) in controller.written_statuses
            # start_request must NOT have been called
            agent.program_runner.start_request.assert_not_called()


# ---------------------------------------------------------------------------
# Test 4 — 类型锁存 (hook type latching)
# ---------------------------------------------------------------------------


class TestHookTypeLatching:
    def test_mid_run_hook_type_change_does_not_modify_task(self):
        """Task running with hook_type=0; PLC changes 40004=1; task.hook_type stays 0."""
        with _runtime_agent_fixture() as (agent, controller):
            agent._set_production_state(ProductionState.STANDBY)
            # Start a low-hook task
            agent._dispatch_command(cmd=3, mode=0, hook_type=0)
            assert agent.production_task is not None
            original_task_id = agent.production_task.task_id
            assert agent.production_task.hook_type == 0
            # PLC sends another 40001=3 with hook_type=1 while RUNNING.
            # Per spec, RUNNING state ignores duplicate 40001=3.
            agent._dispatch_command(cmd=3, mode=0, hook_type=1)
            assert agent.production_state == ProductionState.RUNNING
            assert agent.production_task.hook_type == 0
            assert agent.production_task.task_id == original_task_id
            assert agent.production_task.primary_flow_id == "flow-low"


# ---------------------------------------------------------------------------
# Test 5 — 自动暂停 (auto pause)
# ---------------------------------------------------------------------------


class TestAutoPause:
    def test_running_plus_cmd_0_pauses_and_retains_task(self):
        """RUNNING + 40001=0 (auto mode) → PAUSED, task retained, no stop_event.set."""
        with _runtime_agent_fixture() as (agent, controller):
            agent._set_production_state(ProductionState.STANDBY)
            agent._dispatch_command(cmd=3, mode=0, hook_type=0)
            task = agent.production_task
            assert task is not None
            original_task_id = task.task_id
            controller.written_statuses.clear()
            # 40001=0 in auto mode → delegate returns True (pause handled)
            agent._dispatch_command(cmd=0, mode=0, hook_type=0)
            assert agent.production_state == ProductionState.PAUSED
            # Task MUST be retained
            assert agent.production_task is not None
            assert agent.production_task.task_id == original_task_id
            # paused_at_step should be recorded from current_module_index
            assert agent.production_task.paused_at_step == 2
            # program_runner.pause + controller.pause called
            agent.program_runner.pause.assert_called_once()
            assert controller.pause_calls == 1
            # 40001 written to 0 (PAUSED maps to 0)
            assert (0, 0) in controller.written_statuses

    def test_pause_in_non_running_state_enqueued_no_state_change(self):
        """40001=0 when not RUNNING → delegate enqueues (returns True);
        _dispatch_command no-ops (no state change)."""
        with _runtime_agent_fixture() as (agent, _controller):
            agent._set_production_state(ProductionState.STANDBY)
            # PR 5 Task 4: auto-mode commands are always consumed (enqueued).
            handled = agent._on_modbus_command_delegate(cmd=0, mode=0, hook_type=0)
            assert handled is True
            # _handle_pause_command is a no-op outside RUNNING.
            agent._dispatch_command(cmd=0, mode=0, hook_type=0)
            assert agent.production_state == ProductionState.STANDBY


# ---------------------------------------------------------------------------
# Test 6 — 恢复流程 (resume)
# ---------------------------------------------------------------------------


class TestResumeFlow:
    def test_paused_plus_hook_3_resumes_without_new_task_id(self):
        """PAUSED + 40001=3 → RUNNING, same task_id, no 40004 re-read."""
        with _runtime_agent_fixture() as (agent, controller):
            agent._set_production_state(ProductionState.STANDBY)
            agent._dispatch_command(cmd=3, mode=0, hook_type=0)
            task = agent.production_task
            assert task is not None
            original_task_id = task.task_id
            # Pause
            agent._dispatch_command(cmd=0, mode=0, hook_type=0)
            assert agent.production_state == ProductionState.PAUSED
            controller.written_statuses.clear()
            # Resume with 40001=3 (hook_type arg ignored in PAUSED path)
            agent._dispatch_command(cmd=3, mode=0, hook_type=1)
            assert agent.production_state == ProductionState.RUNNING
            assert agent.production_task is not None
            assert agent.production_task.task_id == original_task_id
            # hook_type MUST NOT change (no 40004 re-read)
            assert agent.production_task.hook_type == 0
            # program_runner.resume + controller.continue_motion called
            agent.program_runner.resume.assert_called_once()
            assert controller.continue_calls == 1
            # 40001 written to 4 (RUNNING)
            assert (4, 0) in controller.written_statuses
            # build_production_request must NOT be called again (no new task)
            agent.program_runner.build_production_request.assert_called_once()


# ---------------------------------------------------------------------------
# Test 7 — 手动模式 (manual offline)
# ---------------------------------------------------------------------------


class TestManualOffline:
    def test_mode_0_to_1_triggers_manual_offline(self):
        """40002 0→1 → MANUAL_OFFLINE, manual_offline=True, task cleared."""
        with _runtime_agent_fixture() as (agent, controller):
            agent._set_production_state(ProductionState.STANDBY)
            agent._dispatch_command(cmd=3, mode=0, hook_type=0)
            assert agent.production_task is not None
            # Simulate 40002 0→1 via the mode-changed callback
            agent._on_mode_changed(old_mode=0, new_mode=1)
            assert agent.production_state == ProductionState.MANUAL_OFFLINE
            assert agent.manual_offline is True
            assert agent.supervisor.manual_offline is True
            assert agent.production_task is None
            # Robot connection should be closed
            assert controller.close_transport_calls >= 1
            # program_runner.stop called
            agent.program_runner.stop.assert_called()
            # dashboard.Stop called
            assert controller.dashboard.stop_calls >= 1

    def test_supervisor_manual_offline_skips_reconnect(self):
        """RobotConnectionSupervisor.step() must not attempt reconnect when manual_offline."""
        with _runtime_agent_fixture() as (agent, controller):
            controller.is_connected = False
            agent.supervisor.manual_offline = True
            state = agent.supervisor.step()
            # Should return current state without attempting connect
            assert state == agent.supervisor.state


# ---------------------------------------------------------------------------
# Test 8 — 重新上线 (re-online)
# ---------------------------------------------------------------------------


class TestReOnline:
    def test_manual_offline_plus_mode_0_then_cmd_1_reonlines(self):
        """MANUAL_OFFLINE + 40002=0 + 40001=1 → STANDBY + 40001=2."""
        with _runtime_agent_fixture() as (agent, controller):
            agent._set_production_state(ProductionState.STANDBY)
            agent._dispatch_command(cmd=3, mode=0, hook_type=0)
            # Go manual offline
            agent._on_mode_changed(old_mode=0, new_mode=1)
            assert agent.production_state == ProductionState.MANUAL_OFFLINE
            assert agent.manual_offline is True
            # 40002 1→0: should NOT immediately re-online (deferred to 40001=1)
            agent._on_mode_changed(old_mode=1, new_mode=0)
            assert agent.production_state == ProductionState.MANUAL_OFFLINE
            # Now 40001=1 triggers re-online
            controller.written_statuses.clear()
            # controller.is_connected is True in the fixture
            agent._dispatch_command(cmd=1, mode=0, hook_type=0)
            assert agent.production_state == ProductionState.STANDBY
            assert agent.manual_offline is False
            assert agent.supervisor.manual_offline is False
            # ResetStrategy (ERROR path for MANUAL_OFFLINE) should clear+enable+move
            assert controller.clear_error_calls >= 1
            assert controller.enable_calls >= 1
            assert controller.move_to_initial_calls >= 1
            # 40001 written to 2 (STANDBY)
            assert (2, 0) in controller.written_statuses


# ---------------------------------------------------------------------------
# Test 9 — 扶钩状态 (holding hook)
# ---------------------------------------------------------------------------


class TestHoldingHook:
    def test_production_flow_success_transitions_to_holding_hook(self):
        """Main flow success → HOLDING_HOOK + 40001=5 + task retained."""
        with _runtime_agent_fixture() as (agent, controller):
            agent._set_production_state(ProductionState.STANDBY)
            agent._dispatch_command(cmd=3, mode=0, hook_type=0)
            task = agent.production_task
            assert task is not None
            original_task_id = task.task_id
            controller.written_statuses.clear()
            # Simulate program_runner completion callback (success)
            agent._on_production_flow_finished(FlowResult.success_result())
            assert agent.production_state == ProductionState.HOLDING_HOOK
            # Task MUST be retained (not cleared)
            assert agent.production_task is not None
            assert agent.production_task.task_id == original_task_id
            # 40001 written to 5 (HOLDING_HOOK)
            assert (5, 0) in controller.written_statuses

    def test_holding_hook_rejects_cmd_3(self):
        """HOLDING_HOOK + 40001=3 → rejected (no state change)."""
        with _runtime_agent_fixture() as (agent, controller):
            agent._set_production_state(ProductionState.HOLDING_HOOK)
            agent.production_task = ProductionTaskContext.create(
                hook_type=0,
                primary_flow_id="flow-low",
                recovery_flow_id="flow-recovery",
                state="holding_hook",
            )
            agent._dispatch_command(cmd=3, mode=0, hook_type=0)
            assert agent.production_state == ProductionState.HOLDING_HOOK
            # No new task started
            agent.program_runner.start_request.assert_not_called()


# ---------------------------------------------------------------------------
# Test 10 — 扶钩后复位 (reset after holding hook)
# ---------------------------------------------------------------------------


class TestResetAfterHoldingHook:
    def test_holding_hook_plus_cmd_1_resets_to_standby(self):
        """HOLDING_HOOK + 40001=1 → RESETTING → STANDBY + 40001=2 + task cleared."""
        with _runtime_agent_fixture() as (agent, controller):
            agent._set_production_state(ProductionState.HOLDING_HOOK)
            agent.production_task = ProductionTaskContext.create(
                hook_type=0,
                primary_flow_id="flow-low",
                recovery_flow_id="flow-recovery",
                state="holding_hook",
            )
            controller.written_statuses.clear()
            agent._dispatch_command(cmd=1, mode=0, hook_type=0)
            # Final state STANDBY
            assert agent.production_state == ProductionState.STANDBY
            # Task cleared
            assert agent.production_task is None
            # ResetStrategy (HOLDING_HOOK path) calls move_to_initial
            assert controller.move_to_initial_calls >= 1
            # 40001 written to 2 (STANDBY)
            assert (2, 0) in controller.written_statuses

    def test_reset_failure_transitions_to_flow_error(self):
        """HOLDING_HOOK + 40001=1 + move fails → FLOW_ERROR + 40001=110."""
        with _runtime_agent_fixture() as (agent, controller):
            agent._set_production_state(ProductionState.HOLDING_HOOK)
            agent.production_task = ProductionTaskContext.create(
                hook_type=0,
                primary_flow_id="flow-low",
                recovery_flow_id="flow-recovery",
                state="holding_hook",
            )
            controller.move_to_initial_return = False
            controller.written_statuses.clear()
            agent._dispatch_command(cmd=1, mode=0, hook_type=0)
            assert agent.production_state == ProductionState.FLOW_ERROR
            assert (110, 0) in controller.written_statuses


# ---------------------------------------------------------------------------
# Additional state-machine coverage (Tasks 6-13 edge cases)
# ===========================================================================


class TestRunningIgnoresDuplicateHook:
    def test_running_plus_hook_3_ignored(self):
        """RUNNING + 40001=3 → ignored, no new task."""
        with _runtime_agent_fixture() as (agent, _controller):
            agent._set_production_state(ProductionState.STANDBY)
            agent._dispatch_command(cmd=3, mode=0, hook_type=0)
            assert agent.production_state == ProductionState.RUNNING
            call_count = agent.program_runner.build_production_request.call_count
            # Duplicate 40001=3
            agent._dispatch_command(cmd=3, mode=0, hook_type=0)
            assert agent.production_state == ProductionState.RUNNING
            assert agent.program_runner.build_production_request.call_count == call_count


class TestResettingStateGuards:
    def test_resetting_ignores_hook_command(self):
        """RESETTING + 40001=3 → ignored (only 40001=0 falls through)."""
        with _runtime_agent_fixture() as (agent, _controller):
            agent._set_production_state(ProductionState.RESETTING)
            agent._dispatch_command(cmd=3, mode=0, hook_type=0)
            # delegate owns it (rejected); state unchanged
            assert agent.production_state == ProductionState.RESETTING

    def test_resetting_stop_enqueued_no_state_change(self):
        """RESETTING + 40001=0 → delegate enqueues (returns True);
        _dispatch_command no-ops (RESETTING guard, no state change)."""
        with _runtime_agent_fixture() as (agent, _controller):
            agent._set_production_state(ProductionState.RESETTING)
            # PR 5 Task 4: auto-mode commands are always consumed (enqueued).
            handled = agent._on_modbus_command_delegate(cmd=0, mode=0, hook_type=0)
            assert handled is True
            # _dispatch_command no-ops for CMD_STOP in RESETTING.
            agent._dispatch_command(cmd=0, mode=0, hook_type=0)
            assert agent.production_state == ProductionState.RESETTING


class TestManualModeFallthrough:
    def test_manual_mode_commands_fall_through(self):
        """mode=MANUAL → delegate returns False for all commands."""
        with _runtime_agent_fixture() as (agent, _controller):
            agent._set_production_state(ProductionState.STANDBY)
            # mode=1 (MANUAL) — all commands fall through
            assert agent._on_modbus_command_delegate(cmd=3, mode=1, hook_type=0) is False
            assert agent._on_modbus_command_delegate(cmd=0, mode=1, hook_type=0) is False
            assert agent._on_modbus_command_delegate(cmd=1, mode=1, hook_type=0) is False


class TestStartNewTaskGuards:
    def test_maintenance_mode_blocks_new_task(self):
        with _runtime_agent_fixture() as (agent, _controller):
            agent._set_production_state(ProductionState.STANDBY)
            agent.maintenance_mode = True
            agent._dispatch_command(cmd=3, mode=0, hook_type=0)
            assert agent.production_state == ProductionState.STANDBY
            agent.program_runner.start_request.assert_not_called()

    def test_debug_task_blocks_new_production_task(self):
        with _runtime_agent_fixture() as (agent, _controller):
            agent._set_production_state(ProductionState.STANDBY)
            agent.program_runner.task_mode = "debug"
            agent._dispatch_command(cmd=3, mode=0, hook_type=0)
            assert agent.production_state == ProductionState.STANDBY
            agent.program_runner.start_request.assert_not_called()

    def test_start_request_rejection_does_not_advance_state(self):
        with _runtime_agent_fixture() as (agent, _controller):
            agent._set_production_state(ProductionState.STANDBY)
            agent.program_runner.start_request = MagicMock(return_value=False)
            agent._dispatch_command(cmd=3, mode=0, hook_type=0)
            assert agent.production_state == ProductionState.STANDBY
            assert agent.production_task is None


class TestProductionFlowFailure:
    def test_production_flow_failure_transitions_to_flow_error(self):
        with _runtime_agent_fixture() as (agent, controller):
            agent._set_production_state(ProductionState.STANDBY)
            agent._dispatch_command(cmd=3, mode=0, hook_type=0)
            controller.written_statuses.clear()
            agent._on_production_flow_finished(
                FlowResult.failure(
                    code="TEST_FAIL",
                    message="primary flow failed",
                    failure_kind="flow",
                    recoverable=False,
                )
            )
            assert agent.production_state == ProductionState.FLOW_ERROR
            assert (110, 0) in controller.written_statuses


class TestResetFromPaused:
    def test_paused_plus_cmd_1_resets_to_standby(self):
        """PAUSED + 40001=1 → RESETTING → STANDBY + task cleared."""
        with _runtime_agent_fixture() as (agent, controller):
            agent._set_production_state(ProductionState.STANDBY)
            agent._dispatch_command(cmd=3, mode=0, hook_type=0)
            agent._dispatch_command(cmd=0, mode=0, hook_type=0)
            assert agent.production_state == ProductionState.PAUSED
            controller.written_statuses.clear()
            agent._dispatch_command(cmd=1, mode=0, hook_type=0)
            assert agent.production_state == ProductionState.STANDBY
            assert agent.production_task is None
            assert controller.move_to_initial_calls >= 1
            assert (2, 0) in controller.written_statuses


class TestResetFromError:
    def test_flow_error_plus_cmd_1_resets_to_standby(self):
        """FLOW_ERROR + 40001=1 → RESETTING → STANDBY + task cleared."""
        with _runtime_agent_fixture() as (agent, controller):
            agent._set_production_state(ProductionState.FLOW_ERROR)
            controller.written_statuses.clear()
            agent._dispatch_command(cmd=1, mode=0, hook_type=0)
            assert agent.production_state == ProductionState.STANDBY
            assert controller.clear_error_calls >= 1
            assert controller.enable_calls >= 1
            assert controller.move_to_initial_calls >= 1
            assert (2, 0) in controller.written_statuses


class TestReonlineNotConnected:
    def test_reonline_when_not_connected_defers_reset(self):
        """Re-online when robot not connected → manual_offline cleared, reset deferred."""
        with _runtime_agent_fixture() as (agent, controller):
            agent._set_production_state(ProductionState.MANUAL_OFFLINE)
            agent.manual_offline = True
            agent.supervisor.manual_offline = True
            controller.is_connected = False
            controller.written_statuses.clear()
            agent._dispatch_command(cmd=1, mode=0, hook_type=0)
            # manual_offline flags cleared
            assert agent.manual_offline is False
            assert agent.supervisor.manual_offline is False
            # Reset deferred — state stays MANUAL_OFFLINE (no STANDBY transition)
            assert agent.production_state == ProductionState.MANUAL_OFFLINE
            # 40001=2 NOT written (reset hasn't completed)
            assert (2, 0) not in controller.written_statuses


class TestSetProductionState:
    def test_state_transition_writes_modbus_status(self):
        with _runtime_agent_fixture() as (agent, controller):
            controller.written_statuses.clear()
            agent._set_production_state(ProductionState.STANDBY)
            assert (2, 0) in controller.written_statuses

    def test_same_state_no_transition(self):
        with _runtime_agent_fixture() as (agent, controller):
            agent._set_production_state(ProductionState.STANDBY)
            controller.written_statuses.clear()
            agent._set_production_state(ProductionState.STANDBY)
            assert controller.written_statuses == []

    def test_state_without_mapping_skips_40001_write(self):
        with _runtime_agent_fixture() as (agent, controller):
            controller.written_statuses.clear()
            agent._set_production_state(ProductionState.RESETTING)
            # RESETTING has no MODBUS_STATUS_MAP entry
            assert controller.written_statuses == []

    def test_state_transition_updates_task_state(self):
        with _runtime_agent_fixture() as (agent, _controller):
            agent.production_task = ProductionTaskContext.create(
                hook_type=0,
                primary_flow_id="f",
                recovery_flow_id="r",
                state="standby",
            )
            agent._set_production_state(ProductionState.RUNNING)
            assert agent.production_task.state == "running"
