#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主功能控制面板 - 从 DobotMainWindow 的主功能选项卡中提取
"""

from qt_compat import (
    QWidget, QVBoxLayout, QGridLayout, QPushButton, QLabel, QComboBox,
    QLineEdit, pyqtSignal,
)
from ui_theme import apply_status_visual, set_button_role


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
    get_pose = pyqtSignal()
    set_collision_level = pyqtSignal()
    clear_error = pyqtSignal()
    pause = pyqtSignal()
    resume = pyqtSignal()
    collision_level_changed = pyqtSignal(int)
    ip_changed = pyqtSignal(str)

    BTN_HEIGHT = 40

    def __init__(self, robot_ip: str = "", parent=None):
        super().__init__(parent)
        self._build_ui(robot_ip)
        self._connect_signals()

    def _build_ui(self, robot_ip: str):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)

        # IP 地址输入
        ip_layout = QGridLayout()
        ip_layout.setSpacing(10)
        ip_label = QLabel("IP地址:")
        self.ip_input = QLineEdit(robot_ip)
        self.ip_input.setMaximumWidth(150)
        self.ip_input.setPlaceholderText("机器人IP地址")
        ip_layout.addWidget(ip_label, 0, 0)
        ip_layout.addWidget(self.ip_input, 0, 1)
        ip_layout.setColumnStretch(2, 1)
        layout.addLayout(ip_layout)

        # 功能按钮布局
        button_layout = QGridLayout()
        button_layout.setSpacing(10)

        row = 0

        # 运行抓取任务按钮
        self.run_task_btn = QPushButton("运行抓取任务")
        set_button_role(self.run_task_btn, "primary")
        self.run_task_btn.setDefault(True)
        self.run_task_btn.setMinimumHeight(self.BTN_HEIGHT)
        button_layout.addWidget(self.run_task_btn, row, 0, 1, 2)
        row += 1

        # 连接机器人按钮
        self.connect_robot_btn = QPushButton("连接机器人")
        set_button_role(self.connect_robot_btn, "connect")
        self.connect_robot_btn.setDefault(True)
        self.connect_robot_btn.setMinimumHeight(self.BTN_HEIGHT)
        button_layout.addWidget(self.connect_robot_btn, row, 0, 1, 2)
        row += 1

        # 使能机器人按钮
        self.enable_robot_btn = QPushButton("使能机器人")
        set_button_role(self.enable_robot_btn, "connect")
        self.enable_robot_btn.setMinimumHeight(self.BTN_HEIGHT)
        button_layout.addWidget(self.enable_robot_btn, row, 0)

        # 下使能机器人按钮
        self.disable_robot_btn = QPushButton("下使能机器人")
        set_button_role(self.disable_robot_btn, "warning")
        self.disable_robot_btn.setMinimumHeight(self.BTN_HEIGHT)
        button_layout.addWidget(self.disable_robot_btn, row, 1)
        row += 1

        # D435i 相机
        self.d435i_status_label = QLabel("D435i: 未连接")
        apply_status_visual(self.d435i_status_label, "未连接")
        button_layout.addWidget(self.d435i_status_label, row, 0, 1, 2)
        row += 1

        self.d435i_connect_btn = QPushButton("D435i 连接")
        set_button_role(self.d435i_connect_btn, "connect")
        self.d435i_connect_btn.setMinimumHeight(self.BTN_HEIGHT)
        button_layout.addWidget(self.d435i_connect_btn, row, 0)

        self.d435i_disconnect_btn = QPushButton("D435i 断开")
        set_button_role(self.d435i_disconnect_btn, "secondary")
        self.d435i_disconnect_btn.setMinimumHeight(self.BTN_HEIGHT)
        self.d435i_disconnect_btn.setEnabled(False)
        button_layout.addWidget(self.d435i_disconnect_btn, row, 1)
        row += 1

        # D405 相机
        self.d405_status_label = QLabel("D405: 未连接")
        apply_status_visual(self.d405_status_label, "未连接")
        button_layout.addWidget(self.d405_status_label, row, 0, 1, 2)
        row += 1

        self.d405_connect_btn = QPushButton("D405 连接")
        set_button_role(self.d405_connect_btn, "connect")
        self.d405_connect_btn.setMinimumHeight(self.BTN_HEIGHT)
        button_layout.addWidget(self.d405_connect_btn, row, 0)

        self.d405_disconnect_btn = QPushButton("D405 断开")
        set_button_role(self.d405_disconnect_btn, "secondary")
        self.d405_disconnect_btn.setMinimumHeight(self.BTN_HEIGHT)
        self.d405_disconnect_btn.setEnabled(False)
        button_layout.addWidget(self.d405_disconnect_btn, row, 1)
        row += 1

        # 获取位置按钮
        self.get_pos_btn = QPushButton("获取位置")
        set_button_role(self.get_pos_btn, "secondary")
        self.get_pos_btn.setMinimumHeight(self.BTN_HEIGHT)
        button_layout.addWidget(self.get_pos_btn, row, 0)
        row += 1

        # 碰撞等级
        collision_label = QLabel("碰撞等级:")
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
        button_layout.addWidget(collision_label, row, 0)
        button_layout.addWidget(self.collision_combo, row, 1)
        row += 1

        # 设置碰撞等级按钮
        self.collision_set_btn = QPushButton("设置碰撞等级")
        set_button_role(self.collision_set_btn, "secondary")
        self.collision_set_btn.setMinimumHeight(self.BTN_HEIGHT)
        button_layout.addWidget(self.collision_set_btn, row, 0, 1, 2)
        row += 1

        # 清除故障按钮
        self.clear_error_btn = QPushButton("清除故障")
        set_button_role(self.clear_error_btn, "danger")
        self.clear_error_btn.setMinimumHeight(self.BTN_HEIGHT)
        button_layout.addWidget(self.clear_error_btn, row, 0, 1, 2)
        row += 1

        # 暂停/继续按钮
        self.pause_btn = QPushButton("暂停")
        set_button_role(self.pause_btn, "warning")
        self.pause_btn.setMinimumHeight(self.BTN_HEIGHT)
        self.pause_btn.setEnabled(False)
        button_layout.addWidget(self.pause_btn, row, 0)

        self.continue_btn = QPushButton("继续")
        set_button_role(self.continue_btn, "connect")
        self.continue_btn.setMinimumHeight(self.BTN_HEIGHT)
        self.continue_btn.setEnabled(False)
        button_layout.addWidget(self.continue_btn, row, 1)

        layout.addLayout(button_layout)
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
        self.get_pos_btn.clicked.connect(self.get_pose.emit)
        self.collision_set_btn.clicked.connect(self.set_collision_level.emit)
        self.clear_error_btn.clicked.connect(self.clear_error.emit)
        self.pause_btn.clicked.connect(self.pause.emit)
        self.continue_btn.clicked.connect(self.resume.emit)
        self.collision_combo.currentIndexChanged.connect(self.collision_level_changed.emit)
        self.ip_input.editingFinished.connect(
            lambda: self.ip_changed.emit(self.ip_input.text().strip())
        )
