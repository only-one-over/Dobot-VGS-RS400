# -*- coding: utf-8 -*-
"""PR 4 — Error recovery policy tests.

Covers Tasks 1-8 of the add-flow-recovery-policy spec:
  * FlowResult dataclass + factory methods (Task 1)
  * RecoveryPolicy.can_recover (Task 3)
  * ERROR_RECOVERY state integration (Task 4)
  * 110/111/112 error classification (Task 5)
  * Serial recovery execution (Task 6)
  * recovery_started anti-recursion (Task 7)
  * Recovery success does NOT change primary error code (Task 8)

Mapped to the 4 acceptance scenarios:
  Test 11 — 普通流程错误 → 执行 error_recovery → 最终 40001=110
  Test 12 — 机器人故障 (RobotMode=9) → 不执行 error_recovery → 40001=111
  Test 13 — 相机故障 (D405 断线) → 机器人健康 + Recovery 不依赖 D405 → 执行 error_recovery → 最终 40001=112
  Test 14 — Recovery 失败 → 不再触发第二次 Recovery → 直接进入最终错误状态
"""
from __future__ import annotations

import sys
import types

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
from contextlib import contextmanager  # noqa: E402
from pathlib import Path  # noqa: E402
from unittest.mock import MagicMock  # noqa: E402

import pytest  # noqa: E402

from dobot_move.flow.flow_result import (  # noqa: E402
    FAILURE_KIND_CAMERA,
    FAILURE_KIND_FLOW,
    FAILURE_KIND_ROBOT,
    FAILURE_KIND_VISION_PROCESS,
    FlowResult,
)
from dobot_move.runtime.production_flow_router import ProductionFlowRouter  # noqa: E402
from dobot_move.runtime.production_state import ProductionState  # noqa: E402
from dobot_move.runtime.recovery_policy import RecoveryPolicy  # noqa: E402
from dobot_move.runtime.runtime_agent import (  # noqa: E402
    DobotRuntimeAgent,
    RuntimeExecutionRequest,
)


# ===========================================================================
# Task 1.4 — FlowResult dataclass unit tests
# ===========================================================================


class TestFlowResultDataclass:
    def test_success_result_factory(self):
        result = FlowResult.success_result()
        assert result.success is True
        assert result.code == "OK"
        assert result.message == ""
        assert result.failure_kind == ""
        assert result.failed_module_index is None
        assert result.failed_module_name is None
        assert result.recoverable is False

    def test_failure_factory_populates_fields(self):
        result = FlowResult.failure(
            code="TARGET_LOST",
            message="D405 target lost",
            failure_kind=FAILURE_KIND_VISION_PROCESS,
            failed_module_index=6,
            failed_module_name="视觉伺服",
            recoverable=True,
        )
        assert result.success is False
        assert result.code == "TARGET_LOST"
        assert result.message == "D405 target lost"
        assert result.failure_kind == FAILURE_KIND_VISION_PROCESS
        assert result.failed_module_index == 6
        assert result.failed_module_name == "视觉伺服"
        assert result.recoverable is True

    def test_failure_factory_defaults_optional_fields(self):
        result = FlowResult.failure(
            code="GENERIC",
            message="fail",
            failure_kind=FAILURE_KIND_FLOW,
        )
        assert result.failed_module_index is None
        assert result.failed_module_name is None
        assert result.recoverable is False

    def test_dataclass_field_types_preserved(self):
        result = FlowResult.failure(
            code=123,  # int — should be coerced to str
            message=456,  # int — should be coerced to str
            failure_kind=FAILURE_KIND_FLOW,
            recoverable=1,  # truthy — should be coerced to bool
        )
        assert isinstance(result.code, str)
        assert result.code == "123"
        assert isinstance(result.message, str)
        assert isinstance(result.recoverable, bool)


# ===========================================================================
# Task 3.4 — RecoveryPolicy unit tests
# ===========================================================================


