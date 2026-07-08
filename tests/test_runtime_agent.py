"""Regression tests for the unattended runtime agent."""
import json
import shutil
import sys
import threading
import time
import types
import uuid
from contextlib import contextmanager
from pathlib import Path

if "pyrealsense2" not in sys.modules:
    sys.modules["pyrealsense2"] = types.ModuleType("pyrealsense2")


def _install_modbus_stub():
    module = types.ModuleType("dobot_move.modbus_server")

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
    module._CMD_DISPLAY = {0: "idle", 1: "reset", 3: "run", 4: "running", 5: "done", 110: "flow error", 111: "robot error", 112: "camera error"}
    module._MODE_DISPLAY = {0: "auto", 1: "manual"}
    sys.modules["dobot_move.modbus_server"] = module


_install_modbus_stub()

import dobot_move.runtime.runtime_agent as runtime_module  # noqa: E402
from dobot_move.runtime.runtime_agent import (  # noqa: E402
    DobotRuntimeAgent,
    RobotConnectionState,
    RobotConnectionSupervisor,
    RuntimeProgramRunner,
)
from dobot_move.runtime.runtime_resilience import RuntimeState, RuntimeStateStore  # noqa: E402
from dobot_move.runtime.runtime_ipc import IpcCommandError  # noqa: E402
from dobot_move.runtime.runtime_ipc import RuntimeIpcServer  # noqa: E402
from dobot_move.ui.gui_ipc_client import RuntimeIpcClient  # noqa: E402


class _FakeDashboard:
    def __init__(self):
        self.closed = False
        self.stop_calls = 0

    def close(self):
        self.closed = True

    def Stop(self):
        self.stop_calls += 1
        return "0,{0},0;"


class _FakeController:
    def __init__(self):
        self.is_connected = False
        self.is_enabled = False
        self.dashboard = _FakeDashboard()
        self.robot_ip = "192.168.1.50"
        self.last_error = ""
        self.connect_results = []
        self.connect_calls = 0
        self.stop_feedback_calls = 0
        self.start_feedback_calls = 0
        self.modbus_running = False
        self.modbus_start_calls = 0
        self.program_runner = None
        self._last_modbus_command = None
        self._last_modbus_command_time = 0.0
        self._last_speed_factor = None
        self.feed_thread = None
        self.feedback_health = {"health": "ok"}
        self.status_writes = []
        self.finished = []
        self.alarms = []
        self._active_flow_thread = None
        self.runtime_recovery_required = None
        self.runtime_maintenance = False

    def connect(self):
        self.connect_calls += 1
        result = self.connect_results.pop(0) if self.connect_results else False
        self.is_connected = bool(result)
        self.last_error = "" if result else "connect failed"
        return result

    def stop_feedback(self):
        self.stop_feedback_calls += 1

    def start_feedback(self):
        self.start_feedback_calls += 1

    def get_feedback_health(self, max_age=0.3):
        return dict(self.feedback_health)

    def get_modbus_stats(self):
        return {"is_running": self.modbus_running, "port": 502, "cycle_count": 0, "last_duration_ms": 0}

    def start_modbus(self, port=502, slave_id=5):
        self.modbus_start_calls += 1
        self.modbus_running = True
        return True

    def stop_modbus(self):
        self.modbus_running = False

    def set_modbus_program_runner(self, runner, readiness_checker=None):
        self.program_runner = runner
        self.program_readiness_checker = readiness_checker

    def close_robot_transport(self):
        self.stop_feedback()
        if self.dashboard:
            self.dashboard.close()
        self.is_connected = False
        self.is_enabled = False

    def abort_active_flow_for_disconnect(self, reason, source="flow"):
        flow = self._active_flow_thread
        ctx = getattr(flow, "_ctx", None) if flow is not None else None
        if ctx is not None:
            ctx.stop_event.set()
        if self.dashboard:
            self.dashboard.Stop()
        self._write_modbus_status(110)

    def _write_modbus_status(self, status, mode=0):
        self.status_writes.append((status, mode))

    def record_alarm(self, *args, **kwargs):
        self.alarms.append((args, kwargs))

    def mark_modbus_program_finished(self, success, mode=0, failure_status=None):
        self.finished.append((success, mode, failure_status))

    def set_runtime_recovery_required(self, required=True, on_cleared=None):
        self.runtime_recovery_required = bool(required)

    def set_runtime_maintenance(self, active=True):
        self.runtime_maintenance = bool(active)

    @contextmanager
    def _temp_timeout(self, seconds):
        del seconds
        yield


