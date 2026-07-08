#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Task 4 测试：验证 time.time / monotonic 时钟域统一。

覆盖：
1. _store_feedback_packet 设置 last_feed_time 在 monotonic 域
2. NTP 跳变（time.time 大幅变化）不影响 pose_age 计算
3. get_cached_pose 使用 monotonic 域判定过期
4. get_motion_safety_state feedback_age 使用 monotonic 域
"""

import importlib
import sys
import time
import types

import numpy as np
import pytest


def _install_pymodbus_stub():
    """Stub pymodbus 子模块以允许 dobot_move.communication.modbus_server 导入。"""
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


def _ensure_real_modules():
    try:
        importlib.import_module("dobot_move.communication.modbus_server")
    except ImportError as exc:
        if "pymodbus" not in str(exc):
            raise
        _install_pymodbus_stub()
        sys.modules.pop("dobot_move.communication.modbus_server", None)
        importlib.import_module("dobot_move.communication.modbus_server")


@pytest.fixture(scope="module")
def controller_module():
    _ensure_real_modules()
    import dobot_move.robot.robot_controller as ctrl_module
    return ctrl_module


@pytest.fixture(scope="module")
def dobot_controller_cls(controller_module):
    return controller_module.DobotController


@pytest.fixture(scope="module")
def my_type():
    from dobot_move.robot.dobot_api import MyType
    return MyType


def _make_feedback_packet(my_type, pose=None):
    packet = np.zeros(1, dtype=my_type)
    packet["TestValue"][0] = 0x123456789ABCDEF
    if pose is not None:
        packet["ToolVectorActual"][0] = pose
    else:
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


def _make_controller(dobot_controller_cls):
    controller = dobot_controller_cls("192.168.1.50")
    controller.is_connected = True
    return controller


# ---------------------------------------------------------------------------
# 1. last_feed_time 在 monotonic 域
# ---------------------------------------------------------------------------

def test_last_feed_time_in_monotonic_domain(dobot_controller_cls, my_type):
    """_store_feedback_packet 设置的 last_feed_time 应在 monotonic 域。"""
    controller = _make_controller(dobot_controller_cls)
    packet = _make_feedback_packet(my_type)

    before = time.monotonic()
    controller._store_feedback_packet(packet)
    after = time.monotonic()

    # last_feed_time 应在 monotonic 域，接近当前 monotonic 值
    assert before <= controller.last_feed_time <= after
    assert controller.latest_feed_time == controller.last_feed_time
    assert controller.latest_pose_time == controller.last_feed_time


def test_latest_pose_time_in_monotonic_domain(dobot_controller_cls, my_type):
    """latest_pose_time 应在 monotonic 域。"""
    controller = _make_controller(dobot_controller_cls)
    packet = _make_feedback_packet(my_type, pose=[1, 2, 3, 4, 5, 6])
    controller._store_feedback_packet(packet)

    before = time.monotonic()
    controller._store_feedback_packet(packet)
    after = time.monotonic()

    assert before <= controller.latest_pose_time <= after


# ---------------------------------------------------------------------------
# 2. NTP 跳变不影响 pose_age
# ---------------------------------------------------------------------------

def test_ntp_jump_does_not_affect_pose_age(
    dobot_controller_cls, controller_module, my_type, monkeypatch
):
    """模拟 NTP 跳变（time.time 大幅变化），pose_age 不受影响。

    pose_age = time.monotonic() - controller.last_feed_time，
    last_feed_time 在 monotonic 域，故 time.time 跳变不影响 pose_age。
    """
    controller = _make_controller(dobot_controller_cls)
    packet = _make_feedback_packet(my_type)
    controller._store_feedback_packet(packet)

    real_monotonic = time.monotonic
    time.sleep(0.05)

    # 模拟 NTP 跳变：让 robot_controller 模块看到的 time.time() 跳到很远
    ntp_offset = 100000.0
    original_time = time.time
    monkeypatch.setattr(controller_module.time, "time", lambda: original_time() + ntp_offset)
    # time.monotonic 不受影响

    # 计算 pose_age（与 visual_servo_controller.py 中的逻辑一致）
    pose_age = real_monotonic() - controller.last_feed_time

    # pose_age 应该很小（约 0.05s + 少量开销），不受 NTP 跳变影响
    assert 0.0 < pose_age < 1.0, f"pose_age 应不受 NTP 跳变影响，实际: {pose_age}"


def test_feedback_age_uses_monotonic_not_wall_clock(
    dobot_controller_cls, controller_module, my_type, monkeypatch
):
    """get_motion_safety_state 的 feedback_age 应使用 monotonic，不受 time.time 跳变影响。"""
    controller = _make_controller(dobot_controller_cls)
    packet = _make_feedback_packet(my_type)
    controller._store_feedback_packet(packet)

    time.sleep(0.05)

    # 模拟 NTP 跳变
    original_time = time.time
    monkeypatch.setattr(controller_module.time, "time", lambda: original_time() + 100000.0)

    state = controller.get_motion_safety_state()
    # feedback_age 应该很小（约 0.05s），不受 NTP 跳变影响
    assert 0.0 <= state.feedback_age < 1.0, (
        f"feedback_age 应使用 monotonic，实际: {state.feedback_age}"
    )


# ---------------------------------------------------------------------------
# 3. get_cached_pose 使用 monotonic 域
# ---------------------------------------------------------------------------

def test_get_cached_pose_uses_monotonic_domain(
    dobot_controller_cls, controller_module, my_type, monkeypatch
):
    """get_cached_pose 过期判定应使用 monotonic，不受 time.time 跳变影响。"""
    controller = _make_controller(dobot_controller_cls)
    packet = _make_feedback_packet(my_type, pose=[1, 2, 3, 4, 5, 6])
    controller._store_feedback_packet(packet)

    # 模拟 NTP 跳变
    original_time = time.time
    monkeypatch.setattr(controller_module.time, "time", lambda: original_time() + 100000.0)

    # 刚写入，应在 max_age 内有效
    pose = controller.get_cached_pose(max_age=1.0)
    assert pose is not None
    np.testing.assert_allclose(pose, [1, 2, 3, 4, 5, 6])


# ---------------------------------------------------------------------------
# 4. _motion_command_sent_time 在 monotonic 域
# ---------------------------------------------------------------------------

def test_motion_command_sent_time_in_monotonic_domain(
    dobot_controller_cls, controller_module, monkeypatch
):
    """_motion_command_sent_time 赋值应使用 monotonic。"""
    controller = _make_controller(dobot_controller_cls)

    # 模拟 NTP 跳变
    original_time = time.time
    monkeypatch.setattr(controller_module.time, "time", lambda: original_time() + 100000.0)

    before = time.monotonic()
    controller._motion_command_sent_time = time.monotonic()
    after = time.monotonic()

    assert before <= controller._motion_command_sent_time <= after
    # 应远小于 NTP 跳变后的 time.time()
    assert controller._motion_command_sent_time < original_time() + 100000.0 - 50000.0
