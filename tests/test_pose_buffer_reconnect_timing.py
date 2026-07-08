#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Task 1 测试：验证 PoseBuffer clear 时序。

覆盖：
1. close_robot_transport() 中 feed_thread.join() 在 pose_buffer.clear() 之前调用
2. close 后新 push 的位姿不被 clear 抹掉
3. connect() 重连后 pose_buffer 被清空（旧位姿不残留）
"""

import importlib
import sys
import threading
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


class _FakeTransportSocket:
    def __init__(self):
        self.timeout = 1.0

    def gettimeout(self):
        return self.timeout

    def settimeout(self, value):
        self.timeout = value


class _AtomicDashboard:
    def __init__(self, ip, port, **kwargs):
        self.socket_dobot = _FakeTransportSocket()
        self.closed = False

    def RobotMode(self):
        return "0,{5},RobotMode();"

    def GetAngle(self):
        return "0,{1,2,3,4,5,6},GetAngle();"

    def close(self):
        self.closed = True


class _AtomicFeedback:
    packet = None

    def __init__(self, ip, port, **kwargs):
        self.socket_dobot = _FakeTransportSocket()
        self.closed = False

    def feedBackData(self):
        time.sleep(0.005)
        return self.packet

    def close(self):
        self.closed = True


def _install_atomic_transports(controller_module, monkeypatch, packet):
    _AtomicFeedback.packet = packet
    monkeypatch.setattr(controller_module, "DobotApiDashboard", _AtomicDashboard)
    monkeypatch.setattr(controller_module, "DobotApiFeedBack", _AtomicFeedback)


# ---------------------------------------------------------------------------
# 1. close_robot_transport() 中 join 在 clear 之前
# ---------------------------------------------------------------------------

def test_close_robot_transport_joins_thread_before_clear(
    dobot_controller_cls, controller_module, my_type, monkeypatch
):
    """close_robot_transport() 必须先 join feedback 线程，再 clear pose_buffer。

    通过追踪 join() 和 clear() 的调用顺序验证时序不变量。
    """
    packet = _make_feedback_packet(my_type)
    _install_atomic_transports(controller_module, monkeypatch, packet)
    controller = dobot_controller_cls("192.168.1.50")
    assert controller.connect() is True

    # 记录调用顺序
    call_order = []
    original_join = controller.feed_thread.join

    def tracking_join(timeout=None):
        call_order.append("join_start")
        original_join(timeout=timeout)
        call_order.append("join_end")

    controller.feed_thread.join = tracking_join

    original_clear = controller.pose_buffer.clear

    def tracking_clear():
        call_order.append("clear")
        original_clear()

    controller.pose_buffer.clear = tracking_clear

    controller.close_robot_transport()

    # join 必须在 clear 之前完成
    join_idx = call_order.index("join_start")
    clear_idx = call_order.index("clear")
    assert join_idx < clear_idx, f"join 应在 clear 之前，实际顺序: {call_order}"


# ---------------------------------------------------------------------------
# 2. close 后新 push 不被 clear 抹掉
# ---------------------------------------------------------------------------

def test_push_after_close_not_wiped(dobot_controller_cls):
    """close_robot_transport() 后 push 到 pose_buffer 的位姿不被抹掉。"""
    controller = _make_controller(dobot_controller_cls)
    controller.pose_buffer.clear()
    assert len(controller.pose_buffer) == 0

    # 模拟 close 后新帧到达
    controller.pose_buffer.push(time.perf_counter(), [1, 2, 3, 4, 5, 6])
    assert len(controller.pose_buffer) == 1

    _, p = controller.pose_buffer.latest()
    np.testing.assert_allclose(p, [1, 2, 3, 4, 5, 6])


# ---------------------------------------------------------------------------
# 3. connect() 重连后 pose_buffer 被清空
# ---------------------------------------------------------------------------

def test_connect_clears_old_pose_buffer(
    dobot_controller_cls, controller_module, my_type, monkeypatch
):
    """connect() 成功后 pose_buffer 中旧位姿被清空。"""
    packet = _make_feedback_packet(my_type)
    _install_atomic_transports(controller_module, monkeypatch, packet)
    controller = dobot_controller_cls("192.168.1.50")

    # 预填充旧位姿
    controller.pose_buffer.push(time.perf_counter() - 10, [99, 99, 99, 0, 0, 0])
    controller.pose_buffer.push(time.perf_counter() - 5, [88, 88, 88, 0, 0, 0])
    assert len(controller.pose_buffer) == 2

    assert controller.connect() is True

    # 旧位姿应被清空
    assert len(controller.pose_buffer) == 0

    controller.close_robot_transport()


def _make_controller(dobot_controller_cls):
    controller = dobot_controller_cls("192.168.1.50")
    controller.is_connected = True
    return controller
