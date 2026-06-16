"""Regression tests for Dobot 30004 feedback cache parsing."""
import sys
import time
import types

import numpy as np


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
from dobot_move.robot_controller import DobotController  # noqa: E402


def _make_feedback_packet():
    packet = np.zeros(1, dtype=MyType)
    packet["TestValue"][0] = 0x123456789ABCDEF
    packet["ToolVectorActual"][0] = [100.0, 200.0, 300.0, 1.0, 2.0, 3.0]
    packet["TCPSpeedActual"][0] = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
    packet["ToolVectorTarget"][0] = [101.0, 201.0, 301.0, 1.1, 2.1, 3.1]
    packet["QActual"][0] = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0]
    packet["QTarget"][0] = [11.0, 21.0, 31.0, 41.0, 51.0, 61.0]
    packet["RobotMode"][0] = 5
    packet["RunningStatus"][0] = 0
    packet["RunQueuedCmd"][0] = 0
    packet["CurrentCommandId"][0] = 1234
    return packet


def _make_controller():
    controller = DobotController("192.168.1.50")
    controller.is_connected = True
    return controller


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
    assert controller._extract_robot_mode_from_feed_data(packet) == 5
    assert controller._extract_current_command_id_from_feed_data(packet) == 1234


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
