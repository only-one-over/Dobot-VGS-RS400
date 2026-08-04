#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""运动调试页 — jog 步进、手动位姿运动、实时位姿与安全停止。

页面只发出信号，不直接调用 ``RuntimeFacade``；由 ``gui_app`` 把信号接到
``runtime_facade`` 的对应 IPC 方法。定时器也在 ``gui_app`` 注册，回调通过
:meth:`update_current_pose` 刷新位姿显示。
"""

from __future__ import annotations

from ..ui.qt_compat import (
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
    pyqtSignal,
)
from ..ui.ui_theme import (
    COLORS,
    card_style,
    metric_title_style,
    metric_value_style,
    set_button_role,
)


# 6 自由度顺序与单位（X/Y/Z 平动 mm，Rx/Ry/Rz 转动 °）
_AXES: list[tuple[str, str]] = [
    ("X", "mm"),
    ("Y", "mm"),
    ("Z", "mm"),
    ("Rx", "°"),
    ("Ry", "°"),
    ("Rz", "°"),
]


def _motion_type_from_combo(combo: QComboBox) -> str:
    """"MovJ 关节" -> "MovJ"；"MovL 直线" -> "MovL"。"""
    text = combo.currentText()
    return text.split(" ", 1)[0] if text else "MovJ"


class MotionDebugPage(QWidget):
    """运动调试页：jog 步进 / 手动位姿运动 / 实时位姿 + 安全停止。

    Signals
    -------
    jog_triggered(str, int, float, str):
        ``(axis, direction, step, motion_type)`` —— direction 取 +1 / -1。
    move_to_pose_triggered(list, str, float):
        ``(pose, motion_type, speed)`` —— pose 长度恒为 6。
    safe_stop_triggered():
        操作员按下大红色"安全停止"按钮。
    """

    jog_triggered = pyqtSignal(str, int, float, str)
    move_to_pose_triggered = pyqtSignal(list, str, float)
    safe_stop_triggered = pyqtSignal()

    BTN_HEIGHT = 36

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _make_card(self, title: str, accent: str = "") -> tuple:
        """Create a dashboard card frame with title. Returns (frame, layout)."""
        card = QFrame()
        card.setObjectName("statusCard")
        card.setStyleSheet(card_style(accent))
        layout = QVBoxLayout(card)
        layout.setSpacing(8)
        layout.setContentsMargins(14, 12, 14, 12)
        if title:
            title_label = QLabel(title)
            title_label.setStyleSheet(metric_title_style())
            layout.addWidget(title_label)
        return card, layout

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(8, 8, 8, 8)

        self._build_jog_card(root)
        self._build_move_to_pose_card(root)
        self._build_pose_and_stop_card(root)

        root.addStretch()

    def _build_jog_card(self, root_layout: QVBoxLayout) -> None:
        """Jog 步进控制卡片：步长 + 运动类型 + 6 轴 ±按钮。"""
        card, layout = self._make_card("Jog 步进控制", COLORS["primary"])

        param_row = QHBoxLayout()
        param_row.setSpacing(8)
        param_row.addWidget(QLabel("步长:"))
        self.jog_step_spin = QDoubleSpinBox()
        self.jog_step_spin.setRange(0.1, 100.0)
        self.jog_step_spin.setValue(5.0)
        self.jog_step_spin.setSingleStep(0.5)
        self.jog_step_spin.setSuffix(" mm/°")
        param_row.addWidget(self.jog_step_spin)

        param_row.addWidget(QLabel("运动类型:"))
        self.jog_motion_combo = QComboBox()
        self.jog_motion_combo.addItems(["MovJ 关节", "MovL 直线"])
        param_row.addWidget(self.jog_motion_combo, 1)
        layout.addLayout(param_row)

        # 6 行：轴标签 + "−" + "+"
        self.jog_buttons: dict[str, dict[str, QPushButton]] = {}
        grid = QGridLayout()
        grid.setSpacing(6)
        for row, (axis, unit) in enumerate(_AXES):
            axis_label = QLabel(f"{axis} ({unit})")
            axis_label.setMinimumWidth(70)
            grid.addWidget(axis_label, row, 0)

            minus_btn = QPushButton("−")
            set_button_role(minus_btn, "secondary")
            minus_btn.setFixedSize(40, self.BTN_HEIGHT)
            plus_btn = QPushButton("+")
            set_button_role(plus_btn, "secondary")
            plus_btn.setFixedSize(40, self.BTN_HEIGHT)
            grid.addWidget(minus_btn, row, 1)
            grid.addWidget(plus_btn, row, 2)

            minus_btn.clicked.connect(
                lambda _c=False, a=axis: self._emit_jog(a, -1)
            )
            plus_btn.clicked.connect(
                lambda _c=False, a=axis: self._emit_jog(a, +1)
            )

            self.jog_buttons[axis] = {"minus": minus_btn, "plus": plus_btn}

        layout.addLayout(grid)
        root_layout.addWidget(card)

    def _build_move_to_pose_card(self, root_layout: QVBoxLayout) -> None:
        """手动位姿运动卡片：6 个位姿输入 + 速度 + 运动类型 + 执行按钮。"""
        card, layout = self._make_card("手动位姿运动", COLORS["primary_dark"])

        self.pose_inputs: dict[str, QDoubleSpinBox] = {}
        grid = QGridLayout()
        grid.setSpacing(6)
        for row, (axis, unit) in enumerate(_AXES):
            axis_label = QLabel(f"{axis} ({unit}):")
            axis_label.setMinimumWidth(70)
            grid.addWidget(axis_label, row, 0)
            spin = QDoubleSpinBox()
            spin.setRange(-9999.0, 9999.0)
            spin.setValue(0.0)
            spin.setDecimals(3)
            spin.setSuffix(f" {unit}")
            grid.addWidget(spin, row, 1)
            self.pose_inputs[axis] = spin
        layout.addLayout(grid)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        action_row.addWidget(QLabel("速度:"))
        self.move_speed_spin = QDoubleSpinBox()
        self.move_speed_spin.setRange(0.1, 100.0)
        self.move_speed_spin.setValue(10.0)
        self.move_speed_spin.setSuffix(" %")
        action_row.addWidget(self.move_speed_spin)

        action_row.addWidget(QLabel("运动类型:"))
        self.move_motion_combo = QComboBox()
        self.move_motion_combo.addItems(["MovJ 关节", "MovL 直线"])
        action_row.addWidget(self.move_motion_combo, 1)
        layout.addLayout(action_row)

        self.move_to_pose_btn = QPushButton("运动到此位姿")
        set_button_role(self.move_to_pose_btn, "primary")
        self.move_to_pose_btn.setMinimumHeight(self.BTN_HEIGHT)
        self.move_to_pose_btn.clicked.connect(self._emit_move_to_pose)
        layout.addWidget(self.move_to_pose_btn)

        root_layout.addWidget(card)

    def _build_pose_and_stop_card(self, root_layout: QVBoxLayout) -> None:
        """实时位姿 + 安全停止卡片：6 个位姿 label + 刷新按钮 + 安全停止按钮。"""
        card, layout = self._make_card("实时位姿 + 安全停止", COLORS["danger"])

        self.runtime_online_label = QLabel("Runtime: 未知")
        self.runtime_online_label.setStyleSheet(metric_value_style(COLORS["muted"]))
        layout.addWidget(self.runtime_online_label)

        self.pose_labels: dict[str, QLabel] = {}
        grid = QGridLayout()
        grid.setSpacing(6)
        for row, (axis, _unit) in enumerate(_AXES):
            axis_label = QLabel(f"{axis}:")
            axis_label.setMinimumWidth(40)
            grid.addWidget(axis_label, row, 0)
            value_label = QLabel("—")
            value_label.setStyleSheet(metric_value_style())
            grid.addWidget(value_label, row, 1)
            self.pose_labels[axis] = value_label
        layout.addLayout(grid)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.refresh_pose_btn = QPushButton("刷新位姿")
        set_button_role(self.refresh_pose_btn, "secondary")
        self.refresh_pose_btn.setMinimumHeight(self.BTN_HEIGHT)
        btn_row.addWidget(self.refresh_pose_btn)

        self.safe_stop_btn = QPushButton("安全停止")
        set_button_role(self.safe_stop_btn, "danger")
        self.safe_stop_btn.setMinimumHeight(48)
        # safe_stop_triggered 不带参数；clicked 传 bool，PySide6 允许目标槽参数更少
        self.safe_stop_btn.clicked.connect(self.safe_stop_triggered.emit)
        btn_row.addWidget(self.safe_stop_btn, 1)
        layout.addLayout(btn_row)

        root_layout.addWidget(card)

    # ------------------------------------------------------------------
    # Signal emission helpers
    # ------------------------------------------------------------------

    def _emit_jog(self, axis: str, direction: int) -> None:
        step = float(self.jog_step_spin.value())
        motion_type = _motion_type_from_combo(self.jog_motion_combo)
        self.jog_triggered.emit(axis, int(direction), step, motion_type)

    def _emit_move_to_pose(self) -> None:
        pose = [float(self.pose_inputs[axis].value()) for axis, _ in _AXES]
        motion_type = _motion_type_from_combo(self.move_motion_combo)
        speed = float(self.move_speed_spin.value())
        self.move_to_pose_triggered.emit(pose, motion_type, speed)

    # ------------------------------------------------------------------
    # Public refresh API（由 gui_app 调用）
    # ------------------------------------------------------------------

    def update_current_pose(self, pose: list) -> None:
        """刷新 6 个实时位姿 label。

        ``pose`` 长度不为 6 时所有 label 重置为 ``"—"``。
        """
        if not isinstance(pose, (list, tuple)) or len(pose) != 6:
            for label in self.pose_labels.values():
                label.setText("—")
            return
        for (axis, _unit), value in zip(_AXES, pose):
            try:
                text = f"{float(value):.3f}"
            except (TypeError, ValueError):
                text = "—"
            self.pose_labels[axis].setText(text)

    def set_runtime_online(self, online: bool) -> None:
        """根据 Runtime 在线状态启用/禁用 jog 与运动按钮。

        安全停止按钮始终保持启用（安全关键操作）。离线时位姿 label 清空为
        ``"—"``，状态 label 显示 ``"Runtime: 离线"``。
        """
        online = bool(online)
        for buttons in self.jog_buttons.values():
            for btn in buttons.values():
                btn.setEnabled(online)
        self.move_to_pose_btn.setEnabled(online)
        if online:
            self.runtime_online_label.setText("Runtime: 在线")
            self.runtime_online_label.setStyleSheet(
                metric_value_style(COLORS["success"])
            )
        else:
            self.runtime_online_label.setText("Runtime: 离线")
            self.runtime_online_label.setStyleSheet(
                metric_value_style(COLORS["muted"])
            )
            for label in self.pose_labels.values():
                label.setText("—")
