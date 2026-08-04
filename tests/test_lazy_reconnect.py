"""Regression tests for the lazy (on-demand) reconnect strategy.

Covers Tasks 1-4: ``RobotConnectionSupervisor`` was removed in favour of
``DobotController.ensure_connected()``, which performs a single
reconnect attempt with no backoff. These tests bind the real
``DobotController`` methods onto a lightweight fake controller so the
motion / emergency-stop code paths are exercised without hardware.
"""
from __future__ import annotations

import threading
import types
from unittest.mock import patch

from dobot_move.robot.motion_safety import MotionValidationResult
from dobot_move.robot.robot_controller import DobotController


def _ok_result() -> MotionValidationResult:
    return MotionValidationResult(ok=True, code=0, message="OK")


class _FakeController:
    """Minimal stand-in exposing only the attributes touched by the real
    ``DobotController`` methods under test."""

    def __init__(self):
        self.is_connected = False
        self.is_enabled = False
        self.dashboard = None
        self.robot_ip = "192.168.1.50"
        self.software_emergency_active = False
        self._connect_attempt_lock = threading.Lock()
        self._connect_result = False
        self.connect_calls = 0
        self._emergency_stop_direct_calls = 0
        self.modbus_server = None
        self._active_flow_thread = None
        self._last_speed_factor = None
        self._modbus_status_override = None
        self.current_speed = 30

    def connect(self):
        self.connect_calls += 1
        self.is_connected = bool(self._connect_result)
        return self._connect_result

    def _emergency_stop_direct(self, mode=1):
        self._emergency_stop_direct_calls += 1
        return True

    def record_alarm(self, *args, **kwargs):
        pass


def _bind_real_methods(fake: _FakeController) -> _FakeController:
    """Bind the real ``DobotController`` methods onto the fake instance."""
    fake.ensure_connected = types.MethodType(DobotController.ensure_connected, fake)
    fake.move_to_point = types.MethodType(DobotController.move_to_point, fake)
    fake.send_relative_command = types.MethodType(DobotController.send_relative_command, fake)
    fake.emergency_stop = types.MethodType(DobotController.emergency_stop, fake)
    return fake


def _make_fake() -> _FakeController:
    return _bind_real_methods(_FakeController())


# -- ensure_connected ------------------------------------------------------

def test_ensure_connected_already_connected():
    ctrl = _make_fake()
    ctrl.is_connected = True
    ctrl.dashboard = object()  # non-None dashboard

    assert ctrl.ensure_connected() is True
    # Already connected → connect() must not be called.
    assert ctrl.connect_calls == 0


def test_ensure_connected_reconnects_once():
    ctrl = _make_fake()
    ctrl.is_connected = False
    ctrl.dashboard = None
    ctrl._connect_result = True  # connect() succeeds on this attempt

    assert ctrl.ensure_connected() is True
    # Disconnected → exactly one connect() attempt (no backoff schedule).
    assert ctrl.connect_calls == 1


def test_ensure_connected_no_retry():
    ctrl = _make_fake()
    ctrl.is_connected = False
    ctrl.dashboard = None
    ctrl._connect_result = False  # connect() fails

    assert ctrl.ensure_connected() is False
    # Single attempt only — no retry / exponential backoff.
    assert ctrl.connect_calls == 1


# -- move_to_point ---------------------------------------------------------

def test_move_to_point_returns_false_when_disconnected():
    ctrl = _make_fake()
    ctrl.is_connected = False
    ctrl.dashboard = None
    ctrl._connect_result = False  # reconnect attempt fails

    # Patch validation to pass so we exercise the ensure_connected
    # ("reconnect failed") branch rather than the validation guard.
    with patch(
        "dobot_move.robot.robot_controller.validate_absolute_pose",
        return_value=_ok_result(),
    ):
        result = ctrl.move_to_point([300, 0, 200, 0, 0, -90], speed_percentage=10)

    # Must return False (not raise AttributeError) after a failed reconnect.
    assert result is False
    assert ctrl.connect_calls == 1


# -- send_relative_command -------------------------------------------------

def test_send_relative_command_wait_false_returns_tuple():
    ctrl = _make_fake()
    ctrl.is_connected = False
    ctrl.dashboard = None
    ctrl._connect_result = False  # reconnect attempt fails

    with patch(
        "dobot_move.robot.robot_controller.validate_relative_delta",
        return_value=_ok_result(),
    ):
        result = ctrl.send_relative_command([10, 0, 0, 0, 0, 0], wait=False)

    # Non-waiting relative command returns a (code, command_id) tuple,
    # with code 1 when the robot could not be connected.
    assert isinstance(result, tuple)
    assert result == (1, None)
    assert ctrl.connect_calls == 1


# -- emergency_stop --------------------------------------------------------

def test_emergency_stop_works_when_disconnected():
    ctrl = _make_fake()
    ctrl.is_connected = False
    ctrl.dashboard = None

    assert ctrl.emergency_stop() is True
    # The independent socket path must run even when the main connection
    # is down — emergency stop is safety-critical and never gated on
    # is_connected.
    assert ctrl._emergency_stop_direct_calls == 1