class _FakeIpcServer:
    def __init__(self):
        self.started = False
        self.stopped = False
        self.last_error = ""

    def start(self):
        self.started = True
        return True

    def stop(self):
        self.stopped = True

    def snapshot(self):
        return {
            "running": self.started and not self.stopped,
            "host": "127.0.0.1",
            "port": 8765,
            "clients": 0,
            "queue_depth": 0,
            "last_error": self.last_error,
        }


@contextmanager
def _runtime_agent_fixture():
    temp_dir = Path.cwd() / f"_runtime_ipc_agent_test_{uuid.uuid4().hex}"
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


def test_runtime_defaults_stay_in_project_root_after_package_move():
    project_root = Path(__file__).resolve().parents[1]
    user_data = project_root / "user_data"

    assert runtime_module.PROJECT_ROOT == project_root
    assert runtime_module.DEFAULT_HEALTH_PATH == user_data / "runtime_health.json"
    assert runtime_module.DEFAULT_STATE_PATH == user_data / "runtime_state.json"
    assert runtime_module.DEFAULT_LOCK_PATH == user_data / "runtime_agent.lock"
    assert runtime_module.DEFAULT_LOG_DIR == user_data / "logs"


def test_ipc_maintenance_transitions_are_idempotent():
    with _runtime_agent_fixture() as (agent, controller):
        controller.is_connected = True
        agent.state_store.transition(RuntimeState.READY)

        entered = agent._handle_ipc_command("enter_maintenance", {})
        entered_again = agent._handle_ipc_command("enter_maintenance", {})
        exited = agent._handle_ipc_command("exit_maintenance", {})

        assert entered["runtime_state"] == RuntimeState.MAINTENANCE.value
        assert entered["already_active"] is False
        assert entered_again["already_active"] is True
        assert controller.runtime_maintenance is False
        assert exited["runtime_state"] == RuntimeState.READY.value
        assert exited["auto_resumed"] is False


def test_ipc_enter_maintenance_rejects_running_flow(monkeypatch):
    with _runtime_agent_fixture() as (agent, _controller):
        monkeypatch.setattr(
            agent.program_runner,
            "snapshot",
            lambda: {"running": True},
        )

        try:
            agent._handle_ipc_command("enter_maintenance", {})
        except IpcCommandError as exc:
            assert exc.code == "RUNTIME_BUSY"
        else:
            raise AssertionError("running flow must block maintenance")

        assert agent.maintenance_mode is False


def test_ipc_maintenance_race_restores_previous_state(monkeypatch):
    with _runtime_agent_fixture() as (agent, controller):
        agent.state_store.transition(RuntimeState.READY)
        checks = iter([False, True])
        monkeypatch.setattr(
            agent,
            "_runtime_motion_busy",
            lambda: next(checks),
        )

        try:
            agent._handle_ipc_command("enter_maintenance", {})
        except IpcCommandError as exc:
            assert exc.code == "RUNTIME_BUSY"
        else:
            raise AssertionError("maintenance race must fail")

        assert agent.maintenance_mode is False
        assert controller.runtime_maintenance is False
        assert agent.state_store.snapshot()["state"] == RuntimeState.READY.value


def test_ipc_stop_current_task_sets_stop_and_sends_robot_stop():
    with _runtime_agent_fixture() as (agent, controller):
        stop_event = threading.Event()

        class Flow:
            def __init__(self):
                self._ctx = types.SimpleNamespace(stop_event=stop_event)
                self.stop_calls = 0

            def stop(self):
                self.stop_calls += 1

        flow = Flow()
        controller._active_flow_thread = flow

        result = agent._handle_ipc_command("stop_current_task", {})

        assert result["stop_requested"] is True
        assert result["stop_sent"] is True
        assert stop_event.is_set()
        assert flow.stop_calls == 1
        assert controller.dashboard.stop_calls == 1