class _SafetyState:
    """Minimal stand-in for MotionSafetyState."""

    def __init__(self, robot_mode=5, error_status=0):
        self.is_connected = True
        self.is_enabled = True
        self.robot_mode = robot_mode
        self.error_status = error_status


class _PolicyController:
    """Controller stub exposing the attributes RecoveryPolicy inspects."""

    def __init__(
        self,
        connected=True,
        feedback_health="ok",
        robot_mode=5,
        error_status=0,
    ):
        self.is_connected = connected
        self._feedback_health = {"health": feedback_health}
        self._safety = _SafetyState(robot_mode=robot_mode, error_status=error_status)

    def get_feedback_health(self, max_age=0.3):
        return self._feedback_health

    def get_motion_safety_state(self):
        return self._safety


class TestRecoveryPolicy:
    def test_can_recover_returns_true_when_all_healthy(self):
        result = FlowResult.failure(
            code="X", message="y", failure_kind=FAILURE_KIND_FLOW, recoverable=True
        )
        controller = _PolicyController(connected=True, feedback_health="ok")
        assert RecoveryPolicy().can_recover(result, controller) is True

    def test_can_recover_false_when_result_none(self):
        controller = _PolicyController()
        assert RecoveryPolicy().can_recover(None, controller) is False

    def test_can_recover_false_when_recoverable_false(self):
        result = FlowResult.failure(
            code="X", message="y", failure_kind=FAILURE_KIND_FLOW, recoverable=False
        )
        controller = _PolicyController()
        assert RecoveryPolicy().can_recover(result, controller) is False

    def test_can_recover_false_when_controller_none(self):
        result = FlowResult.failure(
            code="X", message="y", failure_kind=FAILURE_KIND_FLOW, recoverable=True
        )
        assert RecoveryPolicy().can_recover(result, None) is False

    def test_can_recover_false_when_controller_disconnected(self):
        result = FlowResult.failure(
            code="X", message="y", failure_kind=FAILURE_KIND_FLOW, recoverable=True
        )
        controller = _PolicyController(connected=False)
        assert RecoveryPolicy().can_recover(result, controller) is False

    def test_can_recover_false_when_feedback_disconnected(self):
        result = FlowResult.failure(
            code="X", message="y", failure_kind=FAILURE_KIND_FLOW, recoverable=True
        )
        controller = _PolicyController(feedback_health="disconnected")
        assert RecoveryPolicy().can_recover(result, controller) is False

    def test_can_recover_false_when_robot_mode_is_estop(self):
        """RobotMode=9 (急停) → not recoverable."""
        result = FlowResult.failure(
            code="X", message="y", failure_kind=FAILURE_KIND_FLOW, recoverable=True
        )
        controller = _PolicyController(robot_mode=9)
        assert RecoveryPolicy().can_recover(result, controller) is False

    def test_can_recover_false_when_robot_mode_is_fault(self):
        """RobotMode=11 (故障) → not recoverable."""
        result = FlowResult.failure(
            code="X", message="y", failure_kind=FAILURE_KIND_FLOW, recoverable=True
        )
        controller = _PolicyController(robot_mode=11)
        assert RecoveryPolicy().can_recover(result, controller) is False

    def test_can_recover_false_when_error_status_nonzero(self):
        result = FlowResult.failure(
            code="X", message="y", failure_kind=FAILURE_KIND_FLOW, recoverable=True
        )
        controller = _PolicyController(error_status=7)
        assert RecoveryPolicy().can_recover(result, controller) is False

    def test_can_recover_false_when_get_motion_safety_state_raises(self):
        result = FlowResult.failure(
            code="X", message="y", failure_kind=FAILURE_KIND_FLOW, recoverable=True
        )

        class _BrokenController(_PolicyController):
            def get_motion_safety_state(self):
                raise RuntimeError("boom")

        assert RecoveryPolicy().can_recover(result, _BrokenController()) is False

    def test_can_recover_false_when_get_feedback_health_raises(self):
        result = FlowResult.failure(
            code="X", message="y", failure_kind=FAILURE_KIND_FLOW, recoverable=True
        )

        class _BrokenController(_PolicyController):
            def get_feedback_health(self, max_age=0.3):
                raise RuntimeError("boom")

        assert RecoveryPolicy().can_recover(result, _BrokenController()) is False


