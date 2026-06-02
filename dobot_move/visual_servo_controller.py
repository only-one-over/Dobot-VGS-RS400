#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import numpy as np
import time

logger = logging.getLogger(__name__)


class VisualServoController:
    def __init__(self, vision, controller,
                 gain_far=0.6, gain_mid=0.4, gain_near=0.2,
                 threshold_far=50.0, threshold_mid=10.0,
                 converge_threshold=2.0,
                 max_step_mm=5.0,
                 max_iterations=60,
                 speed_far=10, speed_mid=5, speed_near=2,
                 enable_feedforward=True):
        self.vision = vision
        self.controller = controller
        self.gain_far = gain_far
        self.gain_mid = gain_mid
        self.gain_near = gain_near
        self.threshold_far = threshold_far
        self.threshold_mid = threshold_mid
        self.converge_threshold = converge_threshold
        self.max_step_mm = max_step_mm
        self.max_iterations = max_iterations
        self.speed_far = speed_far
        self.speed_mid = speed_mid
        self.speed_near = speed_near
        self.enable_feedforward = enable_feedforward

    def _adaptive_gain(self, error_mm):
        if error_mm > self.threshold_far:
            return self.gain_far, self.speed_far
        elif error_mm > self.threshold_mid:
            return self.gain_mid, self.speed_mid
        else:
            return self.gain_near, self.speed_near

    def _safety_clamp(self, cmd_pos, current_pos):
        cmd_pos = np.array(cmd_pos, dtype=np.float64)
        current_pos = np.array(current_pos, dtype=np.float64)
        delta = cmd_pos - current_pos
        distance = np.linalg.norm(delta)
        if distance > self.max_step_mm:
            delta = delta / distance * self.max_step_mm
            cmd_pos = current_pos + delta
        if cmd_pos[2] < 0:
            return None
        return cmd_pos

    def servo_to_target(self, target_type="grasp_point", log_callback=None):
        self.vision.reset_tracking()

        for i in range(self.max_iterations):
            depth_frame, color_frame = self.vision.capture_frames()
            if not depth_frame or not color_frame:
                if log_callback:
                    log_callback(f"🔄 迭代{i+1}: 无法捕获帧")
                continue

            color_image = np.asanyarray(color_frame.get_data())
            target = self.vision.run_detection_tracked(color_image)
            object_position = self.vision.calculate_object_position_smoothed(
                depth_frame, color_frame, target
            )

            if not object_position:
                if log_callback:
                    log_callback(f"🔄 迭代{i+1}: 检测失败")
                continue

            end_coords = self.vision.convert_to_end_coords(object_position['camera_coords'])
            current_pose = self.controller.get_current_pose()
            if not current_pose:
                if log_callback:
                    log_callback(f"🔄 迭代{i+1}: 无法获取位姿")
                continue

            base_coords = self.vision.convert_to_base_coords(end_coords, current_pose)
            if base_coords is None:
                if log_callback:
                    log_callback(f"🔄 迭代{i+1}: 坐标转换失败")
                continue

            if base_coords is None:
                if log_callback:
                    log_callback(f"🔄 迭代{i+1}: 目标坐标转换失败")
                continue

            e = np.array(base_coords[:3]) - np.array(current_pose[:3])
            error_mm = np.linalg.norm(e)

            if log_callback:
                conf = object_position.get('confidence', 0.0)
                log_callback(f"🔄 迭代{i+1}: 误差={error_mm:.1f}mm 置信度={conf:.2f}")

            if error_mm < self.converge_threshold:
                if log_callback:
                    log_callback(f"✅ 收敛成功! 最终误差={error_mm:.1f}mm, 迭代次数={i+1}")
                self._update_points(object_position, current_pose)
                return True, error_mm, i + 1

            gain, speed = self._adaptive_gain(error_mm)

            cmd_pos = np.array(current_pose[:3]) + e * gain

            if self.enable_feedforward and self.vision.kalman_3d is not None and self.vision.kalman_3d.initialized:
                v = self.vision.kalman_3d.x[3:6]
                ff = v * (1.0 / 30.0)
                cmd_pos = cmd_pos + ff

            cmd_pos = self._safety_clamp(cmd_pos, current_pose[:3])
            if cmd_pos is None:
                if log_callback:
                    log_callback(f"⚠️ 迭代{i+1}: 安全检查未通过(Z<0)")
                continue

            cmd_pose = list(cmd_pos) + list(current_pose[3:])
            success = self.controller.move_to_point(cmd_pose, move_type="MovL", speed_percentage=speed)
            if not success:
                if log_callback:
                    log_callback(f"⚠️ 迭代{i+1}: 运动指令失败")
                continue

        if log_callback:
            log_callback(f"❌ 视觉伺服超时, 迭代次数={self.max_iterations}")
        return False, error_mm if 'error_mm' in dir() else -1.0, self.max_iterations

    def _update_points(self, object_position, current_pose):
        from config_manager import get_point, set_point

        if 'camera_coords' in object_position:
            end_coords = self.vision.convert_to_end_coords(object_position['camera_coords'])
            base_coords = self.vision.convert_to_base_coords(end_coords, current_pose)
            if base_coords is not None:
                point_data = get_point("d435i") or {"coords": [0]*6, "is_relative": False, "relative_to": None, "offset": [0]*6, "is_default": True}
                point_data["coords"] = list(base_coords) + list(current_pose[3:])
                set_point("d435i", point_data)