def test_ipc_reload_config_refreshes_next_task_only(monkeypatch):
    with _runtime_agent_fixture() as (agent, controller):
        monkeypatch.setattr(
            runtime_module,
            "reload_config",
            lambda: {"user_index": 2, "tool_index": 3},
        )
        monkeypatch.setattr(agent, "validate_startup_inputs", lambda: [])
        monkeypatch.setattr(
            agent,
            "_refresh_startup_requirements",
            lambda force=False: None,
        )
        agent._startup_main_flow_id = "flow-1"
        agent._startup_main_flow_name = "流程 1"

        result = agent._handle_ipc_command("reload_config", {})

        assert result["reloaded"] is True
        assert result["applies_to_running_task"] is False
        assert controller._user_index == 2
        assert controller._tool_index == 3


def test_ipc_reload_config_rejects_running_flow(monkeypatch):
    with _runtime_agent_fixture() as (agent, _controller):
        monkeypatch.setattr(
            agent.program_runner,
            "snapshot",
            lambda: {"running": True},
        )

        try:
            agent._handle_ipc_command("reload_config", {})
        except IpcCommandError as exc:
            assert exc.code == "RUNTIME_BUSY"
        else:
            raise AssertionError("running flow must block config reload")


def test_ipc_unknown_command_has_stable_error_code():
    with _runtime_agent_fixture() as (agent, _controller):
        try:
            agent._handle_ipc_command("does_not_exist", {})
        except IpcCommandError as exc:
            assert exc.code == "UNKNOWN_COMMAND"
        else:
            raise AssertionError("unknown command must fail")


def test_debug_flow_requires_maintenance_mode():
    with _runtime_agent_fixture() as (agent, controller):
        controller.is_connected = True
        controller.is_enabled = True
        try:
            agent._handle_ipc_command("start_debug_flow", {})
        except IpcCommandError as exc:
            assert exc.code == "NOT_IN_MAINTENANCE"
        else:
            raise AssertionError("debug flow must require maintenance mode")


def test_validate_flow_reports_published_dependencies():
    with _runtime_agent_fixture() as (agent, _controller):
        result = agent._handle_ipc_command("validate_flow", {})

        assert result["flow_id"]
        assert result["module_count"] >= 0
        assert isinstance(result["required_cameras"], list)
        assert result["revision"]


def test_gui_client_reaches_runtime_agent_through_command_queue():
    with _runtime_agent_fixture() as (agent, controller):
        controller.is_connected = True
        agent.state_store.transition(RuntimeState.READY)
        server = RuntimeIpcServer(agent._handle_ipc_command, port=0)
        agent.ipc_server = server
        assert server.start() is True
        try:
            client = RuntimeIpcClient(port=server.port)

            ping = client.ping()
            entered = client.request("enter_maintenance")
            status = client.request("get_status")
            exited = client.request("exit_maintenance")

            assert ping["data"]["pong"] is True
            assert entered["data"]["runtime_state"] == "MAINTENANCE"
            assert status["data"]["maintenance"] is True
            assert exited["data"]["auto_resumed"] is False
        finally:
            server.stop()


def test_supervisor_reconnects_with_backoff():
    controller = _FakeController()
    supervisor = RobotConnectionSupervisor(controller, reconnect_delays=(1.0, 2.0))

    supervisor.step(now=100.0)
    supervisor._connect_thread.join(timeout=1.0)
    supervisor.step(now=100.0)
    assert controller.connect_calls == 1
    assert supervisor.state == RobotConnectionState.DISCONNECTED
    assert supervisor.next_attempt_at == 101.0

    supervisor.step(now=100.5)
    assert controller.connect_calls == 1

    supervisor.step(now=101.1)
    supervisor._connect_thread.join(timeout=1.0)
    supervisor.step(now=101.1)
    assert controller.connect_calls == 2
    assert supervisor.next_attempt_at == 103.1


def test_supervisor_marks_connected_after_successful_reconnect():
    controller = _FakeController()
    controller.connect_results = [True]
    supervisor = RobotConnectionSupervisor(controller, reconnect_delays=(1.0,))

    supervisor.step(now=200.0)
    supervisor._connect_thread.join(timeout=1.0)
    supervisor.step(now=200.0)

    assert controller.connect_calls == 1
    assert supervisor.state == RobotConnectionState.CONNECTED
    assert supervisor.next_attempt_at == 0.0


