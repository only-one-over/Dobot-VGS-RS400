#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Qt adapter for flow execution.

This module provides the Qt-facing ``FlowThread`` and ``RobotCmdThread``
that the GUI uses. ``FlowThread`` is a thin adapter that holds a
``FlowExecutor`` (pure Python, from ``flow_executor.py``) and bridges its
callback hooks to ``pyqtSignal`` emissions so Qt widgets can connect slots
as before.

The headless runtime (``runtime_agent.py``) should NOT import this module —
it should use ``FlowExecutor`` directly.
"""

import logging

from ..ui.qt_compat import QThread, pyqtSignal
from .flow_executor import FlowExecutor

logger = logging.getLogger(__name__)


class RobotCmdThread(QThread):
    """机器人指令后台执行线程"""
    cmd_finished = pyqtSignal(str, bool)

    def __init__(self, cmd_name, cmd_func, parent=None):
        super().__init__(parent)
        self._cmd_name = cmd_name
        self._cmd_func = cmd_func

    def run(self):
        try:
            result = self._cmd_func()
            self.cmd_finished.emit(self._cmd_name, bool(result))
        except Exception as e:
            logger.error(f"❌ 指令执行异常: {e}")
            self.cmd_finished.emit(self._cmd_name, False)


class FlowThread(QThread):
    """Qt adapter around :class:`FlowExecutor`.

    Preserves the original ``FlowThread`` signal surface so existing GUI
    code (``flow_log``, ``flow_finished``, ``flow_module_progress``) keeps
    working. All flow execution logic lives in ``FlowExecutor``; this class
    only wires callbacks to signals and proxies attribute access.
    """

    flow_log = pyqtSignal(str)
    flow_finished = pyqtSignal(bool)
    flow_module_progress = pyqtSignal(int, int, str)

    def __init__(
        self,
        controller,
        vision_d435i,
        vision_d405,
        grasp_flow_modules,
        is_paused_ref,
        parent=None,
        camera_test_workers=None,
    ):
        super().__init__(parent)
        self._executor = FlowExecutor(
            controller=controller,
            vision_d435i=vision_d435i,
            vision_d405=vision_d405,
            grasp_flow_modules=grasp_flow_modules,
            is_paused_ref=is_paused_ref,
            camera_test_workers=camera_test_workers,
        )
        # Wire callbacks to Qt signals
        self._executor.on_log = self.flow_log.emit
        self._executor.on_finished = self.flow_finished.emit
        self._executor.on_progress = self.flow_module_progress.emit

    def run(self):
        self._executor.run()

    def stop(self):
        self._executor.stop()

    def __getattr__(self, name):
        """Proxy unknown attribute access to the wrapped FlowExecutor.

        Only called when normal attribute lookup fails — Qt/QThread
        attributes are still resolved normally.
        """
        # Avoid recursion during unpickling / before _executor is set
        if name == "_executor":
            raise AttributeError(name)
        return getattr(self._executor, name)
