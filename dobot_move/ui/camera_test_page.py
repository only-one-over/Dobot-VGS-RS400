#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camera test page widget — extracted from gui_app.py."""

from ..ui.qt_compat import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    Qt,
    QVBoxLayout,
    QWidget,
)
from ..ui.ui_theme import COLORS, set_button_role

_CAM_COORD_STYLE = (
    "font-family: monospace; font-size: 13pt; color: #64748b;"
)


class CameraTestPage(QWidget):
    """Camera test tab: live image display and coordinate readouts."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        """Build camera test page: image display + coordinate info."""
        page_layout = QVBoxLayout(self)

        # Top control bar
        cam_test_ctrl = QHBoxLayout()
        cam_test_ctrl.addWidget(QLabel("选择相机:"))
        self.cam_test_combo = QComboBox()
        self.cam_test_combo.addItems(["D435i", "D405"])
        cam_test_ctrl.addWidget(self.cam_test_combo)
        self.cam_test_start_btn = QPushButton("开始测试")
        set_button_role(self.cam_test_start_btn, "connect")
        cam_test_ctrl.addWidget(self.cam_test_start_btn)
        self.cam_test_stop_btn = QPushButton("停止测试")
        set_button_role(self.cam_test_stop_btn, "warning")
        self.cam_test_stop_btn.setEnabled(False)
        cam_test_ctrl.addWidget(self.cam_test_stop_btn)
        self.cam_self_test_btn = QPushButton("相机自检")
        set_button_role(self.cam_self_test_btn, "secondary")
        cam_test_ctrl.addWidget(self.cam_self_test_btn)
        cam_test_ctrl.addStretch()
        page_layout.addLayout(cam_test_ctrl)

        # Main content area
        cam_test_content = QHBoxLayout()

        # Left: image display
        self.cam_test_image_label = QLabel("等待测试...")
        self.cam_test_image_label.setMinimumSize(480, 360)
        self.cam_test_image_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.cam_test_image_label.setStyleSheet(f"background-color: {COLORS['bg']}; color: #64748b; font-size: 16pt; border: 1px solid {COLORS['line']}; border-radius: 8px;")
        self.cam_test_image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cam_test_content.addWidget(self.cam_test_image_label)

        # Right: coordinate display
        coord_group = QGroupBox("坐标信息")
        coord_layout = QVBoxLayout(coord_group)

        self.cam_test_status_label = QLabel("状态: 未开始")
        self.cam_test_status_label.setStyleSheet(f"font-weight: bold; font-size: 14pt; color: {COLORS['accent_blue']};")
        coord_layout.addWidget(self.cam_test_status_label)

        coord_layout.addWidget(QLabel("相机坐标 (mm):"))
        self.cam_test_cam_coords = QLabel("X: ---  Y: ---  Z: ---")
        self.cam_test_cam_coords.setStyleSheet(_CAM_COORD_STYLE)
        coord_layout.addWidget(self.cam_test_cam_coords)

        coord_layout.addWidget(QLabel("末端坐标 (mm):"))
        self.cam_test_end_coords = QLabel("X: ---  Y: ---  Z: ---")
        self.cam_test_end_coords.setStyleSheet(_CAM_COORD_STYLE)
        coord_layout.addWidget(self.cam_test_end_coords)

        coord_layout.addWidget(QLabel("基座坐标 (mm):"))
        self.cam_test_base_coords = QLabel("X: ---  Y: ---  Z: ---")
        self.cam_test_base_coords.setStyleSheet(_CAM_COORD_STYLE)
        coord_layout.addWidget(self.cam_test_base_coords)

        coord_layout.addWidget(QLabel("置信度"))
        self.cam_test_confidence = QLabel("---")
        self.cam_test_confidence.setStyleSheet(_CAM_COORD_STYLE)
        coord_layout.addWidget(self.cam_test_confidence)

        # D405 specific
        self.cam_test_d405_group = QGroupBox("D405 端点信息")
        d405_layout = QVBoxLayout(self.cam_test_d405_group)
        d405_layout.addWidget(QLabel("抓取坐标 (mm):"))
        self.cam_test_handle_coords = QLabel("X: ---  Y: ---  Z: ---")
        self.cam_test_handle_coords.setStyleSheet(_CAM_COORD_STYLE)
        d405_layout.addWidget(self.cam_test_handle_coords)
        d405_layout.addWidget(QLabel("钩尖坐标 (mm):"))
        self.cam_test_tip_coords = QLabel("X: ---  Y: ---  Z: ---")
        self.cam_test_tip_coords.setStyleSheet(_CAM_COORD_STYLE)
        d405_layout.addWidget(self.cam_test_tip_coords)
        d405_layout.addWidget(QLabel("铁钩长度:"))
        self.cam_test_hook_length = QLabel("--- mm")
        self.cam_test_hook_length.setStyleSheet(_CAM_COORD_STYLE)
        d405_layout.addWidget(self.cam_test_hook_length)
        self.cam_test_d405_group.setVisible(False)
        coord_layout.addWidget(self.cam_test_d405_group)

        coord_layout.addStretch()
        cam_test_content.addWidget(coord_group)
        page_layout.addLayout(cam_test_content)

        self.cam_test_worker = None