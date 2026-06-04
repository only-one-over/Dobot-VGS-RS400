#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import time
import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QImage
from config_manager import get_point, set_point, resolve_point
from force_arc_controller import ForceArcController
from visual_servo_controller import VisualServoController

try:
    import cv2
except ImportError:
    cv2 = None

logger = logging.getLogger(__name__)


class DeviceInitThread(QThread):
    init_finished = pyqtSignal(object)
    init_progress = pyqtSignal(str)
    init_error = pyqtSignal(str)

    def run(self):
        battery = None

        self.init_progress.emit("正在连接电池监控...")
        try:
            from battery_monitor import BatteryMonitor
            battery = BatteryMonitor()
            battery.connect()
        except Exception as e:
            self.init_error.emit(f"电池监控连接失败: {e}")
            battery = None

        self.init_finished.emit(battery)


class MonitorThread(QThread):
    data_updated = pyqtSignal(object)
    error_occurred = pyqtSignal(str)

    def __init__(self, device, read_fn, interval=200):
        super().__init__()
        self._device = device
        self._read_fn = read_fn
        self._interval = interval
        self._running = True

    def run(self):
        while self._running:
            if self._device.is_connected:
                try:
                    result = self._read_fn()
                    if result is not None:
                        self.data_updated.emit(result)
                except Exception as e:
                    self.error_occurred.emit(str(e))
            self.msleep(self._interval)

    def stop(self):
        self._running = False
        self.wait(3000)


