#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置中心页面 - 集中管理机器人、相机、手眼标定、Modbus、Runtime 等参数配置。
将分散在多个 Tab 中的配置入口统一收纳，方便一站式查看与修改。
"""

import os

import numpy as np

from ..ui.qt_compat import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton, QLabel,
    QComboBox, QLineEdit, QGroupBox, QScrollArea, QTableWidget,
    QTableWidgetItem, QHeaderView, QFrame, Qt, pyqtSignal, QMessageBox,
    QDialog, QDialogButtonBox, QSpinBox,
)
from ..ui.ui_theme import COLORS, apply_status_visual, set_button_role


class ConfigCenterPage(QWidget):
    """配置中心页面：集中管理 5 类配置参数。

    配置组：
      1. 机器人配置  - 机器人 IP、拍照位
      2. 相机配置    - D435i / D405 模型选择与连接
      3. 手眼标定    - cam_to_flange 位姿与 4x4 矩阵
      4. Modbus 配置 - 端口与从站地址（只读）
      5. Runtime 配置 - IPC 端口（只读）

    保存按钮仅发出信号，实际保存逻辑由主窗口处理。
    """

    # ── 机器人配置信号 ──
    ip_save_requested = pyqtSignal(str)                    # IP 地址
    photo_position_save_requested = pyqtSignal(list)       # [x, y, z, rx, ry, rz]
    connect_robot_requested = pyqtSignal()                 # 连接设备

    # ── 相机配置信号 ──
    camera_model_select_requested = pyqtSignal(str)       # camera_type: "D435i"/"D405"
    camera_connect_requested = pyqtSignal(str)             # camera_type
    camera_disconnect_requested = pyqtSignal(str)          # camera_type

    # ── 手眼标定信号 ──
    calib_save_requested = pyqtSignal(str, list)           # camera_type, pose_values
    calib_reset_requested = pyqtSignal(str)                # camera_type
    calib_refresh_requested = pyqtSignal(str)              # camera_type
    calib_camera_changed = pyqtSignal(str)                 # camera_type（下拉框切换）
    calib_matrix_import_requested = pyqtSignal(str)         # camera_type（请求打开矩阵输入对话框）

    # ── 配置重载信号 ──
    reload_config_requested = pyqtSignal()

    # ── 运动安全配置信号 ──
    motion_safety_save_requested = pyqtSignal(dict)            # 15 字段 config dict

    BTN_HEIGHT = 38

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self._connect_signals()
        # 初始加载配置值
        try:
            self.load_config_values()
        except Exception:
            # 加载失败不阻塞页面构建，主窗口可在初始化后再次调用
            pass

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------
    def _build_ui(self):
        """构建页面整体布局：外层 QScrollArea 包裹内容区。"""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        content.setObjectName("configCenterContent")
        layout = QVBoxLayout(content)
        layout.setSpacing(12)
        layout.setContentsMargins(12, 12, 12, 12)

        # 依次构建 6 个配置组
        layout.addWidget(self._build_robot_group())
        layout.addWidget(self._build_camera_group())
        layout.addWidget(self._build_calib_group())
        layout.addWidget(self._build_modbus_group())
        layout.addWidget(self._build_motion_safety_group())
        layout.addWidget(self._build_runtime_group())
        layout.addStretch()

        scroll.setWidget(content)
        outer.addWidget(scroll)

    # ── 1. 机器人配置组 ──────────────────────────────────────────────
    def _build_robot_group(self):
        """机器人配置：IP 输入框 + 拍照位（6 轴）+ 保存并重载按钮。"""
        group = QGroupBox("机器人配置")
        v = QVBoxLayout(group)
        v.setSpacing(10)

        # 机器人 IP
        ip_row = QHBoxLayout()
        ip_row.setSpacing(8)
        ip_label = QLabel("机器人 IP:")
        ip_label.setStyleSheet(
            f"color: {COLORS['muted']}; font-weight: 600; background: transparent; border: none;"
        )
        self.ip_input = QLineEdit()
        self.ip_input.setPlaceholderText("例如 192.168.1.50")
        self.ip_input.setMaximumWidth(220)
        ip_row.addWidget(ip_label)
        ip_row.addWidget(self.ip_input, 1)
        ip_row.addStretch()
        v.addLayout(ip_row)

        # 连接设备按钮 + 状态标签
        conn_row = QHBoxLayout()
        conn_row.setSpacing(8)
        self.connect_robot_btn = QPushButton("连接设备")
        set_button_role(self.connect_robot_btn, "connect")
        self.connect_robot_btn.setMinimumHeight(self.BTN_HEIGHT)
        self.connect_robot_btn.setMaximumWidth(160)
        conn_row.addWidget(self.connect_robot_btn)

        self.robot_conn_status_label = QLabel("未连接")
        self.robot_conn_status_label.setStyleSheet(
            f"color: {COLORS['muted']}; font-weight: 600; "
            "background: transparent; border: none;"
        )
        conn_row.addWidget(self.robot_conn_status_label)
        conn_row.addStretch()
        v.addLayout(conn_row)

        # 拍照位 [x, y, z, rx, ry, rz]
        photo_row = QHBoxLayout()
        photo_row.setSpacing(6)
        photo_title = QLabel("拍照位 (只读，请在点位管理修改) (x/y/z/rx/ry/rz):")
        photo_title.setStyleSheet(
            f"color: {COLORS['muted']}; font-weight: 600; background: transparent; border: none;"
        )
        photo_row.addWidget(photo_title)
        self.photo_inputs = []
        for label_text in ("x", "y", "z", "rx", "ry", "rz"):
            photo_row.addWidget(QLabel(label_text))
            le = QLineEdit()
            le.setPlaceholderText("0.0")
            le.setMaximumWidth(90)
            le.setReadOnly(True)
            photo_row.addWidget(le)
            self.photo_inputs.append(le)
        photo_row.addStretch()
        v.addLayout(photo_row)

        # 工具坐标系 / 用户坐标系（Tool0 = 法兰坐标系，User0 = 基坐标系）
        coord_row = QHBoxLayout()
        coord_row.setSpacing(8)
        coord_label_style = (
            f"color: {COLORS['muted']}; font-weight: 600; "
            "background: transparent; border: none;"
        )

        tool_label = QLabel("工具坐标系 (Tool Index):")
        tool_label.setStyleSheet(coord_label_style)
        coord_row.addWidget(tool_label)
        self.tool_index_spin = QSpinBox()
        self.tool_index_spin.setRange(0, 9)
        self.tool_index_spin.setValue(0)
        self.tool_index_spin.setMaximumWidth(80)
        coord_row.addWidget(self.tool_index_spin)
        coord_row.addWidget(self._readonly_hint("Tool0 = 法兰坐标系"))

        coord_row.addSpacing(20)

        user_label = QLabel("用户坐标系 (User Index):")
        user_label.setStyleSheet(coord_label_style)
        coord_row.addWidget(user_label)
        self.user_index_spin = QSpinBox()
        self.user_index_spin.setRange(0, 9)
        self.user_index_spin.setValue(0)
        self.user_index_spin.setMaximumWidth(80)
        coord_row.addWidget(self.user_index_spin)
        coord_row.addWidget(self._readonly_hint("User0 = 基坐标系"))

        coord_row.addStretch()
        v.addLayout(coord_row)

        # 保存并重载按钮
        self.robot_save_btn = QPushButton("保存并重载")
        set_button_role(self.robot_save_btn, "primary")
        self.robot_save_btn.setMinimumHeight(self.BTN_HEIGHT)
        self.robot_save_btn.setMaximumWidth(200)
        v.addWidget(self.robot_save_btn)

        return group

    # ── 2. 相机配置组 ────────────────────────────────────────────────
    def _build_camera_group(self):
        """相机配置：D435i / D405 模型路径 + 选择 + 连接/断开 + 状态。"""
        group = QGroupBox("相机配置")
        v = QVBoxLayout(group)
        v.setSpacing(10)

        v.addWidget(self._build_camera_block("D435i"))
        v.addWidget(self._build_camera_block("D405"))
        return group

    def _build_camera_block(self, camera_type: str):
        """构建单个相机的配置块。"""
        block = QFrame()
        block.setStyleSheet(
            f"QFrame {{ background: {COLORS['surface']}; border: 1px solid {COLORS['line']}; "
            "border-radius: 6px; padding: 8px; }"
        )
        v = QVBoxLayout(block)
        v.setSpacing(6)
        v.setContentsMargins(10, 8, 10, 8)

        # 状态标签
        status_label = QLabel(f"{camera_type}: 未连接")
        apply_status_visual(status_label, "未连接")
        v.addWidget(status_label)

        # 模型路径行
        model_row = QHBoxLayout()
        model_row.setSpacing(8)
        model_path = QLineEdit()
        model_path.setReadOnly(True)
        model_path.setPlaceholderText("未选择模型")
        select_btn = QPushButton("选择模型")
        set_button_role(select_btn, "secondary")
        select_btn.setMinimumHeight(self.BTN_HEIGHT)
        model_row.addWidget(QLabel("模型:"))
        model_row.addWidget(model_path, 1)
        model_row.addWidget(select_btn)
        v.addLayout(model_row)

        # 连接/断开按钮行
        conn_row = QHBoxLayout()
        conn_row.setSpacing(8)
        connect_btn = QPushButton(f"{camera_type} 连接")
        set_button_role(connect_btn, "connect")
        connect_btn.setMinimumHeight(self.BTN_HEIGHT)
        disconnect_btn = QPushButton(f"{camera_type} 断开")
        set_button_role(disconnect_btn, "secondary")
        disconnect_btn.setMinimumHeight(self.BTN_HEIGHT)
        disconnect_btn.setEnabled(False)
        conn_row.addWidget(connect_btn)
        conn_row.addWidget(disconnect_btn)
        conn_row.addStretch()
        v.addLayout(conn_row)

        # 按相机类型存储控件引用
        if camera_type == "D435i":
            self.d435i_status_label = status_label
            self.d435i_model_path = model_path
            self.d435i_model_select_btn = select_btn
            self.d435i_connect_btn = connect_btn
            self.d435i_disconnect_btn = disconnect_btn
        else:
            self.d405_status_label = status_label
            self.d405_model_path = model_path
            self.d405_model_select_btn = select_btn
            self.d405_connect_btn = connect_btn
            self.d405_disconnect_btn = disconnect_btn

        return block

    # ── 3. 手眼标定配置组 ───────────────────────────────────────────
    def _build_calib_group(self):
        """手眼标定：相机选择 + cam_to_flange 位姿 + 4x4 矩阵 + 保存/重置/刷新。"""
        group = QGroupBox("手眼标定")
        v = QVBoxLayout(group)
        v.setSpacing(10)

        # 相机选择下拉框
        sel_row = QHBoxLayout()
        sel_row.setSpacing(8)
        sel_row.addWidget(QLabel("选择相机:"))
        self.calib_camera_combo = QComboBox()
        self.calib_camera_combo.addItems(["D435i", "D405"])
        sel_row.addWidget(self.calib_camera_combo)
        sel_row.addStretch()
        v.addLayout(sel_row)

        # cam_to_flange 位姿输入
        pose_row = QHBoxLayout()
        pose_row.setSpacing(6)
        pose_row.addWidget(QLabel("cam_to_flange 位姿:"))
        self.calib_pose_inputs = []
        for label_text in ("x", "y", "z", "rx", "ry", "rz"):
            pose_row.addWidget(QLabel(label_text))
            le = QLineEdit()
            le.setPlaceholderText("0.0")
            le.setMaximumWidth(90)
            pose_row.addWidget(le)
            self.calib_pose_inputs.append(le)
        pose_row.addStretch()
        v.addLayout(pose_row)

        # 4x4 矩阵表格（只读显示）
        self.calib_table = QTableWidget(4, 4)
        self.calib_table.setHorizontalHeaderLabels(["Col 0", "Col 1", "Col 2", "Col 3"])
        self.calib_table.setVerticalHeaderLabels(["Row 0", "Row 1", "Row 2", "Row 3"])
        self.calib_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.calib_table.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.calib_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        v.addWidget(self.calib_table)

        # 操作按钮
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.calib_save_btn = QPushButton("保存")
        set_button_role(self.calib_save_btn, "primary")
        self.calib_save_btn.setMinimumHeight(self.BTN_HEIGHT)
        self.calib_reset_btn = QPushButton("重置")
        set_button_role(self.calib_reset_btn, "warning")
        self.calib_reset_btn.setMinimumHeight(self.BTN_HEIGHT)
        self.calib_refresh_btn = QPushButton("刷新")
        set_button_role(self.calib_refresh_btn, "secondary")
        self.calib_refresh_btn.setMinimumHeight(self.BTN_HEIGHT)
        self.calib_import_matrix_btn = QPushButton("写入手眼标定矩阵")
        set_button_role(self.calib_import_matrix_btn, "secondary")
        self.calib_import_matrix_btn.setMinimumHeight(self.BTN_HEIGHT)
        btn_row.addWidget(self.calib_save_btn)
        btn_row.addWidget(self.calib_reset_btn)
        btn_row.addWidget(self.calib_refresh_btn)
        btn_row.addWidget(self.calib_import_matrix_btn)
        btn_row.addStretch()
        v.addLayout(btn_row)

        return group

    # ── 4. Modbus 配置组 ────────────────────────────────────────────
    def _build_modbus_group(self):
        """Modbus 配置：端口与从站地址（只读，由 Runtime 管理）。"""
        group = QGroupBox("Modbus 配置")
        grid = QGridLayout(group)
        grid.setSpacing(10)

        readonly_style = (
            f"QLineEdit {{ background: {COLORS['bg']}; color: #86868b; "
            f"border: 1px solid {COLORS['line']}; }}"
        )

        # 监听端口
        grid.addWidget(QLabel("Modbus 端口:"), 0, 0)
        self.modbus_port_input = QLineEdit()
        self.modbus_port_input.setReadOnly(True)
        self.modbus_port_input.setStyleSheet(readonly_style)
        self.modbus_port_input.setMaximumWidth(160)
        grid.addWidget(self.modbus_port_input, 0, 1)
        grid.addWidget(self._readonly_hint("由 Runtime 管理"), 0, 2)

        # 从站地址
        grid.addWidget(QLabel("从站地址:"), 1, 0)
        self.modbus_slave_id_input = QLineEdit()
        self.modbus_slave_id_input.setReadOnly(True)
        self.modbus_slave_id_input.setStyleSheet(readonly_style)
        self.modbus_slave_id_input.setMaximumWidth(160)
        grid.addWidget(self.modbus_slave_id_input, 1, 1)
        grid.addWidget(self._readonly_hint("由 Runtime 管理"), 1, 2)

        grid.setColumnStretch(3, 1)
        return group

    # ── 5. 运动安全配置组 ──────────────────────────────────────────────
    def _build_motion_safety_group(self):
        """运动安全配置：workspace 边界 + delta 上限 + 姿态角 + 速度/加速度。"""
        group = QGroupBox("运动安全配置")
        grid = QGridLayout(group)
        grid.setSpacing(8)

        label_style = (
            f"color: {COLORS['muted']}; font-weight: 600; "
            "background: transparent; border: none;"
        )
        hint_style = "color: #86868b; font-size: 9pt; font-style: italic; background: transparent; border: none;"

        # 收集所有输入框引用到 dict（key=字段名）
        self.motion_safety_inputs = {}
        field_specs = [
            # (label, key, default_placeholder, row, col)
            ("X 最小 (mm)", "workspace_x_min", "-1900.0", 0, 0),
            ("X 最大 (mm)", "workspace_x_max", "1900.0", 0, 2),
            ("Y 最小 (mm)", "workspace_y_min", "-1900.0", 1, 0),
            ("Y 最大 (mm)", "workspace_y_max", "1900.0", 1, 2),
            ("Z 最小 (mm)", "workspace_z_min", "-1200.0", 2, 0),
            ("Z 最大 (mm)", "workspace_z_max", "1200.0", 2, 2),
            ("姿态角最小 (度)", "orientation_min", "-360.0", 3, 0),
            ("姿态角最大 (度)", "orientation_max", "360.0", 3, 2),
            ("单段 XYZ 偏移上限 (mm)", "max_delta_xyz", "800.0", 4, 0),
            ("单段姿态偏移上限 (度)", "max_delta_rot", "90.0", 4, 2),
            ("速度最小 (v=百分比)", "speed_min", "1.0", 5, 0),
            ("速度最大 (百分比)", "speed_max_percent", "100.0", 5, 2),
            ("速度绝对最大 (mm/s)", "speed_max_abs", "2000.0", 6, 0),
            ("加速度最小", "accel_min", "1.0", 6, 2),
            ("加速度最大", "accel_max", "100.0", 7, 0),
        ]

        for label_text, key, placeholder, row, col in field_specs:
            lbl = QLabel(label_text)
            lbl.setStyleSheet(label_style)
            le = QLineEdit()
            le.setPlaceholderText(placeholder)
            le.setMaximumWidth(120)
            grid.addWidget(lbl, row, col)
            grid.addWidget(le, row, col + 1)
            self.motion_safety_inputs[key] = le

        # 说明提示
        hint = QLabel("修改后点击保存并重载，下次运动校验自动生效。feedback_max_age_* 属运行时参数，不在此处。")
        hint.setStyleSheet(hint_style)
        hint.setWordWrap(True)
        grid.addWidget(hint, 8, 0, 1, 4)

        # 保存按钮
        self.motion_safety_save_btn = QPushButton("保存并重载")
        set_button_role(self.motion_safety_save_btn, "primary")
        self.motion_safety_save_btn.setMinimumHeight(self.BTN_HEIGHT)
        self.motion_safety_save_btn.setMaximumWidth(200)
        grid.addWidget(self.motion_safety_save_btn, 9, 0, 1, 4)

        grid.setColumnStretch(4, 1)
        return group

    # ── 6. Runtime 配置组 ───────────────────────────────────────────
    def _build_runtime_group(self):
        """Runtime 配置：IPC 端口与 Stop 端口（只读，需修改 config.json）。"""
        group = QGroupBox("Runtime 配置")
        grid = QGridLayout(group)
        grid.setSpacing(10)

        readonly_style = (
            f"QLineEdit {{ background: {COLORS['bg']}; color: #86868b; "
            f"border: 1px solid {COLORS['line']}; }}"
        )

        # IPC 主通道端口
        grid.addWidget(QLabel("IPC 端口:"), 0, 0)
        self.runtime_ipc_port_input = QLineEdit()
        self.runtime_ipc_port_input.setReadOnly(True)
        self.runtime_ipc_port_input.setStyleSheet(readonly_style)
        self.runtime_ipc_port_input.setMaximumWidth(160)
        grid.addWidget(self.runtime_ipc_port_input, 0, 1)
        grid.addWidget(self._readonly_hint("需修改 config.json"), 0, 2)

        # 安全停止通道端口
        grid.addWidget(QLabel("Stop 端口:"), 1, 0)
        self.runtime_stop_port_input = QLineEdit()
        self.runtime_stop_port_input.setReadOnly(True)
        self.runtime_stop_port_input.setStyleSheet(readonly_style)
        self.runtime_stop_port_input.setMaximumWidth(160)
        grid.addWidget(self.runtime_stop_port_input, 1, 1)
        grid.addWidget(self._readonly_hint("需修改 config.json"), 1, 2)

        # 重载配置按钮
        self.reload_config_btn = QPushButton("重载配置")
        set_button_role(self.reload_config_btn, "secondary")
        self.reload_config_btn.setMinimumHeight(self.BTN_HEIGHT)
        self.reload_config_btn.setMaximumWidth(200)
        grid.addWidget(self.reload_config_btn, 2, 0, 1, 3)

        grid.setColumnStretch(3, 1)
        return group

    def _readonly_hint(self, text: str) -> QLabel:
        """生成只读项的灰色提示标签。"""
        label = QLabel(text)
        label.setStyleSheet(
            "color: #86868b; font-size: 9pt; font-style: italic; "
            "background: transparent; border: none;"
        )
        return label

    # ------------------------------------------------------------------
    # 信号连接
    # ------------------------------------------------------------------
    def _connect_signals(self):
        """连接按钮点击到信号发射。"""
        # 机器人配置
        self.robot_save_btn.clicked.connect(self._emit_robot_save)
        self.connect_robot_btn.clicked.connect(self.connect_robot_requested.emit)

        # 相机配置
        self.d435i_model_select_btn.clicked.connect(
            lambda: self.camera_model_select_requested.emit("D435i")
        )
        self.d435i_connect_btn.clicked.connect(
            lambda: self.camera_connect_requested.emit("D435i")
        )
        self.d435i_disconnect_btn.clicked.connect(
            lambda: self.camera_disconnect_requested.emit("D435i")
        )
        self.d405_model_select_btn.clicked.connect(
            lambda: self.camera_model_select_requested.emit("D405")
        )
        self.d405_connect_btn.clicked.connect(
            lambda: self.camera_connect_requested.emit("D405")
        )
        self.d405_disconnect_btn.clicked.connect(
            lambda: self.camera_disconnect_requested.emit("D405")
        )

        # 手眼标定
        self.calib_camera_combo.currentTextChanged.connect(
            self.calib_camera_changed.emit
        )
        self.calib_save_btn.clicked.connect(self._emit_calib_save)
        self.calib_reset_btn.clicked.connect(self._emit_calib_reset)
        self.calib_refresh_btn.clicked.connect(self._emit_calib_refresh)
        self.calib_import_matrix_btn.clicked.connect(self._open_matrix_dialog)

        # 运动安全配置
        self.motion_safety_save_btn.clicked.connect(self._emit_motion_safety_save)

        # Runtime 配置重载
        self.reload_config_btn.clicked.connect(self.reload_config_requested.emit)

    # ------------------------------------------------------------------
    # 信号发射辅助方法
    # ------------------------------------------------------------------
    def _emit_robot_save(self):
        """收集机器人 IP，发出保存信号并触发重载。"""
        ip = self.ip_input.text().strip()
        self.ip_save_requested.emit(ip)

        # 工具 / 用户坐标系索引写入 config.json（重启 Runtime 后生效）
        from ..config import config_manager
        config_manager.set_tool_index(int(self.tool_index_spin.value()))
        config_manager.set_user_index(int(self.user_index_spin.value()))

        # 保存后自动触发 Runtime 配置重载
        self.reload_config_requested.emit()

    def _emit_calib_save(self):
        """收集当前相机的位姿值，发出标定保存信号。"""
        camera_type = self.calib_camera_combo.currentText()
        pose_values = []
        for le in self.calib_pose_inputs:
            text = le.text().strip()
            try:
                pose_values.append(float(text) if text else 0.0)
            except ValueError:
                pose_values.append(0.0)
        self.calib_save_requested.emit(camera_type, pose_values)

    def _emit_calib_reset(self):
        """发出标定重置信号。"""
        self.calib_reset_requested.emit(self.calib_camera_combo.currentText())

    def _emit_calib_refresh(self):
        """发出标定刷新信号。"""
        self.calib_refresh_requested.emit(self.calib_camera_combo.currentText())

    def _emit_motion_safety_save(self):
        """收集运动安全配置输入框值，校验后发出保存信号。"""
        config_dict = {}
        for key, le in self.motion_safety_inputs.items():
            text = le.text().strip()
            if not text:
                # 空值用 placeholder 提示的默认值
                text = le.placeholderText() or "0"
            try:
                config_dict[key] = float(text)
            except ValueError:
                QMessageBox.warning(
                    self, "输入无效",
                    f"字段 {key} 的值 '{text}' 不是有效数值",
                )
                return

        # min <= max 校验（与 set_motion_safety_config 一致，但提前在 UI 拦截）
        pair_checks = [
            ("workspace_x_min", "workspace_x_max", "X"),
            ("workspace_y_min", "workspace_y_max", "Y"),
            ("workspace_z_min", "workspace_z_max", "Z"),
            ("orientation_min", "orientation_max", "姿态角"),
            ("speed_min", "speed_max_percent", "速度百分比"),
            ("accel_min", "accel_max", "加速度"),
        ]
        for min_key, max_key, label in pair_checks:
            if config_dict[min_key] > config_dict[max_key]:
                QMessageBox.warning(
                    self, "范围无效",
                    f"{label} 最小值不能大于最大值: {min_key}={config_dict[min_key]}, {max_key}={config_dict[max_key]}",
                )
                return

        self.motion_safety_save_requested.emit(config_dict)

    def _open_matrix_dialog(self):
        """打开 4×4 矩阵输入对话框。"""
        from ..robot.transform_utils import pose2matrix
        camera_type = self.calib_camera_combo.currentText()
        dialog = CalibMatrixDialog(camera_type, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            pose = dialog.get_result_pose()
            if pose is not None:
                # 填入 6 输入框
                for i in range(6):
                    self.calib_pose_inputs[i].setText(f"{pose[i]:.6f}")
                # 从位姿计算矩阵并刷新 4×4 只读表格
                matrix = pose2matrix(*pose)
                self._fill_calib_table(matrix)

    # ------------------------------------------------------------------
    # 公开方法
    # ------------------------------------------------------------------
    def load_config_values(self):
        """从 config.json 加载所有配置值到 UI 控件。"""
        from ..config import config_manager

        config = config_manager.get_config()

        # 机器人 IP
        robot_ip = config.get("robot_ip", "192.168.1.50")
        self.ip_input.setText(str(robot_ip))

        # 拍照位 [x, y, z, rx, ry, rz]（只读显示，数据源为 points.initial_point.coords）
        photo = None
        initial_point = config_manager.get_point("initial_point")
        if initial_point and isinstance(initial_point.get("coords"), (list, tuple)) and len(initial_point["coords"]) >= 6:
            photo = initial_point["coords"]
        else:
            photo = config_manager.get_photo_position()
        if isinstance(photo, (list, tuple)) and len(photo) >= 6:
            for i in range(6):
                self.photo_inputs[i].setText(str(photo[i]))

        # 工具 / 用户坐标系索引
        self.tool_index_spin.setValue(int(config_manager.get_tool_index()))
        self.user_index_spin.setValue(int(config_manager.get_user_index()))

        # 相机模型路径
        for cam_type, path_edit in (("D435i", self.d435i_model_path),
                                    ("D405", self.d405_model_path)):
            try:
                model_path = config_manager.get_camera_model_path(cam_type)
                if model_path and os.path.exists(model_path):
                    path_edit.setText(model_path)
                else:
                    path_edit.clear()
            except Exception:
                path_edit.clear()

        # 手眼标定（加载当前下拉框所选相机）
        self._load_calib_from_config(self.calib_camera_combo.currentText())

        # Modbus 配置（只读显示）
        self.modbus_port_input.setText(str(config_manager.get_modbus_port()))
        self.modbus_slave_id_input.setText(str(config_manager.get_modbus_slave_id()))

        # 运动安全配置
        try:
            motion_safety = config_manager.get_motion_safety_config()
            for key, le in self.motion_safety_inputs.items():
                if key in motion_safety:
                    le.setText(str(motion_safety[key]))
        except Exception:
            # 加载失败不阻塞，保持 placeholder
            pass

        # Runtime 配置（只读显示）
        runtime = config_manager.get_runtime_config()
        self.runtime_ipc_port_input.setText(str(runtime.get("ipc_port", 8765)))
        self.runtime_stop_port_input.setText(str(runtime.get("ipc_stop_port", 8766)))

    def refresh_photo_position_display(self):
        """从 points.initial_point.coords 读取最新值并更新拍照位 6 个 QLineEdit 显示。

        点位管理页保存 initial_point 后调用此方法刷新配置中心页的拍照位显示。
        """
        from ..config import config_manager
        try:
            initial_point = config_manager.get_point("initial_point")
            if initial_point and isinstance(initial_point.get("coords"), (list, tuple)) and len(initial_point["coords"]) >= 6:
                photo = initial_point["coords"]
            else:
                photo = config_manager.get_photo_position()
            if isinstance(photo, (list, tuple)) and len(photo) >= 6:
                for i in range(6):
                    self.photo_inputs[i].setText(str(photo[i]))
        except Exception as e:
            import logging
            logging.getLogger(__name__).debug("刷新拍照位显示失败: %s", e)

    def _load_calib_from_config(self, camera_type: str):
        """从配置加载指定相机的标定位姿与矩阵到 UI。"""
        from ..robot.hand_eye_calib import HandEyeCalibManager

        try:
            manager = HandEyeCalibManager()
            # 位姿
            poses = manager.get_poses(camera_type)
            cam_to_flange_pose = poses.get("cam_to_flange_pose", [])
            if isinstance(cam_to_flange_pose, (list, tuple)) and len(cam_to_flange_pose) >= 6:
                for i in range(6):
                    self.calib_pose_inputs[i].setText(f"{cam_to_flange_pose[i]:.6f}")
            else:
                for le in self.calib_pose_inputs:
                    le.clear()
            # 矩阵
            matrix = manager.get_matrix(camera_type)
            self._fill_calib_table(matrix)
        except Exception:
            for le in self.calib_pose_inputs:
                le.clear()
            self._clear_calib_table()

    def _fill_calib_table(self, matrix):
        """将 4x4 矩阵填充到标定表格（只读显示）。"""
        for i in range(4):
            for j in range(4):
                try:
                    value = float(matrix[i][j])
                except (IndexError, TypeError, ValueError):
                    value = 0.0
                item = QTableWidgetItem(f"{value:.6f}")
                self.calib_table.setItem(i, j, item)

    def _clear_calib_table(self):
        """清空标定表格。"""
        for i in range(4):
            for j in range(4):
                self.calib_table.setItem(i, j, QTableWidgetItem(""))

    def update_camera_status(self, camera_type: str, status: str, model_path: str = ""):
        """更新相机状态显示。

        Args:
            camera_type: "D435i" 或 "D405"
            status: 状态文本，如 "已连接"/"未连接"/"错误"
            model_path: 可选的模型路径，非空时同步更新模型路径输入框
        """
        if camera_type == "D435i":
            status_label = self.d435i_status_label
            path_edit = self.d435i_model_path
            connect_btn = self.d435i_connect_btn
            disconnect_btn = self.d435i_disconnect_btn
        elif camera_type == "D405":
            status_label = self.d405_status_label
            path_edit = self.d405_model_path
            connect_btn = self.d405_connect_btn
            disconnect_btn = self.d405_disconnect_btn
        else:
            return

        status_label.setText(f"{camera_type}: {status}")
        apply_status_visual(status_label, status)

        # 根据连接状态切换按钮可用性
        # 注意：必须先检查"断开"类状态，避免 "connected" 子串匹配到 "disconnected"
        status_text = str(status)
        is_disconnected = any(
            key in status_text
            for key in ("未连接", "disconnected", "断开", "offline", "离线", "错误", "error", "失败", "failed")
        )
        is_connected = not is_disconnected and any(
            key in status_text
            for key in ("已连接", "connected", "运行", "running", "成功", "success")
        )
        connect_btn.setEnabled(not is_connected)
        disconnect_btn.setEnabled(is_connected)

        # 更新模型路径显示
        if model_path:
            path_edit.setText(model_path)
            path_edit.setToolTip(model_path)

    def update_robot_connection_status(self, connected: bool, runtime_online: bool) -> None:
        """更新机器人连接状态标签和连接按钮的启用状态。

        Args:
            connected: 机器人是否已连接
            runtime_online: Runtime 是否在线
        """
        if not runtime_online:
            status_text = "Runtime 离线"
            color = COLORS['muted']
            self.connect_robot_btn.setEnabled(False)
        elif connected:
            status_text = "已连接"
            color = COLORS['success']
            self.connect_robot_btn.setEnabled(False)
        else:
            status_text = "未连接"
            color = COLORS['muted']
            self.connect_robot_btn.setEnabled(True)

        self.robot_conn_status_label.setText(status_text)
        self.robot_conn_status_label.setStyleSheet(
            f"color: {color}; font-weight: 600; background: transparent; border: none;"
        )

    def update_calib_display(self, camera_type: str, pose_values: list, matrix: list):
        """更新标定显示（位姿值和矩阵）。

        Args:
            camera_type: 当前显示的相机类型
            pose_values: 6 元素位姿列表 [x, y, z, rx, ry, rz]
            matrix: 4x4 矩阵（嵌套列表）
        """
        # 仅更新当前下拉框选中的相机，避免覆盖正在编辑的内容
        if self.calib_camera_combo.currentText() != camera_type:
            return

        # 更新位姿输入
        if isinstance(pose_values, (list, tuple)) and len(pose_values) >= 6:
            for i in range(6):
                self.calib_pose_inputs[i].setText(f"{float(pose_values[i]):.6f}")

        # 更新矩阵表格
        self._fill_calib_table(matrix)


class CalibMatrixDialog(QDialog):
    """4×4 手眼标定矩阵输入对话框。"""

    def __init__(self, camera_type: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"写入手眼标定矩阵 - {camera_type}")
        self._pose_result = None
        self._camera_type = camera_type

        layout = QVBoxLayout(self)

        # 说明文字
        hint = QLabel("请输入 4×4 齐次变换矩阵（最后一行须为 [0, 0, 0, 1]）:")
        layout.addWidget(hint)

        # 4×4 QLineEdit 网格
        grid = QGridLayout()
        self._inputs = []
        for i in range(4):
            row_inputs = []
            for j in range(4):
                le = QLineEdit()
                le.setMaximumWidth(100)
                grid.addWidget(le, i, j)
                row_inputs.append(le)
            self._inputs.append(row_inputs)
        layout.addLayout(grid)

        # 错误提示
        self._error_label = QLabel()
        self._error_label.setStyleSheet("color: red;")
        self._error_label.setVisible(False)
        layout.addWidget(self._error_label)

        # 按钮
        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.accepted.connect(self._on_accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

        # 预填当前矩阵值
        self._prefill_matrix()

    def _prefill_matrix(self):
        """从 config 读取当前矩阵并预填。"""
        try:
            from ..robot.hand_eye_calib import HandEyeCalibManager
            manager = HandEyeCalibManager()
            matrix = manager.get_matrix(self._camera_type)
            for i in range(4):
                for j in range(4):
                    self._inputs[i][j].setText(f"{matrix[i][j]:.6f}")
        except Exception:
            pass

    def _on_accept(self):
        """确定按钮：读取、校验、转换。"""
        import numpy as np
        from ..robot.hand_eye_calib import _matrix2pose

        # 读取 16 个值
        matrix = np.zeros((4, 4), dtype=np.float64)
        for i in range(4):
            for j in range(4):
                text = self._inputs[i][j].text().strip()
                try:
                    matrix[i][j] = float(text) if text else 0.0
                except ValueError:
                    self._show_error(f"第 {i+1} 行第 {j+1} 列不是有效数字: {text}")
                    return

        # 校验最后一行
        last_row = matrix[3]
        expected_last = np.array([0.0, 0.0, 0.0, 1.0])
        if not np.allclose(last_row, expected_last, atol=1e-6):
            self._show_error(
                f"最后一行必须为 [0, 0, 0, 1]，当前为 [{last_row[0]}, {last_row[1]}, {last_row[2]}, {last_row[3]}]"
            )
            return

        # 校验旋转正交性
        R = matrix[:3, :3]
        if not np.allclose(R.T @ R, np.eye(3), atol=1e-3):
            self._show_error("旋转部分（左上 3×3）不是正交矩阵，请检查输入")
            return

        # 校验通过，转为位姿
        self._pose_result = _matrix2pose(matrix)
        self.accept()

    def _show_error(self, msg: str):
        """显示错误提示。"""
        self._error_label.setText(msg)
        self._error_label.setVisible(True)

    def get_result_pose(self):
        """返回转换后的 6 元素位姿 [x, y, z, rx, ry, rz]。"""
        return self._pose_result
