"""Regression tests for the unattended runtime agent."""
import json
import sys
import types


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
    sys.modules["dobot_move.modbus_server"] = module


_install_modbus_stub()

from runtime_agent import (  # noqa: E402
    DobotRuntimeAgent,
    RobotConnectionState,
    RobotConnectionSupervisor,
)


class _FakeDashboard:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


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


def test_supervisor_reconnects_with_backoff():
    controller = _FakeController()
    supervisor = RobotConnectionSupervisor(controller, reconnect_delays=(1.0, 2.0))

    supervisor.step(now=100.0)
    assert controller.connect_calls == 1
    assert supervisor.state == RobotConnectionState.DISCONNECTED
    assert supervisor.next_attempt_at == 101.0

    supervisor.step(now=100.5)
    assert controller.connect_calls == 1

    supervisor.step(now=101.1)
    assert controller.connect_calls == 2
    assert supervisor.next_attempt_at == 103.1


def test_supervisor_marks_connected_after_successful_reconnect():
    controller = _FakeController()
    controller.connect_results = [True]
    supervisor = RobotConnectionSupervisor(controller, reconnect_delays=(1.0,))

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


def test_runtime_agent_writes_health_file(tmp_path):
    controller = _FakeController()
    controller.modbus_running = True
    controller.is_connected = True
    controller.is_enabled = True
    health_path = tmp_path / "runtime_health.json"
    agent = DobotRuntimeAgent(controller=controller, health_path=health_path, startup_delay=0, poll_interval=0.1)
    agent.write_health()

    data = json.loads(health_path.read_text(encoding="utf-8"))
    assert data["runtime"]["running"] is True
    assert data["robot"]["connected"] is True
    assert data["robot"]["enabled"] is True
    assert data["modbus"]["is_running"] is True