# ===========================================================================
# Integration tests — runtime_agent ERROR_RECOVERY (Tests 11-14)
# ===========================================================================


class _FakeDashboard:
    def __init__(self):
        self.stop_calls = 0

    def Stop(self):
        self.stop_calls += 1
        return "0,0,0;"


class _FakeController:
    """Controller stub supporting PR 4 recovery policy inspection."""

    def __init__(self, robot_mode=5, error_status=0, feedback_health="ok"):
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
        self._robot_mode = robot_mode
        self._error_status = error_status
        self._feedback_health = feedback_health
        # Tracks serial execution: how many times run_recovery_sync was
        # invoked (via program_runner mock).
        self.recovery_runs = 0

    def get_feedback_health(self, max_age=0.3):
        return {"health": self._feedback_health}

    def get_motion_safety_state(self):
        return _SafetyState(
            robot_mode=self._robot_mode, error_status=self._error_status
        )

    def get_modbus_stats(self):
        return {"is_running": self.modbus_running}

    def set_modbus_program_runner(self, runner, readiness_checker=None, command_delegate=None):
        pass

    def set_modbus_mode_changed_callback(self, callback):
        pass

    def close_robot_transport(self):
        pass

    def abort_active_flow_for_disconnect(self, reason):
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
        pass

    def continue_motion(self):
        pass

    def clear_error(self):
        pass

    def enable_robot(self):
        return True

    def move_to_initial_position(self, verify_start_pose=True, verify_end_pose=True, **kwargs):
        return True


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
def _recovery_agent_fixture(robot_mode=5, error_status=0, feedback_health="ok"):
    """Create a DobotRuntimeAgent wired for PR 4 recovery tests.

    The program_runner is heavily mocked so we can capture recovery
    dispatch without spinning up real flow threads. ``run_recovery_sync``
    is mocked to return a configurable FlowResult.
    """
    temp_dir = Path.cwd() / f"_recovery_test_{uuid.uuid4().hex}"
    temp_dir.mkdir()
    try:
        controller = _FakeController(
            robot_mode=robot_mode,
            error_status=error_status,
            feedback_health=feedback_health,
        )
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
            side_effect=lambda flow_id: _make_fake_request(flow_id)
        )
        agent.program_runner.start_request = MagicMock(return_value=True)
        agent.program_runner.pause = MagicMock(return_value=True)
        agent.program_runner.resume = MagicMock(return_value=True)
        agent.program_runner.stop = MagicMock(return_value=True)
        agent.program_runner.current_module_index = None
        agent.program_runner.task_mode = None
        # Default: recovery succeeds. Individual tests override this.
        agent.program_runner.run_recovery_sync = MagicMock(
            return_value=FlowResult.success_result()
        )
        yield agent, controller
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _start_primary_task(agent, controller, hook_type=0):
    """Drive the agent into RUNNING with a latched ProductionTaskContext."""
    agent._set_production_state(ProductionState.STANDBY)
    controller.written_statuses.clear()
    agent._on_modbus_command_delegate(cmd=3, mode=0, hook_type=hook_type)
    assert agent.production_state == ProductionState.RUNNING
    assert agent.production_task is not None


# ---------------------------------------------------------------------------
# Test 11 — 普通流程错误 → 执行 error_recovery → 最终 40001=110
# ---------------------------------------------------------------------------


