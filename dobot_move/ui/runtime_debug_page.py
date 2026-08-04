#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Runtime debug page widget -- extracted from gui_app.py."""

from ..ui.qt_compat import (
    Qt,
    QCheckBox,
    QComboBox,
    QFont,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QTableWidget,
    QTextCursor,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    pyqtSignal,
)
from ..ui.ui_theme import set_button_role, COLORS, metric_value_style


class RuntimeDebugPage(QWidget):
    """Four-tab Runtime debug panel: status overview, flow debug, vision
    diagnostics, and live log streaming."""

    fetch_detection_test = pyqtSignal()
    camera_connect_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)

        tabs = QTabWidget()
        tabs.setObjectName("debugTabs")

        # --- Tab 1: 状态概览 ---
        tab_status = QWidget()
        tab_status_layout = QVBoxLayout(tab_status)
        tab_status_layout.setSpacing(10)
        tab_status_layout.setContentsMargins(0, 0, 0, 0)

        # Runtime 状态 group
        runtime_status_group = QGroupBox("Runtime 状态")
        runtime_status_layout = QGridLayout(runtime_status_group)
        runtime_status_layout.setColumnStretch(1, 1)

        # Row 0: 运行状态
        title_label = QLabel("运行状态:")
        title_label.setStyleSheet(
            f"color: {COLORS['muted']}; font-size: 10pt; font-weight: 700;"
        )
        runtime_status_layout.addWidget(title_label, 0, 0)
        self.runtime_overview_state_label = QLabel("未知")
        self.runtime_overview_state_label.setStyleSheet(metric_value_style())
        self.runtime_overview_state_label.setMinimumWidth(200)
        runtime_status_layout.addWidget(self.runtime_overview_state_label, 0, 1)

        # Row 1: 在线状态
        title_label = QLabel("在线状态:")
        title_label.setStyleSheet(
            f"color: {COLORS['muted']}; font-size: 10pt; font-weight: 700;"
        )
        runtime_status_layout.addWidget(title_label, 1, 0)
        self.runtime_overview_online_label = QLabel("离线")
        self.runtime_overview_online_label.setStyleSheet(metric_value_style())
        self.runtime_overview_online_label.setMinimumWidth(200)
        runtime_status_layout.addWidget(self.runtime_overview_online_label, 1, 1)

        # Row 2: 最后错误
        title_label = QLabel("最后错误:")
        title_label.setStyleSheet(
            f"color: {COLORS['muted']}; font-size: 10pt; font-weight: 700;"
        )
        runtime_status_layout.addWidget(title_label, 2, 0)
        self.runtime_overview_error_label = QLabel("无")
        self.runtime_overview_error_label.setStyleSheet(metric_value_style())
        self.runtime_overview_error_label.setMinimumWidth(200)
        runtime_status_layout.addWidget(self.runtime_overview_error_label, 2, 1)

        # Row 3: 当前模块
        title_label = QLabel("当前模块:")
        title_label.setStyleSheet(
            f"color: {COLORS['muted']}; font-size: 10pt; font-weight: 700;"
        )
        runtime_status_layout.addWidget(title_label, 3, 0)
        self.runtime_overview_module_label = QLabel("---")
        self.runtime_overview_module_label.setStyleSheet(metric_value_style())
        self.runtime_overview_module_label.setMinimumWidth(200)
        runtime_status_layout.addWidget(self.runtime_overview_module_label, 3, 1)

        tab_status_layout.addWidget(runtime_status_group)

        # Runtime 维护控制 group
        runtime_group = QGroupBox("Runtime 维护控制")
        runtime_layout = QHBoxLayout(runtime_group)
        self.debug_runtime_state = QLabel("Runtime: 未连接")
        runtime_layout.addWidget(self.debug_runtime_state)
        for text, command in (
            ("进入维护", "enter_maintenance"),
            ("退出维护", "exit_maintenance"),
            ("清除恢复锁", "clear_recovery"),
            ("刷新状态", "get_status"),
            ("发布状态", "get_publication_status"),
        ):
            button = QPushButton(text)
            set_button_role(
                button,
                {"enter_maintenance": "warning"}.get(command, "secondary"),
            )
            # Click connections are handled by the host gui_app.py
            runtime_layout.addWidget(button)
        self.debug_reload_config_btn = QPushButton("重载配置")
        set_button_role(self.debug_reload_config_btn, "secondary")
        runtime_layout.addWidget(self.debug_reload_config_btn)
        runtime_layout.addStretch()
        tab_status_layout.addWidget(runtime_group)

        # 任务状态 group
        task_status_group = QGroupBox("任务状态")
        task_status_layout = QHBoxLayout(task_status_group)
        self.debug_task_status_label = QLabel("任务状态: 未知")
        self.debug_task_status_label.setStyleSheet(
            f"color: {COLORS['text']}; font-weight: 600; background: transparent; border: none;"
        )
        task_status_layout.addWidget(self.debug_task_status_label)
        task_status_layout.addStretch()
        tab_status_layout.addWidget(task_status_group)

        tab_status_layout.addStretch()

        # --- Tab 2: 流程调试 ---
        tab_flow = QWidget()
        tab_flow_layout = QVBoxLayout(tab_flow)
        tab_flow_layout.setSpacing(10)
        tab_flow_layout.setContentsMargins(0, 0, 0, 0)

        flow_group = QGroupBox("流程调试")
        flow_layout = QGridLayout(flow_group)

        self.debug_validate_btn = QPushButton("校验当前流程")
        set_button_role(self.debug_validate_btn, "primary")
        flow_layout.addWidget(self.debug_validate_btn, 0, 0)

        self.debug_start_btn = QPushButton("运行当前流程")
        set_button_role(self.debug_start_btn, "primary")
        flow_layout.addWidget(self.debug_start_btn, 0, 1)

        flow_layout.addWidget(QLabel("步骤序号:"), 0, 2)
        self.debug_step_input = QLineEdit("1")
        self.debug_step_input.setMaximumWidth(80)
        flow_layout.addWidget(self.debug_step_input, 0, 3)

        self.debug_step_btn = QPushButton("运行单步")
        set_button_role(self.debug_step_btn, "secondary")
        flow_layout.addWidget(self.debug_step_btn, 0, 4)

        for column, (text, command) in enumerate(
            (
                ("暂停", "pause_debug_flow"),
                ("继续", "resume_debug_flow"),
                ("停止", "stop_debug_flow"),
                ("读取位姿", "get_current_pose"),
            )
        ):
            button = QPushButton(text)
            set_button_role(
                button,
                {
                    "pause_debug_flow": "warning",
                    "stop_debug_flow": "danger",
                }.get(command, "secondary"),
            )
            # Click connections are handled by the host gui_app.py
            flow_layout.addWidget(button, 1, column)

        tab_flow_layout.addWidget(flow_group)
        tab_flow_layout.addStretch()

        # --- Tab 3: 视觉诊断 ---
        tab_vision = QWidget()
        tab_vision_layout = QVBoxLayout(tab_vision)
        tab_vision_layout.setSpacing(10)
        tab_vision_layout.setContentsMargins(0, 0, 0, 0)

        vision_group = QGroupBox("视觉诊断")
        vision_layout = QGridLayout(vision_group)

        self.debug_camera_combo = QComboBox()
        self.debug_camera_combo.addItems(["D405", "D435i"])

        # 用 QHBoxLayout 把 combo 和"连接相机"按钮包在一起
        camera_bar = QHBoxLayout()
        camera_bar.addWidget(self.debug_camera_combo)
        self.debug_camera_connect_button = QPushButton("连接相机")
        set_button_role(self.debug_camera_connect_button, "secondary")
        self.debug_camera_connect_button.clicked.connect(
            lambda *_: self.camera_connect_requested.emit(
                self.debug_camera_combo.currentText()
            )
        )
        camera_bar.addWidget(self.debug_camera_connect_button)
        vision_layout.addLayout(camera_bar, 0, 0)

        snapshot_button = QPushButton("采集诊断快照")
        set_button_role(snapshot_button, "secondary")
        # Click connection handled by host gui_app.py
        vision_layout.addWidget(snapshot_button, 0, 1)

        logs_button = QPushButton("读取 Runtime 日志")
        set_button_role(logs_button, "secondary")
        # Click connection handled by host gui_app.py
        vision_layout.addWidget(logs_button, 0, 2)

        # "实时图"走流模式：start_vision_stream + get_vision_stream_frame，
        # 由 host gui_app.py 周期性拉取帧并刷新 debug_image_label。
        self.debug_live_button = QPushButton("开始实时图")
        set_button_role(self.debug_live_button, "secondary")
        self.debug_live_button.setCheckable(True)
        # Toggled connection handled by host gui_app.py
        vision_layout.addWidget(self.debug_live_button, 0, 3)

        self.debug_image_label = QLabel("等待 Runtime 视觉快照")
        self.debug_image_label.setMinimumSize(360, 240)
        self.debug_image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.debug_image_label.setStyleSheet(
            f"background-color:{COLORS['bg']}; border:1px solid {COLORS['line']};"
        )
        vision_layout.addWidget(self.debug_image_label, 1, 0, 1, 5)

        # Row 2: 检测测试（secondary 角色，通过信号由 host 连接）
        self.debug_detection_btn = QPushButton("检测测试")
        set_button_role(self.debug_detection_btn, "secondary")
        self.debug_detection_btn.clicked.connect(
            lambda *_: self.fetch_detection_test.emit()
        )
        vision_layout.addWidget(self.debug_detection_btn, 2, 0)

        tab_vision_layout.addWidget(vision_group)

        # Debug output text area
        self.debug_output = QTextEdit()
        self.debug_output.setReadOnly(True)
        self.debug_output.setMinimumHeight(150)
        tab_vision_layout.addWidget(self.debug_output)

        tab_vision_layout.addStretch()

        # --- Tab 4: 实时日志 ---
        tab_log = QWidget()
        tab_log_layout = QVBoxLayout(tab_log)
        tab_log_layout.setSpacing(8)
        tab_log_layout.setContentsMargins(0, 0, 0, 0)

        # 日志文本框：只读、等宽字体、自动滚动到底
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        log_font = QFont("Consolas", 9)
        log_font.setStyleHint(QFont.StyleHint.TypeWriter)
        self.log_view.setFont(log_font)

        # 顶部控制栏：刷新开关 + 清空按钮 + 状态标签
        self.log_auto_refresh_checkbox = QCheckBox("刷新开关")
        self.log_clear_btn = QPushButton("清空")
        set_button_role(self.log_clear_btn, "secondary")
        self.log_clear_btn.clicked.connect(self.log_view.clear)
        self.log_status_label = QLabel("实时拉取")
        self.log_status_label.setStyleSheet(
            f"color: {COLORS['muted']}; font-size: 9pt;"
        )
        # 默认勾选刷新开关；勾选后再连接 toggled 信号，避免初始 setChecked
        # 触发时 status_label 尚未就绪。
        self.log_auto_refresh_checkbox.setChecked(True)
        self.log_auto_refresh_checkbox.toggled.connect(
            lambda checked: self.set_log_paused(not checked)
        )

        log_ctrl_layout = QHBoxLayout()
        log_ctrl_layout.addWidget(self.log_auto_refresh_checkbox)
        log_ctrl_layout.addWidget(self.log_clear_btn)
        log_ctrl_layout.addWidget(self.log_status_label)
        log_ctrl_layout.addStretch()
        tab_log_layout.addLayout(log_ctrl_layout)
        tab_log_layout.addWidget(self.log_view, 1)

        # --- Assemble tabs ---
        for tab_widget, tab_name in (
            (tab_status, "状态概览"),
            (tab_flow, "流程调试"),
            (tab_vision, "视觉诊断"),
            (tab_log, "实时日志"),
        ):
            tab_scroll = QScrollArea()
            tab_scroll.setWidget(tab_widget)
            tab_scroll.setWidgetResizable(True)
            tabs.addTab(tab_scroll, tab_name)

        layout.addWidget(tabs)

    # ------------------------------------------------------------------
    # Live log API
    # ------------------------------------------------------------------
    def append_log_lines(self, lines):
        """追加日志行，保留最近 1000 行并自动滚动到底。"""
        if not lines:
            return
        current = self.log_view.toPlainText()
        incoming = [str(line) for line in lines]
        if current:
            all_lines = current.split("\n") + incoming
        else:
            all_lines = list(incoming)
        if len(all_lines) > 1000:
            all_lines = all_lines[-1000:]
        self.log_view.setPlainText("\n".join(all_lines))
        cursor = self.log_view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.log_view.setTextCursor(cursor)

    def set_log_paused(self, paused):
        """更新日志状态标签（已暂停 / 实时拉取）。"""
        self.log_status_label.setText("已暂停" if paused else "实时拉取")