def test_supervisor_step_stays_responsive_while_connect_blocks():
    controller = _FakeController()
    release = threading.Event()

    def blocking_connect():
        controller.connect_calls += 1
        release.wait(1.0)
        return False

    controller.connect = blocking_connect
    supervisor = RobotConnectionSupervisor(controller, reconnect_delays=(1.0,))

    started_at = time.monotonic()
    supervisor.step(now=250.0)
    elapsed = time.monotonic() - started_at

    assert elapsed < 0.2
    assert supervisor.state == RobotConnectionState.CONNECTING
    release.set()
    supervisor._connect_thread.join(timeout=1.0)


def test_supervisor_discards_late_connect_result_after_shutdown():
    controller = _FakeController()
    release = threading.Event()

    def blocking_connect():
        controller.connect_calls += 1
        release.wait(1.0)
        controller.is_connected = True
        return True

    controller.connect = blocking_connect
    supervisor = RobotConnectionSupervisor(controller, reconnect_delays=(1.0,))

    supervisor.request_connect(now=260.0)
    supervisor.shutdown()
    release.set()
    supervisor._connect_thread.join(timeout=1.0)

    assert supervisor._connect_result is None
    assert controller.is_connected is False


def test_supervisor_closes_robot_connection_when_feedback_disconnected():
    controller = _FakeController()
    controller.is_connected = True
    controller.feedback_health = {"health": "disconnected"}
    dashboard = controller.dashboard
    supervisor = RobotConnectionSupervisor(controller, reconnect_delays=(1.0,))

    supervisor.step(now=300.0)

    assert controller.is_connected is False
    assert controller.stop_feedback_calls == 0
    assert dashboard.closed is False
    assert supervisor.state == RobotConnectionState.DISCONNECTED

    supervisor.step(now=301.0)
    supervisor._connect_thread.join(timeout=1.0)
    assert controller.stop_feedback_calls >= 1
    assert dashboard.closed is True


def test_supervisor_stops_active_flow_before_feedback_reconnect():
    controller = _FakeController()
    controller.is_connected = True
    controller.feedback_health = {"health": "disconnected"}
    dashboard = controller.dashboard
    stop_event = threading.Event()
    controller._active_flow_thread = types.SimpleNamespace(
        _ctx=types.SimpleNamespace(stop_event=stop_event)
    )
    supervisor = RobotConnectionSupervisor(controller, reconnect_delays=(1.0,))

    supervisor.step(now=300.0)

    assert stop_event.is_set()
    assert dashboard.stop_calls == 1
    assert controller.status_writes[-1][0] == 110
    assert controller.is_connected is False


def test_runtime_agent_writes_health_file():
    controller = _FakeController()
    controller.modbus_running = True
    controller.is_connected = True
    controller.is_enabled = True
    health_path = Path("_runtime_health_test.json")
    try:
        agent = DobotRuntimeAgent(controller=controller, health_path=health_path, startup_delay=0, poll_interval=0.1)
        agent.write_health()

        data = json.loads(health_path.read_text(encoding="utf-8"))
        assert data["runtime"]["running"] is True
        assert data["robot"]["connected"] is True
        assert data["robot"]["enabled"] is True
        assert data["modbus"]["is_running"] is True
        assert data["schema_version"] == 2
        assert "process" in data
        assert "thread_count" in data["process"]
        assert data["startup_connection"]["fault_latched"] is False
        assert data["startup_connection"]["fault_code"] is None
        assert "deadline_elapsed" in data["startup_connection"]
        assert "retrying" in data["startup_connection"]
    finally:
        health_path.unlink(missing_ok=True)


def test_runtime_agent_latches_recovery_after_unclean_state():
    controller = _FakeController()
    health_path = Path("_runtime_recovery_health_test.json")
    state_path = Path("_runtime_recovery_state_test.json")
    try:
        previous = RuntimeStateStore(state_path)
        previous.begin_boot()
        previous.transition(RuntimeState.RUNNING, flow_id="old-flow")

        agent = DobotRuntimeAgent(
            controller=controller,
            health_path=health_path,
            state_path=state_path,
            startup_delay=0,
            poll_interval=0.1,
        )
        agent.stop_event.set()
        agent.run()

        assert agent.recovery_required is True
        assert controller.runtime_recovery_required is True
    finally:
        health_path.unlink(missing_ok=True)
        state_path.unlink(missing_ok=True)