class Test11FlowErrorRecovery:
    def test_flow_failure_with_recovery_lands_in_flow_error_110(self):
        """failure_kind=flow + recoverable=True + healthy robot
        → ERROR_RECOVERY → recovery runs → final FLOW_ERROR (110)."""
        with _recovery_agent_fixture() as (agent, controller):
            _start_primary_task(agent, controller)
            controller.written_statuses.clear()

            primary_result = FlowResult.failure(
                code="MODULE_FAILED",
                message="模块执行失败",
                failure_kind=FAILURE_KIND_FLOW,
                failed_module_index=2,
                failed_module_name="直线运动",
                recoverable=True,
            )
            agent._on_production_flow_finished(primary_result)

            # Recovery hook MUST have been dispatched (serial, no new
            # async Runner).
            agent.program_runner.run_recovery_sync.assert_called_once()
            # Final state is FLOW_ERROR (not HOLDING_HOOK / RUNNING).
            assert agent.production_state == ProductionState.FLOW_ERROR
            # 40001=110 (STATUS_HOOK_ERR) written via MODBUS_STATUS_MAP.
            assert (110, 0) in controller.written_statuses
            # Anti-recursion flag was set.
            assert agent.production_task.recovery_started is True
            # Failure info recorded on task context.
            assert agent.production_task.failure_code == "MODULE_FAILED"
            assert agent.production_task.failure_kind == FAILURE_KIND_FLOW

    def test_recovery_success_does_not_clear_error_code(self):
        """Task 8 — recovery success still reports 110 (not 4/5)."""
        with _recovery_agent_fixture() as (agent, controller):
            _start_primary_task(agent, controller)
            controller.written_statuses.clear()

            primary_result = FlowResult.failure(
                code="TARGET_LOST",
                message="target lost",
                failure_kind=FAILURE_KIND_VISION_PROCESS,
                recoverable=True,
            )
            # Recovery succeeds.
            agent.program_runner.run_recovery_sync = MagicMock(
                return_value=FlowResult.success_result()
            )
            agent._on_production_flow_finished(primary_result)

            agent.program_runner.run_recovery_sync.assert_called_once()
            # Even though recovery succeeded, final state is FLOW_ERROR.
            assert agent.production_state == ProductionState.FLOW_ERROR
            assert (110, 0) in controller.written_statuses
            # 40001=4 (RUNNING) / 5 (HOOK_OK) must NOT be written.
            assert (4, 0) not in controller.written_statuses
            assert (5, 0) not in controller.written_statuses


# ---------------------------------------------------------------------------
# Test 12 — 机器人故障 (RobotMode=9) → 不执行 error_recovery → 40001=111
# ---------------------------------------------------------------------------


class Test12RobotErrorNoRecovery:
    def test_robot_failure_kind_lands_in_robot_error_111(self):
        """failure_kind=robot → ROBOT_ERROR (111), no recovery attempted."""
        with _recovery_agent_fixture() as (agent, controller):
            _start_primary_task(agent, controller)
            controller.written_statuses.clear()

            primary_result = FlowResult.failure(
                code="ROBOT_DISCONNECTED",
                message="30004 反馈中断",
                failure_kind=FAILURE_KIND_ROBOT,
                recoverable=False,
            )
            agent._on_production_flow_finished(primary_result)

            # Recovery MUST NOT be dispatched for robot failures.
            agent.program_runner.run_recovery_sync.assert_not_called()
            assert agent.production_state == ProductionState.ROBOT_ERROR
            assert (111, 0) in controller.written_statuses

    def test_robot_mode_9_skips_recovery_even_if_recoverable_true(self):
        """RecoveryPolicy rejects recovery when RobotMode=9 (急停)."""
        with _recovery_agent_fixture(robot_mode=9) as (agent, controller):
            _start_primary_task(agent, controller)
            controller.written_statuses.clear()

            primary_result = FlowResult.failure(
                code="MODULE_FAILED",
                message="fail",
                failure_kind=FAILURE_KIND_FLOW,
                recoverable=True,
            )
            agent._on_production_flow_finished(primary_result)

            # Policy rejected recovery → no run_recovery_sync call.
            agent.program_runner.run_recovery_sync.assert_not_called()
            # Lands in FLOW_ERROR (not ROBOT_ERROR) because the failure
            # kind is "flow" — only RobotMode=9 blocks the recovery hook.
            assert agent.production_state == ProductionState.FLOW_ERROR
            assert (110, 0) in controller.written_statuses


