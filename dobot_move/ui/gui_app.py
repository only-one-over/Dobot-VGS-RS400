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
from .motion_editor_page import MotionEditorPage
from .point_management_page import PointManagementPage
from .modbus_comm_page import ModbusCommPage
from .alarm_history_page import AlarmHistoryPage
from .camera_test_page import CameraTestPage
from .runtime_debug_page import RuntimeDebugPage

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
        self._nav_buttons.append(btn)
        if idx == 0:
            btn.setChecked(True)
        return btn

    def _on_nav_clicked(self, index):
        self.stacked_widget.setCurrentIndex(index)
        for i, btn in enumerate(self._nav_buttons):
            btn.setChecked(i == index)

    def set_dark_theme(self):
        """设置深色主题"""
        apply_theme(self)
    
    def init_ui(self):
        """初始化UI"""
        self._nav_buttons = []
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
            "font-size: 18pt; font-weight: bold; color: #1d1d1f; padding: 8px;"
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

        # ── 安全停止按钮 ──
        self.emergency_stop_btn = QPushButton("安全停止")
        self.emergency_stop_btn.setObjectName("emergencyStopButton")
        self.emergency_stop_btn.setFixedSize(82, 82)
        self.emergency_stop_btn.clicked.connect(self.on_emergency_stop)
        self._update_emergency_stop_button()
        sidebar_layout.addWidget(self.emergency_stop_btn, 0, Qt.AlignmentFlag.AlignCenter)

        sidebar_layout.addStretch(0)

        self.stacked_widget = QStackedWidget()
        self.stacked_widget.setObjectName("workspaceStack")

        content_layout.addWidget(self.sidebar)
        content_layout.addWidget(self.stacked_widget, 1)
        
        # ── Page 1: 生产监控页（系统状态卡片 + 生产上下文，从顶部迁移） ──
        self.production_monitor_page = ProductionMonitorPage()
        self.production_monitor_page.realtime_requested.connect(self.open_realtime_feedback)
        self._add_nav_page("生产监控", self.production_monitor_page)

        # 向后兼容：将生产监控页的标签暴露为主窗口属性
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

        # ── Page 2: 配置中心页（机器人/相机/手眼标定/Modbus/Runtime 配置） ──
        self.config_center_page = ConfigCenterPage()
        self._add_nav_page("配置中心", self.config_center_page)
        self._connect_config_center_signals()

        # ── Page 3: 主功能页 ──
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
        self._add_nav_page("主功能", self._wrap_in_scroll(self.main_control))

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

        # ── Page 4: 运动编辑页 ──
        self.motion_editor_page = MotionEditorPage()
        # 连接所有信号到 mixin 方法
        self.motion_editor_page.edit_flow_combo.currentIndexChanged.connect(
            self._on_edit_flow_changed
        )
        self.motion_editor_page.new_flow_btn.clicked.connect(self.create_flow)
        self.motion_editor_page.rename_flow_btn.clicked.connect(self.rename_flow)
        self.motion_editor_page.duplicate_flow_btn.clicked.connect(self.duplicate_flow)
        self.motion_editor_page.delete_flow_btn.clicked.connect(self.delete_flow)
        self.motion_editor_page.flow_step_list.step_clicked.connect(self.on_step_clicked)
        self.motion_editor_page.flow_step_list.step_reordered.connect(self._on_steps_reordered)
        self.motion_editor_page.module_combo.currentIndexChanged.connect(self.on_module_combo_changed)
        self.motion_editor_page.add_module_btn.clicked.connect(self.add_module)
        self.motion_editor_page.remove_module_btn.clicked.connect(self.remove_module)
        self.motion_editor_page.linear_read_current_btn.clicked.connect(self._on_read_current_for_linear)
        self.motion_editor_page.linear_point_combo.currentTextChanged.connect(self._on_linear_point_selected)
        self.motion_editor_page.update_param_btn.clicked.connect(self.update_module_params)
        self.motion_editor_page.view_flow_btn.clicked.connect(self.view_current_grasp_flow)
        self.motion_editor_page.save_flow_btn.clicked.connect(self.save_grasp_flow)
        self.motion_editor_page.publish_flow_btn.clicked.connect(self._publish_runtime_config)
        self.motion_editor_page.load_flow_btn.clicked.connect(self.load_grasp_flow)
        self.motion_editor_page.run_flow_btn.clicked.connect(
            lambda: self.run_grasp_flow(flow_id=self.editing_flow_id)
        )
        self.motion_editor_page.editor_pause_btn.clicked.connect(self.on_pause)
        self.motion_editor_page.editor_continue_btn.clicked.connect(self.on_continue)
        self._add_nav_page("运动编辑", self._wrap_in_scroll(self.motion_editor_page))

        # 向后兼容属性别名：运动编辑页
        me = self.motion_editor_page
        self.edit_flow_combo = me.edit_flow_combo
        self.new_flow_btn = me.new_flow_btn
        self.rename_flow_btn = me.rename_flow_btn
        self.duplicate_flow_btn = me.duplicate_flow_btn
        self.delete_flow_btn = me.delete_flow_btn
        self.flow_step_list = me.flow_step_list
        self.selected_step_index = me.selected_step_index
        self.module_combo = me.module_combo
        self.add_module_btn = me.add_module_btn
        self.remove_module_btn = me.remove_module_btn
        self.param_group = me.param_group
        self.param_layout = me.param_layout
        self.linear_target_combo = me.linear_target_combo
        self.linear_point_combo = me.linear_point_combo
        self.linear_point_preview = me.linear_point_preview
        self.linear_speed = me.linear_speed
        self.linear_force_guard_enabled = me.linear_force_guard_enabled
        self.linear_force_threshold = me.linear_force_threshold
        self.linear_read_current_btn = me.linear_read_current_btn
        self.joint_rotation_params = me.joint_rotation_params
        self.joint_offsets = me.joint_offsets
        self.joint_accel = me.joint_accel
        self.joint_speed = me.joint_speed
        self.relative_move_params = me.relative_move_params
        self.rel_coord_combo = me.rel_coord_combo
        self.rel_motion_combo = me.rel_motion_combo
        self.rel_offsets = me.rel_offsets
        self.rel_speed = me.rel_speed
        self.rel_accel = me.rel_accel
        self.rel_cp = me.rel_cp
        self.rel_force_guard_enabled = me.rel_force_guard_enabled
        self.rel_force_threshold = me.rel_force_threshold
        self.arc_motion_params = me.arc_motion_params
        self.fa_center_offset_z = me.fa_center_offset_z
        self.fa_sweep_angle = me.fa_sweep_angle
        self.fa_arc_direction = me.fa_arc_direction
        self.fa_num_waypoints = me.fa_num_waypoints
        self.fa_speed = me.fa_speed
        self.fa_force_guard_enabled = me.fa_force_guard_enabled
        self.fa_force_threshold = me.fa_force_threshold
        self.camera_params = me.camera_params
        self.camera_module_combo = me.camera_module_combo
        self.delay_params = me.delay_params
        self.delay_wait_mode = me.delay_wait_mode
        self.delay_seconds = me.delay_seconds
        self.relative_path_params = me.relative_path_params
        self.rpath_exec_mode = me.rpath_exec_mode
        self.rpath_seg_table = me.rpath_seg_table
        self.rpath_coord_combo = me.rpath_coord_combo
        self.rpath_motion_combo = me.rpath_motion_combo
        self.rpath_speed = me.rpath_speed
        self.rpath_accel = me.rpath_accel
        self.rpath_cp = me.rpath_cp
        self.rpath_force_guard_enabled = me.rpath_force_guard_enabled
        self.rpath_force_threshold = me.rpath_force_threshold
        self.update_param_btn = me.update_param_btn
        self.view_flow_btn = me.view_flow_btn
        self.save_flow_btn = me.save_flow_btn
        self.publish_flow_btn = me.publish_flow_btn
        self.load_flow_btn = me.load_flow_btn
        self.run_flow_btn = me.run_flow_btn
        self.editor_pause_btn = me.editor_pause_btn
        self.editor_continue_btn = me.editor_continue_btn

        # ── Page 5: 点位管理页 ──
        self.point_management_page = PointManagementPage()
        # 连接所有按钮信号
        self.point_management_page.points_table.itemSelectionChanged.connect(self._on_point_selection_changed)
        self.point_management_page.add_point_btn.clicked.connect(self._on_add_point)
        self.point_management_page.delete_point_btn.clicked.connect(self._on_delete_point)
        self.point_management_page.edit_point_btn.clicked.connect(self._on_edit_point)
        self.point_management_page.save_point_btn.clicked.connect(self._on_save_point_edit)
        self.point_management_page.cancel_point_btn.clicked.connect(self._on_cancel_point_edit)
        self.point_management_page.read_point_btn.clicked.connect(self._on_read_current_for_selected_point)
        self.point_management_page.refresh_points_btn.clicked.connect(self.refresh_points_table)
        self.point_management_page.move_to_point_btn.clicked.connect(self._on_move_to_point)
        self._add_nav_page("点位管理", self._wrap_in_scroll(self.point_management_page))

        # 向后兼容属性别名：点位管理页
        pm = self.point_management_page
        self.points_table = pm.points_table
        self.add_point_btn = pm.add_point_btn
        self.delete_point_btn = pm.delete_point_btn
        self.edit_point_btn = pm.edit_point_btn
        self.save_point_btn = pm.save_point_btn
        self.cancel_point_btn = pm.cancel_point_btn
        self.read_point_btn = pm.read_point_btn
        self.refresh_points_btn = pm.refresh_points_btn
        self.move_to_point_btn = pm.move_to_point_btn

        # ── Page 6: Modbus 通信页 ──
        self.modbus_comm_page = ModbusCommPage(
            modbus_port=str(get_modbus_port()),
            modbus_slave_id=str(get_modbus_slave_id()),
        )
        # 连接信号
        self.modbus_comm_page.modbus_port_input.editingFinished.connect(
            lambda: ConfigService.instance().set('modbus_port', int(self.modbus_comm_page.modbus_port_input.text().strip() or 502))
        )
        self.modbus_comm_page.modbus_slave_id_input.editingFinished.connect(
            lambda: ConfigService.instance().set('modbus_slave_id', int(self.modbus_comm_page.modbus_slave_id_input.text().strip() or 5))
        )
        self.modbus_comm_page.modbus_start_btn.clicked.connect(self.start_modbus_server)
        self.modbus_comm_page.modbus_stop_btn.clicked.connect(self.stop_modbus_server)
        self._add_nav_page("Modbus 通信", self._wrap_in_scroll(self.modbus_comm_page))

        # 向后兼容属性别名：Modbus 通信页
        mc = self.modbus_comm_page
        self.modbus_port_input = mc.modbus_port_input
        self.modbus_slave_id_input = mc.modbus_slave_id_input
        self.modbus_start_btn = mc.modbus_start_btn
        self.modbus_stop_btn = mc.modbus_stop_btn
        self.modbus_status_label = mc.modbus_status_label
        self.modbus_cycle_label = mc.modbus_cycle_label
        self.modbus_duration_label = mc.modbus_duration_label
        self.modbus_status_panel_label = mc.modbus_status_panel_label
        self.modbus_table = mc.modbus_table

        # ── Page 7: 报警记录页 ──
        self.alarm_history_page = AlarmHistoryPage()
        self.alarm_history_page.alarm_refresh_btn.clicked.connect(self._refresh_alarm_table)
        self.alarm_history_page.alarm_clear_btn.clicked.connect(self._clear_alarm_history)
        self._add_nav_page("报警记录", self._wrap_in_scroll(self.alarm_history_page))

        # 向后兼容属性别名：报警记录页
        self.alarm_table = self.alarm_history_page.alarm_table
        self.alarm_refresh_btn = self.alarm_history_page.alarm_refresh_btn
        self.alarm_clear_btn = self.alarm_history_page.alarm_clear_btn

        # ── Page 8: 相机测试页 ──
        self.camera_test_page = CameraTestPage()
        self.camera_test_page.cam_test_start_btn.clicked.connect(self._start_camera_test)
        self.camera_test_page.cam_test_stop_btn.clicked.connect(self._stop_camera_test)
        self.camera_test_page.cam_self_test_btn.clicked.connect(self._run_camera_self_test)
        self._add_nav_page("相机测试", self._wrap_in_scroll(self.camera_test_page))

        # 向后兼容属性别名：相机测试页
        ct = self.camera_test_page
        self.cam_test_combo = ct.cam_test_combo
        self.cam_test_start_btn = ct.cam_test_start_btn
        self.cam_test_stop_btn = ct.cam_test_stop_btn
        self.cam_self_test_btn = ct.cam_self_test_btn
        self.cam_test_image_label = ct.cam_test_image_label
        self.cam_test_status_label = ct.cam_test_status_label
        self.cam_test_cam_coords = ct.cam_test_cam_coords
        self.cam_test_end_coords = ct.cam_test_end_coords
        self.cam_test_base_coords = ct.cam_test_base_coords
        self.cam_test_confidence = ct.cam_test_confidence
        self.cam_test_d405_group = ct.cam_test_d405_group
        self.cam_test_handle_coords = ct.cam_test_handle_coords
        self.cam_test_tip_coords = ct.cam_test_tip_coords
        self.cam_test_hook_length = ct.cam_test_hook_length
        self.cam_test_worker = ct.cam_test_worker

        # ── Page 9: Runtime 调试页 ──
        self.runtime_debug_page = RuntimeDebugPage()
        # 连接显式属性按钮
        self.runtime_debug_page.debug_reload_config_btn.clicked.connect(self._on_reload_config)
        self.runtime_debug_page.debug_validate_btn.clicked.connect(self._validate_debug_flow)
        self.runtime_debug_page.debug_start_btn.clicked.connect(self._start_debug_flow)
        self.runtime_debug_page.debug_step_btn.clicked.connect(self._run_debug_step)
        self.runtime_debug_page.debug_live_button.toggled.connect(self._toggle_live_vision)

        # Connect runtime debug page buttons by text matching
        for btn in self.runtime_debug_page.findChildren(QPushButton):
            text = btn.text()
            if text == "进入维护":
                btn.clicked.connect(lambda _c=False, cmd="enter_maintenance": self._send_runtime_ipc(cmd))
            elif text == "退出维护":
                btn.clicked.connect(lambda _c=False, cmd="exit_maintenance": self._send_runtime_ipc(cmd))
            elif text == "清除恢复锁":
                btn.clicked.connect(self._clear_recovery)
            elif text == "刷新状态":
                btn.clicked.connect(lambda _c=False: self._send_runtime_ipc("get_status", on_success=self._cache_runtime_capabilities))
            elif text == "发布状态":
                btn.clicked.connect(lambda _c=False, cmd="get_publication_status": self._send_runtime_ipc(cmd))
            elif text == "采集诊断快照":
                btn.clicked.connect(self._request_vision_snapshot)
            elif text == "读取 Runtime 日志":
                btn.clicked.connect(lambda: self._send_runtime_ipc("get_runtime_logs", {"limit": 200}, self._show_runtime_logs))
            elif text in ("暂停", "继续", "停止", "读取位姿"):
                cmd_map = {"暂停": "pause_debug_flow", "继续": "resume_debug_flow", "停止": "stop_debug_flow", "读取位姿": "get_current_pose"}
                cmd = cmd_map[text]
                btn.clicked.connect(lambda _c=False, cmd=cmd: self._send_runtime_ipc(cmd))

        self._add_nav_page("Runtime 调试", self._wrap_in_scroll(self.runtime_debug_page))

        # 向后兼容属性别名：Runtime 调试页
        rd = self.runtime_debug_page
        self.debug_runtime_state = rd.debug_runtime_state
        self.debug_reload_config_btn = rd.debug_reload_config_btn
        self.runtime_overview_state_label = rd.runtime_overview_state_label
        self.runtime_overview_online_label = rd.runtime_overview_online_label
        self.runtime_overview_error_label = rd.runtime_overview_error_label
        self.runtime_overview_module_label = rd.runtime_overview_module_label
        self.debug_task_status_label = rd.debug_task_status_label
        self.debug_validate_btn = rd.debug_validate_btn
        self.debug_start_btn = rd.debug_start_btn
        self.debug_step_input = rd.debug_step_input
        self.debug_step_btn = rd.debug_step_btn
        self.debug_camera_combo = rd.debug_camera_combo
        self.debug_image_label = rd.debug_image_label
        self.debug_depth_label = rd.debug_depth_label
        self.debug_depth_checkbox = rd.debug_depth_checkbox
        self.debug_live_button = rd.debug_live_button
        self.debug_telemetry_table = rd.debug_telemetry_table
        self.debug_error_time_plot = rd.debug_error_time_plot
        self.debug_error_iteration_plot = rd.debug_error_iteration_plot
        self.debug_output = rd.debug_output

        # Modbus 数据刷新定时器
        self._modbus_refresh_timer = QTimer()
        self._modbus_refresh_timer.timeout.connect(self._refresh_modbus_table)

        # Debug telemetry timer
        self._debug_telemetry_timer = QTimer(self)
        self._debug_telemetry_timer.timeout.connect(
            lambda: self._send_runtime_ipc(
                "get_visual_servo_telemetry",
                on_success=self._append_servo_telemetry,
                quiet=True,
            )
        )
        self._debug_telemetry_timer.start(1000)

        # Debug live vision timer
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

    def _set_status_visual(self, label, value):
        apply_status_visual(label, value)

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

    # ── 安全停止（紧急停止，走 Stop 通道 port 8766） ──

    def _update_emergency_stop_button(self):
        if not hasattr(self, "emergency_stop_btn"):
            return
        self.emergency_stop_btn.setText("安全停止")
        active = "true" if getattr(self, "_software_emergency_active", False) else "false"
        self.emergency_stop_btn.setProperty("active", active)
        self.emergency_stop_btn.style().unpolish(self.emergency_stop_btn)
        self.emergency_stop_btn.style().polish(self.emergency_stop_btn)

    def on_emergency_stop(self):
        """Software safe-stop via the dedicated Stop channel (port 8766).

        Bypasses the normal FIFO queue so it executes immediately even when
        a long-running command is blocking the command worker thread. The
        button is debounced (500 ms) and stays clickable regardless of
        command execution state.
        """
        import time as _time
        now = _time.monotonic()
        if now - getattr(self, "_last_emergency_click_ts", 0.0) < 0.5:
            return
        self._last_emergency_click_ts = now
        if getattr(self, "_emergency_cmd_running", False):
            return
        self._emergency_cmd_running = True
        self._send_runtime_ipc_stop(
            "safe_stop",
            on_success=lambda data: self._on_emergency_stop_finished(
                "safe_stop", bool(data.get("emergency_stop_sent"))
            ),
            on_failure=lambda msg: self._on_emergency_stop_finished(
                "safe_stop", False, error=msg
            ),
        )

    def _on_emergency_stop_finished(self, cmd_name, success, error=""):
        del cmd_name
        self._emergency_cmd_running = False
        if success:
            self._software_emergency_active = True
            self.statusBar().showMessage("安全停止已执行", 5000)
        else:
            self._software_emergency_active = False
            message = f"安全停止失败: {error}" if error else "安全停止失败"
            self.statusBar().showMessage(message, 5000)
        self._update_emergency_stop_button()

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

    def _clear_recovery(self):
        success, msg = self._runtime_facade.clear_recovery()
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
        page.connect_robot_requested.connect(self.connect_robot)

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