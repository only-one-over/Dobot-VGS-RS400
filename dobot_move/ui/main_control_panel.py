#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主功能控制面板 - Industrial Robotics Dashboard 风格
卡片式分组布局，深色工业仪表盘风格
"""

import os

from ..ui.qt_compat import (
    QWidget, QVBoxLayout, QGridLayout, QPushButton, QLabel, QComboBox,
    QLineEdit, QHBoxLayout, QFrame, pyqtSignal,
)
from ..ui.ui_theme import COLORS, apply_status_visual, set_button_role, card_style, metric_title_style
from ..ui.gui_runtime_status import (
    translate_runtime_state,
    runtime_state_color,
)


class MainControlPanel(QWidget):
    """主功能控制面板，包含机器人连接、相机控制、任务执行等按钮"""

    # 信号定义
    connect_robot = pyqtSignal()
    enable_robot = pyqtSignal()
    disable_robot = pyqtSignal()
    run_grasp = pyqtSignal()
    move_initial = pyqtSignal()
    get_pose = pyqtSignal()
    set_collision_level = pyqtSignal()
    clear_error = pyqtSignal()
    pause = pyqtSignal()
    resume = pyqtSignal()
    stop_current_task = pyqtSignal()
    collision_level_changed = pyqtSignal(int)
    main_flow_changed = pyqtSignal(str)

    BTN_HEIGHT = 38

    def __init__(self, robot_ip: str = "", parent=None):
        super().__init__(parent)
        self._build_ui(robot_ip)
        self._connect_signals()

    def _make_card(self, title: str, accent: str = "") -> tuple:
        """Create a dashboard card frame with title. Returns (frame, content_layout)."""
        card = QFrame()
        card.setObjectName("statusCard")
        card.setStyleSheet(card_style(accent))
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(8)
        card_layout.setContentsMargins(14, 12, 14, 12)
        if title:
            title_label = QLabel(title)
            title_label.setStyleSheet(metric_title_style())
            card_layout.addWidget(title_label)
        return card, card_layout

    def _build_ui(self, robot_ip: str):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(8, 8, 8, 8)

        # ── 连接配置卡片 ──
        conn_card, conn_layout = self._make_card("连接配置", COLORS["primary"])

        # 连接按钮（IP 配置已迁移到配置中心）
        connect_row = QHBoxLayout()
        connect_row.setSpacing(8)
        self.connect_robot_btn = QPushButton("连接设备")
        set_button_role(self.connect_robot_btn, "connect")
        self.connect_robot_btn.setDefault(True)
        self.connect_robot_btn.setMinimumHeight(self.BTN_HEIGHT)
        connect_row.addWidget(self.connect_robot_btn)
        connect_row.addStretch()
        conn_layout.addLayout(connect_row)

        # Runtime 状态指示灯（Task 4：maintenance 显式显示）
        runtime_row = QHBoxLayout()
        runtime_row.setSpacing(8)
        runtime_title = QLabel("Runtime:")
        runtime_title.setStyleSheet(
            f"color: {COLORS['muted']}; font-weight: 600; "
            "background: transparent; border: none;"
        )
        self.runtime_indicator_dot = QLabel()
        self.runtime_indicator_dot.setFixedSize(16, 16)
        self.runtime_indicator_dot.setStyleSheet(
            "background-color: #c9cdd4; border-radius: 8px; border: none;"
        )
        self.runtime_state_text = QLabel("未知")
        self.runtime_state_text.setStyleSheet(
            f"color: {COLORS['text']}; font-weight: 600; "
            "background: transparent; border: none;"
        )
        runtime_row.addWidget(runtime_title)
        runtime_row.addWidget(self.runtime_indicator_dot)
        runtime_row.addWidget(self.runtime_state_text, 1)
        conn_layout.addLayout(runtime_row)

        layout.addWidget(conn_card)

        # ── 任务控制卡片 ──
        task_card, task_layout = self._make_card("任务控制", COLORS["primary_dark"])

        flow_row = QHBoxLayout()
        flow_row.setSpacing(8)
        flow_row.addWidget(QLabel("主流程:"))
        self.main_flow_combo = QComboBox()
        flow_row.addWidget(self.main_flow_combo, 1)
        task_layout.addLayout(flow_row)

        self.run_task_btn = QPushButton("▶  运行抓取任务")
        set_button_role(self.run_task_btn, "primary")
        self.run_task_btn.setDefault(True)
        self.run_task_btn.setMinimumHeight(44)
        task_layout.addWidget(self.run_task_btn)

        task_row = QHBoxLayout()
        task_row.setSpacing(8)
        self.pause_btn = QPushButton("⏸  暂停")
        set_button_role(self.pause_btn, "warning")
        self.pause_btn.setMinimumHeight(self.BTN_HEIGHT)
        self.pause_btn.setEnabled(False)
        task_row.addWidget(self.pause_btn)

        self.continue_btn = QPushButton("▶  继续")
        set_button_role(self.continue_btn, "connect")
        self.continue_btn.setMinimumHeight(self.BTN_HEIGHT)
        self.continue_btn.setEnabled(False)
        task_row.addWidget(self.continue_btn)
        task_layout.addLayout(task_row)

        # 停止当前任务（普通停止，区别于顶部"安全停止"）
        # 走普通 IPC 通道 (8765)，Runtime 调用 dashboard.Stop()
        # 仅停止当前运动，不下使能
        self.stop_task_btn = QPushButton("■  停止当前任务")
        set_button_role(self.stop_task_btn, "warning")
        self.stop_task_btn.setMinimumHeight(self.BTN_HEIGHT)
        self.stop_task_btn.setToolTip(
            "普通停止：仅停止当前运动，不下使能（走普通 IPC 通道）。\n"
            "与顶部\"安全停止\"不同：安全停止会下使能机器人并走独立 Stop 通道。"
        )
        task_layout.addWidget(self.stop_task_btn)

        layout.addWidget(task_card)

        # ── 机器人控制卡片 ──
        robot_card, robot_layout = self._make_card("机器人控制", "#8b5cf6")

        enable_row = QHBoxLayout()
        enable_row.setSpacing(8)
        self.enable_robot_btn = QPushButton("使能机器人")
        set_button_role(self.enable_robot_btn, "connect")
        self.enable_robot_btn.setMinimumHeight(self.BTN_HEIGHT)
        enable_row.addWidget(self.enable_robot_btn)

        self.disable_robot_btn = QPushButton("下使能机器人")
        set_button_role(self.disable_robot_btn, "warning")
        self.disable_robot_btn.setMinimumHeight(self.BTN_HEIGHT)
        enable_row.addWidget(self.disable_robot_btn)
        robot_layout.addLayout(enable_row)

        self.get_pos_btn = QPushButton("获取位置")
        set_button_role(self.get_pos_btn, "secondary")
        self.get_pos_btn.setMinimumHeight(self.BTN_HEIGHT)
        robot_layout.addWidget(self.get_pos_btn)

        self.move_initial_btn = QPushButton("回到初始位置")
        set_button_role(self.move_initial_btn, "secondary")
        self.move_initial_btn.setMinimumHeight(self.BTN_HEIGHT)
        robot_layout.addWidget(self.move_initial_btn)

        # 碰撞等级
        collision_row = QHBoxLayout()
        collision_row.setSpacing(8)
        collision_label = QLabel("碰撞等级:")
        collision_label.setStyleSheet(f"color: {COLORS['muted']}; font-weight: 600; background: transparent; border: none;")
        self.collision_combo = QComboBox()
        self.collision_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.collision_combo.addItems([
            "0-关闭碰撞检测",
            "1-最低灵敏度",
            "2-低灵敏度",
            "3-中灵敏度",
            "4-高灵敏度",
            "5-最高灵敏度"
        ])
        self.collision_combo.setCurrentIndex(3)
        collision_row.addWidget(collision_label)
        collision_row.addWidget(self.collision_combo, 1)
        robot_layout.addLayout(collision_row)

        self.collision_set_btn = QPushButton("设置碰撞等级")
        set_button_role(self.collision_set_btn, "secondary")
        self.collision_set_btn.setMinimumHeight(self.BTN_HEIGHT)
        robot_layout.addWidget(self.collision_set_btn)

        self.clear_error_btn = QPushButton("清除故障")
        set_button_role(self.clear_error_btn, "danger")
        self.clear_error_btn.setMinimumHeight(self.BTN_HEIGHT)
        robot_layout.addWidget(self.clear_error_btn)

        layout.addWidget(robot_card)

        # 相机控制卡片已移除，相关功能迁移到「配置中心」导航页

        layout.addStretch()

    def _connect_signals(self):
        """连接内部按钮事件到信号发射"""
        self.connect_robot_btn.clicked.connect(self.connect_robot.emit)
        self.enable_robot_btn.clicked.connect(self.enable_robot.emit)
        self.disable_robot_btn.clicked.connect(self.disable_robot.emit)
        self.run_task_btn.clicked.connect(self.run_grasp.emit)
        self.move_initial_btn.clicked.connect(self.move_initial.emit)
        self.get_pos_btn.clicked.connect(self.get_pose.emit)
        self.collision_set_btn.clicked.connect(self.set_collision_level.emit)
        self.clear_error_btn.clicked.connect(self.clear_error.emit)
        self.pause_btn.clicked.connect(self.pause.emit)
        self.continue_btn.clicked.connect(self.resume.emit)
        self.stop_task_btn.clicked.connect(self.stop_current_task.emit)
        self.collision_combo.currentIndexChanged.connect(self.collision_level_changed.emit)
        self.main_flow_combo.currentIndexChanged.connect(
            self._emit_main_flow_changed
        )

    def _emit_main_flow_changed(self, index):
        flow_id = self.main_flow_combo.itemData(index)
        if flow_id:
            self.main_flow_changed.emit(str(flow_id))

    def update_runtime_state(self, state: str) -> None:
        """Refresh the runtime-state indicator dot and label.

        Called by gui_app on each status poll. ``state`` is the raw Runtime
        state string (e.g. ``"READY"``, ``"MAINTENANCE"``). Unknown values
        fall back to a grey dot and the verbatim state text.
        """
        state = state or "UNKNOWN"
        color = runtime_state_color(state)
        cn_text = translate_runtime_state(state)
        self.runtime_indicator_dot.setStyleSheet(
            f"background-color: {color}; border-radius: 8px; border: none;"
        )
        self.runtime_state_text.setText(cn_text)

    def set_main_flows(self, flows, selected_id):
        self.main_flow_combo.blockSignals(True)
        self.main_flow_combo.clear()
        selected_index = 0
        for index, flow in enumerate(flows):
            self.main_flow_combo.addItem(flow["name"], flow["id"])
            if flow["id"] == selected_id:
                selected_index = index
        self.main_flow_combo.setCurrentIndex(selected_index)
        self.main_flow_combo.blockSignals(False)
