"""Task 3 — GUI '安全停止' button rename and Stop channel wiring.

Tests the button logic without instantiating the full ``DobotMainWindow``
by calling unbound methods on a stub object that provides the necessary
attributes and helper methods.
"""
from __future__ import annotations

import time

from dobot_move.ui.gui_app import DobotMainWindow


class _StubStatusBar:
    def __init__(self):
        self.messages = []

    def showMessage(self, message, timeout=0):
        self.messages.append((message, timeout))


class _StubWindow:
    """Minimal stub matching the attributes used by safe-stop methods."""

    def __init__(self):
        self._software_emergency_active = False
        self._emergency_cmd_running = False
        self._last_emergency_click_ts = 0.0
        self.stop_calls = []
        self._status_bar = _StubStatusBar()

    def _send_runtime_ipc_stop(self, command, data=None, on_success=None, on_failure=None):
        self.stop_calls.append((command, data, on_success, on_failure))

    def _update_emergency_stop_button(self):
        pass

    def statusBar(self):
        return self._status_bar


# ---------------------------------------------------------------------------
# on_emergency_stop
# ---------------------------------------------------------------------------


def test_on_emergency_stop_sends_safe_stop():
    stub = _StubWindow()
    DobotMainWindow.on_emergency_stop(stub)
    assert len(stub.stop_calls) == 1
    command, data, on_success, on_failure = stub.stop_calls[0]
    assert command == "safe_stop"


def test_on_emergency_stop_sets_running_flag():
    stub = _StubWindow()
    DobotMainWindow.on_emergency_stop(stub)
    assert stub._emergency_cmd_running is True


def test_on_emergency_stop_debounce_within_500ms():
    """A second click within 500 ms is ignored."""
    stub = _StubWindow()
    DobotMainWindow.on_emergency_stop(stub)
    # Second call immediately after should be debounced
    DobotMainWindow.on_emergency_stop(stub)
    assert len(stub.stop_calls) == 1


def test_on_emergency_stop_allows_second_click_after_500ms():
    stub = _StubWindow()
    DobotMainWindow.on_emergency_stop(stub)
    # Simulate time passing beyond debounce window
    stub._last_emergency_click_ts = time.monotonic() - 0.6
    stub._emergency_cmd_running = False
    DobotMainWindow.on_emergency_stop(stub)
    assert len(stub.stop_calls) == 2


def test_on_emergency_stop_blocked_while_running():
    """If a previous safe_stop is still running, ignore new clicks."""
    stub = _StubWindow()
    DobotMainWindow.on_emergency_stop(stub)
    # Simulate the flag still being set (request in flight)
    stub._last_emergency_click_ts = time.monotonic() - 1.0
    DobotMainWindow.on_emergency_stop(stub)
    assert len(stub.stop_calls) == 1


# ---------------------------------------------------------------------------
# _on_emergency_stop_finished
# ---------------------------------------------------------------------------


def test_finished_success_sets_active_and_status():
    stub = _StubWindow()
    DobotMainWindow._on_emergency_stop_finished(stub, "safe_stop", True)
    assert stub._emergency_cmd_running is False
    assert stub._software_emergency_active is True
    assert any("安全停止已执行" in msg for msg, _ in stub._status_bar.messages)


def test_finished_failure_clears_active_and_shows_error():
    stub = _StubWindow()
    stub._software_emergency_active = True
    DobotMainWindow._on_emergency_stop_finished(
        stub, "safe_stop", False, error="Dashboard 断开"
    )
    assert stub._emergency_cmd_running is False
    assert stub._software_emergency_active is False
    assert any("安全停止失败" in msg and "Dashboard 断开" in msg
               for msg, _ in stub._status_bar.messages)


def test_finished_failure_no_error_message():
    stub = _StubWindow()
    DobotMainWindow._on_emergency_stop_finished(stub, "safe_stop", False)
    assert stub._software_emergency_active is False
    assert any("安全停止失败" in msg for msg, _ in stub._status_bar.messages)


# ---------------------------------------------------------------------------
# _on_stop_current_task
# ---------------------------------------------------------------------------


def test_stop_current_task_sends_normal_ipc():
    """_on_stop_current_task uses the normal IPC channel (not Stop)."""
    stub = _StubWindow()
    normal_calls = []

    def _send_runtime_ipc(command, data=None, on_success=None, quiet=False):
        normal_calls.append((command, data, on_success))

    stub._send_runtime_ipc = _send_runtime_ipc
    DobotMainWindow._on_stop_current_task(stub)
    assert len(normal_calls) == 1
    assert normal_calls[0][0] == "stop_current_task"