class RobotCmdThread(QThread):
    """机器人指令后台执行线程"""
    cmd_finished = pyqtSignal(str, bool)

    def __init__(self, cmd_name, cmd_func, parent=None):
        super().__init__(parent)
        self._cmd_name = cmd_name
        self._cmd_func = cmd_func

    def run(self):
        try:
            result = self._cmd_func()
            self.cmd_finished.emit(self._cmd_name, bool(result))
        except Exception as e:
            logger.error(f"❌ 指令执行异常: {e}")
            self.cmd_finished.emit(self._cmd_name, False)


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
        self._stop_requested = False

    def stop(self):
        self._stop_requested = True
        if self.is_paused_ref:
            self.is_paused_ref[0] = False

    def run(self):
        try:
            modules = self.grasp_flow_modules
            total = len(modules)
            base_coords = None
            for i, module in enumerate(modules):
                if self._stop_requested:
                    self.flow_finished.emit(False)
                    return
                while self.is_paused_ref[0]:
                    if self._stop_requested:
                        self.flow_finished.emit(False)
                        return
                    self.msleep(100)
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
                        center_point_name = module['params'].get('center_point_name')
                        if not center_point_name:
                            self.flow_log.emit(f"❌ 模块{i+1}力控圆弧未指定圆心点位")
                            self.flow_finished.emit(False)
                            return
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
                elif module['type'] == "force_guard_move":
                    if not self.controller.is_connected:
                        self.flow_log.emit("❌ 机器人未连接，无法执行力阈值移动")
                        self.flow_finished.emit(False)
                        return
                    p = module.get('params', {})
                    axis = p.get('axis', 'Z')
                    distance = float(p.get('distance', 50.0))
                    force_limit = float(p.get('force_limit', 20.0))
                    speed = int(p.get('speed', 20))
                    self.flow_log.emit(
                        f"➡️ 力阈值移动: 方向={axis}, 距离={distance:.1f}mm, "
                        f"力上限={force_limit:.1f}N, 速度={speed}%"
                    )
                    success = self.controller.move_until_force_limit(
                        axis=axis,
                        distance=distance,
                        force_limit=force_limit,
                        speed_percentage=speed,
                    )
                    if not success:
                        self.flow_log.emit(f"❌ 模块{i+1}力阈值移动失败")
                        self.flow_finished.emit(False)
                        return
                    self.flow_log.emit(f"✅ 模块{i+1}力阈值移动完成")
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
                        if self._stop_requested:
                            self.flow_finished.emit(False)
                            return
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
        perf_config = getattr(self.vision, "performance_config", {})
        detection_fps = max(1.0, float(perf_config.get("camera_test_detection_fps", 10)))
        display_fps = max(1.0, float(perf_config.get("camera_test_display_fps", 10)))
        self.detection_interval = 1.0 / detection_fps
        self.display_interval = 1.0 / display_fps
        self.frame_interval = min(self.detection_interval, self.display_interval)
        self.performance_log_interval_frames = max(1, int(perf_config.get("performance_log_interval_frames", 30)))
        self.last_detection_time = 0
        self.last_display_time = 0
        self.last_target = None
        self.last_object_position = None
        self._perf_count = 0
        self._perf_totals = {}
        self._last_perf_log = 0.0

    def _record_performance(self, timings):
        self._perf_count += 1
        for key, value in timings.items():
            self._perf_totals[key] = self._perf_totals.get(key, 0.0) + value

        now = time.perf_counter()
        if self._perf_count % self.performance_log_interval_frames != 0 or now - self._last_perf_log < 3.0:
            return

        count = max(1, self._perf_count)
        parts = [
            f"{key}={total / count:.1f}ms"
            for key, total in sorted(self._perf_totals.items())
        ]
        logger.info("performance[camera_test_worker] frames=%s %s", self._perf_count, " ".join(parts))
        self._perf_count = 0
        self._perf_totals = {}
        self._last_perf_log = now

    def run(self):
        self.vision.reset_tracking()
        while self.running:
            try:
                loop_start = time.perf_counter()
                elapsed = time.time() - self.last_frame_time
                if elapsed < self.frame_interval:
                    self.msleep(int((self.frame_interval - elapsed) * 1000))
                    if not self.running:
                        break
                self.last_frame_time = time.time()

                depth_frame, color_frame = self.vision.capture_frames()
                if not depth_frame or not color_frame:
                    self.result_ready.emit({'status': 'no_frame'})
                    continue
                capture_done = time.perf_counter()

                color_image = np.asanyarray(color_frame.get_data())
                now = time.time()
                should_detect = now - self.last_detection_time >= self.detection_interval
                should_display = now - self.last_display_time >= self.display_interval
                detection_start = time.perf_counter()

                if should_detect:
                    target = self.vision.run_detection_tracked(color_image)
                    self.last_detection_time = now
                    self.last_target = target
                    self.last_object_position = self.vision.calculate_object_position_smoothed(depth_frame, color_frame, target)
                else:
                    target = self.last_target
                detection_done = time.perf_counter()

                object_position = self.last_object_position
                draw_start = time.perf_counter()
                q_img = None
                if should_display:
                    display_image = color_image.copy()
                    if target and not target.get('predicted', False):
                        bbox = target.get('bbox')
                        if bbox:
                            x1, y1, x2, y2 = bbox
                            cv2.rectangle(display_image, (x1, y1), (x2, y2), (0, 255, 0), 2)
                        mask = target.get('mask')
                        if mask is not None and np.any(mask > 0):
                            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                            cv2.drawContours(display_image, contours, -1, (0, 255, 0), 2)

                    rgb_image = cv2.cvtColor(display_image, cv2.COLOR_BGR2RGB)
                    h, w, ch = rgb_image.shape
                    bytes_per_line = ch * w
                    q_img = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format.Format_RGB888).copy()
                    self.last_display_time = now
                draw_done = time.perf_counter()

                result = {
                    'status': 'ok',
                    'object_position': object_position,
                    'cam_type': self.cam_type,
                }
                if q_img is not None:
                    result['q_image'] = q_img

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
                emit_done = time.perf_counter()
                timings = {
                    "capture": (capture_done - loop_start) * 1000.0,
                    "emit": (emit_done - draw_done) * 1000.0,
                    "total": (emit_done - loop_start) * 1000.0,
                }
                if should_detect:
                    timings["detect"] = (detection_done - detection_start) * 1000.0
                if should_display:
                    timings["draw_emit"] = (draw_done - draw_start) * 1000.0
                self._record_performance(timings)

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
        perf_config = getattr(self.vision, "performance_config", {})
        low_fps = max(1.0, float(perf_config.get("low_fps_detection_fps", 5)))
        self.frame_interval = 1.0 / low_fps
        self.last_frame_time = 0
        self.performance_log_interval_frames = max(1, int(perf_config.get("performance_log_interval_frames", 30)))
        self._perf_count = 0
        self._perf_totals = {}
        self._last_perf_log = 0.0

    def _record_performance(self, timings):
        self._perf_count += 1
        for key, value in timings.items():
            self._perf_totals[key] = self._perf_totals.get(key, 0.0) + value

        now = time.perf_counter()
        if self._perf_count % self.performance_log_interval_frames != 0 or now - self._last_perf_log < 3.0:
            return

        count = max(1, self._perf_count)
        parts = [
            f"{key}={total / count:.1f}ms"
            for key, total in sorted(self._perf_totals.items())
        ]
        logger.info("performance[d435i_low_fps_worker] frames=%s %s", self._perf_count, " ".join(parts))
        self._perf_count = 0
        self._perf_totals = {}
        self._last_perf_log = now

    def run(self):
        self.vision.reset_tracking()
        while self.running:
            try:
                loop_start = time.perf_counter()
                elapsed = time.time() - self.last_frame_time
                if elapsed < self.frame_interval:
                    self.msleep(int((self.frame_interval - elapsed) * 1000))
                    if not self.running:
                        break
                self.last_frame_time = time.time()

                depth_frame, color_frame = self.vision.capture_frames()
                if not depth_frame or not color_frame:
                    self.low_fps_result.emit({'status': 'no_frame'})
                    continue
                capture_done = time.perf_counter()

                color_image = np.asanyarray(color_frame.get_data())
                target = self.vision.run_detection_tracked(color_image)
                detection_done = time.perf_counter()
                object_position = self.vision.calculate_object_position_smoothed(depth_frame, color_frame, target)
                position_done = time.perf_counter()

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
                            result['current_pose'] = current_pose

                self.low_fps_result.emit(result)
                emit_done = time.perf_counter()
                self._record_performance(
                    {
                        "capture": (capture_done - loop_start) * 1000.0,
                        "detect": (detection_done - capture_done) * 1000.0,
                        "position": (position_done - detection_done) * 1000.0,
                        "emit": (emit_done - position_done) * 1000.0,
                        "total": (emit_done - loop_start) * 1000.0,
                    }
                )

            except Exception as e:
                self.low_fps_result.emit({'status': 'error', 'error_msg': str(e)[:100]})

    def stop(self):
        self.running = False
