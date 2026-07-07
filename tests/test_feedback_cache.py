"""Regression tests for Dobot 30004 feedback cache parsing."""
import sys
import threading
import time
import types

import numpy as np
import pytest


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
    module.CMD_STOP = 9
    module.CMD_RESET = 1
    module.CMD_HOOK = 3
    sys.modules["dobot_move.modbus_server"] = module


_install_modbus_stub()

from dobot_move.dobot_api import MyType  # noqa: E402
import dobot_move.robot_controller as controller_module  # noqa: E402
from dobot_move.robot_controller import DobotController  # noqa: E402
from dobot_move.motion_safety import MotionSafetyState  # noqa: E402


def _make_feedback_packet():
    packet = np.zeros(1, dtype=MyType)
    packet["TestValue"][0] = 0x123456789ABCDEF
    packet["ToolVectorActual"][0] = [100.0, 200.0, 300.0, 1.0, 2.0, 3.0]
    packet["TCPSpeedActual"][0] = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
    packet["ActualTCPForce"][0] = [1.0, 2.0, 3.0, 0.1, 0.2, 0.3]
    packet["ToolVectorTarget"][0] = [101.0, 201.0, 301.0, 1.1, 2.1, 3.1]
    packet["QActual"][0] = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0]
    packet["QTarget"][0] = [11.0, 21.0, 31.0, 41.0, 51.0, 61.0]
    packet["RobotMode"][0] = 5
    packet["RunningStatus"][0] = 0
    packet["RunQueuedCmd"][0] = 0
    packet["CurrentCommandId"][0] = 1234
    return packet


class _FakeTransportSocket:
    def __init__(self):
        self.timeout = 1.0

    def gettimeout(self):
        return self.timeout

    def settimeout(self, value):
        self.timeout = value


class _AtomicDashboard:
    instances = []

    def __init__(self, ip, port, **kwargs):
        self.ip = ip
        self.port = port
        self.kwargs = kwargs
        self.socket_dobot = _FakeTransportSocket()
        self.closed = False
        self.__class__.instances.append(self)

    def RobotMode(self):
        return "0,{5},RobotMode();"

    def GetAngle(self):
        return "0,{1,2,3,4,5,6},GetAngle();"

    def close(self):
        self.closed = True


class _AtomicFeedback:
    instances = []
    packet = None
    entered = None
    release = None

    def __init__(self, ip, port, **kwargs):
        self.ip = ip
        self.port = port
        self.kwargs = kwargs
        self.socket_dobot = _FakeTransportSocket()
        self.closed = False
        self.__class__.instances.append(self)

    def feedBackData(self):
        if self.entered is not None:
            self.entered.set()
        if self.release is not None:
            self.release.wait(1.0)
        if self.closed:
            raise OSError("feedback closed")
        time.sleep(0.005)
        return self.packet

    def close(self):
        self.closed = True


def _install_atomic_transports(monkeypatch, packet):
    _AtomicDashboard.instances = []
    _AtomicFeedback.instances = []
    _AtomicFeedback.packet = packet
    _AtomicFeedback.entered = None
    _AtomicFeedback.release = None
    monkeypatch.setattr(
        controller_module,
        "DobotApiDashboard",
        _AtomicDashboard,
    )
    monkeypatch.setattr(
        controller_module,
        "DobotApiFeedBack",
        _AtomicFeedback,
    )


def _make_controller():
    controller = DobotController("192.168.1.50")
    controller.is_connected = True
    return controller


class _FakeStopDashboard:
    def __init__(self):
        self.calls = []

    def Stop(self):
        self.calls.append("Stop")
        return "0,{0},0;"


class _FakeRelativeRetryDashboard:
    def __init__(self):
        self.calls = []
        self.relative_calls = 0

    def Stop(self):
        self.calls.append("Stop")
        return "0,{0},0;"

    def RelMovLUser(self, *args, **kwargs):
        self.calls.append("RelMovLUser")
        self.relative_calls += 1
        if self.relative_calls == 1:
            return "-7,{0},0;"
        return "0,42;"


