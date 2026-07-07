"""Task 5/6/7 — GUI entry points for move_to_point, camera self-test,
reload_config, and the point-selection toggle.

Tests the mixin methods via stub objects to avoid instantiating the full
Qt window.
"""
from __future__ import annotations

from dobot_move.ui.mixins.point_management_mixin import PointManagementMixin
from dobot_move.ui.mixins.vision_mixin import VisionMixin
from dobot_move.ui.gui_app import DobotMainWindow


class _StubStatusBar:
    def __init__(self):
        self.messages = []

    def showMessage(self, message, timeout=0):
        self.messages.append((message, timeout))


class _StubTable:
    """Minimal QTableWidget stub for point selection tests."""

    def __init__(self, rows):
        self._rows = rows
        self._current_row = -1

    def currentRow(self):
        return self._current_row

    def item(self, row, col):
        if 0 <= row < len(self._rows) and col == 0:
            return self._rows[row]
        return None


class _StubTableWidgetItem:
    def __init__(self, text):
        self._text = text

    def text(self):
        return self._text


class _StubComboBox:
    def __init__(self, text="D435i"):
        self._text = text

    def currentText(self):
        return self._text


# ---------------------------------------------------------------------------
# Task 5: move_to_point GUI entry
# ---------------------------------------------------------------------------


def test_on_move_to_point_sends_correct_data():
    """Clicking '运动到此点' sends move_to_point IPC with point_name."""
    stub = _StubWindowWithIpc()
    stub.points_table = _StubTable([_StubTableWidgetItem("pointA")])
    stub.points_table._current_row = 0

    PointManagementMixin._on_move_to_point(stub)
    assert len(stub.ipc_calls) == 1
    command, data, _on_success = stub.ipc_calls[0]
    assert command == "move_to_point"
    assert data["point_name"] == "pointA"
    assert data["motion_type"] == "MovJ"
    assert data["speed"] == 10


def test_on_move_to_point_no_selection_does_nothing(monkeypatch):
    stub = _StubWindowWithIpc()
    stub.points_table = _StubTable([_StubTableWidgetItem("pointA")])
    stub.points_table._current_row = -1

    # Stub QMessageBox.warning so it doesn't require a real QWidget parent
    monkeypatch.setattr(
        "dobot_move.ui.mixins.point_management_mixin.QMessageBox.warning",
        lambda *args, **kwargs: None,
    )

    PointManagementMixin._on_move_to_point(stub)
    assert len(stub.ipc_calls) == 0


def test_on_point_selection_changed_enables_button():
    stub = _StubWindowWithIpc()
    stub.points_table = _StubTable([])
    stub.move_to_point_btn = _StubButton()

    stub.points_table._current_row = 0
    PointManagementMixin._on_point_selection_changed(stub)
    assert stub.move_to_point_btn.enabled is True

    stub.points_table._current_row = -1
    PointManagementMixin._on_point_selection_changed(stub)
    assert stub.move_to_point_btn.enabled is False


def test_on_point_selection_changed_no_button_does_nothing():
    """No crash if move_to_point_btn doesn't exist."""
    stub = _StubWindowWithIpc()
    stub.points_table = _StubTable([])
    # Don't set move_to_point_btn
    PointManagementMixin._on_point_selection_changed(stub)  # should not raise


# ---------------------------------------------------------------------------
# Task 6: camera self-test GUI entry
# ---------------------------------------------------------------------------


def test_run_camera_self_test_d435i():
    stub = _StubWindowWithIpc()
    stub.cam_test_combo = _StubComboBox("D435i")
    VisionMixin._run_camera_self_test(stub)
    assert len(stub.ipc_calls) == 1
    command, _data, _on_success = stub.ipc_calls[0]
    assert command == "test_d435i"


def test_run_camera_self_test_d405():
    stub = _StubWindowWithIpc()
    stub.cam_test_combo = _StubComboBox("D405")
    VisionMixin._run_camera_self_test(stub)
    command, _data, _on_success = stub.ipc_calls[0]
    assert command == "test_d405"


def test_on_camera_self_test_finished_pass():
    stub = _StubWindowWithIpc()
    VisionMixin._on_camera_self_test_finished(
        stub, "D435i", {"camera_ok": True, "inference_ok": True}
    )
    assert any("通过" in msg for msg, _ in stub._status_bar.messages)


def test_on_camera_self_test_finished_fail():
    stub = _StubWindowWithIpc()
    VisionMixin._on_camera_self_test_finished(
        stub, "D405", {"camera_ok": False, "inference_ok": True}
    )
    assert any("失败" in msg and "相机不可用" in msg
               for msg, _ in stub._status_bar.messages)


def test_on_camera_self_test_finished_inference_fail():
    stub = _StubWindowWithIpc()
    VisionMixin._on_camera_self_test_finished(
        stub, "D435i", {"camera_ok": True, "inference_ok": False}
    )
    assert any("失败" in msg and "推理失败" in msg
               for msg, _ in stub._status_bar.messages)


# ---------------------------------------------------------------------------
# Task 7: reload_config and debug_task_status
# ---------------------------------------------------------------------------


def test_on_reload_config_sends_ipc():
    stub = _StubWindowWithIpc()
    DobotMainWindow._on_reload_config(stub)
    assert len(stub.ipc_calls) == 1
    command, _data, _on_success = stub.ipc_calls[0]
    assert command == "reload_config"


def test_update_debug_task_status_running():
    stub = _StubWindowWithIpc()
    stub.debug_task_status_label = _StubButton()
    DobotMainWindow._update_debug_task_status(
        stub, {"running": True, "flow_name": "流程A", "current_step": 3}
    )
    assert "运行中" in stub.debug_task_status_label.text
    assert "流程A" in stub.debug_task_status_label.text
    assert "3" in stub.debug_task_status_label.text


def test_update_debug_task_status_idle():
    stub = _StubWindowWithIpc()
    stub.debug_task_status_label = _StubButton()
    DobotMainWindow._update_debug_task_status(stub, {"running": False})
    assert "空闲" in stub.debug_task_status_label.text


def test_update_debug_task_status_no_label_does_nothing():
    """No crash if debug_task_status_label doesn't exist."""
    stub = _StubWindowWithIpc()
    DobotMainWindow._update_debug_task_status(stub, {"running": True})  # no raise


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class _StubButton:
    def __init__(self):
        self.enabled = False
        self.text = ""

    def setEnabled(self, value):
        self.enabled = bool(value)

    def setText(self, text):
        self.text = text


class _StubWindowWithIpc:
    """Minimal stub providing _send_runtime_ipc, statusBar, etc."""

    def __init__(self):
        self.ipc_calls = []
        self._status_bar = _StubStatusBar()

    def _send_runtime_ipc(self, command, data=None, on_success=None, quiet=False):
        self.ipc_calls.append((command, data, on_success))

    def statusBar(self):
        return self._status_bar