# ---------------------------------------------------------------------------
# Test 13 — 相机故障 (D405 断线) → 机器人健康 + Recovery 不依赖 D405
#            → 执行 error_recovery → 最终 40001=112
# ---------------------------------------------------------------------------


class Test13CameraErrorRecovery:
    def test_camera_failure_with_recovery_lands_in_camera_error_112(self):
        """failure_kind=camera + recoverable=True + healthy robot
        → ERROR_RECOVERY → recovery runs → final CAMERA_ERROR (112)."""
        with _recovery_agent_fixture() as (agent, controller):
            _start_primary_task(agent, controller)
            controller.written_statuses.clear()

            primary_result = FlowResult.failure(
                code="CAMERA_DISCONNECTED",
                message="D405 相机未连接",
                failure_kind=FAILURE_KIND_CAMERA,
                failed_module_index=3,
                failed_module_name="D405识别",
                recoverable=True,
            )
            agent._on_production_flow_finished(primary_result)

            agent.program_runner.run_recovery_sync.assert_called_once()
            assert agent.production_state == ProductionState.CAMERA_ERROR
            assert (112, 0) in controller.written_statuses
            assert agent.production_task.recovery_started is True
            assert agent.production_task.failure_kind == FAILURE_KIND_CAMERA

    def test_camera_failure_recovery_success_still_reports_112(self):
        """Task 8 — camera failure + recovery success → 112 (not 4/5)."""
        with _recovery_agent_fixture() as (agent, controller):
            _start_primary_task(agent, controller)
            controller.written_statuses.clear()

            primary_result = FlowResult.failure(
                code="CAMERA_DETECTION_FAILED",
                message="detection failed",
                failure_kind=FAILURE_KIND_CAMERA,
                recoverable=True,
            )
            agent.program_runner.run_recovery_sync = MagicMock(
                return_value=FlowResult.success_result()
            )
            agent._on_production_flow_finished(primary_result)

            agent.program_runner.run_recovery_sync.assert_called_once()
            assert agent.production_state == ProductionState.CAMERA_ERROR
            assert (112, 0) in controller.written_statuses
            assert (4, 0) not in controller.written_statuses
            assert (5, 0) not in controller.written_statuses


# ---------------------------------------------------------------------------
# Test 14 — Recovery 失败 → 不再触发第二次 Recovery → 直接进入最终错误状态
# ---------------------------------------------------------------------------


class Test14RecoveryFailureNoRecursion:
    def test_recovery_started_flag_blocks_second_recovery(self):
        """Task 7 — recovery_started=True → skip recovery, go to final state."""
        with _recovery_agent_fixture() as (agent, controller):
            _start_primary_task(agent, controller)
            # Simulate that recovery was already attempted for this task.
            agent.production_task.recovery_started = True
            controller.written_statuses.clear()

            primary_result = FlowResult.failure(
                code="MODULE_FAILED",
                message="fail",
                failure_kind=FAILURE_KIND_FLOW,
                recoverable=True,
            )
            agent._on_production_flow_finished(primary_result)

            # Recovery MUST NOT be dispatched again.
            agent.program_runner.run_recovery_sync.assert_not_called()
            # Lands directly in FLOW_ERROR (110).
            assert agent.production_state == ProductionState.FLOW_ERROR
            assert (110, 0) in controller.written_statuses

    def test_recovery_failure_does_not_trigger_second_recovery(self):
        """Recovery fails → final state FLOW_ERROR → no second recovery attempt.

        This simulates the full flow:
          1. Primary flow fails (failure_kind=flow, recoverable=True)
          2. RecoveryPolicy allows recovery
          3. run_recovery_sync returns a FAILURE FlowResult
          4. Final state is FLOW_ERROR (110)
          5. No second recovery dispatch
        """
        with _recovery_agent_fixture() as (agent, controller):
            _start_primary_task(agent, controller)
            controller.written_statuses.clear()

            primary_result = FlowResult.failure(
                code="MODULE_FAILED",
                message="primary failed",
                failure_kind=FAILURE_KIND_FLOW,
                recoverable=True,
            )
            # Recovery flow also fails.
            agent.program_runner.run_recovery_sync = MagicMock(
                return_value=FlowResult.failure(
                    code="RECOVERY_FAILED",
                    message="recovery also failed",
                    failure_kind=FAILURE_KIND_FLOW,
                    recoverable=False,
                )
            )
            agent._on_production_flow_finished(primary_result)

            # Recovery was dispatched exactly once (no recursion).
            agent.program_runner.run_recovery_sync.assert_called_once()
            # Final state FLOW_ERROR (110) regardless of recovery failure.
            assert agent.production_state == ProductionState.FLOW_ERROR
            assert (110, 0) in controller.written_statuses
            # Anti-recursion flag is set.
            assert agent.production_task.recovery_started is True


