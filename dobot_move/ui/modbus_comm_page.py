#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Modbus 通信页面组件。

提供独立的 QWidget，包含：
- Modbus 运行状态标签
- 寄存器数据表
- 手动写寄存器（调试）卡片

从 gui_app.py 抽取以实现模块化 UI 结构。
"""

from __future__ import annotations

from ..ui.qt_compat import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QVBoxLayout,
    QWidget,
    pyqtSignal,
)
from ..ui.ui_theme import COLORS, set_button_role

_MODBUS_METRIC_STYLE = (
    f"font-size: 13pt; font-weight: bold; color: {COLORS['accent_blue']}; "
    "background: transparent;"
)


def _get_input_value(input_widget: QWidget) -> int:
    """从输入控件获取值，兼容 QSpinBox 和 QComboBox。

    - ``QComboBox`` 返回 ``currentData()``（即 ``addItem`` 时传入的 data 值）。
    - ``QSpinBox`` 返回 ``value()``。
    """
    if isinstance(input_widget, QComboBox):
        return input_widget.currentData()
    return input_widget.value()


class ModbusCommPage(QWidget):
    """独立的 Modbus 通信页面。

    Parameters
    ----------
    parent : QWidget, optional
        父部件。
    """

    # 操作员点击手动写入按钮时发出。
    # 载荷：(寄存器地址: int, 值: int)。
    write_register_triggered = pyqtSignal(int, int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)

        # --- Modbus 运行状态标签 ---
        self.modbus_status_label = QLabel("Modbus 未运行")
        self.modbus_status_label.setStyleSheet(_MODBUS_METRIC_STYLE)
        layout.addWidget(self.modbus_status_label)

        # --- 寄存器数据表 ---
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

        # --- 手动写寄存器（调试） ---
        layout.addWidget(self._build_manual_write_card())

    def _build_manual_write_card(self) -> QGroupBox:
        """在只读表格下方构建"手动写寄存器（调试）"卡片。

        每行映射一个保持寄存器（40001-40004），提供输入控件和写入按钮。
        - 命令寄存器（40001）使用 ``QComboBox``，限制只能输入 0/1/3。
        - 其它寄存器使用 ``QSpinBox``（0-65535）。

        点击"写入"按钮会以 ``(addr, value)`` 发出
        :pyattr:`write_register_triggered` 信号；宿主窗口通过 IPC 将其
        转发给 runtime。对于命令寄存器（40001），宿主窗口会在转发时
        追加 ``simulate_external=True``，使写入走与外部 PLC 通过 502
        端口写入完全一致的命令分派链路。
        """
        group = QGroupBox("手动写寄存器（调试）")
        self._manual_write_group = group
        group_layout = QVBoxLayout()
        group_layout.setSpacing(8)

        # 警告横幅 —— 橙色以引起操作员注意。
        self._manual_write_warning = QLabel(
            "⚠️ 写入会触发 PLC 联动，请确认产线状态"
        )
        self._manual_write_warning.setStyleSheet(
            f"color: {COLORS['warning']}; font-weight: bold; "
            "background: transparent; padding: 4px 0;"
        )
        group_layout.addWidget(self._manual_write_warning)

        # 每个寄存器一行。属性既以命名字段暴露
        # （``self.reg_write_input_40001``），也聚合在
        # ``self._reg_write_widgets`` 中以便统一遍历。
        # _reg_write_widgets 是统一 3 元组列表：(addr, input_widget, btn)。
        self._reg_write_widgets: list[tuple] = []
        registers = (
            (40001, "命令/状态(0=停止/1=复位/2=复位完成/3=执行流程/4=运行中/5=延时等待/110=流程ERR/111=机器人报错/112=相机报错)", "uint16", True),
            (40002, "模式(0=自动/1=手动)", "uint16", False),
            (40003, "心跳(1/0交替)", "uint16", False),
            (40004, "提钩杆类型(0=低钩子/1=高钩子)", "uint16", False),
        )
        for addr, meaning, _reg_type, is_command in registers:
            row_layout = QHBoxLayout()
            row_layout.setSpacing(10)

            addr_label = QLabel(f"地址 {addr}")
            addr_label.setMinimumWidth(90)
            row_layout.addWidget(addr_label)

            meaning_label = QLabel(meaning)
            meaning_label.setMinimumWidth(280)
            row_layout.addWidget(meaning_label)

            if is_command:
                # 命令寄存器用 QComboBox，限制只能输入 0/1/3
                input_widget = QComboBox()
                input_widget.addItem("0=停止", 0)
                input_widget.addItem("1=复位", 1)
                input_widget.addItem("3=执行流程", 3)
                # 默认选第 0 项（0=停止）
                input_widget.setCurrentIndex(0)
            else:
                # 非命令寄存器保持 QSpinBox
                input_widget = QSpinBox()
                input_widget.setRange(0, 65535)
                input_widget.setValue(0)

            input_widget.setMinimumWidth(140)
            row_layout.addWidget(input_widget)

            btn = QPushButton("写入")
            set_button_role(btn, "warning")
            btn.setMinimumWidth(80)
            row_layout.addWidget(btn)

            row_layout.addStretch()
            group_layout.addLayout(row_layout)

            # 以命名字段暴露，便于测试 / 外部访问。
            attr_input = f"reg_write_input_{addr}"
            attr_btn = f"reg_write_btn_{addr}"
            setattr(self, attr_input, input_widget)
            setattr(self, attr_btn, btn)
            self._reg_write_widgets.append((addr, input_widget, btn))

            # 连接写入按钮 -> write_register_triggered 信号
            btn.clicked.connect(
                lambda _checked=False, a=addr, w=input_widget: self.write_register_triggered.emit(
                    a, _get_input_value(w)
                )
            )

        group.setLayout(group_layout)

        # 初始禁用；mixin 在 runtime 在线且 modbus 从站运行时开启。
        self.set_write_enabled(False, reason="等待 Runtime 在线")
        return group

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    def set_write_enabled(self, enabled: bool, reason: str = "") -> None:
        """启用 / 禁用所有手动写入按钮。

        禁用时将 ``reason`` 追加到 group-box 标题，让操作员看到写入被
        阻止的原因。按钮会被切换；输入控件保持可编辑，便于提前准备值。

        ``_reg_write_widgets`` 是统一 3 元组列表：
        ``(addr, input_widget, btn)``。
        """
        for _addr, _spin, btn in self._reg_write_widgets:
            btn.setEnabled(enabled)
        base = "手动写寄存器（调试）"
        if reason:
            self._manual_write_group.setTitle(f"{base} — {reason}")
        else:
            self._manual_write_group.setTitle(base)