def test_runtime_runner_camera_failure_writes_flow_error(monkeypatch):
    from dobot_move.flow.flow_result import FailureKind

    controller = _FakeController()
    controller.is_connected = True
    runner = RuntimeProgramRunner(controller)
    monkeypatch.setattr(
        runner,
        "_load_modules",
        lambda: [{"type": "camera", "params": {"camera_type": "D405"}}],
    )
    dispatched: list = []
    runner.on_production_finished = lambda result: dispatched.append(result)
    runner._run_once()

    # PR-FIX-3 Task 4: readiness failure classified by primary_failure_kind
    # (D405 missing → FailureKind.CAMERA, code=CAMERA_NOT_READY).
    assert len(dispatched) == 1
    assert dispatched[0].success is False
    assert dispatched[0].code == "CAMERA_NOT_READY"
    assert dispatched[0].failure_kind == FailureKind.CAMERA
    # PR-FIX-3 Task 5: production path no longer calls
    # mark_modbus_program_finished directly; 40001 is owned by the
    # production state machine via the callback.
    assert controller.finished == []


def test_runtime_runner_passes_reused_cameras_to_flow(monkeypatch):
    import dobot_move.flow.flow_executor as flow_executor

    controller = _FakeController()
    controller.is_connected = True
    runner = RuntimeProgramRunner(controller)
    runner.vision_d405 = object()
    captured = {}

    class FakeFlowExecutor:
        def __init__(self, controller_arg, vision_d435i, vision_d405, modules, paused, camera_test_workers=None):
            captured["vision_d435i"] = vision_d435i
            captured["vision_d405"] = vision_d405
            self.on_log = None
            self.on_finished = None
            self.on_progress = None

        def run(self):
            # PR 4: on_finished now receives a FlowResult.
            from dobot_move.flow.flow_result import FlowResult
            if self.on_finished:
                self.on_finished(FlowResult.success_result())

    monkeypatch.setattr(
        runner,
        "_load_modules",
        lambda: [{"type": "camera", "params": {"camera_type": "D405"}}],
    )
    monkeypatch.setattr(flow_executor, "FlowExecutor", FakeFlowExecutor)

    runner._run_once()

    assert captured["vision_d435i"] is None
    assert captured["vision_d405"] is runner.vision_d405
    # PR-FIX-3 Task 5: production path no longer writes 40001 directly.
    assert controller.finished == []


def test_runtime_runner_timeout_requests_flow_and_robot_stop(monkeypatch):
    import dobot_move.flow.flow_executor as flow_executor

    controller = _FakeController()
    controller.is_connected = True
    runner = RuntimeProgramRunner(controller)
    stopped = threading.Event()

    class HangingFlowExecutor:
        def __init__(self, *args):
            self.on_log = None
            self.on_finished = None
            self.on_progress = None

        def run(self):
            if self.on_progress:
                self.on_progress(1, 1, "卡死模块")
            stopped.wait(1.0)

        def stop(self):
            stopped.set()

    monkeypatch.setattr(
        runner,
        "_load_modules",
        lambda: [{"type": "delay", "params": {"duration_s": 1}}],
    )
    monkeypatch.setattr(flow_executor, "FlowExecutor", HangingFlowExecutor)
    monkeypatch.setattr(runtime_module, "module_timeout_seconds", lambda module: 0.03)
    monkeypatch.setattr(runtime_module, "flow_timeout_seconds", lambda modules: 0.03)

    runner._run_once()

    assert stopped.is_set()
    assert controller.dashboard.stop_calls == 1
    # PR-FIX-3 Task 5: production path no longer calls
    # mark_modbus_program_finished directly; the timeout FlowResult is
    # dispatched via on_production_finished instead.
    assert controller.finished == []
    assert any(args[0] == "Runtime流程看门狗" for args, _ in controller.alarms)
