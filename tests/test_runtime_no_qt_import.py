#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify that runtime_agent.py does not depend on Qt.

The headless runtime must run without PySide6/PyQt6. These tests use
AST analysis (immune to test-ordering side effects) plus a runtime
import check when Qt hasn't been loaded yet.
"""

import ast
import importlib
import inspect
import sys
import types


# --- AST-based checks (reliable, no test-ordering issues) -------------------

def _check_no_qt_imports(module_path, module_name):
    """Assert that a module's source has no Qt imports at module level."""
    with open(module_path, encoding="utf-8") as f:
        source = f.read()
    tree = ast.parse(source)
    qt_symbols = {"QThread", "QImage", "pyqtSignal", "QTimer", "QObject",
                  "QColor", "QPalette", "QPainter", "QPen", "QWidget"}
    qt_modules = {"qt_compat", "PySide6", "PyQt6"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert module not in qt_modules, (
                f"{module_name} imports from {module} at line {node.lineno}"
            )
            for alias in node.names:
                assert alias.name not in qt_symbols, (
                    f"{module_name} imports Qt symbol {alias.name} at line {node.lineno}"
                )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith(("PySide6", "PyQt6")), (
                    f"{module_name} imports {alias.name} at line {node.lineno}"
                )


def test_runtime_agent_source_has_no_qt_imports():
    """runtime_agent.py must not contain any Qt import statements."""
    import dobot_move.runtime.runtime_agent as ra
    source_path = inspect.getsourcefile(ra)
    _check_no_qt_imports(source_path, "runtime_agent")


def test_flow_executor_source_has_no_qt_imports():
    """flow_executor.py must not contain any Qt import statements."""
    from dobot_move.flow import flow_executor
    source_path = inspect.getsourcefile(flow_executor)
    _check_no_qt_imports(source_path, "flow_executor")


def test_runtime_agent_module_has_no_qt_symbols():
    """The runtime_agent module namespace should not contain Qt symbols."""
    # Ensure pymodbus stubs exist so import doesn't fail
    _ensure_mock_modules()
    mod = importlib.import_module("dobot_move.runtime.runtime_agent")
    for symbol in ("QThread", "QImage", "pyqtSignal", "QTimer", "QObject"):
        assert not hasattr(mod, symbol), (
            f"runtime_agent has Qt symbol '{symbol}'"
        )


# --- Runtime import check (only meaningful when Qt not yet loaded) ----------

def test_importing_runtime_agent_does_not_load_qt():
    """When imported fresh (no Qt in sys.modules), runtime_agent must not
    pull in qt_compat or PySide6.

    This test is skipped if Qt was already loaded by another test, since
    we can't reliably un-load it in that case.
    """
    _ensure_mock_modules()
    qt_already_loaded = any(
        name.startswith(("PySide6", "PyQt6")) or name == "dobot_move.ui.qt_compat"
        for name in sys.modules
    )
    if qt_already_loaded:
        import pytest
        pytest.skip("Qt already loaded by another test; AST tests cover this case")

    # Remove runtime_agent so it gets a fresh import
    for name in list(sys.modules):
        if name.startswith("dobot_move.runtime.runtime_agent"):
            del sys.modules[name]

    importlib.import_module("dobot_move.runtime.runtime_agent")

    qt_loaded = [
        name for name in sys.modules
        if name.startswith(("PySide6", "PyQt6")) or name == "dobot_move.ui.qt_compat"
    ]
    assert not qt_loaded, (
        f"runtime_agent imported Qt modules: {sorted(qt_loaded)}"
    )


def _ensure_mock_modules():
    """Stub out optional heavy deps so runtime_agent can be imported."""
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


# --- PR 2: capture_worker 提取后的额外 AST 检查 -----------------------------

def _check_no_camera_test_worker_imports(module_path, module_name):
    """Assert that a module's source does not import from camera_test_worker.

    ``camera_test_worker`` (flow shim) pulls in Qt via ui.camera_test_worker,
    so headless modules must not import from it.
    """
    with open(module_path, encoding="utf-8") as f:
        source = f.read()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert "camera_test_worker" not in module, (
                f"{module_name} imports from {module} at line {node.lineno} "
                f"(should use vision.capture_worker instead)"
            )


def test_flow_executor_source_has_no_camera_test_worker_imports():
    """flow_executor.py must not import from camera_test_worker (pulls in Qt)."""
    _ensure_mock_modules()
    from dobot_move.flow import flow_executor
    source_path = inspect.getsourcefile(flow_executor)
    _check_no_camera_test_worker_imports(source_path, "flow_executor")


def test_capture_worker_source_has_no_qt_imports():
    """vision/capture_worker.py must not contain any Qt import statements."""
    _ensure_mock_modules()
    import dobot_move.vision.capture_worker as cw
    source_path = inspect.getsourcefile(cw)
    _check_no_qt_imports(source_path, "capture_worker")


def test_capture_worker_source_has_no_camera_test_worker_imports():
    """vision/capture_worker.py must not import from camera_test_worker."""
    _ensure_mock_modules()
    import dobot_move.vision.capture_worker as cw
    source_path = inspect.getsourcefile(cw)
    _check_no_camera_test_worker_imports(source_path, "capture_worker")
