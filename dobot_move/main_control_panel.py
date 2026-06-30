#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主功能控制面板 - Industrial Robotics Dashboard 风格
卡片式分组布局，深色工业仪表盘风格
"""

from .qt_compat import (
    QWidget, QVBoxLayout, QGridLayout, QPushButton, QLabel, QComboBox,
    QLineEdit, QHBoxLayout, QFrame, pyqtSignal,
)
from .ui_theme import apply_status_visual, set_button_role, card_style, metric_title_style


class MainControlPanel(QWidget):
    """主功能控制面板，包含机器人连接、相机控制、任务执行等按钮"""

    # 信号定义
    connect_robot = pyqtSignal()
    enable_robot = pyqtSignal()
    disable_robot = pyqtSignal()
    connect_d435i = pyqtSignal()
    disconnect_d435i = pyqtSignal()
    connect_d405 = pyqtSignal()
    disconnect_d405 = pyqtSignal()
    run_grasp = pyqtSignal()
    move_initial = pyqtSignal()
    get_pose = pyqtSignal()
    set_collision_level = pyqtSignal()
    clear_error = pyqtSignal()
    pause = pyqtSignal()
    resume = pyqtSignal()
    collision_level_changed = pyqtSignal(int)
    ip_changed = pyqtSignal(str)

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
        conn_card, conn_layout = self._make_card("连接配置", "#3b82f6")

        ip_row = QHBoxLayout()
        ip_row.setSpacing(8)
        ip_label = QLabel("IP:")
        ip_label.setStyleSheet("color: #94a3b8; font-weight: 600; background: transparent; border: none;")
        self.ip_input = QLineEdit(robot_ip)
        self.ip_input.setMaximumWidth(150)
        self.ip_input.setPlaceholderText("机器人IP地址")
        ip_row.addWidget(ip_label)
        ip_row.addWidget(self.ip_input)
        ip_row.addStretch()

        self.connect_robot_btn = QPushButton("连接机器人")
        set_button_role(self.connect_robot_btn, "connect")
        self.connect_robot_btn.setDefault(True)
        self.connect_robot_btn.setMinimumHeight(self.BTN_HEIGHT)
        ip_row.addWidget(self.connect_robot_btn)

        conn_layout.addLayout(ip_row)
        layout.addWidget(conn_card)

        # ── 任务控制卡片 ──
        task_card, task_layout = self._make_card("任务控制", "#2563eb")

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
        collision_label.setStyleSheet("color: #94a3b8; font-weight: 600; background: transparent; border: none;")
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

        # ── 相机控制卡片 ──
        cam_card, cam_layout = self._make_card("相机控制", "#06b6d4")

        # D435i
        self.d435i_status_label = QLabel("D435i: 未连接")
        apply_status_visual(self.d435i_status_label, "未连接")
        cam_layout.addWidget(self.d435i_status_label)

        d435i_row = QHBoxLayout()
        d435i_row.setSpacing(8)
        self.d435i_connect_btn = QPushButton("D435i 连接")
        set_button_role(self.d435i_connect_btn, "connect")
        self.d435i_connect_btn.setMinimumHeight(self.BTN_HEIGHT)
        d435i_row.addWidget(self.d435i_connect_btn)

        self.d435i_disconnect_btn = QPushButton("D435i 断开")
        set_button_role(self.d435i_disconnect_btn, "secondary")
        self.d435i_disconnect_btn.setMinimumHeight(self.BTN_HEIGHT)
        self.d435i_disconnect_btn.setEnabled(False)
        d435i_row.addWidget(self.d435i_disconnect_btn)
        cam_layout.addLayout(d435i_row)

        # D405
        self.d405_status_label = QLabel("D405: 未连接")
        apply_status_visual(self.d405_status_label, "未连接")
        cam_layout.addWidget(self.d405_status_label)

        d405_row = QHBoxLayout()
        d405_row.setSpacing(8)
        self.d405_connect_btn = QPushButton("D405 连接")
        set_button_role(self.d405_connect_btn, "connect")
        self.d405_connect_btn.setMinimumHeight(self.BTN_HEIGHT)
        d405_row.addWidget(self.d405_connect_btn)

        self.d405_disconnect_btn = QPushButton("D405 断开")
        set_button_role(self.d405_disconnect_btn, "secondary")
        self.d405_disconnect_btn.setMinimumHeight(self.BTN_HEIGHT)
        self.d405_disconnect_btn.setEnabled(False)
        d405_row.addWidget(self.d405_disconnect_btn)
        cam_layout.addLayout(d405_row)

        layout.addWidget(cam_card)

        layout.addStretch()

    def _connect_signals(self):
        """连接内部按钮事件到信号发射"""
        self.connect_robot_btn.clicked.connect(self.connect_robot.emit)
        self.enable_robot_btn.clicked.connect(self.enable_robot.emit)
        self.disable_robot_btn.clicked.connect(self.disable_robot.emit)
        self.d435i_connect_btn.clicked.connect(self.connect_d435i.emit)
        self.d435i_disconnect_btn.clicked.connect(self.disconnect_d435i.emit)
        self.d405_connect_btn.clicked.connect(self.connect_d405.emit)
        self.d405_disconnect_btn.clicked.connect(self.disconnect_d405.emit)
        self.run_task_btn.clicked.connect(self.run_grasp.emit)
        self.move_initial_btn.clicked.connect(self.move_initial.emit)
        self.get_pos_btn.clicked.connect(self.get_pose.emit)
        self.collision_set_btn.clicked.connect(self.set_collision_level.emit)
        self.clear_error_btn.clicked.connect(self.clear_error.emit)
        self.pause_btn.clicked.connect(self.pause.emit)
        self.continue_btn.clicked.connect(self.resume.emit)
        self.collision_combo.currentIndexChanged.connect(self.collision_level_changed.emit)
        self.ip_input.editingFinished.connect(
            lambda: self.ip_changed.emit(self.ip_input.text().strip())
        )
