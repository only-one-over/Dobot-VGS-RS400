# -*- coding: utf-8 -*-
"""手眼标定矩阵导入按钮单元测试。

覆盖：
- SubTask 5.1: 6 输入框可编辑、表格只读、按钮存在
- SubTask 5.2: CalibMatrixDialog 矩阵校验和转换
- SubTask 5.3: _emit_calib_save 从 6 输入框读取位姿
"""
import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dobot_move.ui.config_center_page import ConfigCenterPage, CalibMatrixDialog
from dobot_move.ui.qt_compat import QApplication, QTableWidget, QTableWidgetItem, QDialog


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


# ---------------------------------------------------------------------------
# SubTask 5.1: 6 输入框可编辑、表格只读、按钮存在
# ---------------------------------------------------------------------------

def test_calib_pose_inputs_are_editable(qapp):
    """6 个位姿 QLineEdit 应为可编辑（非只读）。"""
    page = ConfigCenterPage()
    for le in page.calib_pose_inputs:
        assert le.isReadOnly() is False


def test_calib_table_is_readonly(qapp):
    """4×4 QTableWidget 应为只读。"""
    page = ConfigCenterPage()
    triggers = page.calib_table.editTriggers()
    # 应包含 NoEditTriggers
    assert triggers == QTableWidget.EditTrigger.NoEditTriggers


def test_calib_import_matrix_button_exists(qapp):
    """应存在"写入手眼标定矩阵"按钮。"""
    page = ConfigCenterPage()
    assert hasattr(page, "calib_import_matrix_btn")
    assert page.calib_import_matrix_btn.text() == "写入手眼标定矩阵"


def test_calib_matrix_import_requested_signal_exists(qapp):
    """应存在 calib_matrix_import_requested 信号。"""
    page = ConfigCenterPage()
    assert hasattr(page, "calib_matrix_import_requested")


# ---------------------------------------------------------------------------
# SubTask 5.2: _emit_calib_save 从 6 输入框读取位姿
# ---------------------------------------------------------------------------

def test_emit_calib_save_reads_pose_from_inputs(qapp):
    """_emit_calib_save 从 6 个 QLineEdit 读取位姿并 emit calib_save_requested。"""
    page = ConfigCenterPage()
    page.calib_camera_combo.setCurrentText("D405")

    # 填入位姿值
    pose_values = [10.12, -278.82, -137.24, 0.0, 0.0, 0.0]
    for i, val in enumerate(pose_values):
        page.calib_pose_inputs[i].setText(str(val))

    received = []
    page.calib_save_requested.connect(lambda cam, pose: received.append((cam, pose)))

    page._emit_calib_save()

    assert len(received) == 1
    camera_type, emitted_pose = received[0]
    assert camera_type == "D405"
    assert len(emitted_pose) == 6
    assert np.allclose(emitted_pose, pose_values)


def test_emit_calib_save_handles_empty_input(qapp):
    """空输入框应转为 0.0。"""
    page = ConfigCenterPage()
    page.calib_camera_combo.setCurrentText("D435i")

    for le in page.calib_pose_inputs:
        le.clear()

    received = []
    page.calib_save_requested.connect(lambda cam, pose: received.append((cam, pose)))

    page._emit_calib_save()

    assert len(received) == 1
    emitted_pose = received[0][1]
    assert all(v == 0.0 for v in emitted_pose)


# ---------------------------------------------------------------------------
# SubTask 5.3: CalibMatrixDialog 矩阵校验和转换
# ---------------------------------------------------------------------------

def test_calib_matrix_dialog_accepts_valid_identity(qapp):
    """CalibMatrixDialog 接受单位矩阵并转为位姿。"""
    page = ConfigCenterPage()
    page.calib_camera_combo.setCurrentText("D405")

    dialog = CalibMatrixDialog("D405", page)

    # 填入单位矩阵
    identity = np.eye(4)
    for i in range(4):
        for j in range(4):
            dialog._inputs[i][j].setText(f"{identity[i][j]:.6f}")

    # 模拟点击确定（不调用 exec，直接调用 _on_accept）
    dialog._on_accept()

    # 应被接受
    assert dialog.result() == QDialog.DialogCode.Accepted
    pose = dialog.get_result_pose()
    assert pose is not None
    assert len(pose) == 6
    # 单位矩阵 → 位姿 [0, 0, 0, 0, 0, 0]
    assert np.allclose(pose, [0, 0, 0, 0, 0, 0])