def _force_snapshot(force, command_id=1, robot_mode=7, tcp_speed=None, running_status=1, run_queued_cmd=1):
    return {
        "pose": [300.0, 0.0, 200.0, 0.0, 0.0, -90.0],
        "tcp_speed": list(tcp_speed if tcp_speed is not None else [5.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
        "running_status": running_status,
        "run_queued_cmd": run_queued_cmd,
        "current_command_id": command_id,
        "tool_vector_target": None,
        "robot_mode": robot_mode,
        "q_actual": None,
        "q_target": None,
        "actual_tcp_force": list(force),
        "timestamp": time.time(),
        "health": "ok",
        "feedback_age": 0.0,
        "pose_timestamp": time.time(),
    }


def _settled_force_snapshot(force=None, command_id=1, robot_mode=5):
    return _force_snapshot(
        force or [4, 6, 3, 0, 0, 0],
        command_id=command_id,
        robot_mode=robot_mode,
        tcp_speed=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        running_status=0,
        run_queued_cmd=0,
    )


def _cache_packet(controller, packet):
    now = time.time()
    with controller.feed_lock:
        controller.feed_data = packet
        controller.last_feed_time = now
        controller.latest_feed_time = now
        controller.latest_pose = controller._extract_pose_from_feed_data(packet)
        controller.latest_pose_time = now
        controller.latest_tcp_speed = controller._extract_tcp_speed_from_feed_data(packet)
        controller.latest_tcp_speed_time = now
        controller.latest_actual_tcp_force = controller._extract_actual_tcp_force_from_feed_data(packet)
        controller.latest_actual_tcp_force_time = now
        controller.latest_robot_mode = controller._extract_robot_mode_from_feed_data(packet)
        controller.latest_robot_mode_time = now
        controller.latest_running_status = controller._extract_running_status_from_feed_data(packet)
        controller.latest_running_status_time = now
        controller.latest_run_queued_cmd = controller._extract_run_queued_cmd_from_feed_data(packet)
        controller.latest_run_queued_cmd_time = now
        controller.latest_current_command_id = controller._extract_current_command_id_from_feed_data(packet)
        controller.latest_current_command_id_time = now
        controller.latest_tool_vector_target = controller._extract_tool_vector_target_from_feed_data(packet)
        controller.latest_tool_vector_target_time = now
        controller.latest_q_actual = controller._extract_q_actual_from_feed_data(packet)
        controller.latest_q_actual_time = now
        controller.latest_q_target = controller._extract_q_target_from_feed_data(packet)
        controller.latest_q_target_time = now


def test_structured_feedback_fields_are_extracted():
    controller = _make_controller()
    packet = _make_feedback_packet()

    assert controller._extract_pose_from_feed_data(packet).tolist() == [
        100.0, 200.0, 300.0, 1.0, 2.0, 3.0
    ]
    assert controller._extract_tcp_speed_from_feed_data(packet).tolist() == [
        0.1, 0.2, 0.3, 0.4, 0.5, 0.6
    ]
    assert controller._extract_actual_tcp_force_from_feed_data(packet).tolist() == [
        1.0, 2.0, 3.0, 0.1, 0.2, 0.3
    ]
    assert controller._extract_robot_mode_from_feed_data(packet) == 5
    assert controller._extract_current_command_id_from_feed_data(packet) == 1234


def test_force_delta_norm_uses_xyz_resultant():
    assert DobotController._force_delta_norm([4, 6, 3, 0, 0, 0], [1, 2, 3, 0, 0, 0]) == 5.0


def test_prepare_force_guard_averages_pre_motion_baseline(monkeypatch):
    controller = _make_controller()
    snapshots = [
        _force_snapshot([1, 2, 3, 0, 0, 0]),
        _force_snapshot([3, 4, 5, 0, 0, 0]),
    ]

    def fake_snapshot(max_age=0.3):
        return snapshots.pop(0)

    monkeypatch.setattr(controller, "get_motion_feedback_snapshot", fake_snapshot)

    guard = controller.prepare_force_guard({
        "enabled": True,
        "threshold_n": 5,
        "baseline_samples": 2,
        "baseline_interval": 0,
    })

    assert guard["baseline_force"][:3] == [2.0, 3.0, 4.0]
    assert guard["threshold_n"] == 5.0
    assert guard["debounce_samples"] == 1


def test_prepare_force_guard_rejects_missing_force_feedback(monkeypatch):
    controller = _make_controller()
    monkeypatch.setattr(
        controller,
        "get_motion_feedback_snapshot",
        lambda max_age=0.3: {"health": "disconnected", "actual_tcp_force": None},
    )

    with pytest.raises(RuntimeError, match="TCP力反馈不可用"):
        controller.prepare_force_guard({
            "enabled": True,
            "threshold_n": 5,
            "baseline_samples": 1,
            "baseline_interval": 0,
            "sample_timeout": 0.01,
        })


def test_wait_force_guard_stops_and_succeeds_before_command_id(monkeypatch):
    controller = _make_controller()
    controller.dashboard = _FakeStopDashboard()
    snapshots = [
        _force_snapshot([4, 6, 3, 0, 0, 0], command_id=999, robot_mode=5),
        _force_snapshot([4, 6, 3, 0, 0, 0], command_id=999, robot_mode=5),
        _settled_force_snapshot(command_id=999, robot_mode=5),
        _settled_force_snapshot(command_id=999, robot_mode=5),
    ]

    def fake_snapshot(max_age=0.3):
        return snapshots.pop(0) if snapshots else _settled_force_snapshot(command_id=999, robot_mode=5)

    monkeypatch.setattr(controller, "get_motion_feedback_snapshot", fake_snapshot)

    ok = controller.wait_for_motion_completion(
        timeout=0.5,
        poll_interval=0,
        settle_time=0,
        command_id=999,
        force_guard={
            "enabled": True,
            "threshold_n": 4.9,
            "baseline_force": [1, 2, 3, 0, 0, 0],
            "debounce_samples": 2,
        },
    )

    assert ok is True
    assert controller.dashboard.calls == ["Stop"]
    assert controller._last_motion_completion_reason == "force_triggered"
    assert controller._last_force_guard_event["delta_n"] == 5.0
    assert controller._last_force_guard_event["post_robot_mode"] == 5
    assert controller._last_force_guard_event["post_error_status"] == 0


def test_wait_force_guard_waits_for_stop_settle_then_succeeds(monkeypatch):
    controller = _make_controller()
    controller.dashboard = _FakeStopDashboard()
    snapshots = [
        _force_snapshot([4, 6, 3, 0, 0, 0], command_id=999, robot_mode=7),
        _force_snapshot(
            [4, 6, 3, 0, 0, 0],
            command_id=999,
            robot_mode=7,
            tcp_speed=[2.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            running_status=1,
            run_queued_cmd=1,
        ),
        _settled_force_snapshot(command_id=999, robot_mode=5),
        _settled_force_snapshot(command_id=999, robot_mode=5),
    ]

    monkeypatch.setattr(controller, "get_motion_feedback_snapshot", lambda max_age=0.3: snapshots.pop(0))

    ok = controller.wait_for_motion_completion(
        timeout=0.5,
        poll_interval=0,
        settle_time=0,
        command_id=999,
        force_guard={
            "enabled": True,
            "threshold_n": 4.9,
            "baseline_force": [1, 2, 3, 0, 0, 0],
            "debounce_samples": 1,
        },
    )

    assert ok is True
    assert controller.dashboard.calls == ["Stop"]


def test_wait_force_guard_fails_when_stop_settle_sees_alarm(monkeypatch):
    controller = _make_controller()
    controller.dashboard = _FakeStopDashboard()
    snapshots = [
        _force_snapshot([4, 6, 3, 0, 0, 0], command_id=999, robot_mode=7),
        _settled_force_snapshot(command_id=999, robot_mode=9),
    ]
    def fake_safety_state():
        return MotionSafetyState(is_connected=True, is_enabled=True, error_status=1, robot_mode=9, feedback_age=0.0)

    monkeypatch.setattr(controller, "get_motion_feedback_snapshot", lambda max_age=0.3: snapshots.pop(0))
    monkeypatch.setattr(controller, "get_motion_safety_state", fake_safety_state)

    ok = controller.wait_for_motion_completion(
        timeout=0.5,
        poll_interval=0,
        settle_time=0,
        command_id=999,
        force_guard={
            "enabled": True,
            "threshold_n": 4.9,
            "baseline_force": [1, 2, 3, 0, 0, 0],
            "debounce_samples": 1,
        },
    )

    assert ok is False
    assert "力触发Stop后机器人报警" in controller.last_error


def test_relative_motion_retries_once_after_stop_rejected(monkeypatch):
    controller = _make_controller()
    controller.is_enabled = True
    controller.dashboard = _FakeRelativeRetryDashboard()
    controller.latest_pose = [0.0, 0.0, 200.0, 0.0, 0.0, 0.0]

    monkeypatch.setattr(
        controller,
        "get_motion_safety_state",
        lambda: MotionSafetyState(
            is_connected=True,
            is_enabled=True,
            error_status=0,
            robot_mode=5,
            feedback_age=0.0,
        ),
    )
    monkeypatch.setattr(
        controller,
        "get_motion_feedback_snapshot",
        lambda max_age=0.3: _settled_force_snapshot(command_id=42, robot_mode=5),
    )
    monkeypatch.setattr(controller, "wait_for_motion_completion", lambda **kwargs: True)

    ok = controller.move_relative(
        [10, 0, 0, 0, 0, 0],
        coord_system="user",
        motion_type="linear",
        speed=20,
        acceleration=20,
        cp=10,
        wait_poll_interval=0,
    )

    assert ok is True
    assert controller.dashboard.calls == ["RelMovLUser", "Stop", "RelMovLUser"]
    assert controller._last_command_id == 42


def test_feedback_health_uses_feed_timestamp():
    controller = _make_controller()
    packet = _make_feedback_packet()
    _cache_packet(controller, packet)

    health = controller.get_feedback_health(max_age=0.3)

    assert health["health"] == "ok"
    assert health["robot_mode"] == 5
    assert health["pose"] == [100.0, 200.0, 300.0, 1.0, 2.0, 3.0]


def test_motion_snapshot_uses_feed_timestamp_even_without_pose_timestamp():
    controller = _make_controller()
    packet = _make_feedback_packet()
    _cache_packet(controller, packet)
    controller.latest_pose_time = 0.0

    snapshot = controller.get_motion_feedback_snapshot(max_age=0.3)

    assert snapshot["health"] == "ok"
    assert snapshot["timestamp"] == controller.latest_feed_time
    assert snapshot["pose_timestamp"] == 0.0
    assert snapshot["current_command_id"] == 1234
    assert snapshot["actual_tcp_force"] == [1.0, 2.0, 3.0, 0.1, 0.2, 0.3]


def test_stop_feedback_clears_cached_packet(monkeypatch):
    controller = _make_controller()
    packet = _make_feedback_packet()
    _cache_packet(controller, packet)
    controller._feed_running = True

    monkeypatch.setattr(controller, "feed_four", None)
    monkeypatch.setattr(controller, "feed_thread", None)

    controller.stop_feedback()

    assert controller.feed_data is None
    assert controller.latest_feed_time == 0.0
    assert controller.latest_pose is None
    assert controller.latest_actual_tcp_force is None


def test_robot_connect_atomically_publishes_valid_transports(monkeypatch):
    packet = _make_feedback_packet()
    _install_atomic_transports(monkeypatch, packet)
    controller = DobotController("192.168.1.50")

    assert controller.connect() is True
    assert controller.dashboard is _AtomicDashboard.instances[0]
    assert controller.feed_four is _AtomicFeedback.instances[0]
    assert controller.is_connected is True
    assert controller.get_feedback_health()["health"] == "ok"
    assert _AtomicDashboard.instances[0].kwargs["connect_timeout"] <= 2.0

    controller.close_robot_transport()


def test_robot_connect_failure_does_not_publish_partial_transport(monkeypatch):
    packet = _make_feedback_packet()
    packet["TestValue"][0] = 0
    _install_atomic_transports(monkeypatch, packet)
    controller = DobotController("192.168.1.50")
    controller._robot_connect_deadline_s = 0.05
    existing_dashboard = _FakeStopDashboard()
    controller.dashboard = existing_dashboard

    assert controller.connect() is False
    assert controller.dashboard is existing_dashboard
    assert controller.feed_four is None
    assert controller.is_connected is False
    assert _AtomicDashboard.instances[0].closed is True
    assert _AtomicFeedback.instances[0].closed is True


def test_robot_connect_discards_result_after_generation_changes(monkeypatch):
    packet = _make_feedback_packet()
    _install_atomic_transports(monkeypatch, packet)
    entered = threading.Event()
    release = threading.Event()
    _AtomicFeedback.entered = entered
    _AtomicFeedback.release = release
    controller = DobotController("192.168.1.50")
    controller._robot_connect_deadline_s = 1.0
    results = []

    worker = threading.Thread(target=lambda: results.append(controller.connect()))
    worker.start()
    assert entered.wait(1.0)

    controller.close_robot_transport()
    release.set()
    worker.join(timeout=2.0)

    assert results == [False]
    assert controller.dashboard is None
    assert controller.feed_four is None
    assert controller.is_connected is False
    assert _AtomicDashboard.instances[0].closed is True
    assert _AtomicFeedback.instances[0].closed is True


def test_maintenance_mode_blocks_modbus_motion_commands(monkeypatch):
    controller = DobotController("192.168.1.50")
    run_calls = []
    monkeypatch.setattr(
        controller,
        "_modbus_run_edited_program",
        lambda mode=0: run_calls.append(mode),
    )
    controller.set_runtime_maintenance(True)

    controller._on_modbus_command(3, mode=0)

    assert run_calls == []
    assert controller._modbus_status_override == 0


def test_maintenance_stop_does_not_auto_enable_robot(monkeypatch):
    controller = DobotController("192.168.1.50")
    auto_enable_values = []
    monkeypatch.setattr(
        controller,
        "_clear_faults_for_modbus_zero",
        lambda auto_enable=True: auto_enable_values.append(auto_enable),
    )
    controller.set_runtime_maintenance(True)

    controller._on_modbus_command(0, mode=0)

    assert auto_enable_values == [False]
