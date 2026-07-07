"""Task 4 — maintenance state explicit display unit tests.

Covers the i18n/colour helpers added to ``dobot_move.ui.gui_runtime_status``
and the invariant that every ``RuntimeState`` enum value has a Chinese
translation.
"""

from __future__ import annotations

from dobot_move.runtime.runtime_resilience import RuntimeState
from dobot_move.ui.gui_runtime_status import (
    RUNTIME_STATE_CN,
    runtime_state_color,
    translate_runtime_state,
)


# ---------------------------------------------------------------------------
# translate_runtime_state
# ---------------------------------------------------------------------------

def test_translate_maintenance_state():
    assert translate_runtime_state("MAINTENANCE") == "维护中"


def test_translate_ready_state():
    assert translate_runtime_state("READY") == "就绪"


def test_translate_offline_state():
    assert translate_runtime_state("OFFLINE") == "离线"


def test_translate_unknown_state_returns_original():
    # Unknown state values fall through verbatim so the UI can still render
    # something meaningful instead of a silent "未知" placeholder.
    assert translate_runtime_state("UNKNOWN_STATE") == "UNKNOWN_STATE"


def test_translate_empty_state_returns_unknown_cn():
    assert translate_runtime_state("") == "未知"


def test_every_runtime_state_enum_has_translation():
    missing = [
        member.value
        for member in RuntimeState
        if member.value not in RUNTIME_STATE_CN
    ]
    assert not missing, f"RuntimeState values without CN translation: {missing}"


# ---------------------------------------------------------------------------
# runtime_state_color
# ---------------------------------------------------------------------------

def test_color_maintenance_is_yellow():
    assert runtime_state_color("MAINTENANCE") == "#ffc107"


def test_color_ready_is_green():
    assert runtime_state_color("READY") == "#4caf50"


def test_color_maintenance_requested_is_orange():
    assert runtime_state_color("MAINTENANCE_REQUESTED") == "#ff9800"


def test_color_degraded_and_recovery_are_red():
    assert runtime_state_color("DEGRADED") == "#f44336"
    assert runtime_state_color("RECOVERY_REQUIRED") == "#f44336"


def test_color_offline_and_unknown_are_grey():
    assert runtime_state_color("OFFLINE") == "#9e9e9e"
    assert runtime_state_color("UNKNOWN") == "#9e9e9e"


def test_color_running_is_blue():
    assert runtime_state_color("RUNNING") == "#2196f3"


def test_color_unknown_state_falls_back_to_grey():
    assert runtime_state_color("SOMETHING_NEW") == "#9e9e9e"
