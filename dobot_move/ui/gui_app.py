#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
机器人抓取控制程序 - 图形界面版本
"""

import sys
import os
import json
import base64
import time
import logging
from ..ui.qt_compat import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QGroupBox, QGridLayout, QStatusBar,
    QMessageBox, QLineEdit, QDoubleSpinBox, QComboBox, QFileDialog,
    QTableWidget, QTableWidgetItem, QHeaderView, QFrame, QScrollArea, QStackedWidget,
    QCheckBox, QSizePolicy, QTextEdit, QTabWidget,
    Qt, QTimer, QPixmap,
)

from ..config.alarm_history import AlarmHistory
from ..config.config_manager import (
    ConfigService,
    get_grasp_flow_file,
    get_initial_point,
    get_modbus_port,
    get_modbus_slave_id,
    get_robot_ip,
    get_runtime_config,
    get_camera_model_path,
    set_camera_model_path,
    set_robot_ip,
    set_photo_position,
)
from ..ui.gui_runtime_status import (
    DEFAULT_RUNTIME_HEALTH_PATH,
    RuntimeHealthReader,
    RuntimeHealthSnapshot,
    translate_runtime_state,
    runtime_state_color,
)
from ..ui.gui_ipc_client import RuntimeIpcClient, RuntimeIpcRequestThread
from ..ui.runtime_facade import RuntimeFacade
from ..runtime.runtime_ipc import DEFAULT_IPC_TOKEN_PATH
from .mixins import (
    RobotControlMixin,
    VisionMixin,
    ModbusMixin,
    PointManagementMixin,
    GraspFlowMixin,
)
from ..ui.ui_theme import apply_theme, apply_status_visual, set_button_role, NAV_ICONS, COLORS, card_style, card_value_color, metric_label_style, metric_title_style, metric_value_style
from ..flow.flow_step_list import FlowStepList
from .production_monitor_page import ProductionMonitorPage
from .config_center_page import ConfigCenterPage
from ..ui.main_control_panel import MainControlPanel
from ..flow.flow_library import FlowLibrary
from ..ui.gui_debug_widgets import ErrorTrendPlot

logger = logging.getLogger(__name__)

try:
    from ..robot.hand_eye_calib import HandEyeCalibManager
    HANDEYE_AVAILABLE = True
except Exception:
    HANDEYE_AVAILABLE = False

_DEFAULT_GRASP_FLOW_MODULES = [
    {
        "type": "move",
        "name": "移动到初始位置",
        "params": {
            "target": "initial_position",
            "motion_type": "MovJ",
            "speed": 20
        }
    },
    {
        "type": "camera",
        "name": "识别物体并计算坐标",
        "params": {
            "camera_type": "D435i"
        }
    },
    {
        "type": "move",
        "name": "直线运动到目标",
        "params": {
            "target": "camera_detected",
            "motion_type": "MovL",
            "speed": 30,
            "point_name": "d435i"
        }
    }
]

_MODBUS_METRIC_STYLE = (
    f"font-size: 13pt; font-weight: bold; color: {COLORS['accent_blue']}; "
    "background: transparent;"
)

_CAM_COORD_STYLE = (
    f"font-family: monospace; font-size: 13pt; color: #64748b;"
)


class DobotMainWindow(RobotControlMixin, VisionMixin, ModbusMixin, PointManagementMixin, GraspFlowMixin, QMainWindow):
    """机器人控制GUI"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Dobot VGS — 工业机器人仪表盘")
        self.setGeometry(100, 100, 1200, 750)
        self.setMinimumSize(1100, 760)
        
        self.set_dark_theme()
        
        self.robot_ip = get_robot_ip()
        runtime_config = get_runtime_config()
        health_path = runtime_config.get(
            "health_path",
            str(DEFAULT_RUNTIME_HEALTH_PATH),
        )
        self._runtime_status_reader = RuntimeHealthReader(
            health_path,
            stale_after_s=3.0,
        )
        self._runtime_ipc_client = RuntimeIpcClient(
            host=runtime_config.get("ipc_host", "127.0.0.1"),
            port=runtime_config.get("ipc_port", 8765),
            stop_port=runtime_config.get("ipc_stop_port", 8766),
            timeout_s=min(
                3.0,
                float(runtime_config.get("ipc_command_timeout_s", 5.0)),
            ),
            token_path=(
                runtime_config.get("ipc_token_path")
                or DEFAULT_IPC_TOKEN_PATH
            ),
        )
        self._runtime_status = RuntimeHealthSnapshot()
        self._runtime_facade = RuntimeFacade(
            ipc_client=self._runtime_ipc_client,
            send_ipc_func=self._send_runtime_ipc,
            is_online_func=lambda: bool(self._runtime_status.online),
            send_stop_func=self._send_runtime_ipc_stop,
        )
        self._ipc_request_threads = set()
        self._ipc_pending_commands = set()
        self._alarm_history = AlarmHistory()
        # PR-C Task 6: runtime capabilities cache. Populated from the
        # ``get_status`` IPC response; empty list means "not yet fetched"
        # (treated as "all supported" to avoid false-disabling on legacy
        # Runtime builds that don't advertise capabilities).
        self._runtime_capabilities: list[str] = []
        
        self._load_grasp_flow_modules()
        
        self.is_paused = False
        self._flow_running = False
        self._flow_started_by_modbus = False
        self._active_flow_id = None
        self._active_flow_name = None
        self._active_flow_modules = []
        self._editing_point_row = -1
        self._editing_point_name = None
        
        self.init_ui()
        self._start_status_timer()
        # PR-C Task 6.2: fetch Runtime capabilities once the UI is live so
        # unsupported buttons get gated. Sent quietly so it doesn't pollute
        # the debug panel on every startup.
        self._refresh_runtime_capabilities()
        # 手眼标定值已由 ConfigCenterPage 在构建时加载，无需在此重复加载
        self.statusBar().showMessage("正在初始化状态监控...")

    def _load_grasp_flow_modules(self):
        """加载抓取流程配置文件"""
        file_path = get_grasp_flow_file()
        try:
            self.flow_library = FlowLibrary.load(
                file_path,
                default_modules=_DEFAULT_GRASP_FLOW_MODULES,
            )
        except Exception as e:
            logger.error(f"加载抓取流程失败: {e}")
            self.flow_library = FlowLibrary.from_modules(
                _DEFAULT_GRASP_FLOW_MODULES,
                file_path,
            )
        self.editing_flow_id = self.flow_library.last_edited_flow_id
        self.grasp_flow_modules = self.flow_library.get_flow(
            self.editing_flow_id
        )["modules"]

    @staticmethod
    def _wrap_in_scroll(widget):
        scroll = QScrollArea()
        scroll.setWidget(widget)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        return scroll

    def _add_nav_page(self, text, widget):
        """添加导航页：左侧图标按钮 + 右侧页面"""
        icon_char = NAV_ICONS.get(text, "●")
        btn = QPushButton(f"  {icon_char}  {text}")
        btn.setObjectName("sideNavButton")
        btn.setCheckable(True)
        idx = self.stacked_widget.count()
        btn.clicked.connect(lambda checked, i=idx: self._on_nav_clicked(i))
        # 在 stretch 之前插入按钮
        sidebar_layout = self.sidebar.layout()
        sidebar_layout.insertWidget(sidebar_layout.count() - 1, btn)
        self.stacked_widget.addWidget(widget)
        if idx == 0:
            btn.setChecked(True)
        return btn

    def _on_nav_clicked(self, index):
        self.stacked_widget.setCurrentIndex(index)
        for i, btn in enumerate(self.sidebar.findChildren(QPushButton)):
            btn.setChecked(i == index)

    def _create_status_card(self, title, card_color, label_name, initial_text, label_color="#94a3b8"):
        """创建状态仪表盘卡片，返回 QFrame 卡片组件。"""
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

    def set_dark_theme(self):
        """设置深色主题"""
        apply_theme(self)
    
    def init_ui(self):
        """初始化UI"""
        # 创建中央部件
        central_widget = QWidget()
        central_widget.setObjectName("appRoot")
        self.setCentralWidget(central_widget)
        
        # 主布局
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(12, 12, 12, 8)
        
        # ── 精简顶栏：仅标题 ──
        # 系统状态卡片组与生产上下文面板已迁移到「生产监控」导航页
        # 安全停止按钮已移除，停止功能由 Modbus 40001=0 或 IPC safe_stop 提供
        top_bar = QHBoxLayout()
        top_bar.setSpacing(12)
        top_bar.setContentsMargins(4, 4, 4, 4)
        title_label = QLabel("DOBOT VGS")
        title_label.setStyleSheet(
            "font-size: 18pt; font-weight: bold; color: #e5e7eb; padding: 8px;"
        )
        top_bar.addWidget(title_label)
        top_bar.addStretch()
        main_layout.addLayout(top_bar)

        # ── 左侧导航 + 右侧内容 ──
        content_layout = QHBoxLayout()
        content_layout.setSpacing(0)
        content_layout.setContentsMargins(0, 0, 0, 0)

        self.sidebar = QWidget()
        self.sidebar.setObjectName("sideNav")
        self.sidebar.setFixedWidth(160)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setSpacing(2)
        sidebar_layout.setContentsMargins(6, 12, 6, 12)
        
        # 侧边栏标题
        nav_header = QLabel("DOBOT VGS")
        nav_header.setStyleSheet(
            f"color: {COLORS['primary']}; font-size: 11pt; font-weight: 900; "
            "letter-spacing: 1px; padding: 8px 10px 12px 10px; "
            "background: transparent; border: none;"
        )
        sidebar_layout.addWidget(nav_header)
        sidebar_layout.addStretch(0)

        self.stacked_widget = QStackedWidget()
        self.stacked_widget.setObjectName("workspaceStack")

        content_layout.addWidget(self.sidebar)
        content_layout.addWidget(self.stacked_widget, 1)
        
        # ── 生产监控页（系统状态卡片 + 生产上下文，从顶部迁移） ──
        self.production_monitor_page = ProductionMonitorPage()
        self.production_monitor_page.realtime_requested.connect(self.open_realtime_feedback)
        self._add_nav_page("生产监控", self.production_monitor_page)

        # 向后兼容：将生产监控页的标签暴露为主窗口属性，
        # 以便现有的 update_status / update_gpu_status
        # 等方法无需修改即可继续工作
        self.robot_status_label = self.production_monitor_page.robot_status_label
        self.camera_status_label = self.production_monitor_page.camera_status_label
        self.gpu_status_label = self.production_monitor_page.gpu_status_label
        self.runtime_status_label = self.production_monitor_page.runtime_status_label
        self.prod_state_label = self.production_monitor_page.prod_state_label
        self.prod_hook_label = self.production_monitor_page.prod_hook_label
        self.prod_flow_label = self.production_monitor_page.prod_flow_label
        self.prod_step_label = self.production_monitor_page.prod_step_label
        self.prod_plc_label = self.production_monitor_page.prod_plc_label
        self.prod_mode_label = self.production_monitor_page.prod_mode_label
        self.prod_task_id_label = self.production_monitor_page.prod_task_id_label
        self.realtime_btn = self.production_monitor_page.realtime_btn

        # ── 配置中心页（机器人/相机/手眼标定/Modbus/Runtime 配置） ──
        self.config_center_page = ConfigCenterPage()
        self._add_nav_page("配置中心", self.config_center_page)
        self._connect_config_center_signals()

        # 主功能选项卡
        self._add_nav_page("主功能", self._wrap_in_scroll(self._build_main_tab()))

        # 运动编辑选项卡
        self._add_nav_page("运动编辑", self._wrap_in_scroll(self._build_motion_tab()))

        # 点位管理选项卡
        self._add_nav_page("点位管理", self._wrap_in_scroll(self._build_point_tab()))

        # Modbus 通信选项卡
        self._add_nav_page("Modbus 通信", self._wrap_in_scroll(self._build_modbus_tab()))

        self._create_alarm_tab()

        # 手眼标定 Tab 已移除，相关功能迁移到「配置中心」导航页

        # ===== 相机测试选项卡 =====
        self._add_nav_page("相机测试", self._wrap_in_scroll(self._build_camera_test_tab()))
        self._create_runtime_debug_page()

        # Modbus 数据刷新定时器
        self._modbus_refresh_timer = QTimer()
        self._modbus_refresh_timer.timeout.connect(self._refresh_modbus_table)

        self.refresh_points_table()

        main_layout.addLayout(content_layout)

        # 设置「生产监控」为首页（导航页注册完成后）
        self.stacked_widget.setCurrentIndex(0)

        # 状态栏
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就绪")

        # Runtime 状态指示（Task 4：maintenance 显式显示）
        self.runtime_state_label = QLabel("Runtime: 未知")
        self.runtime_state_label.setStyleSheet(
            f"color: {COLORS['text']}; background-color: {COLORS['card']}; "
            f"border: 1px solid {COLORS['line']}; border-radius: 6px; "
            "padding: 2px 8px; margin: 0 4px;"
        )
        self.status_bar.addPermanentWidget(self.runtime_state_label)

        self._set_status_visual(self.robot_status_label, "未连接")
        self._set_status_visual(self.camera_status_label, "未连接")
        self._select_editing_flow(self.editing_flow_id)
        self._refresh_action_states()

    def _build_main_tab(self):
        """构建主功能页：主控制面板 + 向后兼容别名。"""
        main_tab = QWidget()
        main_tab_layout = QVBoxLayout(main_tab)
        main_tab_layout.setSpacing(10)
        main_tab_layout.setContentsMargins(10, 10, 10, 10)

        self.main_control = MainControlPanel(self.robot_ip)
        # 连接信号到现有处理方法（相机控制已迁移到配置中心，不再连接）
        self.main_control.connect_robot.connect(self.connect_robot)
        self.main_control.enable_robot.connect(self.enable_robot)
        self.main_control.disable_robot.connect(self.disable_robot)
        self.main_control.run_grasp.connect(self.run_grasping_task)
        self.main_control.move_initial.connect(self.move_to_initial_position)
        self.main_control.get_pose.connect(self.get_current_position)
        self.main_control.set_collision_level.connect(self.set_collision_level)
        self.main_control.clear_error.connect(self.on_clear_error)
        self.main_control.pause.connect(self.on_pause)
        self.main_control.resume.connect(self.on_continue)
        self.main_control.stop_current_task.connect(self._on_stop_current_task)
        self.main_control.main_flow_changed.connect(self._on_main_flow_changed)
        main_tab_layout.addWidget(self.main_control)

        # 向后兼容属性别名，供 mixins 和 _refresh_action_states 访问
        self.run_task_btn = self.main_control.run_task_btn
        self.connect_robot_btn = self.main_control.connect_robot_btn
        self.enable_robot_btn = self.main_control.enable_robot_btn
        self.disable_robot_btn = self.main_control.disable_robot_btn
        self.get_pos_btn = self.main_control.get_pos_btn
        self.move_initial_btn = self.main_control.move_initial_btn
        self.collision_combo = self.main_control.collision_combo
        self.collision_set_btn = self.main_control.collision_set_btn
        self.clear_error_btn = self.main_control.clear_error_btn
        self.pause_btn = self.main_control.pause_btn
        self.continue_btn = self.main_control.continue_btn
        return main_tab

    def _build_motion_tab(self):
        """构建运动编辑页：抓取流程编辑 + 模块拼接工具。"""
        motion_tab = QWidget()
        motion_tab_layout = QVBoxLayout(motion_tab)
        motion_tab_layout.setSpacing(10)
        motion_tab_layout.setContentsMargins(10, 10, 10, 10)
        
        # 抓取流程编辑
        grasp_flow_group = QGroupBox("抓取流程编辑")
        grasp_flow_layout = QVBoxLayout()
        grasp_flow_layout.setSpacing(10)

        flow_select_layout = QHBoxLayout()
        flow_select_layout.setSpacing(8)
        flow_select_layout.addWidget(QLabel("编辑流程:"))
        self.edit_flow_combo = QComboBox()
        self.edit_flow_combo.currentIndexChanged.connect(
            self._on_edit_flow_changed
        )
        flow_select_layout.addWidget(self.edit_flow_combo, 1)
        self.new_flow_btn = QPushButton("新建")
        set_button_role(self.new_flow_btn, "primary")
        self.new_flow_btn.clicked.connect(self.create_flow)
        # Role-flow protection is enforced at FlowLibrary layer:
        # delete_flow/rename_flow raise ValueError for role flows;
        # the mixin's try/except surfaces a QMessageBox to the user.
        flow_select_layout.addWidget(self.new_flow_btn)
        self.rename_flow_btn = QPushButton("重命名")
        set_button_role(self.rename_flow_btn, "secondary")
        self.rename_flow_btn.clicked.connect(self.rename_flow)
        flow_select_layout.addWidget(self.rename_flow_btn)
        self.duplicate_flow_btn = QPushButton("复制")
        set_button_role(self.duplicate_flow_btn, "secondary")
        self.duplicate_flow_btn.clicked.connect(self.duplicate_flow)
        flow_select_layout.addWidget(self.duplicate_flow_btn)
        self.delete_flow_btn = QPushButton("删除")
        set_button_role(self.delete_flow_btn, "danger")
        self.delete_flow_btn.clicked.connect(self.delete_flow)
        flow_select_layout.addWidget(self.delete_flow_btn)
        grasp_flow_layout.addLayout(flow_select_layout)
        
        # 抓取流程显示
        self.flow_step_list = FlowStepList()
        self.flow_step_list.step_clicked.connect(self.on_step_clicked)
        self.flow_step_list.step_reordered.connect(self._on_steps_reordered)
        grasp_flow_layout.addWidget(self.flow_step_list)
        
        # 当前选中的步骤索引
        self.selected_step_index = -1

        module_group = QGroupBox("模块拼接工具")
        module_layout = QVBoxLayout()
        module_layout.setSpacing(10)
        
        # 模块选择
        module_select_layout = QHBoxLayout()
        module_select_layout.setSpacing(10)
        module_select_layout.addWidget(QLabel("选择模块:"))
        self.module_combo = QComboBox()
        self.module_combo.addItems(["相机识别", "直线运动", "圆弧运动", "相对移动", "连续相对路径", "关节旋转", "视觉伺服", "延时"])
        self.module_combo.currentIndexChanged.connect(self.on_module_combo_changed)
        module_select_layout.addWidget(self.module_combo)
        
        self.add_module_btn = QPushButton("添加模块")
        set_button_role(self.add_module_btn, "primary")
        self.add_module_btn.setDefault(True)
        self.add_module_btn.clicked.connect(self.add_module)
        module_select_layout.addWidget(self.add_module_btn)
        
        self.remove_module_btn = QPushButton("移除模块")
        set_button_role(self.remove_module_btn, "danger")
        self.remove_module_btn.clicked.connect(self.remove_module)
        module_select_layout.addWidget(self.remove_module_btn)
        
        module_layout.addLayout(module_select_layout)
        
        # 参数编辑
        self.param_group = QGroupBox("参数编辑")
        self.param_layout = QGridLayout()
        self.param_layout.setSpacing(10)
        
        self.linear_params = QWidget()
        linear_layout = QVBoxLayout(self.linear_params)
        linear_layout.setSpacing(10)

        target_layout = QHBoxLayout()
        target_layout.addWidget(QLabel("目标类型:"))
        self.linear_target_combo = QComboBox()
        self.linear_target_combo.addItems(["已保存点位", "相机识别坐标", "初始位置"])
        self.linear_target_combo.setToolTip("已保存点位: 移动到已保存的点位; 相机识别坐标: 移动到相机识别结果; 初始位置: 移动到初始位置")
        target_layout.addWidget(self.linear_target_combo)
        target_layout.addStretch()
        linear_layout.addLayout(target_layout)

        self.linear_point_combo = QComboBox()
        linear_layout.addWidget(self.linear_point_combo)
        self.linear_point_preview = QLabel("")
        self.linear_point_preview.setStyleSheet("color: #64748b; font-size: 11pt;")
        linear_layout.addWidget(self.linear_point_preview)
        self.linear_point_combo.currentTextChanged.connect(self._on_linear_point_selected)

        speed_layout = QHBoxLayout()
        speed_layout.addWidget(QLabel("速度:"))
        self.linear_speed = QDoubleSpinBox()
        self.linear_speed.setRange(1, 100)
        self.linear_speed.setValue(30)
        speed_layout.addWidget(self.linear_speed)
        speed_layout.addStretch()
        linear_layout.addLayout(speed_layout)

        linear_force_layout = QHBoxLayout()
        self.linear_force_guard_enabled = QCheckBox("启用TCP力停止")
        linear_force_layout.addWidget(self.linear_force_guard_enabled)
        linear_force_layout.addWidget(QLabel("阈值(N):"))
        self.linear_force_threshold = QDoubleSpinBox()
        self.linear_force_threshold.setRange(0.1, 200.0)
        self.linear_force_threshold.setValue(5.0)
        self.linear_force_threshold.setDecimals(1)
        self.linear_force_threshold.setToolTip("当前TCP力相对运动前基线的合力超过该值时停止当前运动并进入下一步")
        linear_force_layout.addWidget(self.linear_force_threshold)
        linear_force_layout.addStretch()
        linear_layout.addLayout(linear_force_layout)

        self.linear_read_current_btn = QPushButton("读取当前位置")
        self.linear_read_current_btn.setMinimumWidth(120)
        self.linear_read_current_btn.clicked.connect(self._on_read_current_for_linear)
        linear_layout.addWidget(self.linear_read_current_btn)
        
        # 关节旋转参数
        self.joint_rotation_params = QWidget()
        joint_layout = QGridLayout(self.joint_rotation_params)
        joint_layout.setSpacing(10)
        
        self.joint_offsets = []
        for i in range(6):
            row = i // 2
            col = (i % 2) * 3
            joint_layout.addWidget(QLabel(f"关节{i+1}偏移:"), row, col * 2)
            spin = QDoubleSpinBox()
            spin.setRange(-360, 360)
            spin.setValue(0)
            self.joint_offsets.append(spin)
            joint_layout.addWidget(spin, row, col * 2 + 1)
        
        joint_layout.addWidget(QLabel("加速度:"), 3, 0)
        self.joint_accel = QDoubleSpinBox()
        self.joint_accel.setRange(1, 100)
        self.joint_accel.setValue(20)
        joint_layout.addWidget(self.joint_accel, 3, 1)
        
        joint_layout.addWidget(QLabel("速度:"), 3, 2)
        self.joint_speed = QDoubleSpinBox()
        self.joint_speed.setRange(1, 100)
        self.joint_speed.setValue(50)
        joint_layout.addWidget(self.joint_speed, 3, 3)

        self.relative_move_params = QWidget()
        rel_layout = QGridLayout(self.relative_move_params)
        rel_layout.setSpacing(10)

        rel_layout.addWidget(QLabel("坐标系"), 0, 0)
        self.rel_coord_combo = QComboBox()
        self.rel_coord_combo.addItems(["用户", "工具", "关节"])
        rel_layout.addWidget(self.rel_coord_combo, 0, 1)

        rel_layout.addWidget(QLabel("运动方式:"), 0, 2)
        self.rel_motion_combo = QComboBox()
        self.rel_motion_combo.addItems(["直线", "关节"])
        rel_layout.addWidget(self.rel_motion_combo, 0, 3)

        self.rel_offsets = []
        for i, axis in enumerate(["X", "Y", "Z", "Rx", "Ry", "Rz"]):
            row = 1 + i // 3
            col = (i % 3) * 2
            rel_layout.addWidget(QLabel(f"{axis}偏移:"), row, col)
            spin = QDoubleSpinBox()
            spin.setRange(-1000, 1000)
            spin.setDecimals(2)
            spin.setValue(0)
            self.rel_offsets.append(spin)
            rel_layout.addWidget(spin, row, col + 1)

        rel_layout.addWidget(QLabel("速度:"), 3, 0)
        self.rel_speed = QDoubleSpinBox()
        self.rel_speed.setRange(1, 100)
        self.rel_speed.setValue(30)
        self.rel_speed.setDecimals(0)
        rel_layout.addWidget(self.rel_speed, 3, 1)

        rel_layout.addWidget(QLabel("加速度:"), 3, 2)
        self.rel_accel = QDoubleSpinBox()
        self.rel_accel.setRange(1, 100)
        self.rel_accel.setValue(20)
        self.rel_accel.setDecimals(0)
        rel_layout.addWidget(self.rel_accel, 3, 3)

        rel_layout.addWidget(QLabel("CP:"), 3, 4)
        self.rel_cp = QDoubleSpinBox()
        self.rel_cp.setRange(0, 100)
        self.rel_cp.setValue(100)
        self.rel_cp.setDecimals(0)
        rel_layout.addWidget(self.rel_cp, 3, 5)

        self.rel_force_guard_enabled = QCheckBox("启用TCP力停止")
        rel_layout.addWidget(self.rel_force_guard_enabled, 4, 0, 1, 2)
        rel_layout.addWidget(QLabel("阈值(N):"), 4, 2)
        self.rel_force_threshold = QDoubleSpinBox()
        self.rel_force_threshold.setRange(0.1, 200.0)
        self.rel_force_threshold.setValue(5.0)
        self.rel_force_threshold.setDecimals(1)
        self.rel_force_threshold.setToolTip("当前TCP力相对运动前基线的合力超过该值时停止当前运动并进入下一步")
        rel_layout.addWidget(self.rel_force_threshold, 4, 3)
        
        self.arc_motion_params = QWidget()
        fa_layout = QVBoxLayout(self.arc_motion_params)
        fa_layout.setSpacing(10)

        fa_params_widget = QWidget()
        fa_params_layout = QGridLayout(fa_params_widget)
        fa_params_layout.setSpacing(10)

        fa_params_layout.addWidget(QLabel("圆心上方距离(mm):"), 0, 0)
        self.fa_center_offset_z = QDoubleSpinBox()
        self.fa_center_offset_z.setRange(1, 500)
        self.fa_center_offset_z.setValue(50)
        self.fa_center_offset_z.setDecimals(2)
        fa_params_layout.addWidget(self.fa_center_offset_z, 0, 1)

        fa_params_layout.addWidget(QLabel("圆弧角度(°):"), 0, 2)
        self.fa_sweep_angle = QDoubleSpinBox()
        self.fa_sweep_angle.setRange(1, 360)
        self.fa_sweep_angle.setValue(90)
        self.fa_sweep_angle.setDecimals(2)
        fa_params_layout.addWidget(self.fa_sweep_angle, 0, 3)

        fa_params_layout.addWidget(QLabel("方向:"), 0, 4)
        self.fa_arc_direction = QComboBox()
        self.fa_arc_direction.addItems(["逆时针", "顺时针"])
        self.fa_arc_direction.setCurrentIndex(0)
        fa_params_layout.addWidget(self.fa_arc_direction, 0, 5)

        fa_params_layout.addWidget(QLabel("路点数"), 1, 0)
        self.fa_num_waypoints = QDoubleSpinBox()
        self.fa_num_waypoints.setRange(2, 500)
        self.fa_num_waypoints.setValue(30)
        self.fa_num_waypoints.setDecimals(0)
        fa_params_layout.addWidget(self.fa_num_waypoints, 1, 1)
        fa_params_layout.itemAtPosition(1, 0).widget().hide()
        self.fa_num_waypoints.hide()

        fa_params_layout.addWidget(QLabel("速度:"), 1, 2)
        self.fa_speed = QDoubleSpinBox()
        self.fa_speed.setRange(1, 100)
        self.fa_speed.setValue(20)
        fa_params_layout.addWidget(self.fa_speed, 1, 3)

        self.fa_force_guard_enabled = QCheckBox("启用TCP力停止")
        fa_params_layout.addWidget(self.fa_force_guard_enabled, 2, 0, 1, 2)
        fa_params_layout.addWidget(QLabel("阈值(N):"), 2, 2)
        self.fa_force_threshold = QDoubleSpinBox()
        self.fa_force_threshold.setRange(0.1, 200.0)
        self.fa_force_threshold.setValue(5.0)
        self.fa_force_threshold.setDecimals(1)
        self.fa_force_threshold.setToolTip("当前TCP力相对运动前基线的合力超过该值时停止当前运动并进入下一步")
        fa_params_layout.addWidget(self.fa_force_threshold, 2, 3)

        fa_layout.addWidget(fa_params_widget)
        self.camera_params = QWidget()
        camera_param_layout = QGridLayout(self.camera_params)
        camera_param_layout.setSpacing(10)

        camera_param_layout.addWidget(QLabel("选择相机:"), 0, 0)
        self.camera_module_combo = QComboBox()
        self.camera_module_combo.addItems(["D435i", "D405"])
        self.camera_module_combo.setCurrentIndex(0)
        camera_param_layout.addWidget(self.camera_module_combo, 0, 1)

        self.delay_params = QWidget()
        delay_layout = QGridLayout(self.delay_params)
        delay_layout.addWidget(QLabel("等待方式:"), 0, 0)
        self.delay_wait_mode = QComboBox()
        self.delay_wait_mode.addItems(["固定延时", "40001放行或超时"])
        self.delay_wait_mode.setToolTip(
            "等待期间40001=5；上位机写1可提前进入下一步"
        )
        delay_layout.addWidget(self.delay_wait_mode, 0, 1)

        delay_layout.addWidget(QLabel("最长等待(秒):"), 1, 0)
        self.delay_seconds = QDoubleSpinBox()
        self.delay_seconds.setRange(0.1, 3600.0)
        self.delay_seconds.setDecimals(1)
        self.delay_seconds.setSingleStep(0.5)
        self.delay_seconds.setValue(1.0)
        self.delay_seconds.setSuffix(" s")
        delay_layout.addWidget(self.delay_seconds, 1, 1)

        delay_layout.setColumnStretch(2, 1)

        # 连续相对路径参数
        self.relative_path_params = QWidget()
        rpath_layout = QVBoxLayout(self.relative_path_params)
        rpath_layout.setSpacing(6)

        # 执行模式
        exec_mode_layout = QHBoxLayout()
        rpath_exec_mode_label = QLabel("执行模式:")
        exec_mode_layout.addWidget(rpath_exec_mode_label)
        self.rpath_exec_mode = QComboBox()
        self.rpath_exec_mode.addItems(["stop_each", "queued"])
        self.rpath_exec_mode.setToolTip("stop_each: 每段等待完成; queued: 连续下发后统一等待")
        exec_mode_layout.addWidget(self.rpath_exec_mode)
        exec_mode_layout.addStretch()
        rpath_layout.addLayout(exec_mode_layout)

        # 段表格
        self.rpath_seg_table = QTableWidget(0, 15)
        self.rpath_seg_table.setHorizontalHeaderLabels(["启用", "名称", "坐标系", "方式", "X", "Y", "Z", "Rx", "Ry", "Rz", "速度", "加速度", "CP", "段后等待", "备注"])
        rpath_header = self.rpath_seg_table.horizontalHeader()
        rpath_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)   # 启用
        rpath_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)  # 名称
        rpath_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)   # 坐标系
        rpath_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)   # 方式
        rpath_header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)   # X
        rpath_header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)   # Y
        rpath_header.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)   # Z
        rpath_header.setSectionResizeMode(7, QHeaderView.ResizeMode.Fixed)   # Rx
        rpath_header.setSectionResizeMode(8, QHeaderView.ResizeMode.Fixed)   # Ry
        rpath_header.setSectionResizeMode(9, QHeaderView.ResizeMode.Fixed)   # Rz
        rpath_header.setSectionResizeMode(10, QHeaderView.ResizeMode.Fixed)  # 速度
        rpath_header.setSectionResizeMode(11, QHeaderView.ResizeMode.Fixed)  # 加速度
        rpath_header.setSectionResizeMode(12, QHeaderView.ResizeMode.Fixed)  # CP
        rpath_header.setSectionResizeMode(13, QHeaderView.ResizeMode.Fixed)  # 段后等待
        rpath_header.setSectionResizeMode(14, QHeaderView.ResizeMode.Stretch)  # 备注
        self.rpath_seg_table.setColumnWidth(0, 60)   # 启用
        self.rpath_seg_table.setColumnWidth(2, 80)   # 坐标系
        self.rpath_seg_table.setColumnWidth(3, 80)   # 方式
        self.rpath_seg_table.setColumnWidth(4, 80)   # X
        self.rpath_seg_table.setColumnWidth(5, 80)   # Y
        self.rpath_seg_table.setColumnWidth(6, 80)   # Z
        self.rpath_seg_table.setColumnWidth(7, 80)   # Rx
        self.rpath_seg_table.setColumnWidth(8, 80)   # Ry
        self.rpath_seg_table.setColumnWidth(9, 80)   # Rz
        self.rpath_seg_table.setColumnWidth(10, 80)  # 速度
        self.rpath_seg_table.setColumnWidth(11, 80)  # 加速度
        self.rpath_seg_table.setColumnWidth(12, 60)  # CP
        self.rpath_seg_table.setColumnWidth(13, 80)  # 段后等待
        self.rpath_seg_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        rpath_layout.addWidget(self.rpath_seg_table)

        # 段操作按钮行
        seg_btn_layout = QHBoxLayout()
        btn_add_seg = QPushButton("添加段")
        btn_add_seg.clicked.connect(lambda: self._add_path_template(self.rpath_seg_table, "empty"))
        seg_btn_layout.addWidget(btn_add_seg)

        btn_del_seg = QPushButton("删除段")
        btn_del_seg.clicked.connect(lambda: self._remove_path_segment(self.rpath_seg_table))
        seg_btn_layout.addWidget(btn_del_seg)

        btn_up_seg = QPushButton("上移")
        btn_up_seg.clicked.connect(lambda: self._move_path_segment(self.rpath_seg_table, -1))
        seg_btn_layout.addWidget(btn_up_seg)

        btn_down_seg = QPushButton("下移")
        btn_down_seg.clicked.connect(lambda: self._move_path_segment(self.rpath_seg_table, 1))
        seg_btn_layout.addWidget(btn_down_seg)

        btn_copy_seg = QPushButton("复制段")
        btn_copy_seg.clicked.connect(lambda: self._copy_path_segment(self.rpath_seg_table))
        seg_btn_layout.addWidget(btn_copy_seg)

        btn_apply_global = QPushButton("应用全局")
        btn_apply_global.clicked.connect(lambda: self._apply_global_to_segments(self.rpath_seg_table))
        seg_btn_layout.addWidget(btn_apply_global)

        btn_zero_sel = QPushButton("清零选中")
        btn_zero_sel.clicked.connect(lambda: self._zero_selected_segments(self.rpath_seg_table))
        seg_btn_layout.addWidget(btn_zero_sel)

        seg_btn_layout.addStretch()
        rpath_layout.addLayout(seg_btn_layout)

        # 通用参数行
        common_layout = QGridLayout()
        common_layout.setSpacing(10)

        common_layout.addWidget(QLabel("坐标系:"), 0, 0)
        self.rpath_coord_combo = QComboBox()
        self.rpath_coord_combo.addItems(["用户", "工具", "关节"])
        common_layout.addWidget(self.rpath_coord_combo, 0, 1)

        common_layout.addWidget(QLabel("运动方式:"), 0, 2)
        self.rpath_motion_combo = QComboBox()
        self.rpath_motion_combo.addItems(["直线", "关节"])
        common_layout.addWidget(self.rpath_motion_combo, 0, 3)

        common_layout.addWidget(QLabel("速度:"), 0, 4)
        self.rpath_speed = QDoubleSpinBox()
        self.rpath_speed.setRange(1, 100)
        self.rpath_speed.setValue(30)
        self.rpath_speed.setDecimals(0)
        common_layout.addWidget(self.rpath_speed, 0, 5)

        common_layout.addWidget(QLabel("加速度:"), 1, 0)
        self.rpath_accel = QDoubleSpinBox()
        self.rpath_accel.setRange(1, 100)
        self.rpath_accel.setValue(30)
        self.rpath_accel.setDecimals(0)
        common_layout.addWidget(self.rpath_accel, 1, 1)

        common_layout.addWidget(QLabel("CP:"), 1, 2)
        self.rpath_cp = QDoubleSpinBox()
        self.rpath_cp.setRange(0, 100)
        self.rpath_cp.setValue(0)
        self.rpath_cp.setDecimals(0)
        common_layout.addWidget(self.rpath_cp, 1, 3)

        self.rpath_force_guard_enabled = QCheckBox("启用TCP力停止")
        common_layout.addWidget(self.rpath_force_guard_enabled, 2, 0, 1, 2)
        common_layout.addWidget(QLabel("阈值(N):"), 2, 2)
        self.rpath_force_threshold = QDoubleSpinBox()
        self.rpath_force_threshold.setRange(0.1, 200.0)
        self.rpath_force_threshold.setValue(5.0)
        self.rpath_force_threshold.setDecimals(1)
        self.rpath_force_threshold.setToolTip("当前TCP力相对运动前基线的合力超过该值时停止当前运动并进入下一步")
        common_layout.addWidget(self.rpath_force_threshold, 2, 3)

        rpath_layout.addLayout(common_layout)

        # 默认显示直线运动参数
        self.param_layout.addWidget(self.linear_params, 0, 0)
        
        self.param_group.setLayout(self.param_layout)
        module_layout.addWidget(self.param_group)
        
        # 模块参数更新按钮
        self.update_param_btn = QPushButton("更新参数")
        set_button_role(self.update_param_btn, "secondary")
        self.update_param_btn.setDefault(True)
        self.update_param_btn.clicked.connect(self.update_module_params)
        module_layout.addWidget(self.update_param_btn)
        
        module_group.setLayout(module_layout)
        grasp_flow_layout.addWidget(module_group)
        
        # 抓取流程操作
        flow_ops_layout = QHBoxLayout()
        flow_ops_layout.setSpacing(10)
        
        self.view_flow_btn = QPushButton("查看当前流程")
        self.view_flow_btn.setMinimumWidth(120)
        set_button_role(self.view_flow_btn, "secondary")
        self.view_flow_btn.clicked.connect(self.view_current_grasp_flow)
        flow_ops_layout.addWidget(self.view_flow_btn)
        
        self.save_flow_btn = QPushButton("保存流程")
        set_button_role(self.save_flow_btn, "secondary")
        self.save_flow_btn.clicked.connect(self.save_grasp_flow)
        flow_ops_layout.addWidget(self.save_flow_btn)

        self.publish_flow_btn = QPushButton("发布到 Runtime")
        set_button_role(self.publish_flow_btn, "primary")
        self.publish_flow_btn.clicked.connect(self._publish_runtime_config)
        flow_ops_layout.addWidget(self.publish_flow_btn)
        
        self.load_flow_btn = QPushButton("加载流程")
        set_button_role(self.load_flow_btn, "secondary")
        self.load_flow_btn.clicked.connect(self.load_grasp_flow)
        flow_ops_layout.addWidget(self.load_flow_btn)
        
        self.run_flow_btn = QPushButton("执行流程")
        set_button_role(self.run_flow_btn, "primary")
        self.run_flow_btn.setDefault(True)
        self.run_flow_btn.clicked.connect(
            lambda: self.run_grasp_flow(flow_id=self.editing_flow_id)
        )
        flow_ops_layout.addWidget(self.run_flow_btn)
        
        grasp_flow_layout.addLayout(flow_ops_layout)

        editor_pause_layout = QHBoxLayout()
        self.editor_pause_btn = QPushButton("暂停")
        set_button_role(self.editor_pause_btn, "warning")
        self.editor_pause_btn.clicked.connect(self.on_pause)
        self.editor_pause_btn.setEnabled(False)
        editor_pause_layout.addWidget(self.editor_pause_btn)
        self.editor_continue_btn = QPushButton("继续")
        set_button_role(self.editor_continue_btn, "connect")
        self.editor_continue_btn.clicked.connect(self.on_continue)
        self.editor_continue_btn.setEnabled(False)
        editor_pause_layout.addWidget(self.editor_continue_btn)
        grasp_flow_layout.addLayout(editor_pause_layout)

        grasp_flow_group.setLayout(grasp_flow_layout)
        motion_tab_layout.addWidget(grasp_flow_group)
        return motion_tab

    def _build_point_tab(self):
        """构建点位管理页：点位表格 + 编辑控件。"""
        point_mgmt_group = QGroupBox("点位管理")
        point_mgmt_layout = QVBoxLayout()
        point_mgmt_layout.setSpacing(10)

        self.points_table = QTableWidget()
        self.points_table.setColumnCount(9)
        self.points_table.setHorizontalHeaderLabels(["名称", "X", "Y", "Z", "Rx", "Ry", "Rz", "相对", "基准点位"])
        header = self.points_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.points_table.setColumnWidth(0, 100)
        for col in range(1, 7):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.Fixed)
        self.points_table.setColumnWidth(7, 60)
        header.setSectionResizeMode(8, QHeaderView.ResizeMode.Fixed)
        self.points_table.setColumnWidth(8, 120)
        self.points_table.setAlternatingRowColors(True)
        self.points_table.verticalHeader().setVisible(False)
        self.points_table.verticalHeader().setDefaultSectionSize(56)
        self.points_table.setMinimumHeight(300)
        self.points_table.itemSelectionChanged.connect(self._on_point_selection_changed)
        point_mgmt_layout.addWidget(self.points_table)

        point_btn_layout = QHBoxLayout()
        point_btn_layout.setSpacing(10)

        self.add_point_btn = QPushButton("添加点位")
        set_button_role(self.add_point_btn, "primary")
        self.add_point_btn.clicked.connect(self._on_add_point)
        point_btn_layout.addWidget(self.add_point_btn)

        self.delete_point_btn = QPushButton("删除点位")
        set_button_role(self.delete_point_btn, "danger")
        self.delete_point_btn.clicked.connect(self._on_delete_point)
        point_btn_layout.addWidget(self.delete_point_btn)

        self.edit_point_btn = QPushButton("修改点位")
        set_button_role(self.edit_point_btn, "secondary")
        self.edit_point_btn.clicked.connect(self._on_edit_point)
        point_btn_layout.addWidget(self.edit_point_btn)

        self.save_point_btn = QPushButton("保存修改")
        set_button_role(self.save_point_btn, "secondary")
        self.save_point_btn.clicked.connect(self._on_save_point_edit)
        self.save_point_btn.setEnabled(False)
        point_btn_layout.addWidget(self.save_point_btn)

        self.cancel_point_btn = QPushButton("取消修改")
        set_button_role(self.cancel_point_btn, "secondary")
        self.cancel_point_btn.clicked.connect(self._on_cancel_point_edit)
        self.cancel_point_btn.setEnabled(False)
        point_btn_layout.addWidget(self.cancel_point_btn)

        self.read_point_btn = QPushButton("读取当前点位")
        set_button_role(self.read_point_btn, "secondary")
        self.read_point_btn.setMinimumWidth(120)
        self.read_point_btn.clicked.connect(self._on_read_current_for_selected_point)
        self.read_point_btn.setEnabled(False)
        point_btn_layout.addWidget(self.read_point_btn)

        self.refresh_points_btn = QPushButton("刷新点位")
        set_button_role(self.refresh_points_btn, "secondary")
        self.refresh_points_btn.clicked.connect(self.refresh_points_table)
        point_btn_layout.addWidget(self.refresh_points_btn)

        # 运动到此点：通过 Runtime IPC 调用 move_to_point（Task 5）
        self.move_to_point_btn = QPushButton("运动到此点")
        set_button_role(self.move_to_point_btn, "secondary")
        self.move_to_point_btn.clicked.connect(self._on_move_to_point)
        self.move_to_point_btn.setEnabled(False)
        point_btn_layout.addWidget(self.move_to_point_btn)

        point_btn_layout.addStretch()
        point_mgmt_layout.addLayout(point_btn_layout)

        point_mgmt_group.setLayout(point_mgmt_layout)

        point_tab = QWidget()
        point_tab_layout = QVBoxLayout(point_tab)
        point_tab_layout.setSpacing(10)
        point_tab_layout.setContentsMargins(10, 10, 10, 10)
        point_tab_layout.addWidget(point_mgmt_group)
        return point_tab

    def _build_modbus_tab(self):
        """构建 Modbus 通信页：从站控制 + 寄存器表格。"""
        modbus_tab = QWidget()
        modbus_layout = QVBoxLayout(modbus_tab)
        modbus_layout.setSpacing(10)
        modbus_layout.setContentsMargins(10, 10, 10, 10)

        # Modbus 控制区
        modbus_ctrl_group = QGroupBox("本机 Modbus 从站服务（外部 PC=主站）")
        modbus_ctrl_layout = QGridLayout()
        modbus_ctrl_layout.setSpacing(10)

        modbus_ctrl_layout.addWidget(QLabel("监听端口:"), 0, 0)
        self.modbus_port_input = QLineEdit(str(get_modbus_port()))
        self.modbus_port_input.setMaximumWidth(100)
        self.modbus_port_input.editingFinished.connect(lambda: ConfigService.instance().set('modbus_port', int(self.modbus_port_input.text().strip() or 502)))
        modbus_ctrl_layout.addWidget(self.modbus_port_input, 0, 1)

        modbus_ctrl_layout.addWidget(QLabel("从站地址:"), 1, 0)
        self.modbus_slave_id_input = QLineEdit(str(get_modbus_slave_id()))
        self.modbus_slave_id_input.setMaximumWidth(100)
        self.modbus_slave_id_input.editingFinished.connect(lambda: ConfigService.instance().set('modbus_slave_id', int(self.modbus_slave_id_input.text().strip() or 5)))
        modbus_ctrl_layout.addWidget(self.modbus_slave_id_input, 1, 1)

        self.modbus_start_btn = QPushButton("启动从站服务")
        set_button_role(self.modbus_start_btn, "connect")
        self.modbus_start_btn.setMinimumWidth(120)
        self.modbus_start_btn.setMinimumHeight(40)
        self.modbus_start_btn.clicked.connect(self.start_modbus_server)
        modbus_ctrl_layout.addWidget(self.modbus_start_btn, 0, 2)

        self.modbus_stop_btn = QPushButton("停止从站服务")
        set_button_role(self.modbus_stop_btn, "warning")
        self.modbus_stop_btn.setMinimumWidth(120)
        self.modbus_stop_btn.setMinimumHeight(40)
        self.modbus_stop_btn.clicked.connect(self.stop_modbus_server)
        self.modbus_stop_btn.setEnabled(False)
        modbus_ctrl_layout.addWidget(self.modbus_stop_btn, 0, 3)

        self.modbus_status_label = QLabel("状态: 未启动")
        modbus_ctrl_layout.addWidget(self.modbus_status_label, 2, 0, 1, 4)

        modbus_ctrl_group.setLayout(modbus_ctrl_layout)
        modbus_layout.addWidget(modbus_ctrl_group)

        # 实时通信状态面板
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
        modbus_layout.addWidget(status_panel)

        # 寄存器数据表格
        reg_group = QGroupBox("寄存器数据")
        reg_layout = QVBoxLayout()
        
        self.modbus_table = QTableWidget()
        self.modbus_table.setColumnCount(4)
        self.modbus_table.setHorizontalHeaderLabels(["地址", "含义", "类型", "当前值"])
        self.modbus_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.modbus_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.modbus_table.setAlternatingRowColors(True)
        reg_layout.addWidget(self.modbus_table)
        
        reg_group.setLayout(reg_layout)
        modbus_layout.addWidget(reg_group)
        return modbus_tab

    def _build_camera_test_tab(self):
        """构建相机测试页：画面显示 + 坐标信息。"""
        camera_test_tab = QWidget()
        camera_test_layout = QVBoxLayout(camera_test_tab)

        # 顶部控制栏
        cam_test_ctrl = QHBoxLayout()
        cam_test_ctrl.addWidget(QLabel("选择相机:"))
        self.cam_test_combo = QComboBox()
        self.cam_test_combo.addItems(["D435i", "D405"])
        cam_test_ctrl.addWidget(self.cam_test_combo)
        self.cam_test_start_btn = QPushButton("开始测试")
        set_button_role(self.cam_test_start_btn, "connect")
        self.cam_test_start_btn.clicked.connect(self._start_camera_test)
        cam_test_ctrl.addWidget(self.cam_test_start_btn)
        self.cam_test_stop_btn = QPushButton("停止测试")
        set_button_role(self.cam_test_stop_btn, "warning")
        self.cam_test_stop_btn.clicked.connect(self._stop_camera_test)
        self.cam_test_stop_btn.setEnabled(False)
        cam_test_ctrl.addWidget(self.cam_test_stop_btn)
        self.cam_self_test_btn = QPushButton("相机自检")
        set_button_role(self.cam_self_test_btn, "secondary")
        self.cam_self_test_btn.clicked.connect(self._run_camera_self_test)
        cam_test_ctrl.addWidget(self.cam_self_test_btn)
        cam_test_ctrl.addStretch()
        camera_test_layout.addLayout(cam_test_ctrl)

        # 主内容区域
        cam_test_content = QHBoxLayout()

        # 左侧: 画面显示
        self.cam_test_image_label = QLabel("等待测试...")
        self.cam_test_image_label.setMinimumSize(480, 360)
        self.cam_test_image_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.cam_test_image_label.setStyleSheet(f"background-color: {COLORS['bg']}; color: #64748b; font-size: 16pt; border: 1px solid {COLORS['line']}; border-radius: 8px;")
        self.cam_test_image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cam_test_content.addWidget(self.cam_test_image_label)

        # 右侧: 坐标显示
        coord_group = QGroupBox("坐标信息")
        coord_layout = QVBoxLayout(coord_group)

        self.cam_test_status_label = QLabel("状态: 未开始")
        self.cam_test_status_label.setStyleSheet(f"font-weight: bold; font-size: 14pt; color: {COLORS['accent_blue']};")
        coord_layout.addWidget(self.cam_test_status_label)

        coord_layout.addWidget(QLabel("相机坐标 (mm):"))
        self.cam_test_cam_coords = QLabel("X: ---  Y: ---  Z: ---")
        self.cam_test_cam_coords.setStyleSheet(_CAM_COORD_STYLE)
        coord_layout.addWidget(self.cam_test_cam_coords)

        coord_layout.addWidget(QLabel("末端坐标 (mm):"))
        self.cam_test_end_coords = QLabel("X: ---  Y: ---  Z: ---")
        self.cam_test_end_coords.setStyleSheet(_CAM_COORD_STYLE)
        coord_layout.addWidget(self.cam_test_end_coords)

        coord_layout.addWidget(QLabel("基座坐标 (mm):"))
        self.cam_test_base_coords = QLabel("X: ---  Y: ---  Z: ---")
        self.cam_test_base_coords.setStyleSheet(_CAM_COORD_STYLE)
        coord_layout.addWidget(self.cam_test_base_coords)

        coord_layout.addWidget(QLabel("置信度"))
        self.cam_test_confidence = QLabel("---")
        self.cam_test_confidence.setStyleSheet(_CAM_COORD_STYLE)
        coord_layout.addWidget(self.cam_test_confidence)

        # D405 专用
        self.cam_test_d405_group = QGroupBox("D405 端点信息")
        d405_layout = QVBoxLayout(self.cam_test_d405_group)
        d405_layout.addWidget(QLabel("抓取坐标 (mm):"))
        self.cam_test_handle_coords = QLabel("X: ---  Y: ---  Z: ---")
        self.cam_test_handle_coords.setStyleSheet(_CAM_COORD_STYLE)
        d405_layout.addWidget(self.cam_test_handle_coords)
        d405_layout.addWidget(QLabel("钩尖坐标 (mm):"))
        self.cam_test_tip_coords = QLabel("X: ---  Y: ---  Z: ---")
        self.cam_test_tip_coords.setStyleSheet(_CAM_COORD_STYLE)
        d405_layout.addWidget(self.cam_test_tip_coords)
        d405_layout.addWidget(QLabel("铁钩长度:"))
        self.cam_test_hook_length = QLabel("--- mm")
        self.cam_test_hook_length.setStyleSheet(_CAM_COORD_STYLE)
        d405_layout.addWidget(self.cam_test_hook_length)
        self.cam_test_d405_group.setVisible(False)
        coord_layout.addWidget(self.cam_test_d405_group)

        coord_layout.addStretch()
        cam_test_content.addWidget(coord_group)
        camera_test_layout.addLayout(cam_test_content)



        self.cam_test_worker = None
        return camera_test_tab


    def _set_status_visual(self, label, value):
        apply_status_visual(label, value)

    def _refresh_action_states(self):
        for attr in (
            "enable_robot_btn", "disable_robot_btn", "get_pos_btn",
            "move_initial_btn", "collision_set_btn", "clear_error_btn", "run_flow_btn",
            "run_task_btn", "connect_robot_btn", "pause_btn", "continue_btn",
            "editor_pause_btn", "editor_continue_btn",
            "realtime_btn", "read_point_btn", "linear_read_current_btn",
            "cam_test_start_btn", "cam_test_stop_btn",
        ):
            if hasattr(self, attr):
                getattr(self, attr).setEnabled(False)
        if hasattr(self.main_control, "main_flow_combo"):
            self.main_control.main_flow_combo.setEnabled(True)

        for attr in (
            "edit_flow_combo",
            "new_flow_btn",
            "rename_flow_btn",
            "duplicate_flow_btn",
            "delete_flow_btn",
        ):
            if hasattr(self, attr):
                getattr(self, attr).setEnabled(True)
        if hasattr(self, "collision_combo"):
            self.collision_combo.setEnabled(False)
        # PR-C Task 6.4: gray out buttons whose command isn't advertised
        # by the Runtime. ``_apply_capability_gating`` is a no-op when
        # capabilities haven't been fetched yet (treated as "all supported").
        self._apply_capability_gating()

    # -- PR-C Task 6: capability-based button gating ----------------------

    # Mapping of GUI button attribute → IPC command name. Buttons listed
    # here are force-disabled when the Runtime doesn't advertise the
    # corresponding command in ``get_status.capabilities``.
    _CAPABILITY_BUTTON_MAP = {
        "enable_robot_btn": "enable_robot",
        "disable_robot_btn": "disable_robot",
        "clear_error_btn": "clear_alarms",
        "connect_robot_btn": "connect_robot",
        "collision_set_btn": "set_collision_level",
        "modbus_start_btn": "start_modbus",
        "modbus_stop_btn": "stop_modbus",
        "realtime_btn": "get_vision_snapshot",
        "get_pos_btn": "get_current_pose",
        "read_point_btn": "get_point",
        "move_initial_btn": "move_to_point",
        "run_flow_btn": "start_debug_flow",
        "run_task_btn": "start_production_flow",
        "pause_btn": "pause_debug_flow",
        "continue_btn": "resume_debug_flow",
    }

    def _is_capability_supported(self, command_name: str) -> bool:
        """Return whether the Runtime advertises ``command_name``.

        When capabilities haven't been fetched yet (empty list, e.g. before
        the first ``get_status`` round-trip completes, or when connected to
        a legacy Runtime that doesn't include the ``capabilities`` field),
        all commands are treated as supported to avoid spuriously disabling
        working buttons.
        """
        if not self._runtime_capabilities:
            return True
        return command_name in self._runtime_capabilities

    def _apply_capability_gating(self):
        """Disable buttons whose command isn't in Runtime capabilities."""
        for btn_attr, command in self._CAPABILITY_BUTTON_MAP.items():
            btn = getattr(self, btn_attr, None)
            if btn is None:
                continue
            if not self._is_capability_supported(command):
                btn.setEnabled(False)
                btn.setToolTip(f"Runtime 版本不支持: {command}")
            else:
                # Clear the tooltip; the regular enable/disable logic in
                # ``_refresh_action_states`` decides the actual state.
                btn.setToolTip("")

    def _cache_runtime_capabilities(self, data: dict):
        """Cache ``capabilities`` from a ``get_status`` IPC response."""
        capabilities = data.get("capabilities") or []
        if isinstance(capabilities, list):
            self._runtime_capabilities = [str(c) for c in capabilities]
            self._apply_capability_gating()

    def _refresh_runtime_capabilities(self):
        """Fetch ``get_status`` via IPC and cache ``capabilities``.

        Called once on startup. Subsequent refreshes happen whenever the
        operator clicks the ``刷新状态`` (get_status) button in the Runtime
        debug page — the response is routed through
        :meth:`_cache_runtime_capabilities` by the ``on_success`` hook.
        """
        self._send_runtime_ipc(
            "get_status",
            on_success=self._cache_runtime_capabilities,
            quiet=True,
        )

    def _create_runtime_debug_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)

        # Task 11: Split the debug page into 3 inner tabs.
        # Widget construction is unchanged; only the layout container changes.
        tabs = QTabWidget()
        tab_status = QWidget()
        tab_status_layout = QVBoxLayout(tab_status)
        tab_status_layout.setSpacing(10)
        tab_status_layout.setContentsMargins(0, 0, 0, 0)
        tab_flow = QWidget()
        tab_flow_layout = QVBoxLayout(tab_flow)
        tab_flow_layout.setSpacing(10)
        tab_flow_layout.setContentsMargins(0, 0, 0, 0)
        tab_vision = QWidget()
        tab_vision_layout = QVBoxLayout(tab_vision)
        tab_vision_layout.setSpacing(10)
        tab_vision_layout.setContentsMargins(0, 0, 0, 0)

        runtime_group = QGroupBox("Runtime 维护控制")
        runtime_layout = QHBoxLayout(runtime_group)
        self.debug_runtime_state = QLabel("Runtime: 未连接")
        runtime_layout.addWidget(self.debug_runtime_state)
        for text, command in (
            ("进入维护", "enter_maintenance"),
            ("退出维护", "exit_maintenance"),
            ("刷新状态", "get_status"),
            ("发布状态", "get_publication_status"),
        ):
            button = QPushButton(text)
            set_button_role(
                button,
                {"enter_maintenance": "warning"}.get(command, "secondary"),
            )
            # PR-C Task 6: ``get_status`` also refreshes the cached
            # capabilities so capability-gated buttons update accordingly.
            if command == "get_status":
                button.clicked.connect(
                    lambda _checked=False: self._send_runtime_ipc(
                        "get_status",
                        on_success=self._cache_runtime_capabilities,
                    )
                )
            else:
                button.clicked.connect(
                    lambda _checked=False, cmd=command: self._send_runtime_ipc(cmd)
                )
            runtime_layout.addWidget(button)
        # 重载配置按钮（成功后在状态栏提示）
        self.debug_reload_config_btn = QPushButton("重载配置")
        set_button_role(self.debug_reload_config_btn, "secondary")
        self.debug_reload_config_btn.clicked.connect(self._on_reload_config)
        runtime_layout.addWidget(self.debug_reload_config_btn)
        runtime_layout.addStretch()
        # Task 4: Runtime 状态概览组（置于页面顶部）
        runtime_status_group = QGroupBox("Runtime 状态")
        runtime_status_layout = QGridLayout(runtime_status_group)
        runtime_status_layout.setColumnStretch(1, 1)
        # 行 0: 运行状态
        title_label = QLabel("运行状态:")
        title_label.setStyleSheet(
            "color: #cbd5e1; font-size: 10pt; font-weight: 700;"
        )
        runtime_status_layout.addWidget(title_label, 0, 0)
        self.runtime_overview_state_label = QLabel("未知")
        self.runtime_overview_state_label.setStyleSheet(metric_value_style())
        self.runtime_overview_state_label.setMinimumWidth(200)
        runtime_status_layout.addWidget(self.runtime_overview_state_label, 0, 1)
        # 行 1: 在线状态
        title_label = QLabel("在线状态:")
        title_label.setStyleSheet(
            "color: #cbd5e1; font-size: 10pt; font-weight: 700;"
        )
        runtime_status_layout.addWidget(title_label, 1, 0)
        self.runtime_overview_online_label = QLabel("离线")
        self.runtime_overview_online_label.setStyleSheet(metric_value_style())
        self.runtime_overview_online_label.setMinimumWidth(200)
        runtime_status_layout.addWidget(self.runtime_overview_online_label, 1, 1)
        # 行 2: 最后错误
        title_label = QLabel("最后错误:")
        title_label.setStyleSheet(
            "color: #cbd5e1; font-size: 10pt; font-weight: 700;"
        )
        runtime_status_layout.addWidget(title_label, 2, 0)
        self.runtime_overview_error_label = QLabel("无")
        self.runtime_overview_error_label.setStyleSheet(metric_value_style())
        self.runtime_overview_error_label.setMinimumWidth(200)
        runtime_status_layout.addWidget(self.runtime_overview_error_label, 2, 1)
        # 行 3: 当前模块
        title_label = QLabel("当前模块:")
        title_label.setStyleSheet(
            "color: #cbd5e1; font-size: 10pt; font-weight: 700;"
        )
        runtime_status_layout.addWidget(title_label, 3, 0)
        self.runtime_overview_module_label = QLabel("---")
        self.runtime_overview_module_label.setStyleSheet(metric_value_style())
        self.runtime_overview_module_label.setMinimumWidth(200)
        runtime_status_layout.addWidget(self.runtime_overview_module_label, 3, 1)
        tab_status_layout.addWidget(runtime_status_group)
        tab_status_layout.addWidget(runtime_group)

        # 任务状态轮询显示（SubTask 7.3）
        task_status_group = QGroupBox("任务状态")
        task_status_layout = QHBoxLayout(task_status_group)
        self.debug_task_status_label = QLabel("任务状态: 未知")
        self.debug_task_status_label.setStyleSheet(
            f"color: {COLORS['text']}; font-weight: 600; background: transparent; border: none;"
        )
        task_status_layout.addWidget(self.debug_task_status_label)
        task_status_layout.addStretch()
        tab_status_layout.addWidget(task_status_group)

        flow_group = QGroupBox("流程调试")
        flow_layout = QGridLayout(flow_group)
        self.debug_validate_btn = QPushButton("校验当前流程")
        set_button_role(self.debug_validate_btn, "primary")
        self.debug_validate_btn.clicked.connect(self._validate_debug_flow)
        flow_layout.addWidget(self.debug_validate_btn, 0, 0)
        self.debug_start_btn = QPushButton("运行当前流程")
        set_button_role(self.debug_start_btn, "primary")
        self.debug_start_btn.clicked.connect(self._start_debug_flow)
        flow_layout.addWidget(self.debug_start_btn, 0, 1)
        flow_layout.addWidget(QLabel("步骤序号:"), 0, 2)
        self.debug_step_input = QLineEdit("1")
        self.debug_step_input.setMaximumWidth(80)
        flow_layout.addWidget(self.debug_step_input, 0, 3)
        self.debug_step_btn = QPushButton("运行单步")
        set_button_role(self.debug_step_btn, "secondary")
        self.debug_step_btn.clicked.connect(self._run_debug_step)
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
            button.clicked.connect(
                lambda _checked=False, cmd=command: self._send_runtime_ipc(cmd)
            )
            flow_layout.addWidget(button, 1, column)
        tab_flow_layout.addWidget(flow_group)

        vision_group = QGroupBox("视觉诊断")
        vision_layout = QGridLayout(vision_group)
        self.debug_camera_combo = QComboBox()
        self.debug_camera_combo.addItems(["D405", "D435i"])
        vision_layout.addWidget(self.debug_camera_combo, 0, 0)
        snapshot_button = QPushButton("采集诊断快照")
        set_button_role(snapshot_button, "secondary")
        snapshot_button.clicked.connect(self._request_vision_snapshot)
        vision_layout.addWidget(snapshot_button, 0, 1)
        logs_button = QPushButton("读取 Runtime 日志")
        set_button_role(logs_button, "secondary")
        logs_button.clicked.connect(
            lambda: self._send_runtime_ipc(
                "get_runtime_logs",
                {"limit": 200},
                self._show_runtime_logs,
            )
        )
        vision_layout.addWidget(logs_button, 0, 2)
        self.debug_live_button = QPushButton("开始实时图")
        set_button_role(self.debug_live_button, "secondary")
        self.debug_live_button.setCheckable(True)
        self.debug_live_button.toggled.connect(self._toggle_live_vision)
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

        self.debug_output = QTextEdit()
        self.debug_output.setReadOnly(True)
        self.debug_output.setMinimumHeight(150)
        tab_vision_layout.addWidget(self.debug_output)

        # Wrap each tab in a scroll area and register on the QTabWidget.
        tab_status_layout.addStretch()
        tab_flow_layout.addStretch()
        tab_vision_layout.addStretch()
        for _tab_widget, _tab_name in (
            (tab_status, "状态概览"),
            (tab_flow, "流程调试"),
            (tab_vision, "视觉诊断"),
        ):
            _tab_scroll = QScrollArea()
            _tab_scroll.setWidget(_tab_widget)
            _tab_scroll.setWidgetResizable(True)
            tabs.addTab(_tab_scroll, _tab_name)
        layout.addWidget(tabs)

        self._add_nav_page("Runtime 调试", self._wrap_in_scroll(page))

        self._debug_telemetry_timer = QTimer(self)
        self._debug_telemetry_timer.timeout.connect(
            lambda: self._send_runtime_ipc(
                "get_visual_servo_telemetry",
                on_success=self._append_servo_telemetry,
                quiet=True,
            )
        )
        self._debug_telemetry_timer.start(1000)
        self._debug_live_timer = QTimer(self)
        self._debug_live_timer.timeout.connect(self._poll_live_vision)

        # 任务状态轮询定时器（SubTask 7.3：每 2 秒查询 get_debug_task_status）
        self._debug_task_status_timer = QTimer(self)
        self._debug_task_status_timer.timeout.connect(
            lambda: self._send_runtime_ipc(
                "get_debug_task_status",
                on_success=self._update_debug_task_status,
                quiet=True,
            )
        )
        self._debug_task_status_timer.start(2000)

    def _send_runtime_ipc(
        self,
        command,
        data=None,
        on_success=None,
        quiet=False,
    ):
        if command in self._ipc_pending_commands:
            return
        self._ipc_pending_commands.add(command)
        thread = RuntimeIpcRequestThread(
            self._runtime_ipc_client,
            command,
            data,
            self,
        )
        self._ipc_request_threads.add(thread)

        def completed(response):
            if response.get("ok"):
                payload = response.get("data") or {}
                if on_success:
                    on_success(payload)
                elif not quiet:
                    self._debug_append(
                        f"{command}: {json.dumps(payload, ensure_ascii=False)}"
                    )
            elif not quiet:
                error = response.get("error") or {}
                self._debug_append(
                    f"{command} [{error.get('code', 'ERROR')}]: "
                    f"{error.get('message', '')}"
                )

        def failed(message):
            if not quiet:
                self._debug_append(f"{command}: Runtime 离线或请求失败: {message}")

        def cleanup():
            self._ipc_pending_commands.discard(command)
            self._ipc_request_threads.discard(thread)
            thread.deleteLater()

        thread.completed.connect(completed)
        thread.failed.connect(failed)
        thread.finished.connect(cleanup)
        thread.start()

    def _send_runtime_ipc_stop(
        self,
        command,
        data=None,
        on_success=None,
        on_failure=None,
    ):
        """Send a command via the dedicated Stop channel (port 8766).

        Stop-channel requests are never deduplicated (a second safe_stop
        must always go through) and bypass the normal FIFO queue.
        """
        thread = RuntimeIpcRequestThread(
            self._runtime_ipc_client,
            command,
            data,
            self,
            use_stop_channel=True,
        )
        self._ipc_request_threads.add(thread)

        def completed(response):
            if response.get("ok"):
                payload = response.get("data") or {}
                if on_success:
                    on_success(payload)
            else:
                error = response.get("error") or {}
                msg = error.get("message", "") or "未知错误"
                if on_failure:
                    on_failure(msg)
                else:
                    self.statusBar().showMessage(
                        f"{command} 失败: {msg}", 5000
                    )

        def failed(message):
            if on_failure:
                on_failure(message)
            else:
                self.statusBar().showMessage(
                    f"{command}: Runtime 离线或请求失败: {message}", 5000
                )

        def cleanup():
            self._ipc_request_threads.discard(thread)
            thread.deleteLater()

        thread.completed.connect(completed)
        thread.failed.connect(failed)
        thread.finished.connect(cleanup)
        thread.start()

    def _debug_append(self, message):
        if hasattr(self, "debug_output"):
            self.debug_output.append(str(message))
        self.statusBar().showMessage(str(message), 5000)

    def _publish_runtime_config(self):
        if self.save_grasp_flow() is False:
            return
        ConfigService.instance().flush()
        self._send_runtime_ipc(
            "publish_config",
            on_success=lambda data: self._debug_append(
                f"发布成功，下一任务版本: {data.get('revision')}"
            ),
        )

    def _on_reload_config(self):
        """Reload Runtime config from disk via IPC (SubTask 7.1)."""
        self._send_runtime_ipc(
            "reload_config",
            on_success=lambda data: self.statusBar().showMessage(
                "配置已重载", 5000
            ),
        )

    def _update_debug_task_status(self, data):
        """Update the task status label from ``get_debug_task_status``."""
        if not hasattr(self, "debug_task_status_label"):
            return
        running = bool(data.get("running"))
        flow_name = data.get("flow_name") or data.get("flow_id") or "-"
        step = data.get("current_step")
        if running:
            text = f"任务状态: 运行中 ({flow_name})"
            if step is not None:
                text += f" 步骤 {step}"
        else:
            text = "任务状态: 空闲"
        self.debug_task_status_label.setText(text)

    def _validate_debug_flow(self):
        self._send_runtime_ipc(
            "validate_flow",
            {"flow_id": self.editing_flow_id},
        )

    def _start_debug_flow(self):
        self._send_runtime_ipc(
            "start_debug_flow",
            {"flow_id": self.editing_flow_id},
        )

    def _run_debug_step(self):
        try:
            step_index = int(self.debug_step_input.text().strip()) - 1
        except ValueError:
            self._debug_append("步骤序号必须是整数")
            return
        self._send_runtime_ipc(
            "run_step",
            {
                "flow_id": self.editing_flow_id,
                "step_index": step_index,
            },
        )

    def _request_vision_snapshot(self):
        self._send_runtime_ipc(
            "get_vision_snapshot",
            {
                "camera_type": self.debug_camera_combo.currentText(),
                "include_color": True,
                "include_depth": self.debug_depth_checkbox.isChecked(),
                "include_mask": True,
                "run_detection": True,
            },
            self._show_vision_snapshot,
        )

    def _show_vision_snapshot(self, data):
        encoded = data.get("color_jpeg_base64")
        if encoded:
            pixmap = QPixmap()
            pixmap.loadFromData(base64.b64decode(encoded))
            self.debug_image_label.setPixmap(
                pixmap.scaled(
                    self.debug_image_label.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        depth_encoded = data.get("depth_preview_jpeg_base64")
        if depth_encoded:
            depth_pixmap = QPixmap()
            depth_pixmap.loadFromData(base64.b64decode(depth_encoded))
            self.debug_depth_label.setPixmap(
                depth_pixmap.scaled(
                    self.debug_depth_label.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        summary = {
            "detection": data.get("detection"),
            "coordinates": data.get("coordinates"),
            "depth": data.get("depth"),
            "timings_ms": data.get("timings_ms"),
            "provider": data.get("provider"),
        }
        self._debug_append(json.dumps(summary, ensure_ascii=False, indent=2))

    def _show_runtime_logs(self, data):
        self.debug_output.setPlainText("\n".join(data.get("lines", [])))

    def _toggle_live_vision(self, active):
        self.debug_live_button.setText("停止实时图" if active else "开始实时图")
        if active:
            self._debug_live_timer.start(750)
            self._poll_live_vision()
        else:
            self._debug_live_timer.stop()

    def _poll_live_vision(self):
        if not self.debug_live_button.isChecked():
            return
        self._send_runtime_ipc(
            "get_vision_snapshot",
            {
                "camera_type": self.debug_camera_combo.currentText(),
                "include_color": True,
                "include_depth": self.debug_depth_checkbox.isChecked(),
                "include_mask": True,
                "run_detection": True,
            },
            self._show_vision_snapshot,
            quiet=True,
        )

    def _append_servo_telemetry(self, data):
        telemetry = data.get("telemetry") or {}
        if not telemetry:
            return
        row = self.debug_telemetry_table.rowCount()
        if row >= 100:
            self.debug_telemetry_table.removeRow(0)
            row -= 1
        self.debug_telemetry_table.insertRow(row)
        xyz = list(telemetry.get("error_xyz_mm") or [0.0, 0.0, 0.0])
        xyz += [0.0] * (3 - len(xyz))
        values = (
            telemetry.get("iterations", 0),
            xyz[0],
            xyz[1],
            xyz[2],
            telemetry.get("error_mm", 0.0),
            telemetry.get("loop_hz", 0.0),
            telemetry.get("capture_ms", 0.0),
            telemetry.get("inference_ms", 0.0),
            telemetry.get("depth_ms", 0.0),
            telemetry.get("servo_ms", 0.0),
            telemetry.get("control_total_ms", 0.0),
        )
        for column, value in enumerate(values):
            text = str(value) if column == 0 else f"{float(value):.2f}"
            self.debug_telemetry_table.setItem(
                row,
                column,
                QTableWidgetItem(text),
            )
        timestamp = time.monotonic()
        iteration = int(telemetry.get("iterations", 0))
        error_mm = float(telemetry.get("error_mm", 0.0))
        self.debug_error_time_plot.add_sample(timestamp, iteration, error_mm)
        self.debug_error_iteration_plot.add_sample(timestamp, iteration, error_mm)

    def _start_status_timer(self):
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._poll_status)
        self._status_timer.start(1000)
        self._poll_status()

    def _poll_status(self):
        self._runtime_status = self._runtime_status_reader.read()
        snapshot = self._runtime_status
        if hasattr(self, "debug_runtime_state"):
            publication = snapshot.raw.get("publication", {})
            revision = publication.get("next_task_revision") or publication.get(
                "revision",
                "-",
            )
            self.debug_runtime_state.setText(
                f"Runtime: {snapshot.runtime_state} | 下一任务版本: {revision}"
            )
        # Task 4: Runtime 调试页状态概览组
        if hasattr(self, "runtime_overview_state_label"):
            state_cn = translate_runtime_state(snapshot.runtime_state)
            state_color = runtime_state_color(snapshot.runtime_state)
            self.runtime_overview_state_label.setText(state_cn)
            self.runtime_overview_state_label.setStyleSheet(metric_value_style(state_color))
        if hasattr(self, "runtime_overview_online_label"):
            if snapshot.online:
                ts_str = (
                    time.strftime("%H:%M:%S", time.localtime(snapshot.timestamp))
                    if snapshot.timestamp > 0
                    else "---"
                )
                online_text = f"在线 (更新于 {ts_str})"
                online_color = "#22c55e"
            else:
                online_text = "离线"
                online_color = "#9e9e9e"
            self.runtime_overview_online_label.setText(online_text)
            self.runtime_overview_online_label.setStyleSheet(metric_value_style(online_color))
        if hasattr(self, "runtime_overview_error_label"):
            error_text = snapshot.last_error if snapshot.last_error else "无"
            self.runtime_overview_error_label.setText(error_text)
            error_color = "#ef4444" if snapshot.last_error else "#cbd5e1"
            self.runtime_overview_error_label.setStyleSheet(metric_value_style(error_color))
        if hasattr(self, "runtime_overview_module_label"):
            flow = snapshot.raw.get("flow") or {}
            if not isinstance(flow, dict):
                flow = {}
            module_name = flow.get("module_name")
            module_index = flow.get("module_index")
            if module_name or module_index is not None:
                parts = []
                if module_name:
                    parts.append(str(module_name))
                if module_index is not None:
                    parts.append(f"#{module_index}")
                module_text = " ".join(parts) if parts else "---"
            else:
                module_text = "---"
            self.runtime_overview_module_label.setText(module_text)
        # Task 4：在状态栏永久区域显式展示 Runtime 状态（含 maintenance）
        self._update_runtime_state_display(snapshot.runtime_state)
        if not snapshot.online:
            robot_status = "Runtime 离线"
        elif snapshot.robot_connected:
            robot_status = "已连接"
        else:
            robot_status = "未连接"
        self.update_status("robot", robot_status)

        cameras = []
        if snapshot.d435i_connected:
            cameras.append("D435i")
        if snapshot.d405_connected:
            cameras.append("D405")
        camera_status = (
            "已连接(" + "+".join(cameras) + ")"
            if cameras
            else ("Runtime 离线" if not snapshot.online else "未连接")
        )
        self.update_status("camera", camera_status)
        # 相机状态更新到配置中心页（相机控制已迁移至配置中心）
        self.config_center_page.update_camera_status(
            "D435i",
            "已连接" if snapshot.d435i_connected else "未连接",
        )
        self.config_center_page.update_camera_status(
            "D405",
            "已连接" if snapshot.d405_connected else "未连接",
        )
        self.production_monitor_page.update_status_cards(snapshot)
        self.production_monitor_page.update_production_display(snapshot)
        self._refresh_modbus_table()

    def _update_runtime_state_display(self, state: str) -> None:
        """Update the status-bar Runtime label and main-control indicator.

        Maintenance-related states (MAINTENANCE / MAINTENANCE_REQUESTED) use a
        yellow/orange background so the operator notices immediately. Other
        states use the neutral status-bar palette. Also forwards the raw
        state string to MainControlPanel.update_runtime_state so the dot
        indicator beside the connection card stays in sync.
        """
        state = state or "UNKNOWN"
        cn_text = translate_runtime_state(state)
        color = runtime_state_color(state)
        if not hasattr(self, "runtime_state_label"):
            return
        self.runtime_state_label.setText(f"Runtime: {cn_text}")
        if state in {"MAINTENANCE", "MAINTENANCE_REQUESTED"}:
            # bg_color == runtime_state_color(state) for maintenance states,
            # so reuse the already-computed ``color`` to avoid hardcoding hex
            # values that must stay in sync with gui_runtime_status.
            self.runtime_state_label.setStyleSheet(
                "color: #1f2937; "
                f"background-color: {color}; "
                f"border: 1px solid {color}; border-radius: 6px; "
                "padding: 2px 8px; margin: 0 4px; font-weight: 700;"
            )
        else:
            self.runtime_state_label.setStyleSheet(
                f"color: {COLORS['text']}; background-color: {COLORS['card']}; "
                f"border: 1px solid {COLORS['line']}; border-radius: 6px; "
                "padding: 2px 8px; margin: 0 4px;"
            )
        # Forward to the main control panel indicator (if present)
        main_panel = getattr(self, "main_control", None)
        if main_panel is not None and hasattr(
            main_panel, "update_runtime_state"
        ):
            main_panel.update_runtime_state(state)

    def update_gpu_status(self, provider_text=None):
        """更新GPU推理模式状态显示。"""
        if provider_text is None:
            self.gpu_status_label.setText("未检测")
            self.gpu_status_label.setStyleSheet(metric_label_style(COLORS["muted"]))
        elif "GPU" in provider_text:
            self.gpu_status_label.setText("GPU")
            self.gpu_status_label.setStyleSheet(metric_label_style(COLORS["success"]))
        else:
            self.gpu_status_label.setText("CPU")
            self.gpu_status_label.setStyleSheet(metric_label_style(COLORS["warning"]))

    def update_status(self, status_type, status_value):
        """更新状态显示。"""
        if status_type == "robot":
            self.robot_status_label.setText(f"{status_value}")
            self._set_status_visual(self.robot_status_label, status_value)
            color = card_value_color(status_value)
            self.robot_status_label.setStyleSheet(metric_label_style(color))
        elif status_type == "camera":
            self.camera_status_label.setText(f"{status_value}")
            self._set_status_visual(self.camera_status_label, status_value)
            color = card_value_color(status_value)
            self.camera_status_label.setStyleSheet(metric_label_style(color))
        elif status_type == "general":
            self.status_bar.showMessage(status_value)
        self._refresh_action_states()

    def _on_stop_current_task(self):
        """Normal motion stop via the normal IPC channel (port 8765).

        This only calls ``dashboard.Stop()`` on the Runtime side to halt
        the current motion without dropping the robot enable state.
        """
        self._send_runtime_ipc(
            "stop_current_task",
            on_success=lambda data: self.statusBar().showMessage(
                f"已停止当前任务: {data}", 5000
            ),
        )

    def _create_alarm_tab(self):
        alarm_tab = QWidget()
        alarm_layout = QVBoxLayout(alarm_tab)
        alarm_layout.setSpacing(10)
        alarm_layout.setContentsMargins(10, 10, 10, 10)

        ops_layout = QHBoxLayout()
        self.alarm_refresh_btn = QPushButton("刷新报警记录")
        set_button_role(self.alarm_refresh_btn, "secondary")
        self.alarm_refresh_btn.setMinimumWidth(120)
        self.alarm_refresh_btn.clicked.connect(self._refresh_alarm_table)
        ops_layout.addWidget(self.alarm_refresh_btn)

        self.alarm_clear_btn = QPushButton("清空本地记录")
        set_button_role(self.alarm_clear_btn, "danger")
        self.alarm_clear_btn.setMinimumWidth(120)
        self.alarm_clear_btn.clicked.connect(self._clear_alarm_history)
        self.alarm_clear_btn.setEnabled(False)
        ops_layout.addWidget(self.alarm_clear_btn)
        ops_layout.addStretch()
        alarm_layout.addLayout(ops_layout)

        self.alarm_table = QTableWidget()
        self.alarm_table.setColumnCount(7)
        self.alarm_table.setHorizontalHeaderLabels(["时间", "来源", "代码", "等级", "描述", "处理建议", "原始响应"])
        header = self.alarm_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)  # 时间
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)  # 来源
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)  # 代码
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)  # 等级
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)  # 描述
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)  # 处理建议
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)  # 原始响应
        self.alarm_table.setColumnWidth(0, 150)  # 时间
        self.alarm_table.setColumnWidth(1, 100)  # 来源
        self.alarm_table.setColumnWidth(2, 80)   # 代码
        self.alarm_table.setColumnWidth(3, 60)   # 等级
        self.alarm_table.setColumnWidth(6, 100)  # 原始响应
        self.alarm_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.alarm_table.setAlternatingRowColors(True)
        alarm_layout.addWidget(self.alarm_table)

        self._add_nav_page("报警记录", self._wrap_in_scroll(alarm_tab))
        self._refresh_alarm_table()

    def _refresh_alarm_table(self):
        try:
            with open(self._alarm_history.path, "r", encoding="utf-8") as handle:
                records = json.load(handle)
            if not isinstance(records, list):
                records = []
        except (OSError, ValueError, json.JSONDecodeError):
            records = []
        self.alarm_table.setRowCount(len(records))
        fields = ["time", "source", "code", "level", "description", "solution", "raw"]
        for row, record in enumerate(reversed(records)):
            for col, field in enumerate(fields):
                self.alarm_table.setItem(row, col, QTableWidgetItem(str(record.get(field, ""))))

    def _clear_alarm_history(self):
        success, msg = self._runtime_facade.clear_alarm_history()
        self.statusBar().showMessage(msg, 3000)
        return success
    
    # ------------------------------------------------------------------
    # 配置中心信号连接与处理
    # ------------------------------------------------------------------
    def _connect_config_center_signals(self):
        """连接配置中心页面的信号到对应处理方法。"""
        page = self.config_center_page

        # 机器人配置
        page.ip_save_requested.connect(self._on_config_save_ip)
        page.photo_position_save_requested.connect(self._on_config_save_photo_position)

        # 相机配置
        page.camera_model_select_requested.connect(self._on_config_select_camera_model)
        page.camera_connect_requested.connect(self._on_config_camera_connect)
        page.camera_disconnect_requested.connect(self._on_config_camera_disconnect)

        # 手眼标定
        page.calib_save_requested.connect(self._on_config_calib_save)
        page.calib_reset_requested.connect(self._on_config_calib_reset)
        page.calib_refresh_requested.connect(self._on_config_calib_refresh)
        page.calib_camera_changed.connect(self._on_config_calib_camera_changed)

        # 配置重载
        page.reload_config_requested.connect(self._on_config_reload)

    def _on_config_save_ip(self, ip):
        """保存机器人 IP 并提示。"""
        if not ip:
            self.statusBar().showMessage("IP 地址不能为空", 3000)
            return
        if set_robot_ip(ip):
            self.robot_ip = ip
            self.statusBar().showMessage(f"机器人 IP 已保存: {ip}", 5000)
        else:
            self.statusBar().showMessage("IP 地址格式无效", 3000)

    def _on_config_save_photo_position(self, pose):
        """保存拍照位并提示。"""
        if set_photo_position(list(pose)):
            self.statusBar().showMessage("拍照位已保存", 5000)
        else:
            self.statusBar().showMessage("拍照位保存失败", 3000)

    def _on_config_select_camera_model(self, camera_type):
        """选择并保存相机 ONNX 模型路径。"""
        if self._runtime_camera_connected(camera_type):
            QMessageBox.warning(
                self, "相机正在使用",
                f"{camera_type} 正由 Runtime 使用，请先安全停用后再更换模型",
            )
            return
        current_path = get_camera_model_path(camera_type)
        selected_path, _ = QFileDialog.getOpenFileName(
            self,
            f"选择 {camera_type} ONNX 模型",
            os.path.dirname(current_path) if current_path else "",
            "ONNX 模型 (*.onnx)",
        )
        if not selected_path:
            return
        try:
            normalized = set_camera_model_path(camera_type, selected_path)
            self.config_center_page.update_camera_status(camera_type, "未连接", normalized)
            self.statusBar().showMessage(f"{camera_type} 模型已保存: {normalized}", 5000)
        except Exception as exc:
            QMessageBox.critical(self, "模型配置失败", str(exc))

    def _on_config_camera_connect(self, camera_type):
        """连接指定相机。"""
        success, msg = self._runtime_facade.connect_camera(camera_type)
        self.statusBar().showMessage(msg, 3000)

    def _on_config_camera_disconnect(self, camera_type):
        """断开指定相机。"""
        success, msg = self._runtime_facade.disconnect_camera(camera_type)
        self.statusBar().showMessage(msg, 3000)

    def _on_config_calib_save(self, camera_type, pose_values):
        """保存手眼标定位姿。"""
        if not HANDEYE_AVAILABLE:
            QMessageBox.critical(self, "错误", "手眼标定模块不可用")
            return
        try:
            manager = HandEyeCalibManager()
            if manager.set_matrix_from_poses(camera_type, list(pose_values)):
                self.config_center_page._load_calib_from_config(camera_type)
                self.statusBar().showMessage(f"{camera_type} 标定位姿已保存", 5000)
            else:
                QMessageBox.critical(self, "错误", "保存标定位姿失败")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败: {e}")

    def _on_config_calib_reset(self, camera_type):
        """重置手眼标定为默认值。"""
        if not HANDEYE_AVAILABLE:
            return
        reply = QMessageBox.question(
            self, "确认",
            f"确定要重置 {camera_type} 的标定矩阵为默认值吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                manager = HandEyeCalibManager()
                if manager.reset_to_default(camera_type):
                    self.config_center_page._load_calib_from_config(camera_type)
                    self.statusBar().showMessage(f"{camera_type} 标定已重置", 5000)
                else:
                    QMessageBox.critical(self, "错误", "重置标定失败")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"重置失败: {e}")

    def _on_config_calib_refresh(self, camera_type):
        """刷新手眼标定显示。"""
        self.config_center_page._load_calib_from_config(camera_type)
        self.statusBar().showMessage(f"{camera_type} 标定已刷新", 3000)

    def _on_config_calib_camera_changed(self, camera_type):
        """相机切换时加载该相机的标定值。"""
        self.config_center_page._load_calib_from_config(camera_type)

    def _on_config_reload(self):
        """通过 IPC 重载 Runtime 配置。"""
        self._on_reload_config()

    def closeEvent(self, event):
        """Close GUI-only resources without touching Runtime hardware."""
        logger.info("正在关闭应用程序...")
        if hasattr(self, '_status_timer') and self._status_timer is not None:
            self._status_timer.stop()
        if hasattr(self, "_modbus_refresh_timer"):
            self._modbus_refresh_timer.stop()
        if hasattr(self, "_debug_telemetry_timer"):
            self._debug_telemetry_timer.stop()
        if hasattr(self, "_debug_live_timer"):
            self._debug_live_timer.stop()
        for thread in list(getattr(self, "_ipc_request_threads", ())):
            thread.requestInterruption()
            thread.wait(3500)
        ConfigService.instance().flush()
        logger.info("应用程序关闭完成")
        event.accept()

def main():
    """应用入口。"""
    from ..ui.logging_config import setup_logging
    setup_logging()
    app = QApplication(sys.argv)
    window = DobotMainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    import warnings
    warnings.warn(
        "直接运行 gui_app.py 已不再支持（使用了包内相对导入）。"
        "请使用: python -m dobot_move",
        RuntimeWarning,
        stacklevel=2,
    )
    # 尝试以包模式重新启动
    import subprocess
    import sys
    sys.exit(subprocess.call([sys.executable, "-m", "dobot_move"]))
