#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Backward-compatibility shim.

``CaptureThread`` 已迁移到 :mod:`dobot_move.vision.capture_worker`（纯 Python，
无 Qt 依赖），``CameraTestWorker`` 已迁移到
:mod:`dobot_move.ui.camera_test_worker`（Qt 依赖，用于 QImage 渲染和
``pyqtSignal`` 发射）。

本模块仅为兼容旧 import 路径保留。新代码应直接从对应模块导入：

- Headless Runtime / ``flow_executor`` → ``dobot_move.vision.capture_worker``
- GUI / Qt 代码                     → ``dobot_move.ui.camera_test_worker``
"""

from ..vision.capture_worker import CaptureWorker, CaptureThread
from ..ui.camera_test_worker import CameraTestWorker

__all__ = ["CaptureWorker", "CaptureThread", "CameraTestWorker"]
