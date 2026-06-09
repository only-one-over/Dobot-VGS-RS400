#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
机器人抓取控制程序 - 图形界面版本
"""

import sys
import time
import math
import numpy as np
import os
import json
import logging
from qt_compat import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QGroupBox, QGridLayout, QStatusBar,
    QMessageBox, QLineEdit, QDoubleSpinBox, QComboBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QFrame, QScrollArea, QStackedWidget,
    QCheckBox, QInputDialog, QSizePolicy,
    Qt, QThread, pyqtSignal, QTimer,
    QImage, QPixmap,
)

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from robot_controller import DobotController
from config_manager import get_robot_ip, get_modbus_port, get_grasp_flow_file, ConfigService
from workers import RobotCmdThread, FlowThread, CameraTestWorker, D435iLowFpsWorker
from gui_mixins import (
    RobotControlMixin,
    VisionMixin,
    ModbusMixin,
    PointManagementMixin,
    GraspFlowMixin,
    JogMixin,
)
from visual_servo_controller import VisualServoController
from ui_theme import apply_theme, apply_status_visual, set_button_role, NAV_ICONS, card_style, metric_label_style, metric_title_style
from flow_step_list import FlowStepList
from main_control_panel import MainControlPanel

logger = logging.getLogger(__name__)

try:
    from hand_eye_calib import HandEyeCalibManager
    HANDEYE_AVAILABLE = True
except Exception:
    HANDEYE_AVAILABLE = False

_missing_deps = []
try:
    import pyrealsense2 as rs
except ImportError:
    rs = None
    _missing_deps.append(("pyrealsense2", "pip install pyrealsense2\n注意: 需要先安装 Intel RealSense SDK\n下载地址: https://github.com/IntelRealSense/librealsense/releases"))

try:
    import cv2
except ImportError:
    cv2 = None
    _missing_deps.append(("opencv-python", "pip install opencv-python"))

try:
    import onnxruntime as ort
except ImportError:
    ort = None
    _missing_deps.append(("onnxruntime", "pip install onnxruntime"))

if _missing_deps:
    logger.error("=" * 60)
    logger.error("视觉系统导入失败，缺少以下依赖：")
    for dep_name, dep_hint in _missing_deps:
        logger.error(f"  ✗ {dep_name}")
        logger.error(f" 安装命令: {dep_hint}")
    logger.error("=" * 60)
    VISION_AVAILABLE = False
    rs = None
    cv2 = None
    class VisionSystem:
        def __init__(self):
            raise Exception("视觉系统不可用，缺少依赖: " + ", ".join(d[0] for d in _missing_deps))
        def close(self):
            pass
else:
    try:
        from vision_system import VisionSystem
        VISION_AVAILABLE = True
    except Exception as e:
        logger.error(f"视觉系统导入失败: {e}")
        VISION_AVAILABLE = False
        class VisionSystem:
            def __init__(self):
                raise Exception("视觉系统不可用")
            def close(self):
                pass

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

class DobotMainWindow(RobotControlMixin, VisionMixin, ModbusMixin, PointManagementMixin, GraspFlowMixin, JogMixin, QMainWindow):
    """机器人控制GUI"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Dobot VGS — 工业机器人仪表盘")
        self.setGeometry(100, 100, 1200, 750)
        self.setMinimumSize(1100, 760)
        
        self.set_dark_theme()
        
        self.robot_ip = get_robot_ip()
        self.controller = DobotController(self.robot_ip)
        self.vision_d435i = None
        self.vision_d405 = None
        
        file_path = get_grasp_flow_file()
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    self.grasp_flow_modules = json.load(f)
            except Exception as e:
                logger.error(f"加载抓取流程失败: {e}")
                self.grasp_flow_modules = list(_DEFAULT_GRASP_FLOW_MODULES)
        else:
            self.grasp_flow_modules = list(_DEFAULT_GRASP_FLOW_MODULES)
        
        self.is_paused = False
        self._flow_running = False
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
        QTimer.singleShot(100, self.start_monitor_threads)

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
        robot_card = QFrame()
        robot_card.setObjectName("statusCard")
        robot_card.setStyleSheet(card_style("#3b82f6"))
        robot_card_layout = QVBoxLayout(robot_card)
        robot_card_layout.setSpacing(2)
        robot_card_layout.setContentsMargins(10, 8, 10, 8)
        robot_title = QLabel("机器人")
        robot_title.setObjectName("cardTitle")
        robot_title.setStyleSheet(metric_title_style())
        self.robot_status_label = QLabel("未连接")
        self.robot_status_label.setObjectName("cardValue")
        self.robot_status_label.setStyleSheet(metric_label_style("#94a3b8"))
        robot_card_layout.addWidget(robot_title)
        robot_card_layout.addWidget(self.robot_status_label)
        status_layout.addWidget(robot_card)
        
        # 相机状态卡片
        camera_card = QFrame()
        camera_card.setObjectName("statusCard")
        camera_card.setStyleSheet(card_style("#06b6d4"))
        camera_card_layout = QVBoxLayout(camera_card)
        camera_card_layout.setSpacing(2)
        camera_card_layout.setContentsMargins(10, 8, 10, 8)
        camera_title = QLabel("相机")
        camera_title.setObjectName("cardTitle")
        camera_title.setStyleSheet(metric_title_style())
        self.camera_status_label = QLabel("未连接")
        self.camera_status_label.setObjectName("cardValue")
        self.camera_status_label.setStyleSheet(metric_label_style("#94a3b8"))
        camera_card_layout.addWidget(camera_title)
        camera_card_layout.addWidget(self.camera_status_label)
        status_layout.addWidget(camera_card)
        
        # 初始位置卡片
        pos_card = QFrame()
        pos_card.setObjectName("statusCard")
        pos_card.setStyleSheet(card_style("#8b5cf6"))
        pos_card_layout = QVBoxLayout(pos_card)
        pos_card_layout.setSpacing(2)
        pos_card_layout.setContentsMargins(10, 8, 10, 8)
        pos_title = QLabel("位置")
        pos_title.setObjectName("cardTitle")
        pos_title.setStyleSheet(metric_title_style())
        self.photo_position_label = QLabel(f"{self.controller.initial_pose}")
        self.photo_position_label.setObjectName("cardValue")
        self.photo_position_label.setStyleSheet(metric_label_style("#8b5cf6"))
        pos_card_layout.addWidget(pos_title)
        pos_card_layout.addWidget(self.photo_position_label)
        status_layout.addWidget(pos_card)
        # 力矩卡片
        torque_card = QFrame()
        torque_card.setObjectName("statusCard")
        torque_card.setStyleSheet(card_style("#f59e0b"))
        torque_card_layout = QVBoxLayout(torque_card)
        torque_card_layout.setSpacing(2)
        torque_card_layout.setContentsMargins(10, 8, 10, 8)
        torque_title = QLabel("力矩")
        torque_title.setObjectName("cardTitle")
        torque_title.setStyleSheet(metric_title_style())
        self.torque_label = QLabel("未连接")
        self.torque_label.setObjectName("cardValue")
        self.torque_label.setStyleSheet(metric_label_style("#94a3b8"))
        torque_card_layout.addWidget(torque_title)
        torque_card_layout.addWidget(self.torque_label)
        status_layout.addWidget(torque_card)
        
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
        self.main_control.run_grasp.connect(self.run_grasping_task)
        self.main_control.get_pose.connect(self.get_current_position)
        self.main_control.set_collision_level.connect(self.set_collision_level)
        self.main_control.clear_error.connect(self.on_clear_error)
        self.main_control.pause.connect(self.on_pause)
        self.main_control.resume.connect(self.on_continue)
        self.main_control.collision_level_changed.connect(self.on_collision_level_changed)
        self.main_control.ip_changed.connect(lambda ip: ConfigService.instance().set_ip('robot_ip', ip))
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
        self.get_pos_btn = self.main_control.get_pos_btn
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
        self.module_combo.addItems(["相机识别", "直线运动", "圆弧运动", "相对移动", "连续相对路径", "关节旋转", "视觉伺服"])
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

        read_current_btn = QPushButton("读取当前位置")
        read_current_btn.setMinimumWidth(120)
        read_current_btn.clicked.connect(self._on_read_current_for_linear)
        linear_layout.addWidget(read_current_btn)
        
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

        fa_layout.addWidget(fa_params_widget)
        self.camera_params = QWidget()
        camera_param_layout = QGridLayout(self.camera_params)
        camera_param_layout.setSpacing(10)

        camera_param_layout.addWidget(QLabel("选择相机:"), 0, 0)
        self.camera_module_combo = QComboBox()
        self.camera_module_combo.addItems(["D435i", "D405"])
        self.camera_module_combo.setCurrentIndex(0)
        camera_param_layout.addWidget(self.camera_module_combo, 0, 1)

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

        btn_x200 = QPushButton("X +200")
        btn_x200.clicked.connect(lambda: self._add_path_template(self.rpath_seg_table, "x200"))
        seg_btn_layout.addWidget(btn_x200)

        btn_zy200 = QPushButton("ZY 平面 200")
        btn_zy200.clicked.connect(lambda: self._add_path_template(self.rpath_seg_table, "zy200"))
        seg_btn_layout.addWidget(btn_zy200)

        btn_y200 = QPushButton("Y +200")
        btn_y200.clicked.connect(lambda: self._add_path_template(self.rpath_seg_table, "y200"))
        seg_btn_layout.addWidget(btn_y200)

        btn_z200 = QPushButton("Z +200")
        btn_z200.clicked.connect(lambda: self._add_path_template(self.rpath_seg_table, "z200"))
        seg_btn_layout.addWidget(btn_z200)

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
        
        self.load_flow_btn = QPushButton("加载流程")
        set_button_role(self.load_flow_btn, "secondary")
        self.load_flow_btn.clicked.connect(self.load_grasp_flow)
        flow_ops_layout.addWidget(self.load_flow_btn)
        
        self.run_flow_btn = QPushButton("执行流程")
        set_button_role(self.run_flow_btn, "primary")
        self.run_flow_btn.setDefault(True)
        self.run_flow_btn.clicked.connect(self.run_grasp_flow)
        flow_ops_layout.addWidget(self.run_flow_btn)
        
        grasp_flow_layout.addLayout(flow_ops_layout)
        grasp_flow_group.setLayout(grasp_flow_layout)
        motion_tab_layout.addWidget(grasp_flow_group)
        
        self._add_nav_page("运动编辑", self._wrap_in_scroll(motion_tab))

        point_tab = QWidget()
        point_tab_layout = QVBoxLayout(point_tab)
        point_tab_layout.setSpacing(10)
        point_tab_layout.setContentsMargins(10, 10, 10, 10)
        point_tab_layout.addWidget(point_mgmt_group)
        self._add_nav_page("点位管理", self._wrap_in_scroll(point_tab))
        # 机器人力控显示选项卡
        torque_tab = QWidget()
        torque_tab_layout = QVBoxLayout(torque_tab)
        torque_tab_layout.setSpacing(10)
        torque_tab_layout.setContentsMargins(10, 10, 10, 10)
        
        # 力矩数据显示
        torque_data_group = QGroupBox("关节力矩数据")
        torque_data_layout = QGridLayout()
        torque_data_layout.setSpacing(10)
        
        self.torque_joint1_label = QLabel("关节1: -- A")
        self.torque_joint2_label = QLabel("关节2: -- A")
        self.torque_joint3_label = QLabel("关节3: -- A")
        self.torque_joint4_label = QLabel("关节4: -- A")
        self.torque_joint5_label = QLabel("关节5: -- A")
        self.torque_joint6_label = QLabel("关节6: -- A")
        
        torque_data_layout.addWidget(self.torque_joint1_label, 0, 0)
        torque_data_layout.addWidget(self.torque_joint2_label, 0, 1)
        torque_data_layout.addWidget(self.torque_joint3_label, 1, 0)
        torque_data_layout.addWidget(self.torque_joint4_label, 1, 1)
        torque_data_layout.addWidget(self.torque_joint5_label, 2, 0)
        torque_data_layout.addWidget(self.torque_joint6_label, 2, 1)
        
        torque_data_group.setLayout(torque_data_layout)
        torque_tab_layout.addWidget(torque_data_group)
        
        self._add_nav_page("机器人力控", self._wrap_in_scroll(torque_tab))

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
        modbus_ctrl_layout.addWidget(self.modbus_status_label, 1, 0, 1, 4)

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

        jog_tab = QWidget()
        jog_tab_layout = QVBoxLayout(jog_tab)
        jog_tab_layout.setSpacing(10)
        jog_tab_layout.setContentsMargins(10, 10, 10, 10)

        mode_layout = QHBoxLayout()
        mode_layout.addWidget(QLabel("控制模式:"))
        self.jog_mode_combo = QComboBox()
        self.jog_mode_combo.addItem("坐标模式", 0)
        self.jog_mode_combo.addItem("轴模式", 1)
        self.jog_mode_combo.currentIndexChanged.connect(self._on_jog_mode_changed)
        mode_layout.addWidget(self.jog_mode_combo)
        mode_layout.addStretch()
        jog_tab_layout.addLayout(mode_layout)

        self.jog_stacked = QStackedWidget()

        coord_widget = QWidget()
        coord_layout = QVBoxLayout(coord_widget)
        coord_layout.setSpacing(10)

        coord_pos_group = QGroupBox("实时坐标")
        coord_pos_layout = QGridLayout()
        coord_pos_layout.setSpacing(5)
        self.coord_x_label = QLabel("X: --")
        self.coord_y_label = QLabel("Y: --")
        self.coord_z_label = QLabel("Z: --")
        self.coord_rx_label = QLabel("Rx: --")
        self.coord_ry_label = QLabel("Ry: --")
        self.coord_rz_label = QLabel("Rz: --")
        coord_pos_layout.addWidget(self.coord_x_label, 0, 0)
        coord_pos_layout.addWidget(self.coord_y_label, 0, 1)
        coord_pos_layout.addWidget(self.coord_z_label, 0, 2)
        coord_pos_layout.addWidget(self.coord_rx_label, 1, 0)
        coord_pos_layout.addWidget(self.coord_ry_label, 1, 1)
        coord_pos_layout.addWidget(self.coord_rz_label, 1, 2)
        coord_pos_group.setLayout(coord_pos_layout)
        coord_layout.addWidget(coord_pos_group)

        coord_target_group = QGroupBox("目标坐标")
        coord_target_layout = QGridLayout()
        coord_target_layout.setSpacing(5)
        self.coord_target_x = QDoubleSpinBox()
        self.coord_target_y = QDoubleSpinBox()
        self.coord_target_z = QDoubleSpinBox()
        self.coord_target_rx = QDoubleSpinBox()
        self.coord_target_ry = QDoubleSpinBox()
        self.coord_target_rz = QDoubleSpinBox()
        for i, (label, spinbox) in enumerate([("X:", self.coord_target_x), ("Y:", self.coord_target_y), ("Z:", self.coord_target_z), ("Rx:", self.coord_target_rx), ("Ry:", self.coord_target_ry), ("Rz:", self.coord_target_rz)]):
            spinbox.setRange(-9999, 9999)
            spinbox.setDecimals(2)
            coord_target_layout.addWidget(QLabel(label), i // 3, (i % 3) * 2)
            coord_target_layout.addWidget(spinbox, i // 3, (i % 3) * 2 + 1)
        self.coord_move_btn = QPushButton("运动到目标")
        self.coord_move_btn.setMinimumHeight(40)
        self.coord_move_btn.clicked.connect(self._on_coord_move_to_target)
        coord_target_layout.addWidget(self.coord_move_btn, 2, 0, 1, 6)
        coord_target_group.setLayout(coord_target_layout)
        coord_layout.addWidget(coord_target_group)

        coord_jog_group = QGroupBox("坐标点动")
        coord_jog_layout = QGridLayout()
        coord_jog_layout.setSpacing(5)
        coord_jog_layout.addWidget(self._create_jog_button("X-", "X-"), 0, 0)
        coord_jog_layout.addWidget(self._create_jog_button("X+", "X+"), 0, 1)
        coord_jog_layout.addWidget(self._create_jog_button("Y-", "Y-"), 1, 0)
        coord_jog_layout.addWidget(self._create_jog_button("Y+", "Y+"), 1, 1)
        coord_jog_layout.addWidget(self._create_jog_button("Z-", "Z-"), 2, 0)
        coord_jog_layout.addWidget(self._create_jog_button("Z+", "Z+"), 2, 1)
        coord_jog_layout.addWidget(self._create_jog_button("Rx-", "Rx-"), 3, 0)
        coord_jog_layout.addWidget(self._create_jog_button("Rx+", "Rx+"), 3, 1)
        coord_jog_layout.addWidget(self._create_jog_button("Ry-", "Ry-"), 4, 0)
        coord_jog_layout.addWidget(self._create_jog_button("Ry+", "Ry+"), 4, 1)
        coord_jog_layout.addWidget(self._create_jog_button("Rz-", "Rz-"), 5, 0)
        coord_jog_layout.addWidget(self._create_jog_button("Rz+", "Rz+"), 5, 1)
        coord_jog_group.setLayout(coord_jog_layout)
        coord_layout.addWidget(coord_jog_group)

        coord_type_layout = QHBoxLayout()
        coord_type_layout.addWidget(QLabel("坐标类型:"))
        self.jog_coord_combo = QComboBox()
        self.jog_coord_combo.addItem("用户坐标", 1)
        self.jog_coord_combo.addItem("工具坐标", 2)
        coord_type_layout.addWidget(self.jog_coord_combo)
        coord_type_layout.addStretch()
        coord_layout.addLayout(coord_type_layout)

        coord_layout.addStretch()
        self.jog_stacked.addWidget(coord_widget)

        axis_widget = QWidget()
        axis_layout = QVBoxLayout(axis_widget)
        axis_layout.setSpacing(10)

        axis_pos_group = QGroupBox("实时关节角度")
        axis_pos_layout = QGridLayout()
        axis_pos_layout.setSpacing(5)
        self.axis_j1_label = QLabel("J1: --")
        self.axis_j2_label = QLabel("J2: --")
        self.axis_j3_label = QLabel("J3: --")
        self.axis_j4_label = QLabel("J4: --")
        axis_pos_layout.addWidget(self.axis_j1_label, 0, 0)
        axis_pos_layout.addWidget(self.axis_j2_label, 0, 1)
        axis_pos_layout.addWidget(self.axis_j3_label, 1, 0)
        axis_pos_layout.addWidget(self.axis_j4_label, 1, 1)
        axis_pos_group.setLayout(axis_pos_layout)
        axis_layout.addWidget(axis_pos_group)

        axis_target_group = QGroupBox("目标关节角度")
        axis_target_layout = QGridLayout()
        axis_target_layout.setSpacing(5)
        self.axis_target_j1 = QDoubleSpinBox()
        self.axis_target_j2 = QDoubleSpinBox()
        self.axis_target_j3 = QDoubleSpinBox()
        self.axis_target_j4 = QDoubleSpinBox()
        for i, (label, spinbox) in enumerate([("J1:", self.axis_target_j1), ("J2:", self.axis_target_j2), ("J3:", self.axis_target_j3), ("J4:", self.axis_target_j4)]):
            spinbox.setRange(-9999, 9999)
            spinbox.setDecimals(2)
            axis_target_layout.addWidget(QLabel(label), i // 2, (i % 2) * 2)
            axis_target_layout.addWidget(spinbox, i // 2, (i % 2) * 2 + 1)
        self.axis_move_btn = QPushButton("运动到目标")
        self.axis_move_btn.setMinimumHeight(40)
        self.axis_move_btn.setEnabled(False)
        self.axis_move_btn.setToolTip("需补齐 J1-J6 后启用")
        self.axis_move_btn.clicked.connect(self._on_axis_move_to_target)
        axis_target_layout.addWidget(self.axis_move_btn, 2, 0, 1, 4)
        axis_target_group.setLayout(axis_target_layout)
        axis_layout.addWidget(axis_target_group)

        axis_jog_group = QGroupBox("关节点动")
        axis_jog_layout = QGridLayout()
        axis_jog_layout.setSpacing(5)
        axis_jog_layout.addWidget(self._create_jog_button("J1-", "J1-"), 0, 0)
        axis_jog_layout.addWidget(self._create_jog_button("J1+", "J1+"), 0, 1)
        axis_jog_layout.addWidget(self._create_jog_button("J2-", "J2-"), 1, 0)
        axis_jog_layout.addWidget(self._create_jog_button("J2+", "J2+"), 1, 1)
        axis_jog_layout.addWidget(self._create_jog_button("J3-", "J3-"), 2, 0)
        axis_jog_layout.addWidget(self._create_jog_button("J3+", "J3+"), 2, 1)
        axis_jog_layout.addWidget(self._create_jog_button("J4-", "J4-"), 3, 0)
        axis_jog_layout.addWidget(self._create_jog_button("J4+", "J4+"), 3, 1)
        axis_jog_group.setLayout(axis_jog_layout)
        axis_layout.addWidget(axis_jog_group)

        axis_layout.addStretch()
        self.jog_stacked.addWidget(axis_widget)

        jog_tab_layout.addWidget(self.jog_stacked)
        self._add_nav_page("点动控制", self._wrap_in_scroll(jog_tab))

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

        low_fps_group = QGroupBox("D435i 低帧率识别 (5fps)")
        low_fps_layout = QVBoxLayout()
        low_fps_layout.setSpacing(8)

        low_fps_btn_layout = QHBoxLayout()
        self.d435i_low_fps_start_btn = QPushButton("启动")
        self.d435i_low_fps_start_btn.clicked.connect(self.start_d435i_low_fps)
        low_fps_btn_layout.addWidget(self.d435i_low_fps_start_btn)

        self.d435i_low_fps_stop_btn = QPushButton("停止")
        self.d435i_low_fps_stop_btn.setEnabled(False)
        self.d435i_low_fps_stop_btn.clicked.connect(self.stop_d435i_low_fps)
        low_fps_btn_layout.addWidget(self.d435i_low_fps_stop_btn)

        self.d435i_low_fps_status = QLabel("状态: 已停止")
        apply_status_visual(self.d435i_low_fps_status, "已停止")
        low_fps_btn_layout.addWidget(self.d435i_low_fps_status)
        low_fps_btn_layout.addStretch()
        low_fps_layout.addLayout(low_fps_btn_layout)

        low_fps_coords_layout = QGridLayout()
        low_fps_coords_layout.setSpacing(6)

        low_fps_coords_layout.addWidget(QLabel("相机坐标:"), 0, 0)
        self.d435i_low_fps_cam_coords = QLabel("X: ---  Y: ---  Z: ---")
        low_fps_coords_layout.addWidget(self.d435i_low_fps_cam_coords, 0, 1)

        low_fps_coords_layout.addWidget(QLabel("末端坐标:"), 1, 0)
        self.d435i_low_fps_end_coords = QLabel("X: ---  Y: ---  Z: ---")
        low_fps_coords_layout.addWidget(self.d435i_low_fps_end_coords, 1, 1)

        low_fps_coords_layout.addWidget(QLabel("基座坐标:"), 2, 0)
        self.d435i_low_fps_base_coords = QLabel("X: ---  Y: ---  Z: ---")
        low_fps_coords_layout.addWidget(self.d435i_low_fps_base_coords, 2, 1)

        low_fps_layout.addLayout(low_fps_coords_layout)
        low_fps_group.setLayout(low_fps_layout)
        camera_test_layout.addWidget(low_fps_group)

        self.cam_test_worker = None

        self._add_nav_page("相机测试", self._wrap_in_scroll(camera_test_tab))

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
        self._refresh_action_states()

    def on_collision_level_changed(self, level):
        """碰撞等级下拉框变化回调。"""
        pass

    def _set_status_visual(self, label, value):
        apply_status_visual(label, value)

    def _update_emergency_stop_button(self):
        if not hasattr(self, "emergency_stop_btn"):
            return
        active = bool(
            getattr(self, "_software_emergency_active", False) or
            getattr(self.controller, "software_emergency_active", False)
        )
        self.emergency_stop_btn.setText("解除" if active else "急停")
        self.emergency_stop_btn.setProperty("active", "true" if active else "false")
        self.emergency_stop_btn.style().unpolish(self.emergency_stop_btn)
        self.emergency_stop_btn.style().polish(self.emergency_stop_btn)

    def _refresh_action_states(self):
        robot_ready = bool(getattr(self.controller, "is_connected", False))
        camera_ready = self.vision_d435i is not None or self.vision_d405 is not None
        flow_running = bool(getattr(self, "_flow_running", False))
        cmd_running = bool(getattr(self, "_cmd_running", False))

        for attr in (
            "enable_robot_btn", "disable_robot_btn", "get_pos_btn",
            "collision_set_btn", "clear_error_btn", "run_flow_btn",
        ):
            if hasattr(self, attr):
                getattr(self, attr).setEnabled(robot_ready and not flow_running and not cmd_running)

        if hasattr(self, "run_task_btn"):
            self.run_task_btn.setEnabled(robot_ready and camera_ready and not flow_running and not cmd_running)
        if hasattr(self, "connect_robot_btn"):
            self.connect_robot_btn.setEnabled(not robot_ready and not flow_running and not cmd_running)
        if hasattr(self, "pause_btn"):
            self.pause_btn.setEnabled(flow_running and not self.is_paused)
        if hasattr(self, "continue_btn"):
            self.continue_btn.setEnabled(flow_running and self.is_paused)
        if hasattr(self, "emergency_stop_btn"):
            self.emergency_stop_btn.setEnabled(robot_ready)
            self._update_emergency_stop_button()

    def _start_status_timer(self):
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._poll_status)
        self._status_timer.start(1000)
        self._poll_status()

    def _poll_status(self):
        if self.controller:
            if self.controller.is_connected:
                # Check 30004 feedback health separately
                fb_health = self.controller.get_feedback_health()
                if fb_health["health"] == "ok":
                    robot_status = "已连接"
                elif fb_health["health"] == "stale":
                    robot_status = "已连接(反馈延迟)"
                else:
                    robot_status = "已连接(反馈异常)"
            else:
                robot_status = "未连接"
            self.update_status("robot", robot_status)

        cameras = []
        if self.vision_d435i and hasattr(self.vision_d435i, "camera") and self.vision_d435i.camera:
            cameras.append("D435i")
        if self.vision_d405 and hasattr(self.vision_d405, "camera") and self.vision_d405.camera:
            cameras.append("D405")
        camera_status = "已连接(" + "+".join(cameras) + ")" if cameras else "未连接"
        self.update_status("camera", camera_status)
    
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
        # 防抖：500ms 内重复点击忽略
        import time as _time
        now = _time.monotonic()
        if now - getattr(self, '_last_emergency_click_ts', 0.0) < 0.5:
            return
        self._last_emergency_click_ts = now

        active = bool(
            getattr(self, "_software_emergency_active", False) or
            getattr(self.controller, "software_emergency_active", False)
        )
        if getattr(self, "_emergency_cmd_running", False):
            if not active:
                logger.warning("急停命令正在执行中，忽略重复点击")
                return
            # 解除急停时允许覆盖正在执行的急停命令
            logger.info("急停命令执行中，允许解除操作")
        if active:
            self.statusBar().showMessage("正在解除软件急停...")
            thread = RobotCmdThread("解除软件急停", self.controller.release_emergency_stop, self)
        else:
            # Immediately mark emergency active and stop flow
            self._software_emergency_active = True
            if hasattr(self, "_flow_thread") and self._flow_thread is not None and self._flow_thread.isRunning():
                self._flow_thread.stop()
            self.statusBar().showMessage("正在触发软件急停...")
            thread = RobotCmdThread("软件急停", self.controller.emergency_stop, self)
        self._emergency_thread = thread
        self._emergency_cmd_running = True
        self._refresh_action_states()
        thread.cmd_finished.connect(self._on_emergency_stop_finished)
        thread.finished.connect(thread.deleteLater)
        thread.start()

    def _on_emergency_stop_finished(self, cmd_name, success):
        self._emergency_cmd_running = False
        if cmd_name == "解除软件急停":
            if success:
                self._software_emergency_active = False
                self.statusBar().showMessage("软件急停已解除")
            else:
                self.statusBar().showMessage("解除软件急停失败")
        else:
            if success:
                self._software_emergency_active = True
                self.statusBar().showMessage("软件急停已触发")
            else:
                self.statusBar().showMessage("软件急停失败")
        if hasattr(self, "_refresh_alarm_table"):
            self._refresh_alarm_table()
        if hasattr(self, "_refresh_modbus_table"):
            self._refresh_modbus_table()
        self._refresh_action_states()

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
        records = self.controller.alarm_history.list_records()
        self.alarm_table.setRowCount(len(records))
        fields = ["time", "source", "code", "level", "description", "solution", "raw"]
        for row, record in enumerate(reversed(records)):
            for col, field in enumerate(fields):
                self.alarm_table.setItem(row, col, QTableWidgetItem(str(record.get(field, ""))))

    def _clear_alarm_history(self):
        reply = QMessageBox.question(
            self,
            "确认",
            "确定清空本地报警记录吗？这不会清除机器人真实报警。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.controller.alarm_history.clear()
            self._refresh_alarm_table()
    
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
                if camera_type == "D435i" and self.vision_d435i is not None:
                    self.vision_d435i.T_cam2gripper = matrix.copy()
                elif camera_type == "D405" and self.vision_d405 is not None:
                    self.vision_d405.T_cam2gripper = matrix.copy()
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
        if hasattr(self, '_status_timer') and self._status_timer is not None:
            self._status_timer.stop()
        if hasattr(self, 'cam_test_worker') and self.cam_test_worker is not None:
            self.cam_test_worker.stop()
            self.cam_test_worker.wait(3000)
            self.cam_test_worker = None
        if hasattr(self, '_low_fps_worker') and self._low_fps_worker is not None:
            self._low_fps_worker.stop()
            self._low_fps_worker.wait(3000)
            self._low_fps_worker = None
        if hasattr(self, '_flow_thread') and self._flow_thread is not None and self._flow_thread.isRunning():
            self._flow_thread.stop()
            self._flow_thread.wait(3000)

        self.stop_modbus_server()
        self.stop_monitor_threads()
        
        # 关闭相机
        if self.vision_d435i is not None:
            self.vision_d435i.close()
        if self.vision_d405 is not None:
            self.vision_d405.close()
        
        # 断开机器人连接
        if self.controller.is_connected:
            self.controller.disconnect()
        
        event.accept()

def main():
    """应用入口。"""
    from logging_config import setup_logging
    setup_logging()
    app = QApplication(sys.argv)
    window = DobotMainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
