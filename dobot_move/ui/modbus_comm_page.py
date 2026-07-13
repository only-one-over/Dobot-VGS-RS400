#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Modbus communication page widget.

Provides a standalone QWidget containing:
- Slave service controls (port, slave ID, start/stop)
- Real-time communication status panel
- Register data table

Extracted from gui_app.py for modular UI structure.
"""

from __future__ import annotations

from ..ui.qt_compat import (
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)
from ..ui.ui_theme import COLORS, card_style, set_button_role

_MODBUS_METRIC_STYLE = (
    f"font-size: 13pt; font-weight: bold; color: {COLORS['accent_blue']}; "
    "background: transparent;"
)


class ModbusCommPage(QWidget):
    """Standalone Modbus communication page.

    Parameters
    ----------
    parent : QWidget, optional
        Parent widget.
    modbus_port : str
        Default Modbus listening port (e.g. ``"502"``).
    modbus_slave_id : str
        Default Modbus slave address (e.g. ``"5"``).
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        modbus_port: str = "502",
        modbus_slave_id: str = "5",
    ) -> None:
        super().__init__(parent)
        self._modbus_port = modbus_port
        self._modbus_slave_id = modbus_slave_id
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)

        # --- Control group ---
        modbus_ctrl_group = QGroupBox("本机 Modbus 从站服务（外部 PC=主站）")
        modbus_ctrl_layout = QGridLayout()
        modbus_ctrl_layout.setSpacing(10)

        modbus_ctrl_layout.addWidget(QLabel("监听端口:"), 0, 0)
        self.modbus_port_input = QLineEdit(self._modbus_port)
        self.modbus_port_input.setMaximumWidth(100)
        modbus_ctrl_layout.addWidget(self.modbus_port_input, 0, 1)

        modbus_ctrl_layout.addWidget(QLabel("从站地址:"), 1, 0)
        self.modbus_slave_id_input = QLineEdit(self._modbus_slave_id)
        self.modbus_slave_id_input.setMaximumWidth(100)
        modbus_ctrl_layout.addWidget(self.modbus_slave_id_input, 1, 1)

        self.modbus_start_btn = QPushButton("启动从站服务")
        set_button_role(self.modbus_start_btn, "connect")
        self.modbus_start_btn.setMinimumWidth(120)
        self.modbus_start_btn.setMinimumHeight(40)
        modbus_ctrl_layout.addWidget(self.modbus_start_btn, 0, 2)

        self.modbus_stop_btn = QPushButton("停止从站服务")
        set_button_role(self.modbus_stop_btn, "warning")
        self.modbus_stop_btn.setMinimumWidth(120)
        self.modbus_stop_btn.setMinimumHeight(40)
        self.modbus_stop_btn.setEnabled(False)
        modbus_ctrl_layout.addWidget(self.modbus_stop_btn, 0, 3)

        self.modbus_status_label = QLabel("状态: 未启动")
        modbus_ctrl_layout.addWidget(self.modbus_status_label, 2, 0, 1, 4)

        modbus_ctrl_group.setLayout(modbus_ctrl_layout)
        layout.addWidget(modbus_ctrl_group)

        # --- Real-time status panel ---
        status_panel = QFrame()
        status_panel.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        status_panel.setStyleSheet(card_style(COLORS["primary"]))
        status_panel_layout = QHBoxLayout(status_panel)
        status_panel_layout.setSpacing(15)
        status_panel_layout.setContentsMargins(12, 8, 12, 8)

        self.modbus_cycle_label = QLabel(" 周期: 0")
        self.modbus_cycle_label.setStyleSheet(_MODBUS_METRIC_STYLE)
        status_panel_layout.addWidget(self.modbus_cycle_label)

        self.modbus_duration_label = QLabel(" 耗时: 0ms")
        self.modbus_duration_label.setStyleSheet(_MODBUS_METRIC_STYLE)
        status_panel_layout.addWidget(self.modbus_duration_label)

        self.modbus_status_panel_label = QLabel(" 状态: 停止")
        self.modbus_status_panel_label.setStyleSheet(_MODBUS_METRIC_STYLE)
        status_panel_layout.addWidget(self.modbus_status_panel_label)

        status_panel_layout.addStretch()
        layout.addWidget(status_panel)

        # --- Register data table ---
        reg_group = QGroupBox("寄存器数据")
        reg_layout = QVBoxLayout()

        self.modbus_table = QTableWidget()
        self.modbus_table.setColumnCount(4)
        self.modbus_table.setHorizontalHeaderLabels(["地址", "含义", "类型", "当前值"])
        self.modbus_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch,
        )
        self.modbus_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.modbus_table.setAlternatingRowColors(True)
        reg_layout.addWidget(self.modbus_table)

        reg_group.setLayout(reg_layout)
        layout.addWidget(reg_group)