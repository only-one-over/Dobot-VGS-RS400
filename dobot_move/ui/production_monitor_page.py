#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生产监控页面。

将原主窗口顶部固定区的「系统状态」卡片组与「生产上下文」面板迁移到独立的
导航页，释放主窗口顶部约 200px 高度。页面通过公开方法接收健康快照更新，
不直接读取文件，也不依赖 DobotMainWindow。
"""

from __future__ import annotations

from ..ui.gui_runtime_status import (
    RuntimeHealthSnapshot,
    runtime_state_color,
    translate_runtime_state,
)
from ..ui.qt_compat import (
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    Qt,
    QVBoxLayout,
    QWidget,
    pyqtSignal,
)
from ..ui.ui_theme import COLORS, card_style, card_value_color, metric_label_style, metric_title_style


class ProductionMonitorPage(QWidget):
    """生产监控页面：聚合系统状态卡片 + 生产上下文面板 + 实时反馈入口。

    通过 :meth:`update_status_cards` 与 :meth:`update_production_display`
    接收 :class:`RuntimeHealthSnapshot` 进行刷新，不直接读取文件。
    """

    # 点击「实时反馈」按钮时发出，由宿主窗口连接到实时反馈弹窗。
    realtime_requested = pyqtSignal()

    # 生产状态值 → 中文显示名
    _PRODUCTION_STATE_CN: dict[str, str] = {
        "manual_offline": "手动下线",
        "idle": "空闲",
        "standby": "待机",
        "running": "运行中",
        "paused": "已暂停",
        "holding_hook": "扶钩等待",
        "resetting": "复位中",
        "flow_error": "流程错误",
        "robot_error": "机器人故障",
        "camera_error": "相机故障",
    }

    # 40001 值 → 中文含义（仪表盘显示用子集）
    _PLC_CMD_CN: dict[int, str] = {
        0: "空闲/中停",
        1: "复位",
        2: "复位完成",
        3: "执行流程",
        4: "运行中",
        5: "流程完成",
        110: "流程ERR",
        111: "机器人报错",
        112: "相机报错",
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        """构建页面：QScrollArea 包裹「系统状态卡片组 + 生产上下文面板 + 实时反馈按钮」。"""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 8)
        outer.setSpacing(8)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(8)

        # 系统状态卡片组（上）
        content_layout.addWidget(self._build_status_group())
        # 实时反馈按钮（位于状态卡片组与生产上下文面板之间）
        self.realtime_btn = QPushButton("实时反馈")
        self.realtime_btn.setMinimumHeight(36)
        self.realtime_btn.clicked.connect(self.realtime_requested)
        content_layout.addWidget(self.realtime_btn)
        # 生产上下文面板（下）
        content_layout.addWidget(self._build_production_group())
        content_layout.addStretch(1)

        scroll.setWidget(content)
        outer.addWidget(scroll)

    def _create_status_card(
        self,
        title: str,
        card_color: str,
        label_name: str,
        initial_text: str,
        label_color: str = "#94a3b8",
    ) -> QFrame:
        """创建状态仪表盘卡片，返回 QFrame 卡片组件。

        与 DobotMainWindow._create_status_card 保持一致：卡片内含标题标签与
        值标签，值标签通过 ``setattr`` 注册为实例属性，供刷新方法访问。
        """
        card = QFrame()
        card.setObjectName("statusCard")
        card.setStyleSheet(card_style(card_color))
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(2)
        card_layout.setContentsMargins(10, 8, 10, 8)
        title_label = QLabel(title)
        title_label.setObjectName("cardTitle")
        title_label.setStyleSheet(metric_title_style())
        value_label = QLabel(initial_text)
        value_label.setObjectName("cardValue")
        value_label.setStyleSheet(metric_label_style(label_color))
        setattr(self, label_name, value_label)
        card_layout.addWidget(title_label)
        card_layout.addWidget(value_label)
        return card

    def _build_status_group(self) -> QGroupBox:
        """构建系统状态卡片组：4 张状态卡横向排列。"""
        group = QGroupBox("系统状态")
        group.setObjectName("topStatusPanel")
        layout = QHBoxLayout()
        layout.setSpacing(12)
        layout.setContentsMargins(12, 10, 12, 10)

        # 机器人状态卡片（蓝色）
        layout.addWidget(
            self._create_status_card(
                "机器人", COLORS["primary"], "robot_status_label", "未连接"
            )
        )
        # 相机状态卡片（青色）
        layout.addWidget(
            self._create_status_card(
                "相机", "#06b6d4", "camera_status_label", "未连接"
            )
        )
        # GPU 推理模式卡片（橙色）
        layout.addWidget(
            self._create_status_card(
                "推理", "#f59e0b", "gpu_status_label", "未检测"
            )
        )
        # Runtime 状态卡片（紫色）
        layout.addWidget(
            self._create_status_card(
                "Runtime",
                "#8b5cf6",
                "runtime_status_label",
                "未知",
                label_color="#8b5cf6",
            )
        )
        # 安全停止按钮不在此页面，保留在主窗口顶部。

        group.setLayout(layout)
        return group

    def _build_production_group(self) -> QGroupBox:
        """构建生产上下文面板：7 行键值对。"""
        group = QGroupBox("生产上下文")
        group.setObjectName("productionContextPanel")
        layout = QGridLayout()
        layout.setSpacing(6)
        layout.setContentsMargins(12, 8, 12, 8)

        # 生产状态 / 钩子类型 / 当前程序 / 当前步骤 / PLC状态 / 模式 / task_id
        value_style = f"color: {COLORS['text']}; font-size: 13pt; font-weight: 600;"
        self.prod_state_label = QLabel("空闲")
        self.prod_state_label.setStyleSheet(value_style)
        self.prod_hook_label = QLabel("---")
        self.prod_hook_label.setStyleSheet(value_style)
        self.prod_flow_label = QLabel("---")
        self.prod_flow_label.setStyleSheet(value_style)
        self.prod_step_label = QLabel("---")
        self.prod_step_label.setStyleSheet(value_style)
        self.prod_plc_label = QLabel("40001=---")
        self.prod_plc_label.setStyleSheet(value_style)
        self.prod_mode_label = QLabel("---")
        self.prod_mode_label.setStyleSheet(value_style)
        self.prod_task_id_label = QLabel("---")
        self.prod_task_id_label.setStyleSheet(
            "font-family: monospace; font-size: 10pt; color: #cbd5e1;"
        )

        rows = [
            ("生产状态:", self.prod_state_label),
            ("钩子类型:", self.prod_hook_label),
            ("当前程序:", self.prod_flow_label),
            ("当前步骤:", self.prod_step_label),
            ("PLC状态:", self.prod_plc_label),
            ("模式:", self.prod_mode_label),
            ("task_id:", self.prod_task_id_label),
        ]
        for row_idx, (title, value_label) in enumerate(rows):
            title_label = QLabel(title)
            title_label.setStyleSheet("color: #cbd5e1; font-size: 10pt;")
            value_label.setMinimumWidth(120)
            layout.addWidget(title_label, row_idx, 0)
            layout.addWidget(value_label, row_idx, 1)

        group.setLayout(layout)
        return group

    # ------------------------------------------------------------------
    # 数据刷新
    # ------------------------------------------------------------------
    def update_status_cards(self, snapshot: RuntimeHealthSnapshot) -> None:
        """根据健康快照更新 4 张状态卡片（机器人/相机/推理/位置）。

        机器人/相机状态由快照字段推断；推理模式与拍照位不在健康快照中，
        保持默认值（由宿主通过其他途径更新，此处不覆盖）。
        """
        # 机器人状态
        if not snapshot.online:
            robot_status = "Runtime 离线"
        elif snapshot.robot_connected:
            robot_status = "已连接"
        else:
            robot_status = "未连接"
        self._set_card_text(self.robot_status_label, robot_status)

        # 相机状态
        cameras = []
        if snapshot.d435i_connected:
            cameras.append("D435i")
        if snapshot.d405_connected:
            cameras.append("D405")
        if cameras:
            camera_status = "已连接(" + "+".join(cameras) + ")"
        elif not snapshot.online:
            camera_status = "Runtime 离线"
        else:
            camera_status = "未连接"
        self._set_card_text(self.camera_status_label, camera_status)

        # Runtime 状态
        runtime_cn = translate_runtime_state(snapshot.runtime_state)
        self._set_card_text(self.runtime_status_label, runtime_cn)
        # Runtime 卡片使用状态对应的颜色
        runtime_color = runtime_state_color(snapshot.runtime_state)
        self.runtime_status_label.setStyleSheet(metric_label_style(runtime_color))

    def _set_card_text(self, label: QLabel, value: str) -> None:
        """更新卡片值文本与颜色（根据状态关键字分类着色）。"""
        label.setText(value)
        color = card_value_color(value)
        label.setStyleSheet(metric_label_style(color))

    def update_production_display(self, snapshot: RuntimeHealthSnapshot) -> None:
        """根据健康快照更新生产上下文面板。

        读取快照中的 ``production`` / ``flow`` / ``modbus`` / ``last_command``
        字段，渲染生产状态、钩子类型、当前程序、当前步骤、PLC 状态、模式与
        task_id。Runtime 离线或字段缺失时回退为 ``"---"`` 占位。
        """
        production = snapshot.raw.get("production") or {}
        if not isinstance(production, dict):
            production = {}
        flow = snapshot.raw.get("flow") or {}
        if not isinstance(flow, dict):
            flow = {}
        modbus = snapshot.raw.get("modbus") or {}
        if not isinstance(modbus, dict):
            modbus = {}
        # last_command 携带 PLC 最后写入的 40001 值
        last_command = snapshot.raw.get("last_command") or {}
        if not isinstance(last_command, dict):
            last_command = {}

        # 生产状态（带颜色编码）
        state_value = str(production.get("state") or "")
        if state_value:
            state_cn = self._PRODUCTION_STATE_CN.get(state_value, state_value)
        else:
            state_cn = "---"
        self.prod_state_label.setText(state_cn)
        if state_value in {"running"}:
            color = COLORS["success"]
        elif state_value in {
            "paused",
            "holding_hook",
            "resetting",
        }:
            color = COLORS["warning"]
        elif state_value in {
            "flow_error",
            "robot_error",
            "camera_error",
            "manual_offline",
        }:
            color = COLORS["danger"]
        else:
            color = COLORS["muted"]
        self.prod_state_label.setStyleSheet(f"color: {color}; font-weight: 600;")

        # 钩子类型
        hook_name = production.get("hook_name")
        self.prod_hook_label.setText(str(hook_name) if hook_name else "---")

        # 当前程序（优先 flow 名称，回退 flow_id）
        flow_name = flow.get("main_flow_name") or production.get("flow_id")
        self.prod_flow_label.setText(str(flow_name) if flow_name else "---")

        # 当前步骤
        step_name = flow.get("module_name")
        self.prod_step_label.setText(str(step_name) if step_name else "---")

        # PLC状态（40001 当前值 + 含义）
        cmd_value = last_command.get("value")
        if cmd_value is None:
            # last_command 缺失时回退到 modbus 统计
            cmd_value = modbus.get("last_command_value")
        if cmd_value is not None:
            try:
                cmd_int = int(cmd_value)
                cmd_meaning = self._PLC_CMD_CN.get(cmd_int, str(cmd_int))
                plc_text = f"40001={cmd_int} ({cmd_meaning})"
            except (TypeError, ValueError):
                plc_text = "40001=---"
        else:
            plc_text = "40001=---"
        self.prod_plc_label.setText(plc_text)

        # 模式（manual_offline → 手动，否则自动）
        if state_value == "manual_offline":
            mode_text = "手动"
        else:
            mode_text = "自动"
        self.prod_mode_label.setText(mode_text)

        # task_id（可选，用于调试）
        task_id = production.get("task_id")
        self.prod_task_id_label.setText(str(task_id) if task_id else "---")
