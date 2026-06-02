#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
越疆机器人抓取控制程序 - 图形界面版本
"""

import sys
import time
import math
import numpy as np
import os
import json
import logging
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QGroupBox, QGridLayout, QStatusBar,
    QMessageBox, QTabWidget, QLineEdit, QDoubleSpinBox, QComboBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QFrame, QScrollArea, QStackedWidget,
    QRadioButton, QCheckBox, QInputDialog
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QPalette, QColor, QImage, QPixmap

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from robot_controller import DobotController
from config_manager import set_photo_position as config_set_photo_position, get_robot_ip, set_robot_ip as config_set_robot_ip, get_cart_ip, set_cart_ip as config_set_cart_ip, get_cart_port, set_cart_port as config_set_cart_port, get_modbus_port, set_modbus_port as config_set_modbus_port, get_points, get_point, set_point, add_point, delete_point, resolve_point
from workers import DeviceInitThread, StatusUpdateThread, MonitorThread, RobotCmdThread
from force_arc_controller import ForceArcController
from gui_mixins import (
    RobotControlMixin,
    VisionMixin,
    ModbusMixin,
    PointManagementMixin,
    ForceArcMixin,
    GraspFlowMixin,
    JogMixin,
)
from visual_servo_controller import VisualServoController

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
        logger.error(f"  ❌ {dep_name}")
        logger.error(f"     安装命令: {dep_hint}")
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
            "point_name": ""
        }
    }
]

class FlowThread(QThread):
    flow_log = pyqtSignal(str)
    flow_finished = pyqtSignal(bool)
    flow_module_progress = pyqtSignal(int, int, str)

    def __init__(self, controller, vision_d435i, vision_d405, grasp_flow_modules, is_paused_ref, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.vision_d435i = vision_d435i
        self.vision_d405 = vision_d405
        self.grasp_flow_modules = grasp_flow_modules
        self.is_paused_ref = is_paused_ref

    def run(self):
        try:
            modules = self.grasp_flow_modules
            total = len(modules)
            base_coords = None
            for i, module in enumerate(modules):
                while self.is_paused_ref[0]:
                    time.sleep(0.1)
                name = module.get("name", f"模块{i+1}")
                self.flow_module_progress.emit(i + 1, total, name)
                try:
                    if hasattr(self.controller, 'dashboard') and self.controller.dashboard:
                        mode = self.controller.dashboard.RobotMode()
                        mode_val = int(str(mode)) if mode is not None else -1
                        if mode_val == 9:
                            self.flow_log.emit("⚠️ 检测到报警，自动清除...")
                            self.controller.clear_error()
                            time.sleep(0.5)
                except Exception:
                    pass
                if module['type'] == "move":
                    if module['params']['target'] == "initial_position":
                        if not self.controller.move_to_initial_position():
                            self.flow_log.emit(f"❌ 模块{i+1}运动失败: 移动到初始位置失败")
                            self.flow_finished.emit(False)
                            return
                    elif module['params']['target'] == "camera_detected":
                        if base_coords is None:
                            self.flow_log.emit("❌ 相机未识别到物体坐标，请确保流程中先有相机识别步骤")
                            self.flow_finished.emit(False)
                            return
                        current_pose = self.controller.get_current_pose()
                        if not current_pose:
                            self.flow_log.emit("❌ 无法获取当前机器人位姿")
                            self.flow_finished.emit(False)
                            return
                        if module['params']['motion_type'] == "MovL":
                            point_name = module['params'].get('point_name', '')
                            if not point_name:
                                self.flow_log.emit(f"❌ 模块{i+1}直线运动未指定目标点位")
                                self.flow_finished.emit(False)
                                return
                            resolved = resolve_point(point_name)
                            if resolved is None:
                                self.flow_log.emit(f"❌ 点位 '{point_name}' 不存在或循环引用")
                                self.flow_finished.emit(False)
                                return
                            success = self.controller.move_to_point(
                                resolved,
                                move_type="MovL",
                                speed_percentage=module['params']['speed']
                            )
                            if not success:
                                self.flow_log.emit(f"❌ 模块{i+1}直线运动失败")
                                self.flow_finished.emit(False)
                                return
                elif module['type'] == "force_arc":
                    if not self.controller.is_connected:
                        self.flow_log.emit("❌ 机器人未连接，无法执行力控圆弧")
                        self.flow_finished.emit(False)
                        return
                    try:
                        p = dict(module['params'])
                        if module['params'].get('mode') == 'point' and module['params'].get('point_name'):
                            point_name = module['params']['point_name']
                            resolved = resolve_point(point_name)
                            if resolved is None:
                                self.flow_log.emit(f"❌ 点位 '{point_name}' 不存在或循环引用")
                                self.flow_finished.emit(False)
                                return
                            p['center'] = resolved[:3]
                        if module['params'].get('center_mode') == 'point' and module['params'].get('center_point_name'):
                            center_point_name = module['params']['center_point_name']
                            center_resolved = resolve_point(center_point_name)
                            if center_resolved is None:
                                self.flow_log.emit(f"❌ 圆心点位 '{center_point_name}' 不存在或循环引用")
                                self.flow_finished.emit(False)
                                return
                            p['center'] = center_resolved[:3]
                        fa_ctrl = ForceArcController()
                        fa_ctrl.set_dashboard(self.controller.dashboard)
                        fa_ctrl.configure_force_control(
                            deviation_pos=p['deviation_pos'],
                            deviation_rot=p['deviation_rot'],
                            controltype=1,
                            damping={
                                'x': p['damping_pos'], 'y': p['damping_pos'], 'z': p['damping_pos'],
                                'rx': p['damping_rot'], 'ry': p['damping_rot'], 'rz': p['damping_rot']
                            }
                        )
                        fa_ctrl.configure_arc(
                            center=p['center'],
                            radius=p['radius'],
                            start_angle=p['start_angle'],
                            end_angle=p['end_angle'],
                            rotation_axis=p['rotation_axis'],
                            num_waypoints=p['num_waypoints'],
                            speed_factor=p['speed']
                        )
                        fa_ctrl.execute(
                            fc_axes=p['fc_axes'],
                            correction_gain=p['correction_gain']
                        )
                        self.flow_log.emit(f"✅ 模块{i+1}力控圆弧运动完成")
                    except Exception as e:
                        self.flow_log.emit(f"❌ 模块{i+1}力控圆弧运动失败: {e}")
                        self.flow_finished.emit(False)
                        return
                elif module['type'] == "camera":
                    camera_type = module['params'].get('camera_type', 'D435i')
                    if camera_type == "D405":
                        vision_to_use = self.vision_d405
                    else:
                        vision_to_use = self.vision_d435i

                    if vision_to_use is None:
                        self.flow_log.emit(f"❌ {camera_type} 相机未连接，无法识别物体")
                        self.flow_finished.emit(False)
                        return

                    vision_to_use.reset_tracking()

                    N_FRAMES = 5
                    best_result = None
                    best_confidence = 0.0

                    for frame_idx in range(N_FRAMES):
                        depth_frame, color_frame = vision_to_use.capture_frames()
                        if not depth_frame or not color_frame:
                            continue
                        color_image = np.asanyarray(color_frame.get_data())

                        target = vision_to_use.run_detection_tracked(color_image)
                        object_position = vision_to_use.calculate_object_position_smoothed(depth_frame, color_frame, target)

                        if object_position:
                            conf = object_position.get('confidence', 0.0)
                            self.flow_log.emit(f"📊 帧{frame_idx+1}/{N_FRAMES} 置信度={conf:.2f} 来源={object_position.get('source', 'unknown')}")
                            if conf > best_confidence:
                                best_result = object_position
                                best_confidence = conf
                            if best_confidence > 0.9:
                                self.flow_log.emit(f"✅ 置信度充足({best_confidence:.2f})，提前退出")
                                break

                    if not best_result or best_confidence < 0.3:
                        self.flow_log.emit(f"❌ 多帧检测失败，最高置信度={best_confidence:.2f}")
                        self.flow_finished.emit(False)
                        return

                    object_position = best_result
                    self.flow_log.emit(f"✅ 最终结果: 置信度={best_confidence:.2f}")

                    end_coords = vision_to_use.convert_to_end_coords(object_position['camera_coords'])
                    current_pose = self.controller.get_current_pose()
                    if not current_pose:
                        self.flow_log.emit("❌ 无法获取当前机器人位姿")
                        self.flow_finished.emit(False)
                        return
                    base_coords = vision_to_use.convert_to_base_coords(end_coords, current_pose)

                    if base_coords is not None and current_pose is not None:
                        point_name = "d435i" if camera_type == "D435i" else "d405"
                        point_data = get_point(point_name) or {"coords": [0]*6, "is_relative": False, "relative_to": None, "offset": [0]*6, "is_default": True}
                        point_data["coords"] = list(base_coords) + list(current_pose[3:])
                        set_point(point_name, point_data)
                        self.flow_log.emit(f"📍 已更新点位 {point_name}")
                elif module['type'] == "visual_servo":
                    if self.vision_d405 is None:
                        self.flow_log.emit("❌ D405 相机未连接，无法执行视觉伺服")
                        self.flow_finished.emit(False)
                        return

                    target_type = module['params'].get('target_type', 'grasp_point')
                    converge_threshold = module['params'].get('converge_threshold', 2.0)
                    max_iterations = module['params'].get('max_iterations', 60)

                    servo_ctrl = VisualServoController(
                        vision=self.vision_d405,
                        controller=self.controller,
                        converge_threshold=converge_threshold,
                        max_iterations=max_iterations,
                    )

                    def servo_log(msg):
                        self.flow_log.emit(msg)

                    success, final_error, iterations = servo_ctrl.servo_to_target(
                        target_type=target_type,
                        log_callback=servo_log,
                    )

                    if not success:
                        self.flow_log.emit(f"❌ 视觉伺服失败，最终误差={final_error:.1f}mm")
                        self.flow_finished.emit(False)
                        return

                    self.flow_log.emit(f"✅ 视觉伺服完成，误差={final_error:.1f}mm，迭代={iterations}次")
                elif module['type'] == "joint_move":
                    offsets = module['params'].get('offsets', [0]*6)
                    acceleration = module['params'].get('acceleration', 20)
                    speed = module['params'].get('speed', 50)
                    success = self.controller.move_joint_relative(
                        offsets,
                        a=acceleration,
                        v=speed
                    )
                    if not success:
                        self.flow_log.emit(f"❌ 模块{i+1}关节旋转运动失败")
                        self.flow_finished.emit(False)
                        return
            self.flow_log.emit("✅ 抓取流程执行完成")
            self.flow_finished.emit(True)
        except Exception as e:
            self.flow_log.emit(f"❌ 流程异常: {e}")
            self.flow_finished.emit(False)

class CameraTestWorker(QThread):
    result_ready = pyqtSignal(dict)

    def __init__(self, vision, cam_type, controller):
        super().__init__()
        self.vision = vision
        self.cam_type = cam_type
        self.controller = controller
        self.running = True
        self.last_frame_time = 0
        self.frame_interval = 1.0 / 30.0

    def run(self):
        self.vision.reset_tracking()
        while self.running:
            try:
                elapsed = time.time() - self.last_frame_time
                if elapsed < self.frame_interval:
                    time.sleep(self.frame_interval - elapsed)
                self.last_frame_time = time.time()

                depth_frame, color_frame = self.vision.capture_frames()
                if not depth_frame or not color_frame:
                    self.result_ready.emit({'status': 'no_frame'})
                    continue

                color_image = np.asanyarray(color_frame.get_data())
                display_image = color_image

                target = self.vision.run_detection_tracked(color_image)

                if target and not target.get('predicted', False):
                    bbox = target.get('bbox')
                    if bbox:
                        x1, y1, x2, y2 = bbox
                        cv2.rectangle(display_image, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    mask = target.get('mask')
                    if mask is not None and np.any(mask > 0):
                        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                        cv2.drawContours(display_image, contours, -1, (0, 255, 0), 2)

                object_position = self.vision.calculate_object_position_smoothed(depth_frame, color_frame, target)

                rgb_image = cv2.cvtColor(display_image, cv2.COLOR_BGR2RGB)
                h, w, ch = rgb_image.shape
                bytes_per_line = ch * w
                q_img = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format.Format_RGB888).copy()

                result = {
                    'status': 'ok',
                    'q_image': q_img,
                    'object_position': object_position,
                    'cam_type': self.cam_type,
                }

                if object_position:
                    cam_coords = object_position.get('camera_coords', [])
                    result['cam_coords'] = cam_coords
                    result['confidence'] = object_position.get('confidence', 0.0)
                    result['source'] = object_position.get('source', 'unknown')

                    if self.controller.is_connected and len(cam_coords) >= 3:
                        end_coords = self.vision.convert_to_end_coords(cam_coords)
                        result['end_coords'] = end_coords
                        current_pose = self.controller.get_current_pose()
                        if current_pose:
                            base_coords = self.vision.convert_to_base_coords(end_coords, current_pose)
                            result['base_coords'] = base_coords


                self.result_ready.emit(result)

            except Exception as e:
                self.result_ready.emit({'status': 'error', 'error_msg': str(e)[:100]})

    def stop(self):
        self.running = False

class D435iLowFpsWorker(QThread):
    low_fps_result = pyqtSignal(dict)

    def __init__(self, vision, controller):
        super().__init__()
        self.vision = vision
        self.controller = controller
        self.running = True
        self.frame_interval = 1.0 / 5.0
        self.last_frame_time = 0

    def run(self):
        self.vision.reset_tracking()
        while self.running:
            try:
                elapsed = time.time() - self.last_frame_time
                if elapsed < self.frame_interval:
                    time.sleep(self.frame_interval - elapsed)
                self.last_frame_time = time.time()

                depth_frame, color_frame = self.vision.capture_frames()
                if not depth_frame or not color_frame:
                    self.low_fps_result.emit({'status': 'no_frame'})
                    continue

                color_image = np.asanyarray(color_frame.get_data())
                target = self.vision.run_detection_tracked(color_image)
                object_position = self.vision.calculate_object_position_smoothed(depth_frame, color_frame, target)

                result = {'status': 'ok', 'object_position': object_position}

                if object_position:
                    cam_coords = object_position.get('camera_coords', [])
                    result['cam_coords'] = cam_coords
                    result['confidence'] = object_position.get('confidence', 0.0)
                    result['source'] = object_position.get('source', 'unknown')

                    if self.controller.is_connected and len(cam_coords) >= 3:
                        end_coords = self.vision.convert_to_end_coords(cam_coords)
                        result['end_coords'] = end_coords
                        current_pose = self.controller.get_current_pose()
                        if current_pose:
                            base_coords = self.vision.convert_to_base_coords(end_coords, current_pose)
                            result['base_coords'] = base_coords
                            from config_manager import get_point, set_point
                            point_data = get_point("d435i") or {"coords": [0]*6, "is_relative": False, "relative_to": None, "offset": [0]*6, "is_default": True}
                            point_data["coords"] = list(base_coords) + list(current_pose[3:])
                            set_point("d435i", point_data)

                self.low_fps_result.emit(result)

            except Exception as e:
                self.low_fps_result.emit({'status': 'error', 'error_msg': str(e)[:100]})

    def stop(self):
        self.running = False

class DobotMainWindow(RobotControlMixin, VisionMixin, ModbusMixin, PointManagementMixin, ForceArcMixin, GraspFlowMixin, JogMixin, QMainWindow):
    """越疆机器人控制GUI"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("越疆机器人抓取控制程序")
        self.setGeometry(100, 100, 800, 600)
        
        self.set_blue_theme()
        
        self.robot_ip = get_robot_ip()
        self.controller = DobotController(self.robot_ip)
        self.vision_d435i = None
        self.vision_d405 = None
        self.battery = None
        self.battery_thread = None
        
        self.status_thread = StatusUpdateThread(self.controller, self.vision_d435i, self.vision_d405)
        self.status_thread.status_updated.connect(self.update_status)
        self.status_thread.start()
        
        _module_dir = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(_module_dir, "grasp_flow_modules.json")
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
        
        self.init_ui()
        if HANDEYE_AVAILABLE:
            self._load_calib_matrix("D435i")
        self.statusBar().showMessage("正在初始化设备连接...")
        QTimer.singleShot(100, self._deferred_init)

    @staticmethod
    def _wrap_in_scroll(widget):
        scroll = QScrollArea()
        scroll.setWidget(widget)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        return scroll

    def _deferred_init(self):
        self._device_init_thread = DeviceInitThread()
        self._device_init_thread.init_progress.connect(
            lambda msg: self.statusBar().showMessage(msg))
        self._device_init_thread.init_error.connect(
            lambda msg: logger.warning(msg))
        self._device_init_thread.init_finished.connect(self._on_device_initFinished)
        self._device_init_thread.start()
    
    def _on_device_initFinished(self, battery):
        self.battery = battery
        self.start_monitor_threads()
        self.statusBar().showMessage("设备初始化完成")
    
    def set_blue_theme(self):
        """设置蓝色主题"""
        # 创建调色板
        palette = QPalette()
        
        # 主背景色 - 浅蓝色
        palette.setColor(QPalette.ColorRole.Window, QColor(240, 248, 255))
        
        # 文本颜色 - 深蓝色
        palette.setColor(QPalette.ColorRole.WindowText, QColor(26, 35, 126))
        
        # 按钮颜色 - 白色
        palette.setColor(QPalette.ColorRole.Button, QColor(255, 255, 255))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(26, 35, 126))
        
        # 选中状态
        palette.setColor(QPalette.ColorRole.Highlight, QColor(33, 150, 243))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
        
        # 应用调色板
        self.setPalette(palette)
        
        # 设置全局样式
        self.setStyleSheet("""
            * {
                font-family: 'Segoe UI', Arial, sans-serif;
                font-size: 10pt;
            }
            QMainWindow {
                background-color: #f0f8ff;
            }
            QWidget {
                background-color: #f0f8ff;
            }
            QScrollArea {
                background-color: #f0f8ff;
                border: none;
            }
            QLineEdit {
                padding: 6px 10px;
                border: 1px solid #42a5f5;
                border-radius: 4px;
                background-color: white;
                color: #1a237e;
            }
            QLineEdit:hover {
                border-color: #2196f3;
            }
            QLineEdit:focus {
                border-color: #1976d2;
                outline: none;
            }
            QTableWidget {
                background-color: white;
                alternate-background-color: #e3f2fd;
                gridline-color: #bbdefb;
                border: 1px solid #42a5f5;
                border-radius: 4px;
                color: #1a237e;
            }
            QTableWidget::item {
                padding: 4px;
            }
            QTableWidget::item:selected {
                background-color: #2196f3;
                color: white;
            }
            QHeaderView::section {
                background-color: #e3f2fd;
                color: #1a237e;
                padding: 6px;
                border: 1px solid #bbdefb;
                font-weight: bold;
            }
            QScrollBar:vertical {
                background-color: #f0f8ff;
                width: 10px;
                border: none;
            }
            QScrollBar::handle:vertical {
                background-color: #90caf9;
                min-height: 30px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #42a5f5;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
            QScrollBar:horizontal {
                background-color: #f0f8ff;
                height: 10px;
                border: none;
            }
            QScrollBar::handle:horizontal {
                background-color: #90caf9;
                min-width: 30px;
                border-radius: 5px;
            }
            QScrollBar::handle:horizontal:hover {
                background-color: #42a5f5;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px;
            }
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
                background: none;
            }
            QGroupBox {
                font-weight: bold;
                border: 1px solid #42a5f5;
                border-radius: 8px;
                margin-top: 15px;
                background-color: white;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 10px 0 10px;
                color: #1a237e;
                background-color: white;
                border-radius: 4px;
            }
            QPushButton {
                padding: 8px 16px;
                border: 1px solid #42a5f5;
                border-radius: 6px;
                background-color: white;
                color: #1a237e;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #e3f2fd;
                border-color: #2196f3;
            }
            QPushButton:pressed {
                background-color: #bbdefb;
                border-color: #1976d2;
            }
            QPushButton:default {
                background-color: #2196f3;
                color: white;
                border-color: #1976d2;
            }
            QPushButton:default:hover {
                background-color: #1976d2;
            }
            QDoubleSpinBox, QComboBox {
                padding: 8px;
                border: 1px solid #42a5f5;
                border-radius: 4px;
                background-color: white;
                color: #1a237e;
                min-height: 30px;
            }
            QComboBox QAbstractItemView {
                background-color: white;
                color: #1a237e;
                selection-background-color: #e3f2fd;
                selection-color: #1a237e;
                border: 1px solid #42a5f5;
            }
            QDoubleSpinBox:hover, QComboBox:hover {
                border-color: #2196f3;
            }
            QDoubleSpinBox:focus, QComboBox:focus {
                border-color: #1976d2;
                outline: none;
            }
            QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
                width: 24px;
                height: 15px;
            }
            QDoubleSpinBox::up-arrow, QDoubleSpinBox::down-arrow {
                width: 10px;
                height: 10px;
            }
            QLabel {
                color: #1a237e;
            }
            QTabWidget::pane {
                border: 1px solid #42a5f5;
                border-radius: 8px;
                background-color: white;
            }
            QTabBar::tab {
                padding: 10px 20px;
                margin-right: 4px;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                background-color: #f0f8ff;
                color: #1a237e;
                border: 1px solid #42a5f5;
                border-bottom: none;
            }
            QTabBar::tab:selected {
                background-color: white;
                border-bottom: 1px solid white;
            }
            QTabBar::tab:hover {
                background-color: #e3f2fd;
            }
            QStatusBar {
                background-color: #e3f2fd;
                border-top: 1px solid #42a5f5;
                color: #1a237e;
            }
            QMessageBox {
                background-color: white;
                border: 1px solid #42a5f5;
                border-radius: 8px;
            }
            QMessageBox QLabel {
                color: #1a237e;
            }
            QMessageBox QPushButton {
                min-width: 80px;
            }
        """.strip())
    
    def init_ui(self):
        """初始化UI"""
        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 主布局
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # 状态显示区域
        status_group = QGroupBox("系统状态")
        status_layout = QGridLayout()
        status_layout.setSpacing(10)
        
        # 机器人状态
        self.robot_status_label = QLabel("机器人状态: 未连接")
        status_layout.addWidget(self.robot_status_label, 0, 0)
        
        # IP地址输入
        ip_label = QLabel("IP地址:")
        self.ip_input = QLineEdit(self.robot_ip)
        self.ip_input.setMaximumWidth(150)
        self.ip_input.setPlaceholderText("机器人IP地址")
        self.ip_input.editingFinished.connect(lambda: config_set_robot_ip(self.ip_input.text().strip()))
        status_layout.addWidget(ip_label, 0, 1)
        status_layout.addWidget(self.ip_input, 0, 2)
        
        # 相机状态
        self.camera_status_label = QLabel("相机状态: 未连接")
        status_layout.addWidget(self.camera_status_label, 1, 0)
        # 拍照位置
        self.photo_position_label = QLabel(f"拍照位置: {self.controller.initial_pose}")
        status_layout.addWidget(self.photo_position_label, 2, 0)
        
        self.battery_label = QLabel("电池: 未连接")
        status_layout.addWidget(self.battery_label, 2, 1, 1, 2)
        
        self.torque_label = QLabel("力矩: 未连接")
        status_layout.addWidget(self.torque_label, 3, 0)
        
        # 实时反馈按钮
        self.realtime_btn = QPushButton("📊 实时反馈")
        self.realtime_btn.clicked.connect(self.open_realtime_feedback)
        self.realtime_btn.setMinimumHeight(40)
        status_layout.addWidget(self.realtime_btn, 3, 1, 1, 2)
        
        status_group.setLayout(status_layout)
        main_layout.addWidget(status_group)
        
        # 功能选项卡
        self.tab_widget = QTabWidget()
        
        # 主功能选项卡
        main_tab = QWidget()
        main_tab_layout = QVBoxLayout(main_tab)
        main_tab_layout.setSpacing(10)
        main_tab_layout.setContentsMargins(10, 10, 10, 10)
        
        # 功能按钮布局
        button_layout = QGridLayout()
        button_layout.setSpacing(10)
        
        BTN_HEIGHT = 40
        
        # 运行抓取任务按钮
        self.run_task_btn = QPushButton("运行抓取任务")
        self.run_task_btn.setDefault(True)
        self.run_task_btn.clicked.connect(self.run_grasping_task)
        self.run_task_btn.setMinimumHeight(BTN_HEIGHT)
        button_layout.addWidget(self.run_task_btn, 0, 0, 1, 2)
        
        # 连接机器人按钮
        self.connect_robot_btn = QPushButton("连接机器人")
        self.connect_robot_btn.setDefault(True)
        self.connect_robot_btn.clicked.connect(self.connect_robot)
        self.connect_robot_btn.setMinimumHeight(BTN_HEIGHT)
        button_layout.addWidget(self.connect_robot_btn, 1, 0, 1, 2)
        
        # 使能机器人按钮
        self.enable_robot_btn = QPushButton("使能机器人")
        self.enable_robot_btn.clicked.connect(self.enable_robot)
        self.enable_robot_btn.setMinimumHeight(BTN_HEIGHT)
        button_layout.addWidget(self.enable_robot_btn, 2, 0)
        
        # 下使能机器人按钮
        self.disable_robot_btn = QPushButton("下使能机器人")
        self.disable_robot_btn.clicked.connect(self.disable_robot)
        self.disable_robot_btn.setMinimumHeight(BTN_HEIGHT)
        button_layout.addWidget(self.disable_robot_btn, 2, 1)
        
        self.d435i_status_label = QLabel("D435i: 未连接")
        self.d435i_status_label.setStyleSheet("color: gray;")
        button_layout.addWidget(self.d435i_status_label, 3, 0, 1, 2)

        self.d435i_connect_btn = QPushButton("D435i 连接")
        self.d435i_connect_btn.clicked.connect(self.connect_d435i)
        self.d435i_connect_btn.setMinimumHeight(BTN_HEIGHT)
        button_layout.addWidget(self.d435i_connect_btn, 4, 0)

        self.d435i_disconnect_btn = QPushButton("D435i 断开")
        self.d435i_disconnect_btn.clicked.connect(self.disconnect_d435i)
        self.d435i_disconnect_btn.setMinimumHeight(BTN_HEIGHT)
        self.d435i_disconnect_btn.setEnabled(False)
        button_layout.addWidget(self.d435i_disconnect_btn, 4, 1)

        self.d405_status_label = QLabel("D405: 未连接")
        self.d405_status_label.setStyleSheet("color: gray;")
        button_layout.addWidget(self.d405_status_label, 5, 0, 1, 2)

        self.d405_connect_btn = QPushButton("D405 连接")
        self.d405_connect_btn.clicked.connect(self.connect_d405)
        self.d405_connect_btn.setMinimumHeight(BTN_HEIGHT)
        button_layout.addWidget(self.d405_connect_btn, 6, 0)

        self.d405_disconnect_btn = QPushButton("D405 断开")
        self.d405_disconnect_btn.clicked.connect(self.disconnect_d405)
        self.d405_disconnect_btn.setMinimumHeight(BTN_HEIGHT)
        self.d405_disconnect_btn.setEnabled(False)
        button_layout.addWidget(self.d405_disconnect_btn, 6, 1)
        
        self.get_pos_btn = QPushButton("获取位置")
        self.get_pos_btn.clicked.connect(self.get_current_position)
        self.get_pos_btn.setMinimumHeight(BTN_HEIGHT)
        button_layout.addWidget(self.get_pos_btn, 7, 0)

        collision_label = QLabel("碰撞等级:")
        self.collision_combo = QComboBox()
        self.collision_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.collision_combo.addItems([
            "0-关闭碰撞检测",
            "1-最低灵敏度",
            "2-低灵敏度",
            "3-中灵敏度",
            "4-高灵敏度",
            "5-最高灵敏度"
        ])
        self.collision_combo.setCurrentIndex(3)
        button_layout.addWidget(collision_label, 8, 0)
        button_layout.addWidget(self.collision_combo, 8, 1)

        self.collision_set_btn = QPushButton("设置碰撞等级")
        self.collision_set_btn.clicked.connect(self.set_collision_level)
        self.collision_set_btn.setMinimumHeight(BTN_HEIGHT)
        button_layout.addWidget(self.collision_set_btn, 9, 0, 1, 2)

        self.clear_error_btn = QPushButton("清除故障")
        self.clear_error_btn.clicked.connect(self.on_clear_error)
        self.clear_error_btn.setMinimumHeight(BTN_HEIGHT)
        button_layout.addWidget(self.clear_error_btn, 10, 0, 1, 2)

        self.pause_btn = QPushButton("暂停")
        self.pause_btn.clicked.connect(self.on_pause)
        self.pause_btn.setMinimumHeight(BTN_HEIGHT)
        self.pause_btn.setEnabled(False)
        button_layout.addWidget(self.pause_btn, 11, 0)

        self.continue_btn = QPushButton("继续")
        self.continue_btn.clicked.connect(self.on_continue)
        self.continue_btn.setMinimumHeight(BTN_HEIGHT)
        self.continue_btn.setEnabled(False)
        button_layout.addWidget(self.continue_btn, 11, 1)

        main_tab_layout.addLayout(button_layout)
        self.tab_widget.addTab(self._wrap_in_scroll(main_tab), "主功能")
        
        # 参数设置选项卡
        param_tab = QWidget()
        param_tab_layout = QVBoxLayout(param_tab)
        param_tab_layout.setSpacing(10)
        param_tab_layout.setContentsMargins(10, 10, 10, 10)
        
        # 拍照位置设置
        photo_group = QGroupBox("拍照位置设置")
        photo_layout = QGridLayout()
        photo_layout.setSpacing(10)
        
        # 位置输入框
        positions = ["X", "Y", "Z", "RX", "RY", "RZ"]
        self.photo_position_inputs = []
        
        for i, pos in enumerate(positions):
            photo_layout.addWidget(QLabel(f"{pos}:"), i // 3, (i % 3) * 2)
            input_box = QDoubleSpinBox()
            # 设置不同的范围：位置±3000mm，角度±360度
            if pos in ["X", "Y", "Z"]:
                input_box.setRange(-3000, 3000)
            else:  # RX, RY, RZ
                input_box.setRange(-360, 360)
            input_box.setValue(self.controller.initial_pose[i])
            self.photo_position_inputs.append(input_box)
            photo_layout.addWidget(input_box, i // 3, (i % 3) * 2 + 1)
        
        self.set_photo_btn = QPushButton("设置拍照位置")
        self.set_photo_btn.setDefault(True)
        self.set_photo_btn.clicked.connect(self.set_photo_position)
        photo_layout.addWidget(self.set_photo_btn, 2, 0, 1, 3)
        
        self.get_photo_from_current_btn = QPushButton("从当前位置获取")
        self.get_photo_from_current_btn.clicked.connect(self._get_photo_from_current)
        photo_layout.addWidget(self.get_photo_from_current_btn, 2, 3, 1, 3)
        
        photo_group.setLayout(photo_layout)
        param_tab_layout.addWidget(photo_group)
        
        self.tab_widget.addTab(self._wrap_in_scroll(param_tab), "参数设置")
        
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
        self.flow_display_widget = QWidget()
        self.flow_display_layout = QVBoxLayout()
        self.flow_display_layout.setSpacing(5)
        self.flow_display_layout.setContentsMargins(15, 15, 15, 15)
        self.flow_display_widget.setLayout(self.flow_display_layout)
        # 设置对象名称（必须在设置样式表之前）
        self.flow_display_widget.setObjectName("flow_display_widget")
        # 只设置边框和圆角，不设置背景色和最小高度，避免影响子控件
        self.flow_display_widget.setStyleSheet("#flow_display_widget { border: 1px solid #42a5f5; border-radius: 6px; }")
        grasp_flow_layout.addWidget(self.flow_display_widget)
        
        # 存储步骤标签
        self.step_labels = []
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
        self.module_combo.addItems(["相机识别", "直线运动", "力控圆弧", "关节旋转", "视觉伺服"])
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

        self.linear_point_combo = QComboBox()
        linear_layout.addWidget(self.linear_point_combo)
        self.linear_point_preview = QLabel("")
        self.linear_point_preview.setStyleSheet("color: #666; font-size: 11px;")
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
        
        self.force_arc_params = QWidget()
        fa_layout = QVBoxLayout(self.force_arc_params)
        fa_layout.setSpacing(10)

        self.fa_mode = "coords"
        fa_mode_layout = QHBoxLayout()
        self.fa_coords_radio = QRadioButton("坐标模式")
        self.fa_coords_radio.setChecked(True)
        self.fa_point_radio = QRadioButton("点位模式")
        fa_mode_layout.addWidget(self.fa_coords_radio)
        fa_mode_layout.addWidget(self.fa_point_radio)
        fa_mode_layout.addStretch()
        fa_layout.addLayout(fa_mode_layout)

        self.fa_point_combo = QComboBox()
        self.fa_point_combo.hide()
        fa_layout.addWidget(self.fa_point_combo)
        self.fa_point_preview = QLabel("")
        self.fa_point_preview.setStyleSheet("color: #666; font-size: 11px;")
        self.fa_point_preview.hide()
        fa_layout.addWidget(self.fa_point_preview)
        self.fa_point_combo.currentTextChanged.connect(self._on_fa_point_selected)

        self.fa_center_mode = "coords"
        fa_center_mode_layout = QHBoxLayout()
        self.fa_center_coords_radio = QRadioButton("圆心坐标模式")
        self.fa_center_coords_radio.setChecked(True)
        self.fa_center_point_radio = QRadioButton("圆心点位模式")
        fa_center_mode_layout.addWidget(self.fa_center_coords_radio)
        fa_center_mode_layout.addWidget(self.fa_center_point_radio)
        fa_center_mode_layout.addStretch()
        fa_layout.addLayout(fa_center_mode_layout)

        self.fa_center_point_combo = QComboBox()
        self.fa_center_point_combo.hide()
        fa_layout.addWidget(self.fa_center_point_combo)
        self.fa_center_point_preview = QLabel("")
        self.fa_center_point_preview.setStyleSheet("color: #666; font-size: 11px;")
        self.fa_center_point_preview.hide()
        fa_layout.addWidget(self.fa_center_point_preview)

        self.fa_center_widget = QWidget()
        fa_center_layout = QGridLayout(self.fa_center_widget)
        fa_center_layout.setSpacing(10)

        fa_center_layout.addWidget(QLabel("圆心 X:"), 0, 0)
        self.fa_center_x = QDoubleSpinBox()
        self.fa_center_x.setRange(-1000, 1000)
        self.fa_center_x.setValue(400)
        fa_center_layout.addWidget(self.fa_center_x, 0, 1)

        fa_center_layout.addWidget(QLabel("圆心 Y:"), 0, 2)
        self.fa_center_y = QDoubleSpinBox()
        self.fa_center_y.setRange(-1000, 1000)
        self.fa_center_y.setValue(0)
        fa_center_layout.addWidget(self.fa_center_y, 0, 3)

        fa_center_layout.addWidget(QLabel("圆心 Z:"), 0, 4)
        self.fa_center_z = QDoubleSpinBox()
        self.fa_center_z.setRange(-1000, 1000)
        self.fa_center_z.setValue(300)
        fa_center_layout.addWidget(self.fa_center_z, 0, 5)
        fa_layout.addWidget(self.fa_center_widget)
        self.fa_center_coords_radio.toggled.connect(self._on_fa_center_mode_changed)
        self.fa_center_point_combo.currentTextChanged.connect(self._on_fa_center_point_selected)

        fa_params_widget = QWidget()
        fa_params_layout = QGridLayout(fa_params_widget)
        fa_params_layout.setSpacing(10)

        fa_params_layout.addWidget(QLabel("半径:"), 0, 0)
        self.fa_radius = QDoubleSpinBox()
        self.fa_radius.setRange(1, 500)
        self.fa_radius.setValue(50)
        fa_params_layout.addWidget(self.fa_radius, 0, 1)

        fa_params_layout.addWidget(QLabel("起始角度:"), 0, 2)
        self.fa_start_angle = QDoubleSpinBox()
        self.fa_start_angle.setRange(-360, 360)
        self.fa_start_angle.setValue(0)
        fa_params_layout.addWidget(self.fa_start_angle, 0, 3)

        fa_params_layout.addWidget(QLabel("终止角度:"), 0, 4)
        self.fa_end_angle = QDoubleSpinBox()
        self.fa_end_angle.setRange(-360, 360)
        self.fa_end_angle.setValue(90)
        fa_params_layout.addWidget(self.fa_end_angle, 0, 5)

        fa_params_layout.addWidget(QLabel("旋转轴:"), 1, 0)
        self.fa_rotation_axis = QComboBox()
        self.fa_rotation_axis.addItems(["X", "Y", "Z"])
        self.fa_rotation_axis.setCurrentIndex(2)
        fa_params_layout.addWidget(self.fa_rotation_axis, 1, 1)

        fa_params_layout.addWidget(QLabel("路点数:"), 1, 2)
        self.fa_num_waypoints = QDoubleSpinBox()
        self.fa_num_waypoints.setRange(2, 500)
        self.fa_num_waypoints.setValue(30)
        self.fa_num_waypoints.setDecimals(0)
        fa_params_layout.addWidget(self.fa_num_waypoints, 1, 3)

        fa_params_layout.addWidget(QLabel("速度:"), 1, 4)
        self.fa_speed = QDoubleSpinBox()
        self.fa_speed.setRange(1, 100)
        self.fa_speed.setValue(20)
        fa_params_layout.addWidget(self.fa_speed, 1, 5)

        fa_params_layout.addWidget(QLabel("力控轴 Rx:"), 2, 0)
        self.fa_fc_rx = QComboBox()
        self.fa_fc_rx.addItems(["开启", "关闭"])
        self.fa_fc_rx.setCurrentIndex(0)
        fa_params_layout.addWidget(self.fa_fc_rx, 2, 1)

        fa_params_layout.addWidget(QLabel("力控轴 Ry:"), 2, 2)
        self.fa_fc_ry = QComboBox()
        self.fa_fc_ry.addItems(["开启", "关闭"])
        self.fa_fc_ry.setCurrentIndex(0)
        fa_params_layout.addWidget(self.fa_fc_ry, 2, 3)

        fa_params_layout.addWidget(QLabel("力控轴 Rz:"), 2, 4)
        self.fa_fc_rz = QComboBox()
        self.fa_fc_rz.addItems(["开启", "关闭"])
        self.fa_fc_rz.setCurrentIndex(0)
        fa_params_layout.addWidget(self.fa_fc_rz, 2, 5)

        fa_params_layout.addWidget(QLabel("修正增益:"), 3, 0)
        self.fa_correction_gain = QDoubleSpinBox()
        self.fa_correction_gain.setRange(0.01, 2.0)
        self.fa_correction_gain.setValue(0.3)
        self.fa_correction_gain.setSingleStep(0.05)
        self.fa_correction_gain.setDecimals(2)
        fa_params_layout.addWidget(self.fa_correction_gain, 3, 1)

        fa_params_layout.addWidget(QLabel("偏差阈值(平移):"), 3, 2)
        self.fa_deviation_pos = QDoubleSpinBox()
        self.fa_deviation_pos.setRange(1, 500)
        self.fa_deviation_pos.setValue(100)
        fa_params_layout.addWidget(self.fa_deviation_pos, 3, 3)

        fa_params_layout.addWidget(QLabel("偏差阈值(旋转):"), 3, 4)
        self.fa_deviation_rot = QDoubleSpinBox()
        self.fa_deviation_rot.setRange(1, 180)
        self.fa_deviation_rot.setValue(36)
        fa_params_layout.addWidget(self.fa_deviation_rot, 3, 5)

        fa_params_layout.addWidget(QLabel("阻尼(平移):"), 4, 0)
        self.fa_damping_pos = QDoubleSpinBox()
        self.fa_damping_pos.setRange(1, 100)
        self.fa_damping_pos.setValue(50)
        fa_params_layout.addWidget(self.fa_damping_pos, 4, 1)

        fa_params_layout.addWidget(QLabel("阻尼(旋转):"), 4, 2)
        self.fa_damping_rot = QDoubleSpinBox()
        self.fa_damping_rot.setRange(0.1, 30)
        self.fa_damping_rot.setValue(5)
        self.fa_damping_rot.setDecimals(1)
        fa_params_layout.addWidget(self.fa_damping_rot, 4, 3)
        fa_layout.addWidget(fa_params_widget)

        self.fa_coords_radio.toggled.connect(self._on_fa_mode_changed)

        self.camera_params = QWidget()
        camera_param_layout = QGridLayout(self.camera_params)
        camera_param_layout.setSpacing(10)

        camera_param_layout.addWidget(QLabel("相机选择:"), 0, 0)
        self.camera_module_combo = QComboBox()
        self.camera_module_combo.addItems(["D435i", "D405"])
        self.camera_module_combo.setCurrentIndex(0)
        camera_param_layout.addWidget(self.camera_module_combo, 0, 1)
        
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
        self.view_flow_btn.clicked.connect(self.view_current_grasp_flow)
        flow_ops_layout.addWidget(self.view_flow_btn)
        
        self.save_flow_btn = QPushButton("保存流程")
        self.save_flow_btn.clicked.connect(self.save_grasp_flow)
        flow_ops_layout.addWidget(self.save_flow_btn)
        
        self.load_flow_btn = QPushButton("加载流程")
        self.load_flow_btn.clicked.connect(self.load_grasp_flow)
        flow_ops_layout.addWidget(self.load_flow_btn)
        
        self.run_flow_btn = QPushButton("执行流程")
        self.run_flow_btn.setDefault(True)
        self.run_flow_btn.clicked.connect(self.run_grasp_flow)
        flow_ops_layout.addWidget(self.run_flow_btn)
        
        grasp_flow_layout.addLayout(flow_ops_layout)
        grasp_flow_group.setLayout(grasp_flow_layout)
        motion_tab_layout.addWidget(grasp_flow_group)
        
        self.tab_widget.addTab(self._wrap_in_scroll(motion_tab), "运动编辑")

        point_tab = QWidget()
        point_tab_layout = QVBoxLayout(point_tab)
        point_tab_layout.setSpacing(10)
        point_tab_layout.setContentsMargins(10, 10, 10, 10)
        point_tab_layout.addWidget(point_mgmt_group)
        self.tab_widget.addTab(self._wrap_in_scroll(point_tab), "点位管理")

        # 电池电量显示选项卡
        battery_tab = QWidget()
        battery_tab_layout = QVBoxLayout(battery_tab)
        battery_tab_layout.setSpacing(10)
        battery_tab_layout.setContentsMargins(10, 10, 10, 10)
        
        # 电池数据显示
        battery_data_group = QGroupBox("电池实时数据")
        battery_data_layout = QGridLayout()
        battery_data_layout.setSpacing(10)
        
        self.battery_voltage_label = QLabel("电压: -- V")
        self.battery_current_label = QLabel("电流: -- A")
        self.battery_temperature_label = QLabel("温度: -- °C")
        self.battery_level_label = QLabel("电量: --%")
        
        battery_data_layout.addWidget(self.battery_voltage_label, 0, 0)
        battery_data_layout.addWidget(self.battery_current_label, 0, 1)
        battery_data_layout.addWidget(self.battery_temperature_label, 1, 0)
        battery_data_layout.addWidget(self.battery_level_label, 1, 1)
        
        battery_data_group.setLayout(battery_data_layout)
        battery_tab_layout.addWidget(battery_data_group)
        
        # 电池历史数据图表
        battery_chart_group = QGroupBox("电池历史数据")
        battery_chart_layout = QVBoxLayout()
        
        self.battery_chart_widget = QWidget()
        self.battery_chart_widget.setMinimumHeight(300)
        self.battery_chart_widget.setStyleSheet("border: 1px solid #42a5f5; border-radius: 6px;")
        
        # 简单的图表占位
        chart_label = QLabel("电池历史数据图表")
        chart_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chart_label.setStyleSheet("font-size: 14px; color: #1a237e;")
        chart_layout = QVBoxLayout(self.battery_chart_widget)
        chart_layout.addWidget(chart_label)
        
        battery_chart_layout.addWidget(self.battery_chart_widget)
        battery_chart_group.setLayout(battery_chart_layout)
        battery_tab_layout.addWidget(battery_chart_group)
        
        self.tab_widget.addTab(self._wrap_in_scroll(battery_tab), "电池电量")
        
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
        
        self.tab_widget.addTab(self._wrap_in_scroll(torque_tab), "机器人力控")

        # Modbus通信选项卡
        modbus_tab = QWidget()
        modbus_layout = QVBoxLayout(modbus_tab)
        modbus_layout.setSpacing(10)
        modbus_layout.setContentsMargins(10, 10, 10, 10)

        # Modbus控制区
        modbus_ctrl_group = QGroupBox("Modbus TCP 服务器")
        modbus_ctrl_layout = QGridLayout()
        modbus_ctrl_layout.setSpacing(10)

        modbus_ctrl_layout.addWidget(QLabel("监听端口:"), 0, 0)
        self.modbus_port_input = QLineEdit(str(get_modbus_port()))
        self.modbus_port_input.setMaximumWidth(100)
        self.modbus_port_input.editingFinished.connect(lambda: config_set_modbus_port(int(self.modbus_port_input.text().strip() or 502)))
        modbus_ctrl_layout.addWidget(self.modbus_port_input, 0, 1)

        self.modbus_start_btn = QPushButton("启动Modbus服务")
        self.modbus_start_btn.setMinimumHeight(40)
        self.modbus_start_btn.clicked.connect(self.start_modbus_server)
        modbus_ctrl_layout.addWidget(self.modbus_start_btn, 0, 2)

        self.modbus_stop_btn = QPushButton("停止Modbus服务")
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
        status_panel.setStyleSheet("""
            QFrame {
                background-color: #e3f2fd;
                border: 1px solid #42a5f5;
                border-radius: 6px;
                padding: 8px;
            }
        """)
        status_panel_layout = QHBoxLayout(status_panel)
        status_panel_layout.setSpacing(15)
        status_panel_layout.setContentsMargins(10, 5, 10, 5)

        self.modbus_cycle_label = QLabel(" 周期: 0")
        self.modbus_cycle_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #1a237e;")
        status_panel_layout.addWidget(self.modbus_cycle_label)

        self.modbus_duration_label = QLabel(" 耗时: 0ms")
        self.modbus_duration_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #1a237e;")
        status_panel_layout.addWidget(self.modbus_duration_label)

        self.modbus_status_panel_label = QLabel(" 状态: 停止")
        self.modbus_status_panel_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #1a237e;")
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

        # Modbus客户端面板 - 小车 (PC=Master)
        modbus_client_group = QGroupBox("Modbus TCP 客户端 - 小车 (PC=Master)")
        modbus_client_layout = QGridLayout()
        modbus_client_layout.setSpacing(10)

        modbus_client_layout.addWidget(QLabel("小车 IP:"), 0, 0)
        self.cart_ip_input = QLineEdit(get_cart_ip())
        self.cart_ip_input.setMaximumWidth(150)
        self.cart_ip_input.editingFinished.connect(lambda: config_set_cart_ip(self.cart_ip_input.text().strip()))
        modbus_client_layout.addWidget(self.cart_ip_input, 0, 1)

        modbus_client_layout.addWidget(QLabel("端口:"), 0, 2)
        self.cart_port_input = QLineEdit(str(get_cart_port()))
        self.cart_port_input.setMaximumWidth(80)
        self.cart_port_input.editingFinished.connect(lambda: config_set_cart_port(int(self.cart_port_input.text().strip() or 502)))
        modbus_client_layout.addWidget(self.cart_port_input, 0, 3)

        self.cart_connect_btn = QPushButton("连接小车")
        self.cart_connect_btn.setMinimumHeight(40)
        self.cart_connect_btn.clicked.connect(self.connect_cart_modbus)
        modbus_client_layout.addWidget(self.cart_connect_btn, 0, 4)

        self.cart_disconnect_btn = QPushButton("断开小车")
        self.cart_disconnect_btn.setMinimumHeight(40)
        self.cart_disconnect_btn.clicked.connect(self.disconnect_cart_modbus)
        self.cart_disconnect_btn.setEnabled(False)
        modbus_client_layout.addWidget(self.cart_disconnect_btn, 0, 5)

        self.cart_status_label = QLabel("小车状态: 未连接")
        modbus_client_layout.addWidget(self.cart_status_label, 1, 0, 1, 6)

        modbus_client_group.setLayout(modbus_client_layout)
        modbus_layout.addWidget(modbus_client_group)

        # 小车数据面板
        cart_data_panel = QFrame()
        cart_data_panel.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        cart_data_panel.setStyleSheet("""
            QFrame {
                background-color: #e8f5e9;
                border: 1px solid #66bb6a;
                border-radius: 6px;
                padding: 8px;
            }
        """)
        cart_data_layout = QHBoxLayout(cart_data_panel)
        cart_data_layout.setSpacing(15)
        cart_data_layout.setContentsMargins(10, 5, 10, 5)

        self.cart_info_label = QLabel(" 小车状态: --- | 故障码: --- | 位置 X: --- Y: --- Z: ---")
        self.cart_info_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #1b5e20;")
        cart_data_layout.addWidget(self.cart_info_label)
        cart_data_layout.addStretch()
        modbus_layout.addWidget(cart_data_panel)

        self.tab_widget.addTab(self._wrap_in_scroll(modbus_tab), "Modbus通信")

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
        self.tab_widget.addTab(self._wrap_in_scroll(jog_tab), "点动控制")

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

        self.tab_widget.addTab(self._wrap_in_scroll(calib_tab), "手眼标定")

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
        self.cam_test_image_label.setStyleSheet("background-color: black; color: white; font-size: 16px;")
        self.cam_test_image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cam_test_content.addWidget(self.cam_test_image_label)

        # 右侧: 坐标显示
        coord_group = QGroupBox("坐标信息")
        coord_layout = QVBoxLayout(coord_group)

        self.cam_test_status_label = QLabel("状态: 未开始")
        self.cam_test_status_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        coord_layout.addWidget(self.cam_test_status_label)

        coord_layout.addWidget(QLabel("相机坐标 (mm):"))
        self.cam_test_cam_coords = QLabel("X: ---  Y: ---  Z: ---")
        self.cam_test_cam_coords.setStyleSheet("font-family: monospace; font-size: 13px;")
        coord_layout.addWidget(self.cam_test_cam_coords)

        coord_layout.addWidget(QLabel("末端坐标 (mm):"))
        self.cam_test_end_coords = QLabel("X: ---  Y: ---  Z: ---")
        self.cam_test_end_coords.setStyleSheet("font-family: monospace; font-size: 13px;")
        coord_layout.addWidget(self.cam_test_end_coords)

        coord_layout.addWidget(QLabel("基座坐标 (mm):"))
        self.cam_test_base_coords = QLabel("X: ---  Y: ---  Z: ---")
        self.cam_test_base_coords.setStyleSheet("font-family: monospace; font-size: 13px;")
        coord_layout.addWidget(self.cam_test_base_coords)

        coord_layout.addWidget(QLabel("置信度:"))
        self.cam_test_confidence = QLabel("---")
        self.cam_test_confidence.setStyleSheet("font-family: monospace; font-size: 13px;")
        coord_layout.addWidget(self.cam_test_confidence)

        # D405 专用
        self.cam_test_d405_group = QGroupBox("D405 端点信息")
        d405_layout = QVBoxLayout(self.cam_test_d405_group)
        d405_layout.addWidget(QLabel("柄端坐标 (mm):"))
        self.cam_test_handle_coords = QLabel("X: ---  Y: ---  Z: ---")
        self.cam_test_handle_coords.setStyleSheet("font-family: monospace; font-size: 13px;")
        d405_layout.addWidget(self.cam_test_handle_coords)
        d405_layout.addWidget(QLabel("钩尖坐标 (mm):"))
        self.cam_test_tip_coords = QLabel("X: ---  Y: ---  Z: ---")
        self.cam_test_tip_coords.setStyleSheet("font-family: monospace; font-size: 13px;")
        d405_layout.addWidget(self.cam_test_tip_coords)
        d405_layout.addWidget(QLabel("铁钩长度:"))
        self.cam_test_hook_length = QLabel("--- mm")
        self.cam_test_hook_length.setStyleSheet("font-family: monospace; font-size: 13px;")
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
        self.d435i_low_fps_status.setStyleSheet("color: gray;")
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

        self.tab_widget.addTab(self._wrap_in_scroll(camera_test_tab), "相机测试")

        # Modbus数据刷新定时器
        self._modbus_refresh_timer = QTimer()
        self._modbus_refresh_timer.timeout.connect(self._refresh_modbus_table)

        self.refresh_points_table()

        main_layout.addWidget(self.tab_widget)
        
        # 状态栏
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就绪")
    
    def update_status(self, status_type, status_value):
        """更新状态显示"""
        if status_type == "robot":
            self.robot_status_label.setText(f"机器人状态: {status_value}")
        elif status_type == "camera":
            self.camera_status_label.setText(f"相机状态: {status_value}")
        elif status_type == "photo_position":
            self.photo_position_label.setText(f"拍照位置: {status_value}")
        elif status_type == "general":
            self.status_bar.showMessage(status_value)
    
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
        self.stop_modbus_server()
        self.disconnect_cart_modbus()
        self.stop_monitor_threads()
        
        self.status_thread.stop()
        
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
    """主函数"""
    from logging_config import setup_logging
    setup_logging()
    app = QApplication(sys.argv)
    window = DobotMainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()