# ---------------------------------------------------------------------------
# Task 6 — Serial execution (no new async Runner / no concurrent thread)
# ---------------------------------------------------------------------------


class TestSerialRecoveryExecution:
    def test_recovery_uses_run_recovery_sync_not_start_request(self):
        """Recovery must go through run_recovery_sync (serial), not
        start_request (which spawns a new async Runner thread)."""
        with _recovery_agent_fixture() as (agent, controller):
            _start_primary_task(agent, controller)
            controller.written_statuses.clear()

            primary_result = FlowResult.failure(
                code="MODULE_FAILED",
                message="fail",
                failure_kind=FAILURE_KIND_FLOW,
                recoverable=True,
            )
            agent._on_production_flow_finished(primary_result)

            # start_request is the async-Runner entry point used for the
            # PRIMARY flow; it must NOT be called again for recovery.
            # (It was called once when the task was started; the count
            # should still be 1, not 2.)
            assert agent.program_runner.start_request.call_count == 1
            # run_recovery_sync (serial) was used instead.
            agent.program_runner.run_recovery_sync.assert_called_once()

    def test_recovery_request_built_with_recovery_flow_id(self):
        """build_production_request must be called with the task's
        recovery_flow_id (not the primary_flow_id)."""
        with _recovery_agent_fixture() as (agent, controller):
            _start_primary_task(agent, controller)
            task = agent.production_task
            assert task.recovery_flow_id == "flow-recovery"
            controller.written_statuses.clear()

            primary_result = FlowResult.failure(
                code="X",
                message="y",
                failure_kind=FAILURE_KIND_FLOW,
                recoverable=True,
            )
            agent._on_production_flow_finished(primary_result)

            # build_production_request called with recovery_flow_id.
            agent.program_runner.build_production_request.assert_called_with(
                "flow-recovery"
            )


# ---------------------------------------------------------------------------
# Task 5 — 110/111/112 classification edge cases
# ---------------------------------------------------------------------------


