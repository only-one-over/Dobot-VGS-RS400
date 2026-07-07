#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for FlowExecutor callback interface (no Qt required)."""

import sys
import threading
import types

import pytest

if "pyrealsense2" not in sys.modules:
    sys.modules["pyrealsense2"] = types.ModuleType("pyrealsense2")

from dobot_move.flow.flow_executor import FlowExecutor


class _DelayController:
    """Minimal controller stub for delay-only flow execution."""

    def __init__(self):
        self._active_flow_thread = None
        self.is_enabled = True
        self.modbus_server = None
        self.released = False

    def acquire_motion(self, owner):
        return owner == "flow"

    def release_motion(self, owner):
        self.released = owner == "flow"

    def begin_modbus_delay_wait(self):
        pass

    def is_modbus_delay_released(self):
        return False

    def end_modbus_delay_wait(self, restore_running=True):
        pass

    def record_alarm(self, *args, **kwargs):
        pass


def test_flow_executor_callbacks_invoke_on_log_and_on_finished():
    """on_log and on_finished callbacks fire during flow execution."""
    controller = _DelayController()
    logs = []
    finished = []

    executor = FlowExecutor(
        controller,
        vision_d435i=None,
        vision_d405=None,
        grasp_flow_modules=[
            {
                "type": "delay",
                "name": "短暂延时",
                "params": {"duration_s": 0.01},
            }
        ],
        is_paused_ref=[False],
    )
    executor.on_log = logs.append
    executor.on_finished = finished.append

    executor.run()

    assert finished == [True]
    assert any("流程" in msg or "模块" in msg for msg in logs)
    assert controller.released is True


def test_flow_executor_callbacks_default_to_silent():
    """Without callbacks set, execution still completes without error."""
    controller = _DelayController()

    executor = FlowExecutor(
        controller,
        vision_d435i=None,
        vision_d405=None,
        grasp_flow_modules=[
            {
                "type": "delay",
                "name": "silent delay",
                "params": {"duration_s": 0.01},
            }
        ],
        is_paused_ref=[False],
    )
    # No callbacks set — should not raise
    executor.run()

    assert controller.released is True


def test_flow_executor_on_progress_callback_fires():
    """on_progress callback receives (current, total, name) tuples."""
    controller = _DelayController()
    progress_events = []

    executor = FlowExecutor(
        controller,
        vision_d435i=None,
        vision_d405=None,
        grasp_flow_modules=[
            {
                "type": "delay",
                "name": "step1",
                "params": {"duration_s": 0.01},
            },
            {
                "type": "delay",
                "name": "step2",
                "params": {"duration_s": 0.01},
            },
        ],
        is_paused_ref=[False],
    )
    executor.on_progress = lambda current, total, name: progress_events.append((current, total, name))

    executor.run()

    assert len(progress_events) >= 2
    assert progress_events[0][0] == 1
    assert progress_events[0][1] == 2
    assert progress_events[0][2] == "step1"


def test_flow_executor_stop_sets_stop_event():
    """stop() sets the stop flag and clears pause."""
    controller = _DelayController()
    pause_ref = [False]

    executor = FlowExecutor(
        controller,
        vision_d435i=None,
        vision_d405=None,
        grasp_flow_modules=[],
        is_paused_ref=pause_ref,
    )

    pause_ref[0] = True
    executor.stop()

    assert executor._stop_requested is True
    assert pause_ref[0] is False
