#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Backward-compatibility shim.

The original ``workers.py`` has been split into focused modules:

- :mod:`dobot_move.flow.flow_executor` — pure-Python flow execution
  (``FlowExecutor``, ``FlowRunContext``, helper functions). No Qt.
- :mod:`dobot_move.flow.qt_workers` — Qt adapter (``FlowThread``,
  ``RobotCmdThread``) wrapping ``FlowExecutor``.
- :mod:`dobot_move.vision.capture_worker` — pure-Python frame capture
  (``CaptureWorker`` / ``CaptureThread``). No Qt.
- :mod:`dobot_move.ui.camera_test_worker` — GUI-only camera test worker
  (``CameraTestWorker``) with Qt deps, composing ``CaptureWorker``.

This module re-exports every public symbol so existing imports
``from dobot_move.flow.workers import X`` keep working. New code should
import from the specific module instead:

- Headless runtime → ``flow_executor`` / ``vision.capture_worker``
- GUI / Qt code    → ``qt_workers`` / ``ui.camera_test_worker``

.. note::

    Importing this shim pulls in Qt (via ``qt_workers`` and
    ``ui.camera_test_worker``). Headless code paths should import from
    ``flow_executor`` directly to avoid the Qt dependency.
"""

# Pure-Python symbols (no Qt)
from .flow_executor import (
    FlowExecutor,
    FlowRunContext,
    build_force_guard,
    coerce_float_vector,
    normalize_module_type,
    validate_grasp_flow_modules,
    wait_for_flow_delay,
    wait_for_flow_delay_or_signal,
)

# Pure-Python frame capture (no Qt) — 直接从新位置导入
from ..vision.capture_worker import CaptureWorker, CaptureThread

# Qt adapter symbols (pulls in Qt)
from .qt_workers import FlowThread, RobotCmdThread

# GUI-only camera test symbols (pulls in Qt + QImage) — 直接从新位置导入
from ..ui.camera_test_worker import CameraTestWorker

__all__ = [
    # flow_executor
    "FlowExecutor",
    "FlowRunContext",
    "build_force_guard",
    "coerce_float_vector",
    "normalize_module_type",
    "validate_grasp_flow_modules",
    "wait_for_flow_delay",
    "wait_for_flow_delay_or_signal",
    # capture_worker
    "CaptureWorker",
    "CaptureThread",
    # qt_workers
    "FlowThread",
    "RobotCmdThread",
    # ui.camera_test_worker
    "CameraTestWorker",
]