def test_calib_matrix_dialog_accepts_translation_rotation(qapp):
    """CalibMatrixDialog 接受带平移旋转的矩阵并正确转换。"""
    page = ConfigCenterPage()
    dialog = CalibMatrixDialog("D435i", page)

    # 绕 Z 旋转 90° + 平移 (10, 20, 30)
    angle = np.radians(90)
    matrix = np.array([
        [np.cos(angle), -np.sin(angle), 0, 10],
        [np.sin(angle),  np.cos(angle), 0, 20],
        [0,              0,              1, 30],
        [0,              0,              0, 1],
    ])
    for i in range(4):
        for j in range(4):
            dialog._inputs[i][j].setText(f"{matrix[i][j]:.6f}")

    dialog._on_accept()

    assert dialog.result() == QDialog.DialogCode.Accepted
    pose = dialog.get_result_pose()
    assert pose is not None
    assert np.isclose(pose[0], 10.0)
    assert np.isclose(pose[1], 20.0)
    assert np.isclose(pose[2], 30.0)
    assert np.isclose(pose[5], 90.0, atol=1.0)


def test_calib_matrix_dialog_rejects_invalid_last_row(qapp):
    """CalibMatrixDialog 拒绝最后一行不为 [0,0,0,1] 的矩阵。"""
    page = ConfigCenterPage()
    dialog = CalibMatrixDialog("D405", page)

    # 最后一行错误
    matrix = np.eye(4)
    matrix[3] = [0, 0, 0, 2]
    for i in range(4):
        for j in range(4):
            dialog._inputs[i][j].setText(f"{matrix[i][j]:.6f}")

    dialog._on_accept()

    # 不应被接受
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.get_result_pose() is None
    # 错误标签应有错误文本
    assert dialog._error_label.text() != ""


def test_calib_matrix_dialog_rejects_non_orthogonal(qapp):
    """CalibMatrixDialog 拒绝非正交旋转矩阵。"""
    page = ConfigCenterPage()
    dialog = CalibMatrixDialog("D405", page)

    # 旋转部分非正交
    matrix = np.array([
        [2, 0, 0, 10],
        [0, 2, 0, 20],
        [0, 0, 2, 30],
        [0, 0, 0, 1],
    ])
    for i in range(4):
        for j in range(4):
            dialog._inputs[i][j].setText(f"{matrix[i][j]:.6f}")

    dialog._on_accept()

    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.get_result_pose() is None
    assert dialog._error_label.text() != ""


def test_calib_matrix_dialog_rejects_non_numeric(qapp):
    """CalibMatrixDialog 拒绝非数字输入。"""
    page = ConfigCenterPage()
    dialog = CalibMatrixDialog("D405", page)

    dialog._inputs[0][0].setText("abc")
    for i in range(4):
        for j in range(4):
            if i != 0 or j != 0:
                dialog._inputs[i][j].setText("0.0")

    dialog._on_accept()

    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.get_result_pose() is None
    assert dialog._error_label.text() != ""


# ---------------------------------------------------------------------------
# 额外：set_matrix_from_poses 和 _matrix2pose 仍正确工作
# ---------------------------------------------------------------------------

def test_set_matrix_from_poses_saves_pose(tmp_path, monkeypatch):
    """set_matrix_from_poses 直接保存 6 元素位姿。"""
    from dobot_move.robot.hand_eye_calib import HandEyeCalibManager
    from dobot_move.config import config_manager

    test_config = {
        "calibration": {
            "D405": {"cam_to_flange_pose": [0, 0, 0, 0, 0, 0]},
        },
    }
    monkeypatch.setattr(config_manager, "get_config", lambda: test_config)
    monkeypatch.setattr(config_manager, "get_all_calibrations", lambda: test_config["calibration"])

    saved_poses = []
    def fake_set_calibration(camera_type, pose):
        saved_poses.append((camera_type, list(pose)))
        test_config["calibration"][camera_type]["cam_to_flange_pose"] = list(pose)
        return True
    monkeypatch.setattr(config_manager, "set_calibration", fake_set_calibration)

    pose = [10.12, -278.82, -137.24, 0.0, 0.0, 0.0]
    manager = HandEyeCalibManager()
    result = manager.set_matrix_from_poses("D405", pose)

    assert result is True
    assert len(saved_poses) == 1
    assert saved_poses[0][0] == "D405"
    assert np.allclose(saved_poses[0][1], pose)


def test_matrix2pose_inverse_of_pose2matrix():
    """_matrix2pose 与 pose2matrix 互逆。"""
    from dobot_move.robot.transform_utils import pose2matrix
    from dobot_move.robot.hand_eye_calib import _matrix2pose

    original_pose = [10.12, -278.82, -137.24, 0.0, 0.0, 0.0]
    matrix = pose2matrix(*original_pose)
    recovered_pose = _matrix2pose(matrix)

    assert np.allclose(original_pose, recovered_pose, atol=1e-4)
