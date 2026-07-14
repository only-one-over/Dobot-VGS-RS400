#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Runtime debug page widget -- extracted from gui_app.py."""

from ..ui.qt_compat import (
    Qt,
    QCheckBox,
    QComboBox,
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
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from ..ui.ui_theme import set_button_role, COLORS, metric_value_style
from ..ui.gui_debug_widgets import ErrorTrendPlot


class RuntimeDebugPage(QWidget):
    """Three-tab Runtime debug panel: status overview, flow debug, vision diagnostics."""

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
        vision_layout.addWidget(self.debug_camera_combo, 0, 0)

        snapshot_button = QPushButton("采集诊断快照")
        set_button_role(snapshot_button, "secondary")
        # Click connection handled by host gui_app.py
        vision_layout.addWidget(snapshot_button, 0, 1)

        logs_button = QPushButton("读取 Runtime 日志")
        set_button_role(logs_button, "secondary")
        # Click connection handled by host gui_app.py
        vision_layout.addWidget(logs_button, 0, 2)

        self.debug_live_button = QPushButton("开始实时图")
        set_button_role(self.debug_live_button, "secondary")
        self.debug_live_button.setCheckable(True)
        # Toggled connection handled by host gui_app.py
        vision_layout.addWidget(self.debug_live_button, 0, 3)

        self.debug_depth_checkbox = QCheckBox("深度图")
        self.debug_depth_checkbox.setChecked(True)
        vision_layout.addWidget(self.debug_depth_checkbox, 0, 4)

        self.debug_image_label = QLabel("等待 Runtime 视觉快照")
        self.debug_image_label.setMinimumSize(360, 240)
        self.debug_image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.debug_image_label.setStyleSheet(
            f"background-color:{COLORS['bg']}; border:1px solid {COLORS['line']};"
        )
        vision_layout.addWidget(self.debug_image_label, 1, 0, 1, 3)

        self.debug_depth_label = QLabel("等待深度图")
        self.debug_depth_label.setMinimumSize(360, 240)
        self.debug_depth_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.debug_depth_label.setStyleSheet(
            f"background-color:{COLORS['bg']}; border:1px solid {COLORS['line']};"
        )
        vision_layout.addWidget(self.debug_depth_label, 1, 3, 1, 2)
        tab_vision_layout.addWidget(vision_group)

        # Telemetry table
        self.debug_telemetry_table = QTableWidget(0, 11)
        self.debug_telemetry_table.setHorizontalHeaderLabels(
            [
                "迭代",
                "X误差",
                "Y误差",
                "Z误差",
                "总误差",
                "频率(Hz)",
                "采集(ms)",
                "推理(ms)",
                "深度(ms)",
                "下发(ms)",
                "总周期(ms)",
            ]
        )
        self.debug_telemetry_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.debug_telemetry_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        tab_vision_layout.addWidget(self.debug_telemetry_table)

        # Error trend plots
        plots_layout = QHBoxLayout()
        self.debug_error_time_plot = ErrorTrendPlot(
            "总误差 vs 时间",
            x_mode="time",
        )
        self.debug_error_iteration_plot = ErrorTrendPlot(
            "总误差 vs 迭代",
            x_mode="iteration",
        )
        plots_layout.addWidget(self.debug_error_time_plot)
        plots_layout.addWidget(self.debug_error_iteration_plot)
        tab_vision_layout.addLayout(plots_layout)

        # Debug output text area
        self.debug_output = QTextEdit()
        self.debug_output.setReadOnly(True)
        self.debug_output.setMinimumHeight(150)
        tab_vision_layout.addWidget(self.debug_output)

        tab_vision_layout.addStretch()

        # --- Assemble tabs ---
        for tab_widget, tab_name in (
            (tab_status, "状态概览"),
            (tab_flow, "流程调试"),
            (tab_vision, "视觉诊断"),
        ):
            tab_scroll = QScrollArea()
            tab_scroll.setWidget(tab_widget)
            tab_scroll.setWidgetResizable(True)
            tabs.addTab(tab_scroll, tab_name)

        layout.addWidget(tabs)