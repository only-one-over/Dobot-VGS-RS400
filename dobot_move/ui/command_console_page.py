#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""命令控制台页面 — 直接向 Runtime 发送 IPC 命令并查看响应。

提供：
- 命令选择下拉框（从 ``COMMAND_SPECS`` 自动填充）
- Payload JSON 输入框
- 发送/清空操作按钮
- 响应显示区（JSON 美化）
- 历史记录区（最近 20 条，可清空）

页面只负责构造 payload 与展示响应，实际 IPC 收发由 ``gui_app`` 通过
``RuntimeIpcRequestThread`` 异步完成，结果回调 ``set_response_text``。
"""

from __future__ import annotations

import json
import time

from ..runtime.runtime_contract import COMMAND_SPECS
from ..ui.qt_compat import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    Qt,
    QWidget,
    pyqtSignal,
)
from ..ui.ui_theme import COLORS, set_button_role

# 历史记录最大保留条数
_MAX_HISTORY = 20

# Payload 输入框占位提示
_PAYLOAD_PLACEHOLDER = (
    '{"axis": "x", "direction": 1, "step": 5.0, "motion_type": "MovL"}'
)

_SCHEMA_HINT_STYLE = (
    f"color: {COLORS['muted']}; font-size: 9pt; background: transparent; "
    "border: none; padding: 2px 4px;"
)


class CommandConsolePage(QWidget):
    """命令控制台页面。

    信号
    ----
    send_requested(str, dict):
        用户点击「发送」且 payload 解析成功后发出，参数为命令名与解析后的
        payload dict。``gui_app`` 接收后启动 ``RuntimeIpcRequestThread``。
    """

    send_requested = pyqtSignal(str, dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # 最近一次发起发送的命令名，用于历史记录归属（避免响应返回时
        # 下拉框已被切换导致命令名错位）。
        self._last_sent_command: str = ""
        self._build_ui()
        self._populate_commands()
        self._connect_signals()

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)

        # ── 卡片 1：命令选择 ──
        cmd_group = QGroupBox("命令选择")
        cmd_layout = QHBoxLayout()
        cmd_layout.setSpacing(10)
        cmd_layout.addWidget(QLabel("选择命令:"))
        self.command_combo = QComboBox()
        self.command_combo.setMinimumWidth(220)
        cmd_layout.addWidget(self.command_combo)
        self.schema_hint_label = QLabel("")
        self.schema_hint_label.setStyleSheet(_SCHEMA_HINT_STYLE)
        self.schema_hint_label.setWordWrap(True)
        cmd_layout.addWidget(self.schema_hint_label, 1)
        cmd_group.setLayout(cmd_layout)
        layout.addWidget(cmd_group)

        # ── 卡片 2：Payload 输入 ──
        payload_group = QGroupBox("Payload")
        payload_layout = QVBoxLayout()
        payload_layout.addWidget(QLabel("Payload (JSON, 可选):"))
        self.payload_edit = QTextEdit()
        self.payload_edit.setPlaceholderText(_PAYLOAD_PLACEHOLDER)
        self.payload_edit.setFixedHeight(90)  # 约 4-6 行
        payload_layout.addWidget(self.payload_edit)
        payload_group.setLayout(payload_layout)
        layout.addWidget(payload_group)

        # ── 操作区 ──
        ops_layout = QHBoxLayout()
        ops_layout.setSpacing(10)
        self.send_btn = QPushButton("发送")
        set_button_role(self.send_btn, "primary")
        self.send_btn.setMinimumWidth(120)
        self.send_btn.setMinimumHeight(38)
        ops_layout.addWidget(self.send_btn)

        self.clear_btn = QPushButton("清空")
        set_button_role(self.clear_btn, "secondary")
        self.clear_btn.setMinimumWidth(120)
        self.clear_btn.setMinimumHeight(38)
        ops_layout.addWidget(self.clear_btn)

        ops_layout.addStretch()
        layout.addLayout(ops_layout)

        # ── 卡片 3：响应显示 ──
        resp_group = QGroupBox("响应")
        resp_layout = QVBoxLayout()
        resp_layout.addWidget(QLabel("响应:"))
        self.response_edit = QTextEdit()
        self.response_edit.setReadOnly(True)
        self.response_edit.setMinimumHeight(120)
        resp_layout.addWidget(self.response_edit)
        resp_group.setLayout(resp_layout)
        layout.addWidget(resp_group)

        # ── 卡片 4：历史记录 ──
        history_group = QGroupBox("历史")
        history_layout = QVBoxLayout()
        history_header = QHBoxLayout()
        history_header.addWidget(QLabel("历史 (最近 20 条):"))
        history_header.addStretch()
        self.clear_history_btn = QPushButton("清空历史")
        set_button_role(self.clear_history_btn, "secondary")
        self.clear_history_btn.setMinimumWidth(100)
        history_header.addWidget(self.clear_history_btn)
        history_layout.addLayout(history_header)

        self.history_list = QListWidget()
        self.history_list.setAlternatingRowColors(True)
        history_layout.addWidget(self.history_list)
        history_group.setLayout(history_layout)
        layout.addWidget(history_group, 1)

    def _populate_commands(self) -> None:
        """按字母序填充命令下拉框并刷新初始 schema 提示。"""
        commands = sorted(COMMAND_SPECS.keys())
        self.command_combo.addItems(commands)
        if commands:
            self._update_schema_hint(commands[0])

    def _connect_signals(self) -> None:
        self.command_combo.currentTextChanged.connect(self._update_schema_hint)
        self.send_btn.clicked.connect(self._on_send_clicked)
        self.clear_btn.clicked.connect(self._on_clear_clicked)
        self.clear_history_btn.clicked.connect(self.history_list.clear)
        self.history_list.itemClicked.connect(self._on_history_item_clicked)

    # ------------------------------------------------------------------
    # 内部槽
    # ------------------------------------------------------------------

    def _update_schema_hint(self, command: str) -> None:
        spec = COMMAND_SPECS.get(command)
        if spec is None:
            self.schema_hint_label.setText("")
            return
        parts = []
        if spec.data_schema:
            required = ", ".join(
                f"{k}: {v.__name__}" for k, v in spec.data_schema.items()
            )
            parts.append(f"必填: {required}")
        if spec.optional_data_schema:
            optional = ", ".join(
                f"{k}: {v.__name__}" for k, v in spec.optional_data_schema.items()
            )
            parts.append(f"可选: {optional}")
        hint = " | ".join(parts) if parts else "无 payload"
        self.schema_hint_label.setText(hint)

    def _on_send_clicked(self) -> None:
        command = self.command_combo.currentText()
        # 记录意图发起的命令，供响应返回时历史归属使用。
        self._last_sent_command = command

        payload_text = self.payload_edit.toPlainText().strip()
        if payload_text:
            try:
                data = json.loads(payload_text)
            except json.JSONDecodeError as exc:
                self.set_response_text(
                    f"Payload JSON 解析失败: {exc}", ok=False
                )
                return
            if not isinstance(data, dict):
                self.set_response_text(
                    "Payload JSON 解析失败: 顶层必须是对象 {}", ok=False
                )
                return
        else:
            data = {}

        self.send_requested.emit(command, data)

    def _on_clear_clicked(self) -> None:
        self.payload_edit.clear()
        self.response_edit.clear()

    def _on_history_item_clicked(self, item: QListWidgetItem) -> None:
        text = item.data(Qt.ItemDataRole.UserRole)
        if text:
            self.response_edit.setPlainText(str(text))

    # ------------------------------------------------------------------
    # 外部回调（由 gui_app 调用）
    # ------------------------------------------------------------------

    def set_response_text(self, text: str, ok: bool) -> None:
        """更新响应区并追加一条历史记录。"""
        self.response_edit.setPlainText(text)

        command = self._last_sent_command or self.command_combo.currentText()
        status = "OK" if ok else "ERR"
        time_str = time.strftime("%H:%M:%S")
        label = f"{time_str} | {command} | {status}"

        item = QListWidgetItem(label)
        item.setData(Qt.ItemDataRole.UserRole, text)
        # 最新记录置顶
        self.history_list.insertItem(0, item)
        # 超过上限时丢弃最旧的一条（列表末尾）
        while self.history_list.count() > _MAX_HISTORY:
            self.history_list.takeItem(self.history_list.count() - 1)

    def set_runtime_online(self, online: bool) -> None:
        """根据 Runtime 在线状态启用/禁用发送按钮。"""
        self.send_btn.setEnabled(bool(online))
