"""Tests for the GUI capability-based button gating (Tasks 6 & 8).

``DobotMainWindow._CAPABILITY_BUTTON_MAP`` is a class-level attribute that
maps GUI button attribute names to the IPC command they dispatch. Buttons
in this map are force-disabled when the Runtime doesn't advertise the
corresponding capability. Safety-critical buttons (emergency stop, safe
stop) are intentionally excluded so they stay enabled at all times.

These tests inspect the class attribute directly — no ``QApplication``
or widget instantiation is required.
"""
from __future__ import annotations

from dobot_move.ui.gui_app import DobotMainWindow


def _capability_map():
    return DobotMainWindow._CAPABILITY_BUTTON_MAP


def test_read_point_btn_maps_to_get_current_pose():
    # ``read_point_btn`` records the current TCP pose, so it must map to
    # the ``get_current_pose`` IPC command (not a legacy ``get_point``).
    assert _capability_map()["read_point_btn"] == "get_current_pose"


def test_emergency_stop_btn_not_in_map():
    # Emergency stop is safety-critical and must remain enabled at all
    # times — it must never be gated by Runtime capabilities.
    assert "emergency_stop_btn" not in _capability_map()
    assert "safe_stop_btn" not in _capability_map()


def test_capability_map_covers_all_ipc_commands():
    values = set(_capability_map().values())
    # Every major IPC command exposed by the Runtime must have at least
    # one button binding so capability gating can disable it when the
    # Runtime doesn't advertise support.
    required = {
        "stop_current_task",
        "validate_flow",
        "run_step",
        "connect_camera",
        "disconnect_camera",
        "clear_alarm_history",
        "move_to_pose",
    }
    missing = required - values
    assert not missing, f"capability map missing commands: {missing}"
