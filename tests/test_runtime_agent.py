"""Regression tests for the unattended runtime agent."""
import json
import sys
import threading
import time
import types
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

import dobot_move.runtime_agent as runtime_module  # noqa: E402
from dobot_move.runtime_agent import (  # noqa: E402
    DobotRuntimeAgent,
    RobotConnectionState,
    RobotConnectionSupervisor,
    RuntimeProgramRunner,
)
from dobot_move.runtime_resilience import RuntimeState, RuntimeStateStore  # noqa: E402


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

    def set_modbus_program_runner(self, runner):
        self.program_runner = runner

    def _write_modbus_status(self, status, mode=0):
        self.status_writes.append((status, mode))

    def record_alarm(self, *args, **kwargs):
        self.alarms.append((args, kwargs))

    def mark_modbus_program_finished(self, success, mode=0, failure_status=None):
        self.finished.append((success, mode, failure_status))

    def set_runtime_recovery_required(self, required=True, on_cleared=None):
        self.runtime_recovery_required = bool(required)


def test_runtime_defaults_stay_in_project_root_after_package_move():
    project_root = Path(__file__).resolve().parents[1]

    assert runtime_module.PROJECT_ROOT == project_root
    assert runtime_module.DEFAULT_HEALTH_PATH == project_root / "runtime_health.json"
    assert runtime_module.DEFAULT_STATE_PATH == project_root / "runtime_state.json"
    assert runtime_module.DEFAULT_LOCK_PATH == project_root / "runtime_agent.lock"
    assert runtime_module.DEFAULT_LOG_DIR == project_root / "logs"


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


def test_supervisor_closes_robot_connection_when_feedback_disconnected():
    controller = _FakeController()
    controller.is_connected = True
    controller.feedback_health = {"health": "disconnected"}
    dashboard = controller.dashboard
    supervisor = RobotConnectionSupervisor(controller, reconnect_delays=(1.0,))

    supervisor.step(now=300.0)

    assert controller.is_connected is False
    assert controller.is_enabled is False
    assert controller.stop_feedback_calls == 1
    assert dashboard.closed is True
    assert controller.dashboard is None
    assert supervisor.state == RobotConnectionState.DISCONNECTED


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
    assert controller.status_writes[-1][0] == 111
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


def test_runtime_runner_camera_failure_writes_camera_error(monkeypatch):
    controller = _FakeController()
    runner = RuntimeProgramRunner(controller)
    monkeypatch.setattr(
        runner,
        "_load_modules",
        lambda: [{"type": "camera", "params": {"camera_type": "D405"}}],
    )
    monkeypatch.setattr(runner, "_ensure_required_cameras", lambda modules: False)

    runner._run_once()

    assert controller.finished == [(False, 0, 112)]


def test_runtime_runner_passes_reused_cameras_to_flow(monkeypatch):
    import dobot_move.workers as workers

    controller = _FakeController()
    runner = RuntimeProgramRunner(controller)
    runner.vision_d405 = object()
    captured = {}

    class Signal:
        def __init__(self):
            self.callbacks = []

        def connect(self, callback):
            self.callbacks.append(callback)

        def emit(self, value):
            for callback in self.callbacks:
                callback(value)

    class FakeFlowThread:
        def __init__(self, controller_arg, vision_d435i, vision_d405, modules, paused):
            captured["vision_d435i"] = vision_d435i
            captured["vision_d405"] = vision_d405
            self.flow_log = Signal()
            self.flow_finished = Signal()

        def run(self):
            self.flow_finished.emit(True)

    monkeypatch.setattr(
        runner,
        "_load_modules",
        lambda: [{"type": "camera", "params": {"camera_type": "D405"}}],
    )
    monkeypatch.setattr(runner, "_ensure_required_cameras", lambda modules: True)
    monkeypatch.setattr(workers, "FlowThread", FakeFlowThread)

    runner._run_once()

    assert captured["vision_d435i"] is None
    assert captured["vision_d405"] is runner.vision_d405
    assert controller.finished == [(True, 0, 110)]


def test_runtime_runner_timeout_requests_flow_and_robot_stop(monkeypatch):
    import dobot_move.workers as workers

    controller = _FakeController()
    runner = RuntimeProgramRunner(controller)
    stopped = threading.Event()

    class Signal:
        def __init__(self):
            self.callbacks = []

        def connect(self, callback):
            self.callbacks.append(callback)

        def emit(self, *values):
            for callback in self.callbacks:
                callback(*values)

    class HangingFlowThread:
        def __init__(self, *args):
            self.flow_log = Signal()
            self.flow_finished = Signal()
            self.flow_module_progress = Signal()

        def run(self):
            self.flow_module_progress.emit(1, 1, "卡死模块")
            stopped.wait(1.0)

        def stop(self):
            stopped.set()

    monkeypatch.setattr(
        runner,
        "_load_modules",
        lambda: [{"type": "delay", "params": {"duration_s": 1}}],
    )
    monkeypatch.setattr(runner, "_ensure_required_cameras", lambda modules: True)
    monkeypatch.setattr(workers, "FlowThread", HangingFlowThread)
    monkeypatch.setattr(runtime_module, "module_timeout_seconds", lambda module: 0.03)
    monkeypatch.setattr(runtime_module, "flow_timeout_seconds", lambda modules: 0.03)

    runner._run_once()

    assert stopped.is_set()
    assert controller.dashboard.stop_calls == 1
    assert controller.finished[-1][0] is False
    assert any(args[0] == "Runtime流程看门狗" for args, _ in controller.alarms)
