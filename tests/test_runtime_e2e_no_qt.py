#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""端到端无 Qt 测试：证明 Runtime 可在 PySide6 不可用条件下运行相机步骤。

测试策略（简化方案）：
1. AST 级检查：``flow_executor.py`` 和 ``capture_worker.py`` 源码无 Qt 导入
   （``qt_compat`` / ``PySide6`` / ``PyQt6`` / ``QThread`` / ``QImage`` / ``pyqtSignal``）。
2. 运行时导入测试：在 ``sys.modules`` 中插入 ``None`` 阻止 ``PySide6`` 和
   ``dobot_move.ui.qt_compat`` 导入，然后 ``FlowExecutor`` 和 ``CaptureWorker``
   必须成功导入。
3. Mock Camera 集成：构造 Mock VisionSystem（``capture_numpy_packet(seq)``
   返回预设 ``FramePacket``），用 ``CaptureWorker`` 启动采集线程，验证
   ``get_latest()`` 能拿到帧。
"""

import ast
import importlib
import inspect
import os
import sys
import threading
import time
import types

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# 辅助：mock 重依赖（pyrealsense2 / pymodbus），与现有测试保持一致
# ---------------------------------------------------------------------------

def _ensure_mock_modules():
    """Stub out optional heavy deps so vision_system can be imported."""
    if "pyrealsense2" not in sys.modules:
        sys.modules["pyrealsense2"] = types.ModuleType("pyrealsense2")

    pymodbus = sys.modules.setdefault("pymodbus", types.ModuleType("pymodbus"))

    class _ModbusDeviceIdentification:
        pass

    pymodbus.ModbusDeviceIdentification = getattr(
        pymodbus, "ModbusDeviceIdentification", _ModbusDeviceIdentification
    )

    server = sys.modules.setdefault("pymodbus.server", types.ModuleType("pymodbus.server"))

    class _ModbusTcpServer:
        pass

    server.ModbusTcpServer = getattr(server, "ModbusTcpServer", _ModbusTcpServer)

    simulator = sys.modules.setdefault(
        "pymodbus.simulator", types.ModuleType("pymodbus.simulator")
    )

    class _SimData:
        pass

    class _SimDevice:
        pass

    class _DataType:
        REGISTERS = "registers"

    simulator.SimData = getattr(simulator, "SimData", _SimData)
    simulator.SimDevice = getattr(simulator, "SimDevice", _SimDevice)
    simulator.DataType = getattr(simulator, "DataType", _DataType)


def _module_source_path(module):
    source_path = inspect.getsourcefile(module)
    assert source_path is not None, f"cannot find source for {module.__name__}"
    return source_path


def _check_no_qt_imports_in_source(source_path, module_label):
    """AST 级检查：源码不得从 Qt 模块导入或导入 Qt 符号。"""
    with open(source_path, encoding="utf-8") as f:
        source = f.read()
    tree = ast.parse(source)
    qt_symbols = {"QThread", "QImage", "pyqtSignal", "QTimer", "QObject",
                  "QColor", "QPalette", "QPainter", "QPen", "QWidget"}
    qt_modules = {"qt_compat", "PySide6", "PyQt6"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert module not in qt_modules, (
                f"{module_label} imports from {module} at line {node.lineno}"
            )
            for alias in node.names:
                assert alias.name not in qt_symbols, (
                    f"{module_label} imports Qt symbol {alias.name} at line {node.lineno}"
                )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith(("PySide6", "PyQt6")), (
                    f"{module_label} imports {alias.name} at line {node.lineno}"
                )


def _check_no_camera_test_worker_imports_in_source(source_path, module_label):
    """AST 级检查：源码不得从 ``camera_test_worker`` 导入（会拉入 Qt）。"""
    with open(source_path, encoding="utf-8") as f:
        source = f.read()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert "camera_test_worker" not in module, (
                f"{module_label} imports from {module} at line {node.lineno} "
                f"(should use vision.capture_worker instead)"
            )


# ---------------------------------------------------------------------------
# 测试 1：AST 级检查
# ---------------------------------------------------------------------------

def test_capture_worker_source_has_no_qt_imports():
    """vision/capture_worker.py 源码不得包含任何 Qt 导入。"""
    _ensure_mock_modules()
    import dobot_move.vision.capture_worker as cw
    _check_no_qt_imports_in_source(_module_source_path(cw), "capture_worker")


def test_flow_executor_source_has_no_qt_imports():
    """flow/flow_executor.py 源码不得包含任何 Qt 导入。"""
    _ensure_mock_modules()
    from dobot_move.flow import flow_executor
    _check_no_qt_imports_in_source(_module_source_path(flow_executor), "flow_executor")


def test_flow_executor_source_has_no_camera_test_worker_imports():
    """flow_executor.py 不得从 camera_test_worker 导入（会拉入 Qt）。"""
    _ensure_mock_modules()
    from dobot_move.flow import flow_executor
    _check_no_camera_test_worker_imports_in_source(
        _module_source_path(flow_executor), "flow_executor"
    )


def test_capture_worker_source_has_no_camera_test_worker_imports():
    """capture_worker.py 不得从 camera_test_worker 导入。"""
    _ensure_mock_modules()
    import dobot_move.vision.capture_worker as cw
    _check_no_camera_test_worker_imports_in_source(
        _module_source_path(cw), "capture_worker"
    )


# ---------------------------------------------------------------------------
# 测试 2：运行时导入测试（PySide6 不可用）
# ---------------------------------------------------------------------------

def test_import_flow_executor_and_capture_worker_without_qt():
    """在 PySide6 / qt_compat 不可用条件下，FlowExecutor 和 CaptureWorker
    必须成功导入，全程无 ImportError。

    若 Qt 已被其他测试加载，则跳过（AST 测试已覆盖此场景）。
    """
    _ensure_mock_modules()
    qt_already_loaded = any(
        name.startswith(("PySide6", "PyQt6")) or name == "dobot_move.ui.qt_compat"
        for name in sys.modules
    )
    if qt_already_loaded:
        pytest.skip("Qt already loaded by another test; AST tests cover this case")

    # 阻止 PySide6 / PyQt6 / qt_compat 导入：sys.modules[name] = None 会让
    # ``import name`` 抛出 ImportError。
    saved = {}
    blocked_names = ("PySide6", "PyQt6", "dobot_move.ui.qt_compat",
                     "dobot_move.ui.camera_test_worker", "dobot_move.flow.qt_workers")
    for name in blocked_names:
        saved[name] = sys.modules.get(name, _MISSING)
        sys.modules[name] = None

    # 清除可能已缓存的 flow_executor / capture_worker 以触发重新导入
    for name in list(sys.modules):
        if name.startswith("dobot_move.flow.flow_executor") or \
           name.startswith("dobot_move.vision.capture_worker"):
            del sys.modules[name]

    try:
        importlib.import_module("dobot_move.flow.flow_executor")
        importlib.import_module("dobot_move.vision.capture_worker")

        # 确认 Qt 模块未被真正加载（sys.modules 中值为 None 表示被阻止，不算加载）
        qt_loaded = [
            name for name, value in sys.modules.items()
            if value is not None and (
                name.startswith(("PySide6", "PyQt6"))
                or name == "dobot_move.ui.qt_compat"
            )
        ]
        assert not qt_loaded, (
            f"importing flow_executor/capture_worker pulled in Qt: {sorted(qt_loaded)}"
        )
    finally:
        # 恢复 sys.modules
        for name, value in saved.items():
            if value is _MISSING:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value


# ---------------------------------------------------------------------------
# 测试 3：Mock Camera 集成测试
# ---------------------------------------------------------------------------

class MockVisionSystem:
    """最小化的 VisionSystem mock，仅实现 CaptureWorker 需要的接口。"""

    def __init__(self, packets):
        self._packets = list(packets)
        self._call_count = 0
        self._lock = threading.Lock()

    def capture_numpy_packet(self, seq):
        """返回预设的 FramePacket，模拟相机采集。"""
        with self._lock:
            if self._call_count >= len(self._packets):
                return None
            packet = self._packets[self._call_count]
            self._call_count += 1
        return packet

    def reset_tracking(self):
        """兼容 CaptureWorker 调用链（flow_executor 会在启动前调用）。"""
        pass


def test_capture_worker_collects_frames_from_mock_vision():
    """CaptureWorker 启动后应持续采集帧，get_latest() 能拿到最新 FramePacket。"""
    from dobot_move.vision.vision_system import FramePacket
    from dobot_move.vision.capture_worker import CaptureWorker, CaptureThread

    # 构造 3 个预设帧
    packets = [
        FramePacket(
            seq=i,
            timestamp=float(i),
            color_image=np.zeros((4, 4, 3), dtype=np.uint8),
            depth_image=np.ones((4, 4), dtype=np.uint16),
        )
        for i in range(3)
    ]
    vision = MockVisionSystem(packets)

    worker = CaptureWorker(vision)
    assert CaptureThread is CaptureWorker, "CaptureThread should be alias of CaptureWorker"

    worker.start()
    try:
        # 等待 worker 采集到至少一帧
        deadline = time.perf_counter() + 2.0
        latest_packet = None
        while time.perf_counter() < deadline:
            latest_packet, capture_ms = worker.get_latest()
            if latest_packet is not None:
                break
            time.sleep(0.01)

        assert latest_packet is not None, "CaptureWorker did not capture any frame within 2s"
        assert isinstance(latest_packet, FramePacket)
        assert latest_packet.seq >= 0
    finally:
        worker.stop()
        worker.join(timeout=2.0)
        assert not worker.is_alive(), "CaptureWorker should terminate after stop()"


def test_capture_worker_get_latest_returns_none_before_first_frame():
    """CaptureWorker 启动前 / 无帧时 get_latest() 返回 (None, 0.0)。"""
    from dobot_move.vision.capture_worker import CaptureWorker

    # vision.capture_numpy_packet 返回 None（模拟无帧）
    vision = MockVisionSystem([])
    worker = CaptureWorker(vision)

    packet, capture_ms = worker.get_latest()
    assert packet is None
    assert capture_ms == 0.0

    # 启动后仍应优雅处理无帧情况
    worker.start()
    try:
        time.sleep(0.1)
        packet, capture_ms = worker.get_latest()
        assert packet is None
    finally:
        worker.stop()
        worker.join(timeout=2.0)


# 用于标记 sys.modules 中"原本不存在"的哨兵
_MISSING = object()