class TestErrorClassification:
    def test_vision_process_failure_lands_in_flow_error_110(self):
        """failure_kind=vision_process → FLOW_ERROR (110), not 111/112."""
        with _recovery_agent_fixture() as (agent, controller):
            _start_primary_task(agent, controller)
            controller.written_statuses.clear()

            primary_result = FlowResult.failure(
                code="TARGET_LOST",
                message="vision servo diverged",
                failure_kind=FAILURE_KIND_VISION_PROCESS,
                recoverable=True,
            )
            agent._on_production_flow_finished(primary_result)

            assert agent.production_state == ProductionState.FLOW_ERROR
            assert (110, 0) in controller.written_statuses
            assert (111, 0) not in controller.written_statuses
            assert (112, 0) not in controller.written_statuses

    def test_protocol_failure_lands_in_flow_error_110(self):
        """failure_kind=protocol (unrecognized kinds) → FLOW_ERROR (110)."""
        with _recovery_agent_fixture() as (agent, controller):
            _start_primary_task(agent, controller)
            controller.written_statuses.clear()

            primary_result = FlowResult.failure(
                code="PROTO_ERR",
                message="protocol mismatch",
                failure_kind="protocol",
                recoverable=True,
            )
            agent._on_production_flow_finished(primary_result)

            assert agent.production_state == ProductionState.FLOW_ERROR
            assert (110, 0) in controller.written_statuses

    def test_empty_failure_kind_defaults_to_flow_error(self):
        """Empty failure_kind → treated as flow → FLOW_ERROR (110)."""
        with _recovery_agent_fixture() as (agent, controller):
            _start_primary_task(agent, controller)
            controller.written_statuses.clear()

            primary_result = FlowResult.failure(
                code="X",
                message="y",
                failure_kind="",
                recoverable=True,
            )
            agent._on_production_flow_finished(primary_result)

            assert agent.production_state == ProductionState.FLOW_ERROR
            assert (110, 0) in controller.written_statuses

    def test_robot_failure_does_not_set_recovery_started(self):
        """failure_kind=robot → ROBOT_ERROR, recovery_started stays False."""
        with _recovery_agent_fixture() as (agent, controller):
            _start_primary_task(agent, controller)
            controller.written_statuses.clear()

            primary_result = FlowResult.failure(
                code="ROBOT_DISCONNECTED",
                message="robot gone",
                failure_kind=FAILURE_KIND_ROBOT,
                recoverable=False,
            )
            agent._on_production_flow_finished(primary_result)

            assert agent.production_state == ProductionState.ROBOT_ERROR
            assert agent.production_task.recovery_started is False


# ---------------------------------------------------------------------------
# Task 4 — ERROR_RECOVERY state entry
# ---------------------------------------------------------------------------


class TestErrorRecoveryStateEntry:
    def test_state_passes_through_error_recovery(self):
        """When recovery is allowed, state MUST enter ERROR_RECOVERY before
        landing in the final error state."""
        with _recovery_agent_fixture() as (agent, controller):
            _start_primary_task(agent, controller)
            controller.written_statuses.clear()

            # Capture intermediate states by instrumenting _set_production_state.
            seen_states: list[ProductionState] = []
            original_set = agent._set_production_state

            def capturing_set(new_state, reason=""):
                seen_states.append(new_state)
                return original_set(new_state, reason=reason)

            agent._set_production_state = capturing_set

            primary_result = FlowResult.failure(
                code="MODULE_FAILED",
                message="fail",
                failure_kind=FAILURE_KIND_FLOW,
                recoverable=True,
            )
            agent._on_production_flow_finished(primary_result)

            # ERROR_RECOVERY must appear in the transition sequence,
            # followed by FLOW_ERROR as the final state.
            assert ProductionState.ERROR_RECOVERY in seen_states
            assert seen_states[-1] == ProductionState.FLOW_ERROR

    def test_non_recoverable_failure_skips_error_recovery_state(self):
        """recoverable=False → skip ERROR_RECOVERY, go straight to FLOW_ERROR."""
        with _recovery_agent_fixture() as (agent, controller):
            _start_primary_task(agent, controller)
            controller.written_statuses.clear()

            seen_states: list[ProductionState] = []
            original_set = agent._set_production_state

            def capturing_set(new_state, reason=""):
                seen_states.append(new_state)
                return original_set(new_state, reason=reason)

            agent._set_production_state = capturing_set

            primary_result = FlowResult.failure(
                code="HARD_FAIL",
                message="non-recoverable",
                failure_kind=FAILURE_KIND_FLOW,
                recoverable=False,
            )
            agent._on_production_flow_finished(primary_result)

            assert ProductionState.ERROR_RECOVERY not in seen_states
            assert seen_states[-1] == ProductionState.FLOW_ERROR
