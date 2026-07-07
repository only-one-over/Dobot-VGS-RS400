#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PR1 集成测试：RobotController.pose_buffer 与 feedback 流的集成。

验证：
1. DobotController.__init__ 中构造 pose_buffer
2. _store_feedback_packet 对每个有效 Pose push 到 pose_buffer
3. clear() 后 pose_buffer 为空
4. connect() 成功后清空 pose_buffer
5. close_robot_transport() 清空 pose_buffer

不依赖硬件：使用 mock feedback packet + mock transport。

注意：pymodbus 桩在 fixture 中安装（非模块顶层），避免污染 pytest 收集阶段的
sys.modules，导致 test_modbus_deadlock.py 误跳过→失败。
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
    """导入 robot_controller，必要时安装 pymodbus 桩。

    在 fixture 中调用（非模块顶层），确保仅在测试执行阶段安装桩。
    """
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
    """在测试执行阶段（非收集阶段）导入 robot_controller 模块。"""
    _ensure_real_modules()
    import dobot_move.robot.robot_controller as ctrl_module
    return ctrl_module


@pytest.fixture(scope="module")
def dobot_controller_cls(controller_module):
    return controller_module.DobotController


@pytest.fixture(scope="module")
def robot_pose_buffer_cls():
    from dobot_move.robot.robot_pose_buffer import RobotPoseBuffer
    return RobotPoseBuffer


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


def _install_atomic_transports(controller_module, monkeypatch, packet):
    _AtomicDashboard.instances = []
    _AtomicFeedback.instances = []
    _AtomicFeedback.packet = packet
    _AtomicFeedback.entered = None
    _AtomicFeedback.release = None
    monkeypatch.setattr(controller_module, "DobotApiDashboard", _AtomicDashboard)
    monkeypatch.setattr(controller_module, "DobotApiFeedBack", _AtomicFeedback)


def _make_controller(dobot_controller_cls):
    controller = dobot_controller_cls("192.168.1.50")
    controller.is_connected = True
    return controller


# ---------------------------------------------------------------------------
# 1. DobotController 拥有 pose_buffer
# ---------------------------------------------------------------------------

def test_controller_has_pose_buffer(dobot_controller_cls, robot_pose_buffer_cls):
    """DobotController.__init__ 中构造 pose_buffer (RobotPoseBuffer 实例)。"""
    controller = _make_controller(dobot_controller_cls)
    assert isinstance(controller.pose_buffer, robot_pose_buffer_cls)
    assert len(controller.pose_buffer) == 0


# ---------------------------------------------------------------------------
# 2. _store_feedback_packet 对有效 Pose push 到 pose_buffer
# ---------------------------------------------------------------------------

def test_store_feedback_packet_pushes_pose_to_buffer(dobot_controller_cls, my_type):
    """_store_feedback_packet 收到有效 Pose 后 pose_buffer 新增一条记录。"""
    controller = _make_controller(dobot_controller_cls)
    assert len(controller.pose_buffer) == 0

    packet = _make_feedback_packet(my_type, pose=[100.0, 200.0, 300.0, 1.0, 2.0, 3.0])
    controller._store_feedback_packet(packet)

    assert len(controller.pose_buffer) == 1
    t, p = controller.pose_buffer.latest()
    assert t > 0.0
    np.testing.assert_allclose(p, [100.0, 200.0, 300.0, 1.0, 2.0, 3.0])


def test_store_feedback_packet_multiple_pushes(dobot_controller_cls, my_type):
    """连续多个 feedback 包 → pose_buffer 有多条记录，latest 为最后一个。"""
    controller = _make_controller(dobot_controller_cls)

    for i in range(5):
        packet = _make_feedback_packet(my_type, pose=[float(i), 0.0, 0.0, 0.0, 0.0, 0.0])
        controller._store_feedback_packet(packet)

    assert len(controller.pose_buffer) == 5
    _, p = controller.pose_buffer.latest()
    np.testing.assert_allclose(p, [4.0, 0.0, 0.0, 0.0, 0.0, 0.0])


def test_store_feedback_packet_does_not_push_when_pose_missing(
    dobot_controller_cls, my_type, monkeypatch
):
    """pose 提取失败时不应 push（pose_buffer 保持空）。"""
    controller = _make_controller(dobot_controller_cls)

    # 让 _extract_pose_from_feed_data 返回 None
    monkeypatch.setattr(controller, "_extract_pose_from_feed_data", lambda data: None)

    packet = _make_feedback_packet(my_type)
    controller._store_feedback_packet(packet)

    assert len(controller.pose_buffer) == 0


# ---------------------------------------------------------------------------
# 3. clear() 后 pose_buffer 为空
# ---------------------------------------------------------------------------

def test_pose_buffer_clear_after_store(dobot_controller_cls, my_type):
    """push 后 clear() → pose_buffer 为空，pose_at 返回 (None, False)。"""
    controller = _make_controller(dobot_controller_cls)
    packet = _make_feedback_packet(my_type, pose=[100.0, 200.0, 300.0, 1.0, 2.0, 3.0])
    controller._store_feedback_packet(packet)
    assert len(controller.pose_buffer) == 1

    controller.pose_buffer.clear()
    assert len(controller.pose_buffer) == 0
    pose, ok = controller.pose_buffer.pose_at(time.perf_counter())
    assert ok is False
    assert pose is None


# ---------------------------------------------------------------------------
# 4. connect() 成功后清空 pose_buffer
# ---------------------------------------------------------------------------

def test_connect_clears_pose_buffer(dobot_controller_cls, controller_module, my_type, monkeypatch):
    """connect() 成功后 pose_buffer.clear() 被执行。"""
    packet = _make_feedback_packet(my_type)
    _install_atomic_transports(controller_module, monkeypatch, packet)
    controller = dobot_controller_cls("192.168.1.50")

    # 预填充 pose_buffer，验证 connect() 后被清空
    controller.pose_buffer.push(time.perf_counter(), [1, 2, 3, 4, 5, 6])
    controller.pose_buffer.push(time.perf_counter(), [7, 8, 9, 10, 11, 12])
    assert len(controller.pose_buffer) == 2

    assert controller.connect() is True

    # connect() 成功后 pose_buffer 应被清空
    assert len(controller.pose_buffer) == 0

    controller.close_robot_transport()


# ---------------------------------------------------------------------------
# 5. close_robot_transport() 清空 pose_buffer
# ---------------------------------------------------------------------------

def test_close_robot_transport_clears_pose_buffer(
    dobot_controller_cls, controller_module, my_type, monkeypatch
):
    """close_robot_transport() 后 pose_buffer.clear() 被执行。"""
    packet = _make_feedback_packet(my_type)
    _install_atomic_transports(controller_module, monkeypatch, packet)
    controller = dobot_controller_cls("192.168.1.50")
    assert controller.connect() is True

    # 模拟 feedback 线程已 push 一些位姿
    for i in range(3):
        p = _make_feedback_packet(my_type, pose=[float(i), 0, 0, 0, 0, 0])
        controller._store_feedback_packet(p)
    assert len(controller.pose_buffer) == 3

    controller.close_robot_transport()

    # close_robot_transport 后 pose_buffer 应被清空
    assert len(controller.pose_buffer) == 0
