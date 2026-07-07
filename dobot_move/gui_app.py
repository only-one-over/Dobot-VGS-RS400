#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
机器人抓取控制程序 - 图形界面版本
"""

import sys
import json
import base64
import time
import numpy as np
import logging
from .qt_compat import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QGroupBox, QGridLayout, QStatusBar,
    QMessageBox, QLineEdit, QDoubleSpinBox, QComboBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QFrame, QScrollArea, QStackedWidget,
    QCheckBox, QSizePolicy, QTextEdit,
    Qt, QTimer, QPixmap,
)

from .alarm_history import AlarmHistory
from .config_manager import (
    ConfigService,
    get_grasp_flow_file,
    get_initial_point,
    get_modbus_port,
    get_modbus_slave_id,
    get_robot_ip,
    get_runtime_config,
)
from .gui_runtime_status import (
    DEFAULT_RUNTIME_HEALTH_PATH,
    RuntimeHealthReader,
    RuntimeHealthSnapshot,
)
from .gui_ipc_client import RuntimeIpcClient, RuntimeIpcRequestThread
from .runtime_ipc import DEFAULT_IPC_TOKEN_PATH
from .gui_mixins import (
    RobotControlMixin,
    VisionMixin,
    ModbusMixin,
    PointManagementMixin,
    GraspFlowMixin,
)
from .ui_theme import apply_theme, apply_status_visual, set_button_role, NAV_ICONS, card_style, metric_label_style, metric_title_style
from .flow_step_list import FlowStepList
from .main_control_panel import MainControlPanel
from .flow_library import FlowLibrary
from .gui_debug_widgets import ErrorTrendPlot

logger = logging.getLogger(__name__)

try:
    from .hand_eye_calib import HandEyeCalibManager
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
        self._ipc_request_threads = set()
        self._ipc_pending_commands = set()
        self._alarm_history = AlarmHistory()
        
        self._load_grasp_flow_modules()
        
        self.is_paused = False
        self._flow_running = False
        self._flow_started_by_modbus = False
        self._active_flow_id = None
        self._active_flow_name = None
        self._active_flow_modules = []
        self._software_emergency_active = False
        self._emergency_cmd_running = False
        self._last_emergency_click_ts = 0.0
        self._editing_point_row = -1
        self._editing_point_name = None
        
        self.init_ui()
        self._start_status_timer()
        if HANDEYE_AVAILABLE:
            self._load_calib_matrix("D435i")
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
        
        # ── 顶部状态仪表盘卡片 ──
        status_group = QGroupBox("系统状态")
        status_group.setObjectName("topStatusPanel")
        status_layout = QHBoxLayout()
        status_layout.setSpacing(12)
        status_layout.setContentsMargins(12, 10, 12, 10)
        
        # 机器人状态卡片
        status_layout.addWidget(self._create_status_card("机器人", "#3b82f6", "robot_status_label", "未连接"))

        # 相机状态卡片
        status_layout.addWidget(self._create_status_card("相机", "#06b6d4", "camera_status_label", "未连接"))

        # GPU推理模式卡片
        status_layout.addWidget(self._create_status_card("推理", "#f59e0b", "gpu_status_label", "未检测"))

        # 初始位置卡片
        status_layout.addWidget(self._create_status_card("位置", "#8b5cf6", "photo_position_label", f"{get_initial_point()}", label_color="#8b5cf6"))

        
        # 右侧操作区
        right_actions = QVBoxLayout()
        right_actions.setSpacing(6)
        
        self.realtime_btn = QPushButton("实时反馈")
        self.realtime_btn.clicked.connect(self.open_realtime_feedback)
        self.realtime_btn.setMinimumHeight(36)
        right_actions.addWidget(self.realtime_btn)

        self.emergency_stop_btn = QPushButton("急停")
        self.emergency_stop_btn.setObjectName("emergencyStopButton")
        self.emergency_stop_btn.setFixedSize(82, 82)
        self.emergency_stop_btn.clicked.connect(self.on_emergency_stop)
        self._update_emergency_stop_button()
        right_actions.addWidget(self.emergency_stop_btn, 0, Qt.AlignmentFlag.AlignCenter)
        
        status_layout.addLayout(right_actions)
        
        status_group.setLayout(status_layout)
        main_layout.addWidget(status_group)
        
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
            "color: #3b82f6; font-size: 11pt; font-weight: 900; "
            "letter-spacing: 1px; padding: 8px 10px 12px 10px; "
            "background: transparent; border: none;"
        )
        sidebar_layout.addWidget(nav_header)
        sidebar_layout.addStretch(0)

        self.stacked_widget = QStackedWidget()
        self.stacked_widget.setObjectName("workspaceStack")

        content_layout.addWidget(self.sidebar)
        content_layout.addWidget(self.stacked_widget, 1)
        
        # 主功能选项卡
        main_tab = QWidget()
        main_tab_layout = QVBoxLayout(main_tab)
        main_tab_layout.setSpacing(10)
        main_tab_layout.setContentsMargins(10, 10, 10, 10)

        self.main_control = MainControlPanel(self.robot_ip)
        # 连接信号到现有处理方法
        self.main_control.connect_robot.connect(self.connect_robot)
        self.main_control.enable_robot.connect(self.enable_robot)
        self.main_control.disable_robot.connect(self.disable_robot)
        self.main_control.connect_d435i.connect(self.connect_d435i)
        self.main_control.disconnect_d435i.connect(self.disconnect_d435i)
        self.main_control.connect_d405.connect(self.connect_d405)
        self.main_control.disconnect_d405.connect(self.disconnect_d405)
        self.main_control.select_camera_model.connect(self._select_camera_model)
        self.main_control.run_grasp.connect(self.run_grasping_task)
        self.main_control.move_initial.connect(self.move_to_initial_position)
        self.main_control.get_pose.connect(self.get_current_position)
        self.main_control.set_collision_level.connect(self.set_collision_level)
        self.main_control.clear_error.connect(self.on_clear_error)
        self.main_control.pause.connect(self.on_pause)
        self.main_control.resume.connect(self.on_continue)
        self.main_control.collision_level_changed.connect(self.on_collision_level_changed)
        self.main_control.ip_changed.connect(lambda ip: ConfigService.instance().set_ip('robot_ip', ip))
        self.main_control.main_flow_changed.connect(self._on_main_flow_changed)
        main_tab_layout.addWidget(self.main_control)

        # 向后兼容属性别名，供 mixins 和 _refresh_action_states 访问
        self.ip_input = self.main_control.ip_input
        self.run_task_btn = self.main_control.run_task_btn
        self.connect_robot_btn = self.main_control.connect_robot_btn
        self.enable_robot_btn = self.main_control.enable_robot_btn
        self.disable_robot_btn = self.main_control.disable_robot_btn
        self.d435i_status_label = self.main_control.d435i_status_label
        self.d435i_connect_btn = self.main_control.d435i_connect_btn
        self.d435i_disconnect_btn = self.main_control.d435i_disconnect_btn
        self.d405_status_label = self.main_control.d405_status_label
        self.d405_connect_btn = self.main_control.d405_connect_btn
        self.d405_disconnect_btn = self.main_control.d405_disconnect_btn
        self._refresh_camera_model_controls()
        self.get_pos_btn = self.main_control.get_pos_btn
        self.move_initial_btn = self.main_control.move_initial_btn
        self.collision_combo = self.main_control.collision_combo
        self.collision_set_btn = self.main_control.collision_set_btn
        self.clear_error_btn = self.main_control.clear_error_btn
        self.pause_btn = self.main_control.pause_btn
        self.continue_btn = self.main_control.continue_btn

        self._add_nav_page("主功能", self._wrap_in_scroll(main_tab))
        
        # 运动编辑选项卡
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
        self.new_flow_btn.clicked.connect(self.create_flow)
        flow_select_layout.addWidget(self.new_flow_btn)
        self.rename_flow_btn = QPushButton("重命名")
        self.rename_flow_btn.clicked.connect(self.rename_flow)
        flow_select_layout.addWidget(self.rename_flow_btn)
        self.duplicate_flow_btn = QPushButton("复制")
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
        point_mgmt_layout.addWidget(self.points_table)

        point_btn_layout = QHBoxLayout()
        point_btn_layout.setSpacing(10)

        self.add_point_btn = QPushButton("添加点位")
        self.add_point_btn.clicked.connect(self._on_add_point)
        point_btn_layout.addWidget(self.add_point_btn)

        self.delete_point_btn = QPushButton("删除点位")
        self.delete_point_btn.clicked.connect(self._on_delete_point)
        point_btn_layout.addWidget(self.delete_point_btn)

        self.edit_point_btn = QPushButton("修改点位")
        self.edit_point_btn.clicked.connect(self._on_edit_point)
        point_btn_layout.addWidget(self.edit_point_btn)

        self.save_point_btn = QPushButton("保存修改")
        self.save_point_btn.clicked.connect(self._on_save_point_edit)
        self.save_point_btn.setEnabled(False)
        point_btn_layout.addWidget(self.save_point_btn)

        self.cancel_point_btn = QPushButton("取消修改")
        self.cancel_point_btn.clicked.connect(self._on_cancel_point_edit)
        self.cancel_point_btn.setEnabled(False)
        point_btn_layout.addWidget(self.cancel_point_btn)

        self.read_point_btn = QPushButton("读取当前点位")
        self.read_point_btn.setMinimumWidth(120)
        self.read_point_btn.clicked.connect(self._on_read_current_for_selected_point)
        self.read_point_btn.setEnabled(False)
        point_btn_layout.addWidget(self.read_point_btn)

        self.refresh_points_btn = QPushButton("刷新点位")
        self.refresh_points_btn.clicked.connect(self.refresh_points_table)
        point_btn_layout.addWidget(self.refresh_points_btn)

        point_btn_layout.addStretch()
        point_mgmt_layout.addLayout(point_btn_layout)

        point_mgmt_group.setLayout(point_mgmt_layout)

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
        self.add_module_btn.setDefault(True)
        self.add_module_btn.clicked.connect(self.add_module)
        module_select_layout.addWidget(self.add_module_btn)
        
        self.remove_module_btn = QPushButton("移除模块")
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
        self.linear_point_preview.setStyleSheet("color: #64748b; font-size: 11px;")
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
        self.rpath_seg_table.horizontalHeader().setStretchLastSection(True)
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
        
        self._add_nav_page("运动编辑", self._wrap_in_scroll(motion_tab))

        point_tab = QWidget()
        point_tab_layout = QVBoxLayout(point_tab)
        point_tab_layout.setSpacing(10)
        point_tab_layout.setContentsMargins(10, 10, 10, 10)
        point_tab_layout.addWidget(point_mgmt_group)
        self._add_nav_page("点位管理", self._wrap_in_scroll(point_tab))


        # Modbus 通信选项卡
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
        self.modbus_start_btn.setMinimumWidth(120)
        self.modbus_start_btn.setMinimumHeight(40)
        self.modbus_start_btn.clicked.connect(self.start_modbus_server)
        modbus_ctrl_layout.addWidget(self.modbus_start_btn, 0, 2)

        self.modbus_stop_btn = QPushButton("停止从站服务")
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
        status_panel.setStyleSheet(card_style("#3b82f6"))
        status_panel_layout = QHBoxLayout(status_panel)
        status_panel_layout.setSpacing(15)
        status_panel_layout.setContentsMargins(12, 8, 12, 8)

        self.modbus_cycle_label = QLabel(" 周期: 0")
        self.modbus_cycle_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #93c5fd; background: transparent;")
        status_panel_layout.addWidget(self.modbus_cycle_label)

        self.modbus_duration_label = QLabel(" 耗时: 0ms")
        self.modbus_duration_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #93c5fd; background: transparent;")
        status_panel_layout.addWidget(self.modbus_duration_label)

        self.modbus_status_panel_label = QLabel(" 状态: 停止")
        self.modbus_status_panel_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #93c5fd; background: transparent;")
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

        self._add_nav_page("Modbus 通信", self._wrap_in_scroll(modbus_tab))

        self._create_alarm_tab()

        calib_tab = QWidget()
        calib_layout = QVBoxLayout(calib_tab)
        calib_layout.setSpacing(10)
        calib_layout.setContentsMargins(10, 10, 10, 10)

        calib_selector_layout = QHBoxLayout()
        calib_selector_layout.addWidget(QLabel("选择相机:"))
        self.calib_camera_combo = QComboBox()
        self.calib_camera_combo.addItems(["D435i", "D405"])
        self.calib_camera_combo.currentTextChanged.connect(self._on_calib_camera_changed)
        calib_selector_layout.addWidget(self.calib_camera_combo)
        calib_selector_layout.addStretch()
        calib_layout.addLayout(calib_selector_layout)

        self.calib_table = QTableWidget(4, 4)
        self.calib_table.setHorizontalHeaderLabels(["Col 0", "Col 1", "Col 2", "Col 3"])
        self.calib_table.setVerticalHeaderLabels(["Row 0", "Row 1", "Row 2", "Row 3"])
        self.calib_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.calib_table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        calib_layout.addWidget(self.calib_table)

        calib_btn_layout = QHBoxLayout()
        self.calib_save_btn = QPushButton("保存")
        self.calib_save_btn.clicked.connect(self._on_calib_save)
        self.calib_reset_btn = QPushButton("重置")
        self.calib_reset_btn.clicked.connect(self._on_calib_reset)
        self.calib_refresh_btn = QPushButton("刷新")
        self.calib_refresh_btn.clicked.connect(self._on_calib_refresh)
        calib_btn_layout.addWidget(self.calib_save_btn)
        calib_btn_layout.addWidget(self.calib_reset_btn)
        calib_btn_layout.addWidget(self.calib_refresh_btn)
        calib_layout.addLayout(calib_btn_layout)

        self._add_nav_page("手眼标定", self._wrap_in_scroll(calib_tab))

        # ===== 相机测试选项卡 =====
        camera_test_tab = QWidget()
        camera_test_layout = QVBoxLayout(camera_test_tab)

        # 顶部控制栏
        cam_test_ctrl = QHBoxLayout()
        cam_test_ctrl.addWidget(QLabel("选择相机:"))
        self.cam_test_combo = QComboBox()
        self.cam_test_combo.addItems(["D435i", "D405"])
        cam_test_ctrl.addWidget(self.cam_test_combo)
        self.cam_test_start_btn = QPushButton("开始测试")
        self.cam_test_start_btn.clicked.connect(self._start_camera_test)
        cam_test_ctrl.addWidget(self.cam_test_start_btn)
        self.cam_test_stop_btn = QPushButton("停止测试")
        self.cam_test_stop_btn.clicked.connect(self._stop_camera_test)
        self.cam_test_stop_btn.setEnabled(False)
        cam_test_ctrl.addWidget(self.cam_test_stop_btn)
        cam_test_ctrl.addStretch()
        camera_test_layout.addLayout(cam_test_ctrl)

        # 主内容区域
        cam_test_content = QHBoxLayout()

        # 左侧: 画面显示
        self.cam_test_image_label = QLabel("等待测试...")
        self.cam_test_image_label.setFixedSize(640, 480)
        self.cam_test_image_label.setStyleSheet("background-color: #0b0f1a; color: #64748b; font-size: 16px; border: 1px solid #2a3550; border-radius: 8px;")
        self.cam_test_image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cam_test_content.addWidget(self.cam_test_image_label)

        # 右侧: 坐标显示
        coord_group = QGroupBox("坐标信息")
        coord_layout = QVBoxLayout(coord_group)

        self.cam_test_status_label = QLabel("状态: 未开始")
        self.cam_test_status_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #93c5fd;")
        coord_layout.addWidget(self.cam_test_status_label)

        coord_layout.addWidget(QLabel("相机坐标 (mm):"))
        self.cam_test_cam_coords = QLabel("X: ---  Y: ---  Z: ---")
        self.cam_test_cam_coords.setStyleSheet("font-family: monospace; font-size: 13px; color: #93c5fd;")
        coord_layout.addWidget(self.cam_test_cam_coords)

        coord_layout.addWidget(QLabel("末端坐标 (mm):"))
        self.cam_test_end_coords = QLabel("X: ---  Y: ---  Z: ---")
        self.cam_test_end_coords.setStyleSheet("font-family: monospace; font-size: 13px; color: #93c5fd;")
        coord_layout.addWidget(self.cam_test_end_coords)

        coord_layout.addWidget(QLabel("基座坐标 (mm):"))
        self.cam_test_base_coords = QLabel("X: ---  Y: ---  Z: ---")
        self.cam_test_base_coords.setStyleSheet("font-family: monospace; font-size: 13px; color: #93c5fd;")
        coord_layout.addWidget(self.cam_test_base_coords)

        coord_layout.addWidget(QLabel("置信度"))
        self.cam_test_confidence = QLabel("---")
        self.cam_test_confidence.setStyleSheet("font-family: monospace; font-size: 13px; color: #93c5fd;")
        coord_layout.addWidget(self.cam_test_confidence)

        # D405 专用
        self.cam_test_d405_group = QGroupBox("D405 端点信息")
        d405_layout = QVBoxLayout(self.cam_test_d405_group)
        d405_layout.addWidget(QLabel("抓取坐标 (mm):"))
        self.cam_test_handle_coords = QLabel("X: ---  Y: ---  Z: ---")
        self.cam_test_handle_coords.setStyleSheet("font-family: monospace; font-size: 13px; color: #93c5fd;")
        d405_layout.addWidget(self.cam_test_handle_coords)
        d405_layout.addWidget(QLabel("钩尖坐标 (mm):"))
        self.cam_test_tip_coords = QLabel("X: ---  Y: ---  Z: ---")
        self.cam_test_tip_coords.setStyleSheet("font-family: monospace; font-size: 13px; color: #93c5fd;")
        d405_layout.addWidget(self.cam_test_tip_coords)
        d405_layout.addWidget(QLabel("铁钩长度:"))
        self.cam_test_hook_length = QLabel("--- mm")
        self.cam_test_hook_length.setStyleSheet("font-family: monospace; font-size: 13px; color: #93c5fd;")
        d405_layout.addWidget(self.cam_test_hook_length)
        self.cam_test_d405_group.setVisible(False)
        coord_layout.addWidget(self.cam_test_d405_group)

        coord_layout.addStretch()
        cam_test_content.addWidget(coord_group)
        camera_test_layout.addLayout(cam_test_content)



        self.cam_test_worker = None

        self._add_nav_page("相机测试", self._wrap_in_scroll(camera_test_tab))
        self._create_runtime_debug_page()

        # Modbus 数据刷新定时器
        self._modbus_refresh_timer = QTimer()
        self._modbus_refresh_timer.timeout.connect(self._refresh_modbus_table)

        self.refresh_points_table()

        main_layout.addLayout(content_layout)
        
        # 状态栏
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就绪")

        self._set_status_visual(self.robot_status_label, "未连接")
        self._set_status_visual(self.camera_status_label, "未连接")
        self._select_editing_flow(self.editing_flow_id)
        self._refresh_action_states()

    def on_collision_level_changed(self, level):
        """碰撞等级下拉框变化回调。"""
        pass

    def _set_status_visual(self, label, value):
        apply_status_visual(label, value)

    def _update_emergency_stop_button(self):
        if not hasattr(self, "emergency_stop_btn"):
            return
        self.emergency_stop_btn.setText("急停")
        self.emergency_stop_btn.setProperty("active", "false")
        self.emergency_stop_btn.style().unpolish(self.emergency_stop_btn)
        self.emergency_stop_btn.style().polish(self.emergency_stop_btn)

    def _refresh_action_states(self):
        for attr in (
            "enable_robot_btn", "disable_robot_btn", "get_pos_btn",
            "move_initial_btn", "collision_set_btn", "clear_error_btn", "run_flow_btn",
            "run_task_btn", "connect_robot_btn", "pause_btn", "continue_btn",
            "editor_pause_btn", "editor_continue_btn", "emergency_stop_btn",
            "realtime_btn", "read_point_btn", "linear_read_current_btn",
            "cam_test_start_btn", "cam_test_stop_btn",
        ):
            if hasattr(self, attr):
                getattr(self, attr).setEnabled(False)
        if hasattr(self.main_control, "main_flow_combo"):
            self.main_control.main_flow_combo.setEnabled(True)

        for camera_type, camera_connected in (
            ("D435i", self._runtime_status.d435i_connected),
            ("D405", self._runtime_status.d405_connected),
        ):
            self.main_control.set_camera_model_selection_enabled(
                camera_type,
                not camera_connected,
            )
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
        self._update_emergency_stop_button()

    def _create_runtime_debug_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)

        runtime_group = QGroupBox("Runtime 维护控制")
        runtime_layout = QHBoxLayout(runtime_group)
        self.debug_runtime_state = QLabel("Runtime: 未连接")
        runtime_layout.addWidget(self.debug_runtime_state)
        for text, command in (
            ("进入维护", "enter_maintenance"),
            ("退出维护", "exit_maintenance"),
            ("刷新状态", "get_status"),
        ):
            button = QPushButton(text)
            button.clicked.connect(
                lambda _checked=False, cmd=command: self._send_runtime_ipc(cmd)
            )
            runtime_layout.addWidget(button)
        runtime_layout.addStretch()
        layout.addWidget(runtime_group)

        flow_group = QGroupBox("流程调试")
        flow_layout = QGridLayout(flow_group)
        self.debug_validate_btn = QPushButton("校验当前流程")
        self.debug_validate_btn.clicked.connect(self._validate_debug_flow)
        flow_layout.addWidget(self.debug_validate_btn, 0, 0)
        self.debug_start_btn = QPushButton("运行当前流程")
        self.debug_start_btn.clicked.connect(self._start_debug_flow)
        flow_layout.addWidget(self.debug_start_btn, 0, 1)
        flow_layout.addWidget(QLabel("步骤序号:"), 0, 2)
        self.debug_step_input = QLineEdit("1")
        self.debug_step_input.setMaximumWidth(80)
        flow_layout.addWidget(self.debug_step_input, 0, 3)
        self.debug_step_btn = QPushButton("运行单步")
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
            button.clicked.connect(
                lambda _checked=False, cmd=command: self._send_runtime_ipc(cmd)
            )
            flow_layout.addWidget(button, 1, column)
        layout.addWidget(flow_group)

        vision_group = QGroupBox("视觉诊断")
        vision_layout = QGridLayout(vision_group)
        self.debug_camera_combo = QComboBox()
        self.debug_camera_combo.addItems(["D405", "D435i"])
        vision_layout.addWidget(self.debug_camera_combo, 0, 0)
        snapshot_button = QPushButton("采集诊断快照")
        snapshot_button.clicked.connect(self._request_vision_snapshot)
        vision_layout.addWidget(snapshot_button, 0, 1)
        logs_button = QPushButton("读取 Runtime 日志")
        logs_button.clicked.connect(
            lambda: self._send_runtime_ipc(
                "get_runtime_logs",
                {"limit": 200},
                self._show_runtime_logs,
            )
        )
        vision_layout.addWidget(logs_button, 0, 2)
        self.debug_live_button = QPushButton("开始实时图")
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
            "background-color:#0b0f1a; border:1px solid #2a3550;"
        )
        vision_layout.addWidget(self.debug_image_label, 1, 0, 1, 3)
        self.debug_depth_label = QLabel("等待深度图")
        self.debug_depth_label.setMinimumSize(360, 240)
        self.debug_depth_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.debug_depth_label.setStyleSheet(
            "background-color:#0b0f1a; border:1px solid #2a3550;"
        )
        vision_layout.addWidget(self.debug_depth_label, 1, 3, 1, 2)
        layout.addWidget(vision_group)

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
        layout.addWidget(self.debug_telemetry_table)
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
        layout.addLayout(plots_layout)

        self.debug_output = QTextEdit()
        self.debug_output.setReadOnly(True)
        self.debug_output.setMinimumHeight(150)
        layout.addWidget(self.debug_output)
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
        self._set_camera_status(
            "D435i",
            "已连接" if snapshot.d435i_connected else "未连接",
        )
        self._set_camera_status(
            "D405",
            "已连接" if snapshot.d405_connected else "未连接",
        )
        self._refresh_modbus_table()
    
    def update_gpu_status(self, provider_text=None):
        """更新GPU推理模式状态显示。"""
        if provider_text is None:
            self.gpu_status_label.setText("未检测")
            self.gpu_status_label.setStyleSheet(metric_label_style("#94a3b8"))
        elif "GPU" in provider_text:
            self.gpu_status_label.setText("GPU")
            self.gpu_status_label.setStyleSheet(metric_label_style("#22c55e"))
        else:
            self.gpu_status_label.setText("CPU")
            self.gpu_status_label.setStyleSheet(metric_label_style("#f59e0b"))

    def update_status(self, status_type, status_value):
        """更新状态显示。"""
        if status_type == "robot":
            self.robot_status_label.setText(f"{status_value}")
            self._set_status_visual(self.robot_status_label, status_value)
            # 更新卡片值颜色
            if any(k in status_value for k in ("已连接", "运行", "成功", "connected", "running")):
                self.robot_status_label.setStyleSheet(metric_label_style("#22c55e"))
            elif any(k in status_value for k in ("错误", "失败", "报警", "error", "failed")):
                self.robot_status_label.setStyleSheet(metric_label_style("#ef4444"))
            else:
                self.robot_status_label.setStyleSheet(metric_label_style("#94a3b8"))
        elif status_type == "camera":
            self.camera_status_label.setText(f"{status_value}")
            self._set_status_visual(self.camera_status_label, status_value)
            if any(k in status_value for k in ("已连接", "运行", "成功", "connected", "running")):
                self.camera_status_label.setStyleSheet(metric_label_style("#22c55e"))
            elif any(k in status_value for k in ("错误", "失败", "error", "failed")):
                self.camera_status_label.setStyleSheet(metric_label_style("#ef4444"))
            else:
                self.camera_status_label.setStyleSheet(metric_label_style("#94a3b8"))
        elif status_type == "photo_position":
            self.photo_position_label.setText(f"{status_value}")
        elif status_type == "general":
            self.status_bar.showMessage(status_value)
        self._refresh_action_states()

    def on_emergency_stop(self):
        return self._show_runtime_ipc_required("GUI 软件急停")

    def _on_emergency_stop_finished(self, cmd_name, success):
        del cmd_name, success

    def _create_alarm_tab(self):
        alarm_tab = QWidget()
        alarm_layout = QVBoxLayout(alarm_tab)
        alarm_layout.setSpacing(10)
        alarm_layout.setContentsMargins(10, 10, 10, 10)

        ops_layout = QHBoxLayout()
        self.alarm_refresh_btn = QPushButton("刷新报警记录")
        self.alarm_refresh_btn.setMinimumWidth(120)
        self.alarm_refresh_btn.clicked.connect(self._refresh_alarm_table)
        ops_layout.addWidget(self.alarm_refresh_btn)

        self.alarm_clear_btn = QPushButton("清空本地记录")
        self.alarm_clear_btn.setMinimumWidth(120)
        self.alarm_clear_btn.clicked.connect(self._clear_alarm_history)
        self.alarm_clear_btn.setEnabled(False)
        ops_layout.addWidget(self.alarm_clear_btn)
        ops_layout.addStretch()
        alarm_layout.addLayout(ops_layout)

        self.alarm_table = QTableWidget()
        self.alarm_table.setColumnCount(7)
        self.alarm_table.setHorizontalHeaderLabels(["时间", "来源", "代码", "等级", "描述", "处理建议", "原始响应"])
        self.alarm_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
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
        return self._show_runtime_ipc_required("清空报警历史")
    
    def _on_calib_camera_changed(self, camera_type):
        self._load_calib_matrix(camera_type)

    def _load_calib_matrix(self, camera_type):
        if not HANDEYE_AVAILABLE:
            return
        try:
            manager = HandEyeCalibManager()
            matrix = manager.get_matrix(camera_type)
            for i in range(4):
                for j in range(4):
                    item = QTableWidgetItem(f"{matrix[i][j]:.6f}")
                    self.calib_table.setItem(i, j, item)
        except Exception as e:
            QMessageBox.warning(self, "警告", f"加载标定矩阵失败: {e}")

    def _on_calib_save(self):
        if not HANDEYE_AVAILABLE:
            QMessageBox.critical(self, "错误", "手眼标定模块不可用")
            return
        camera_type = self.calib_camera_combo.currentText()
        try:
            matrix = np.eye(4)
            for i in range(4):
                for j in range(4):
                    item = self.calib_table.item(i, j)
                    if item:
                        matrix[i][j] = float(item.text())
            manager = HandEyeCalibManager()
            if manager.set_matrix_direct(camera_type, matrix):
                QMessageBox.information(self, "成功", f"{camera_type} 标定矩阵已保存")
            else:
                QMessageBox.critical(self, "错误", "保存标定矩阵失败")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败: {e}")

    def _on_calib_reset(self):
        if not HANDEYE_AVAILABLE:
            return
        camera_type = self.calib_camera_combo.currentText()
        reply = QMessageBox.question(self, "确认", f"确定要重置 {camera_type} 的标定矩阵为默认值吗？",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            try:
                manager = HandEyeCalibManager()
                manager.reset_to_default(camera_type)
                self._load_calib_matrix(camera_type)
                QMessageBox.information(self, "成功", f"{camera_type} 标定矩阵已重置")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"重置失败: {e}")

    def _on_calib_refresh(self):
        camera_type = self.calib_camera_combo.currentText()
        self._load_calib_matrix(camera_type)

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
    from .logging_config import setup_logging
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
