#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from .qt_compat import QImage, QThread, pyqtSignal
from .config_manager import get_point, set_point, resolve_point, get_performance_config
from .vision_system import FramePacket
from .arc_motion_controller import ArcMotionController
from .visual_servo_controller import VisualServoController

try:
    import cv2
except ImportError:
    cv2 = None

logger = logging.getLogger(__name__)


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


@dataclass
class FlowRunContext:
    """Unified context for a single flow execution run."""
    run_id: str
    start_time: float
    current_module_index: int = -1
    stop_event: threading.Event = field(default_factory=threading.Event)
    module_timings: list = field(default_factory=list)
    motion_generation: int = 0
    _flow_detection_cache: dict = field(default_factory=dict)

    def increment_motion_generation(self):
        self.motion_generation += 1

    def is_cache_valid(self, camera_type: str) -> bool:
        entry = self._flow_detection_cache.get(camera_type)
        if entry is None:
            return False
        if entry.get("motion_generation") != self.motion_generation:
            return False
        return True


def normalize_module_type(module: dict) -> dict:
    """Keep saved flows compatible after renaming force_arc to arc_motion."""
    if module.get("type") == "force_arc":
        module["type"] = "arc_motion"
    return module


def validate_grasp_flow_modules(modules: list) -> list:
    """Validate grasp flow module configuration before execution.

    Returns a list of error strings. Empty list means validation passed.
    """
    errors = []
    has_camera_before = set()  # camera types seen so far

    for i, module in enumerate(modules):
        normalize_module_type(module)
        step = i + 1
        name = module.get("name", f"模块{step}")
        mtype = module.get("type", "")
        params = module.get("params", {})

        if mtype == "move":
            target = params.get("target", "")
            if target == "camera_detected":
                camera_type = "D435i"  # default assumption
                if camera_type not in has_camera_before and "D405" not in has_camera_before:
                    errors.append(f"第{step}步「{name}」：目标为 camera_detected，但前面没有相机识别模块")
                motion_type = params.get("motion_type", "")
                point_name = params.get("point_name", "")
                if motion_type == "MovL" and not point_name.strip():
                    errors.append(f"第{step}步「{name}」：直线运动目标为 camera_detected，但未指定目标点位")
            elif target == "initial_position":
                from .config_manager import get_point
                if not get_point("initial_point"):
                    errors.append(f"第{step}步「{name}」：初始位置点位 initial_point 不存在")
            elif target == "saved_point":
                from .config_manager import get_point
                point_name = params.get("point_name", "")
                if not point_name.strip():
                    errors.append(f"第{step}步「{name}」：已保存点位未指定点位名称")
                elif not get_point(point_name):
                    errors.append(f"第{step}步「{name}」：点位 '{point_name}' 不存在")

        elif mtype == "arc_motion":
            center_offset_z = float(params.get('center_offset_z', params.get('radius', 0)))
            sweep_angle = float(params.get('sweep_angle', 0))
            if center_offset_z <= 0:
                errors.append(f"第{step}步「{name}」：圆弧上方距离必须大于0")
            if sweep_angle <= 0:
                errors.append(f"第{step}步「{name}」：圆弧角度必须大于0")

        elif mtype == "relative_path":
            segments = params.get("segments", [])
            if not segments:
                errors.append(f"第{step}步「{name}」：连续相对路径段列表为空")
            else:
                for seg_idx, seg in enumerate(segments):
                    offsets = [seg.get('x', 0), seg.get('y', 0), seg.get('z', 0),
                               seg.get('rx', 0), seg.get('ry', 0), seg.get('rz', 0)]
                    if all(float(v) == 0 for v in offsets):
                        errors.append(f"第{step}步第{seg_idx+1}段：偏移量全为0")

        elif mtype == "camera":
            camera_type = params.get("camera_type", "D435i")
            has_camera_before.add(camera_type)

    return errors


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
        self._ctx: Optional[FlowRunContext] = None
        self.performance_config = get_performance_config()
        self._flow_detection_cache = {}

    def _fail_module(self, ctx, module_index, module_name, reason):
        """Unified failure handler: record timing, emit log/signal, write alarm."""
        module_elapsed = time.perf_counter() - ctx.start_time - sum(t[2] for t in ctx.module_timings)
        ctx.module_timings.append((module_index + 1, module_name, module_elapsed, 0.0, 0.0, 0.0))
        self.flow_log.emit(f"❌ 模块{module_index + 1}失败: {reason}")
        self.controller.record_alarm("流程执行", f"模块{module_index + 1}", "故障", reason)
        self.flow_finished.emit(False)

    def stop(self):
        if self._ctx is not None:
            self._ctx.stop_event.set()
        self._stop_requested = True
        if self.is_paused_ref:
            self.is_paused_ref[0] = False

    def run(self):
        try:
            ctx = FlowRunContext(
                run_id=f"flow_{int(time.perf_counter() * 1000)}",
                start_time=time.perf_counter(),
            )
            self._ctx = ctx
            self.controller._active_flow_thread = self

            if not self.controller.acquire_motion("flow"):
                self.flow_log.emit("❌ 无法获取运动控制权，可能有其他操作正在执行")
                self.flow_finished.emit(False)
                return

            try:
                flow_start = ctx.start_time
                wait_poll_interval = float(self.performance_config.get("flow_wait_poll_interval", 0.05))
                pose_cache_max_age = float(self.performance_config.get("pose_cache_max_age", 0.3))
                stale_fail_age = float(self.performance_config.get("feedback_stale_fail_age", 2.0))
                modules = self.grasp_flow_modules
                total = len(modules)
                base_coords = None

                for i, module in enumerate(modules):
                    module_start = time.perf_counter()
                    camera_elapsed = 0.0
                    cmd_elapsed = 0.0
                    wait_elapsed = 0.0
                    ctx.current_module_index = i

                    if ctx.stop_event.is_set():
                        self._fail_module(ctx, i, module.get("name", f"模块{i+1}"), "用户停止")
                        return

                    while self.is_paused_ref[0]:
                        if ctx.stop_event.is_set():
                            self._fail_module(ctx, i, module.get("name", f"模块{i+1}"), "用户停止")
                            return
                        self.msleep(100)

                    module = normalize_module_type(module)
                    name = module.get("name", f"模块{i+1}")
                    self.flow_module_progress.emit(i + 1, total, name)

                    # --- Feedback health check before motion modules ---
                    if module['type'] in ("move", "arc_motion", "relative_move", "relative_path", "joint_move"):
                        fb = self.controller.get_feedback_health(max_age=pose_cache_max_age)
                        if fb["health"] == "disconnected":
                            self._fail_module(ctx, i, name, f"反馈缓存断流({stale_fail_age:.1f}s)")
                            return

                    # --- Auto-sync is_enabled from feedback RobotMode ---
                    if not self.controller.is_enabled and module['type'] in ("move", "arc_motion", "relative_move", "joint_move"):
                        robot_mode = self.controller.get_robot_mode_fast()
                        if robot_mode in (5, 7):
                            self.controller.is_enabled = True
                            self.flow_log.emit(f"🔄 检测到机器人模式{robot_mode}，自动同步使能状态")

                    stop_checker = lambda: ctx.stop_event.is_set()

                    if module['type'] == "move":
                        if module['params']['target'] == "initial_position":
                            if not self.controller.move_to_initial_position(verify_start_pose=False, verify_end_pose=False, wait_poll_interval=wait_poll_interval):
                                self._fail_module(ctx, i, name, "移动到初始位置失败")
                                return
                            move_timing = getattr(self.controller, '_last_move_timing', {})
                        elif module['params']['target'] == "camera_detected":
                            if base_coords is None:
                                self._fail_module(ctx, i, name, "相机未识别到物体坐标，请确保流程中先有相机识别步骤")
                                return
                            if module['params']['motion_type'] == "MovL":
                                point_name = module['params'].get('point_name', '')
                                if not point_name:
                                    self._fail_module(ctx, i, name, "直线运动未指定目标点位")
                                    return
                                resolved = resolve_point(point_name)
                                if resolved is None:
                                    self._fail_module(ctx, i, name, f"点位 '{point_name}' 不存在或循环引用")
                                    return
                                success = self.controller.move_to_point(
                                    resolved,
                                    move_type="MovL",
                                    speed_percentage=module['params']['speed'],
                                    verify_start_pose=False,
                                    verify_end_pose=False,
                                    wait_poll_interval=wait_poll_interval,
                                )
                                if not success:
                                    self._fail_module(ctx, i, name, "直线运动失败")
                                    return
                            move_timing = getattr(self.controller, '_last_move_timing', {})
                        elif module['params']['target'] == "saved_point":
                            point_name = module['params'].get('point_name', '')
                            if not point_name:
                                self._fail_module(ctx, i, name, "未指定目标点位名称")
                                return
                            resolved = resolve_point(point_name)
                            if resolved is None:
                                self._fail_module(ctx, i, name, f"点位 '{point_name}' 不存在或循环引用")
                                return
                            success = self.controller.move_to_point(
                                resolved,
                                move_type=module['params'].get('motion_type', 'MovJ'),
                                speed_percentage=module['params']['speed'],
                                verify_start_pose=False,
                                verify_end_pose=False,
                                wait_poll_interval=wait_poll_interval,
                            )
                            if not success:
                                self._fail_module(ctx, i, name, f"移动到点位 '{point_name}' 失败")
                                return
                            move_timing = getattr(self.controller, '_last_move_timing', {})
                        else:
                            move_timing = {}
                        speed_set_elapsed = move_timing.get("speed_set", 0.0)
                        command_send_elapsed = move_timing.get("command_send", 0.0)
                        motion_wait_elapsed = move_timing.get("motion_wait", 0.0)
                        cmd_elapsed = speed_set_elapsed + command_send_elapsed + motion_wait_elapsed
                        wait_elapsed = 0.0
                        ctx.increment_motion_generation()

                    elif module['type'] == "arc_motion":
                        if not self.controller.is_connected:
                            self._fail_module(ctx, i, name, "机器人未连接，无法执行圆弧运动")
                            return
                        if not self.controller.is_enabled:
                            self._fail_module(ctx, i, name, "机器人未使能，无法执行圆弧运动")
                            return
                        try:
                            p = dict(module['params'])
                            current_pose = self.controller.get_current_pose_fast(max_age=pose_cache_max_age)
                            if not current_pose or len(current_pose) < 6:
                                self._fail_module(ctx, i, name, "无法获取当前机器人位姿，无法生成圆弧")
                                return

                            center_offset_z = float(p.get('center_offset_z', p.get('radius', 50)))
                            sweep_angle = float(p.get('sweep_angle', abs(float(p.get('end_angle', 90)) - float(p.get('start_angle', 0)))))
                            arc_direction = p.get('arc_direction')
                            if arc_direction is None:
                                arc_direction = 'cw' if float(p.get('end_angle', 90)) < float(p.get('start_angle', 0)) else 'ccw'
                            if center_offset_z <= 0 or sweep_angle <= 0:
                                self._fail_module(ctx, i, name, "圆弧距离和角度必须大于0")
                                return

                            center = [
                                float(current_pose[0]),
                                float(current_pose[1]),
                                float(current_pose[2]) + center_offset_z,
                            ]
                            start_angle = -90.0
                            end_angle = start_angle - sweep_angle if arc_direction == 'cw' else start_angle + sweep_angle
                            base_orientation = [float(v) for v in current_pose[3:6]]
                            orientation = [
                                [base_orientation[0], base_orientation[1], base_orientation[2]],
                                [base_orientation[0], base_orientation[1], base_orientation[2]],
                                [base_orientation[0], base_orientation[1], base_orientation[2]],
                            ]
                            direction_text = "顺时针" if arc_direction == 'cw' else "逆时针"
                            self.flow_log.emit(
                                f"↪️ 圆弧运动: 当前点={current_pose[:3]}, 圆心={center}, "
                                f"距离={center_offset_z:.1f}mm, 角度={sweep_angle:.1f}°, "
                                f"方向={direction_text}, Rx={base_orientation[0]:.1f}(保持不变)"
                            )
                            fa_ctrl = ArcMotionController()
                            fa_ctrl.set_dashboard(self.controller.dashboard)
                            fa_ctrl.configure_arc(
                                center=center,
                                radius=center_offset_z,
                                start_angle=start_angle,
                                end_angle=end_angle,
                                rotation_axis='X',
                                num_waypoints=3,
                                orientation=orientation,
                                speed_factor=p.get('speed', 20)
                            )
                            cmd_start = time.perf_counter()
                            arc_command_id = fa_ctrl.execute(set_speed=False)
                            cmd_elapsed = time.perf_counter() - cmd_start
                            arc_length = abs(center_offset_z * np.deg2rad(sweep_angle))
                            timeout = min(max(arc_length / 20.0 + 5.0, 5.0), 60.0)
                            wait_start = time.perf_counter()
                            if not self.controller.wait_for_motion_completion(timeout=timeout, poll_interval=wait_poll_interval, stop_checker=stop_checker, command_id=arc_command_id):
                                self._fail_module(ctx, i, name, "圆弧运动等待完成失败")
                                return
                            wait_elapsed = time.perf_counter() - wait_start
                            self.flow_log.emit(f"✅ 模块{i+1}圆弧运动完成")
                        except Exception as e:
                            self._fail_module(ctx, i, name, f"圆弧运动失败: {e}")
                            return
                        ctx.increment_motion_generation()

                    elif module['type'] == "relative_move":
                        if not self.controller.is_connected:
                            self._fail_module(ctx, i, name, "机器人未连接，无法执行相对移动")
                            return
                        if not self.controller.is_enabled:
                            self._fail_module(ctx, i, name, "机器人未使能，无法执行相对移动")
                            return
                        p = module.get('params', {})
                        offsets = p.get('offsets', [0, 0, 0, 0, 0, 0])
                        coord_system = p.get('coord_system', 'user')
                        motion_type = p.get('motion_type', 'linear')
                        speed = int(p.get('speed', 30))
                        acceleration = int(p.get('acceleration', 20))
                        cp = int(p.get('cp', 100))
                        self.flow_log.emit(
                            f"➡️ 相对移动: 坐标系={coord_system}, 方式={motion_type}, "
                            f"偏移={offsets}, 速度={speed}%"
                        )
                        cmd_start = time.perf_counter()
                        success = self.controller.move_relative(
                            offsets=offsets,
                            coord_system=coord_system,
                            motion_type=motion_type,
                            speed=speed,
                            acceleration=acceleration,
                            cp=cp,
                            wait_poll_interval=wait_poll_interval,
                        )
                        cmd_elapsed = time.perf_counter() - cmd_start
                        wait_elapsed = 0.0
                        if not success:
                            self._fail_module(ctx, i, name, "相对移动失败")
                            return
                        self.flow_log.emit(f"✅ 模块{i+1}相对移动完成")
                        ctx.increment_motion_generation()

                    elif module['type'] == "relative_path":
                        if not self.controller.is_connected:
                            self._fail_module(ctx, i, name, "机器人未连接，无法执行连续相对路径")
                            return
                        if not self.controller.is_enabled:
                            self._fail_module(ctx, i, name, "机器人未使能，无法执行连续相对路径")
                            return
                        p = module['params']
                        # Global defaults
                        g_coord = str(p.get('coord_system', 'user')).lower()
                        g_motion = str(p.get('motion_type', 'linear')).lower()
                        g_speed = int(p.get('speed', 30))
                        g_accel = int(p.get('acceleration', 30))
                        g_cp = int(p.get('cp', 0))
                        execution_mode = str(p.get('execution_mode', 'stop_each')).lower()
                        segments = p.get('segments', [])

                        if not segments:
                            self._fail_module(ctx, i, name, "连续相对路径段列表为空")
                            return

                        active_segments = [s for s in segments if s.get('enabled', True)]
                        if not active_segments:
                            self._fail_module(ctx, i, name, "所有路径段均已禁用")
                            return

                        self.flow_log.emit(f"  连续相对路径: {len(active_segments)}/{len(segments)}段有效, 模式={execution_mode}")
                        last_enabled_seg_idx = [i for i, s in enumerate(segments) if s.get('enabled', True)][-1]

                        if execution_mode == "queued":
                            # Queued mode: send all commands, then wait once
                            queued_count = 0
                            for seg_idx, seg in enumerate(segments):
                                if not seg.get('enabled', True):
                                    continue
                                if ctx.stop_event.is_set():
                                    self._fail_module(ctx, i, name, f"用户停止（第{seg_idx+1}段下发前）")
                                    return
                                offsets = [
                                    float(seg.get('x', 0)), float(seg.get('y', 0)), float(seg.get('z', 0)),
                                    float(seg.get('rx', 0)), float(seg.get('ry', 0)), float(seg.get('rz', 0))
                                ]
                                seg_coord = str(seg.get('coord_system', g_coord)).lower()
                                seg_motion = str(seg.get('motion_type', g_motion)).lower()
                                seg_speed = int(seg.get('speed', g_speed))
                                seg_accel = int(seg.get('acceleration', g_accel))
                                seg_cp = int(seg.get('cp', g_cp))
                                seg_r = int(seg.get('r', -1))
                                # 最后一个启用段强制 r=-1，确保精确到达终点
                                if seg_idx == last_enabled_seg_idx:
                                    seg_r = -1
                                
                                # Direct command send without waiting
                                resp_code, seg_cmd_id = self.controller.send_relative_command(
                                    offsets=offsets,
                                    coord_system=seg_coord,
                                    motion_type=seg_motion,
                                    speed=seg_speed,
                                    acceleration=seg_accel,
                                    cp=seg_cp,
                                    r=seg_r,
                                    wait=False,
                                )
                                if resp_code is not False and resp_code == 0:
                                    queued_count += 1
                                    logger.info("relative_path queued seg %d: offsets=%s coord=%s speed=%d cp=%d r=%d cmd_id=%s", queued_count, offsets, seg_coord, seg_speed, seg_cp, seg_r, seg_cmd_id)
                                else:
                                    self._fail_module(ctx, i, name, f"第{seg_idx+1}段下发失败: offsets={offsets}")
                                    return
                            
                            # Wait for all queued motions to complete
                            self.flow_log.emit(f"  队列模式: {queued_count}段已下发, 等待完成...")
                            wait_ok = self.controller.wait_for_motion_completion(
                                timeout=60,
                                stop_checker=lambda: ctx.stop_event.is_set(),
                                command_id=self.controller._last_command_id,
                            )
                            if not wait_ok:
                                self._fail_module(ctx, i, name, "队列模式运动等待超时或被停止")
                                return
                            self.flow_log.emit(f"  队列模式完成")
                        
                        else:
                            # stop_each mode: each segment waits for completion
                            for seg_idx, seg in enumerate(segments):
                                if not seg.get('enabled', True):
                                    self.flow_log.emit(f"  段{seg_idx+1}: 已禁用，跳过")
                                    continue
                                if ctx.stop_event.is_set():
                                    self._fail_module(ctx, i, name, f"用户停止（第{seg_idx+1}段）")
                                    return
                                offsets = [
                                    float(seg.get('x', 0)), float(seg.get('y', 0)), float(seg.get('z', 0)),
                                    float(seg.get('rx', 0)), float(seg.get('ry', 0)), float(seg.get('rz', 0))
                                ]
                                seg_coord = str(seg.get('coord_system', g_coord)).lower()
                                seg_motion = str(seg.get('motion_type', g_motion)).lower()
                                seg_speed = int(seg.get('speed', g_speed))
                                seg_accel = int(seg.get('acceleration', g_accel))
                                seg_cp = int(seg.get('cp', g_cp))
                                seg_r = int(seg.get('r', -1))

                                seg_start = time.perf_counter()
                                success = self.controller.move_relative(
                                    offsets,
                                    coord_system=seg_coord,
                                    motion_type=seg_motion,
                                    speed=seg_speed,
                                    acceleration=seg_accel,
                                    cp=seg_cp,
                                    r=seg_r,
                                )
                                seg_elapsed = time.perf_counter() - seg_start

                                if not success:
                                    self._fail_module(ctx, i, name, f"第{seg_idx+1}段相对移动失败: offsets={offsets}")
                                    return

                                seg_name = seg.get('name', f'段{seg_idx+1}')
                                logger.info("relative_path seg %d/%d: name=%s offsets=%s coord=%s speed=%d cp=%d r=%d elapsed=%.3fs", seg_idx + 1, len(segments), seg_name, offsets, seg_coord, seg_speed, seg_cp, seg_r, seg_elapsed)
                                self.flow_log.emit(f"  段{seg_idx+1}/{len(segments)}「{seg_name}」: [{offsets[0]:.1f},{offsets[1]:.1f},{offsets[2]:.1f}] coord={seg_coord} speed={seg_speed}% cp={seg_cp} r={seg_r} %.3fs" % seg_elapsed)

                        ctx.increment_motion_generation()
                        cmd_elapsed = time.perf_counter() - module_start - camera_elapsed
                        wait_elapsed = 0.0

                    elif module['type'] == "camera":
                        camera_type = module['params'].get('camera_type', 'D435i')
                        if camera_type == "D405":
                            vision_to_use = self.vision_d405
                        else:
                            vision_to_use = self.vision_d435i

                        if vision_to_use is None:
                            self._fail_module(ctx, i, name, f"{camera_type} 相机未连接，无法识别物体")
                            return

                        cache_ttl = float(self.performance_config.get("flow_detection_cache_ttl", 1.0))
                        if ctx.is_cache_valid(camera_type):
                            entry = ctx._flow_detection_cache[camera_type]
                            if time.perf_counter() - entry["time"] <= cache_ttl:
                                best_result = entry["result"]
                                best_confidence = entry["confidence"]
                                self.flow_log.emit(f"✅ 复用{camera_type}最近识别结果，置信度={best_confidence:.2f}")
                            else:
                                best_result = None
                                best_confidence = 0.0
                        else:
                            best_result = None
                            best_confidence = 0.0

                        if best_result is None:
                            vision_to_use.reset_tracking()
                            camera_start = time.perf_counter()
                            N_FRAMES = max(1, int(self.performance_config.get("flow_camera_frames", 3)))
                            early_confidence = float(self.performance_config.get("flow_camera_early_confidence", 0.85))
                            best_result = None
                            best_confidence = 0.0

                            for frame_idx in range(N_FRAMES):
                                if ctx.stop_event.is_set():
                                    self._fail_module(ctx, i, name, "用户停止")
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
                                    if best_confidence >= early_confidence:
                                        self.flow_log.emit(f"✅ 置信度充足({best_confidence:.2f})，提前退出")
                                        break
                            camera_elapsed = time.perf_counter() - camera_start
                            if best_result:
                                ctx._flow_detection_cache[camera_type] = {
                                    "time": time.perf_counter(),
                                    "result": best_result,
                                    "confidence": best_confidence,
                                    "motion_generation": ctx.motion_generation,
                                }

                        min_confidence = float(self.performance_config.get("flow_camera_min_confidence", 0.3))
                        if not best_result or best_confidence < min_confidence:
                            self._fail_module(ctx, i, name, f"多帧检测失败，最高置信度={best_confidence:.2f}")
                            return

                        object_position = best_result
                        self.flow_log.emit(f"✅ 最终结果: 置信度={best_confidence:.2f}")

                        end_coords = vision_to_use.convert_to_end_coords(object_position['camera_coords'])
                        current_pose = self.controller.get_current_pose_fast(max_age=pose_cache_max_age)
                        if not current_pose:
                            self._fail_module(ctx, i, name, "无法获取当前机器人位姿")
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
                            self._fail_module(ctx, i, name, "D405 相机未连接，无法执行视觉伺服")
                            return

                        _vs_cfg = get_visual_servo_config()
                        p = module['params']
                        servo_ctrl = VisualServoController(
                            vision=self.vision_d405,
                            controller=self.controller,
                            servo_period=float(p.get('servo_period', _vs_cfg.get('servo_period', 0.06))),
                            servo_p_t=float(p['servo_p_t']) if p.get('servo_p_t') is not None else None,
                            servo_p_aheadtime=int(p.get('servo_p_aheadtime', 50)),
                            servo_p_gain=int(p.get('servo_p_gain', 500)),
                            gain_far=float(p.get('gain_far', _vs_cfg.get('gain_far', 0.8))),
                            gain_mid=float(p.get('gain_mid', _vs_cfg.get('gain_mid', 0.5))),
                            gain_near=float(p.get('gain_near', _vs_cfg.get('gain_near', 0.2))),
                            threshold_far=float(p.get('threshold_far', 50.0)),
                            threshold_mid=float(p.get('threshold_mid', 10.0)),
                            converge_threshold=float(p.get('converge_threshold', 3.0)),
                            max_iterations=int(p.get('max_iterations', 60)),
                            max_target_age=float(p.get('max_target_age', 0.3)),
                            max_pose_age=float(p.get('max_pose_age', 0.1)),
                            max_error_mm=float(p.get('max_error_mm', 300.0)),
                            z_safety_limit=float(p.get('z_safety_limit', 0.0)),
                            enable_feedforward=bool(p.get('enable_feedforward', False)),
                            yolo_every_n=int(p.get('yolo_every_n', _vs_cfg.get('yolo_every_n', 3))),
                            stop_on_converge=bool(p.get('stop_on_converge', _vs_cfg.get('stop_on_converge', False))),
                            max_step_far=float(p.get('max_step_far', _vs_cfg.get('max_step_far', 35.0))),
                            max_step_mid=float(p.get('max_step_mid', _vs_cfg.get('max_step_mid', 18.0))),
                            max_step_near=float(p.get('max_step_near', _vs_cfg.get('max_step_near', 6.0))),
                            max_step_fine=float(p.get('max_step_fine', _vs_cfg.get('max_step_fine', 2.0))),
                        )

                        def servo_log(msg):
                            self.flow_log.emit(msg)

                        success, final_error, iterations = servo_ctrl.servo_to_target(
                            log_callback=servo_log,
                        )

                        if not success:
                            self._fail_module(ctx, i, name, f"视觉伺服失败，最终误差={final_error:.1f}mm")
                            return

                        self.flow_log.emit(f"✅ 视觉伺服完成，误差={final_error:.1f}mm，迭代={iterations}次")
                        ctx.increment_motion_generation()

                    elif module['type'] == "joint_move":
                        offsets = module['params'].get('offsets', [0]*6)
                        acceleration = module['params'].get('acceleration', 20)
                        speed = module['params'].get('speed', 50)
                        cmd_start = time.perf_counter()
                        success = self.controller.move_joint_relative(
                            offsets,
                            a=acceleration,
                            v=speed,
                            verify_end_pose=False,
                            wait_poll_interval=wait_poll_interval,
                        )
                        cmd_elapsed = time.perf_counter() - cmd_start
                        wait_elapsed = 0.0
                        if not success:
                            self._fail_module(ctx, i, name, "关节旋转运动失败")
                            return
                        ctx.increment_motion_generation()

                    module_elapsed = time.perf_counter() - module_start
                    # For non-motion modules, cmd_elapsed equals total module time
                    if module['type'] not in ("move", "arc_motion", "relative_move", "relative_path", "joint_move"):
                        cmd_elapsed = module_elapsed
                    ctx.module_timings.append((i + 1, name, module_elapsed, camera_elapsed, cmd_elapsed, wait_elapsed))
                    logger.info("flow module %s/%s finished: %s total=%.3fs camera=%.3fs cmd=%.3fs wait=%.3fs", i + 1, total, name, module_elapsed, camera_elapsed, cmd_elapsed, wait_elapsed)
                    if module_elapsed > 1.0:
                        if module['type'] == "move":
                            logger.warning("flow module %s/%s SLOW: %s total=%.3fs speed_set=%.3fs cmd=%.3fs motion_wait=%.3fs camera=%.3fs", i + 1, total, name, module_elapsed, speed_set_elapsed, command_send_elapsed, motion_wait_elapsed, camera_elapsed)
                        else:
                            logger.warning("flow module %s/%s SLOW: %s total=%.3fs cmd=%.3fs wait=%.3fs camera=%.3fs", i + 1, total, name, module_elapsed, cmd_elapsed, wait_elapsed, camera_elapsed)

                self.flow_log.emit("✅ 抓取流程执行完成")
                total_elapsed = time.perf_counter() - flow_start
                summary = "; ".join(
                    f"{idx}.{module_name}={elapsed:.2f}s(cmd={cmd:.2f}s,wait={wait:.2f}s)"
                    for idx, module_name, elapsed, _, cmd, wait in ctx.module_timings
                )
                logger.info("flow finished total=%.3fs modules=[%s]", total_elapsed, summary)
                for idx, module_name, elapsed, cam_elapsed, cmd_e, wait_e in ctx.module_timings:
                    if elapsed > 0.5:
                        logger.info("  模块%d.%s: total=%.3fs cmd=%.3fs wait=%.3fs camera=%.3fs", idx, module_name, elapsed, cmd_e, wait_e, cam_elapsed)
                self.flow_log.emit(f"流程总耗时 {total_elapsed:.2f}s")
                self.flow_finished.emit(True)
            finally:
                self.controller.release_motion("flow")
                self._ctx = None
                self.controller._active_flow_thread = None
        except Exception as e:
            self.flow_log.emit(f"❌ 流程异常: {e}")
            self.flow_finished.emit(False)


class CaptureThread(threading.Thread):
    """Background thread that continuously captures frames into a latest-frame buffer."""

    def __init__(self, vision):
        super().__init__(daemon=True)
        self.vision = vision
        self.running = True
        self._lock = threading.Lock()
        self._latest_packet: Optional[FramePacket] = None
        self._seq = 0
        self._capture_ms = 0.0
        self._dropped = 0

    def run(self):
        while self.running:
            try:
                capture_start = time.perf_counter()
                packet = self.vision.capture_numpy_packet(self._seq)
                if packet is not None:
                    with self._lock:
                        if self._latest_packet is not None:
                            self._dropped += 1
                        self._latest_packet = packet
                        self._seq += 1
                    self._capture_ms = (time.perf_counter() - capture_start) * 1000.0
            except Exception:
                pass

    def get_latest(self):
        with self._lock:
            if self._latest_packet is None:
                return None, 0.0
            return self._latest_packet, self._capture_ms

    def stop(self):
        self.running = False


class CameraTestWorker(QThread):
    result_ready = pyqtSignal(dict)

    def __init__(self, vision, cam_type, controller):
        super().__init__()
        self.vision = vision
        self.cam_type = cam_type
        self.controller = controller
        self.running = True
        perf_config = getattr(self.vision, "performance_config", {})
        detection_fps = max(1.0, float(perf_config.get("camera_test_detection_fps", 10)))
        display_fps = max(1.0, float(perf_config.get("camera_test_display_fps", 10)))
        self.detection_interval = 1.0 / detection_fps
        self.display_interval = 1.0 / display_fps
        self.frame_interval = min(self.detection_interval, self.display_interval)
        self.performance_log_interval_frames = max(1, int(perf_config.get("performance_log_interval_frames", 30)))
        self.last_target = None
        self.last_object_position = None
        self._perf_count = 0
        self._perf_totals = {}
        self._last_perf_log = 0.0
        self._capture_thread = None
        self._frame_count = 0
        self._last_processed_seq = -1
        self._detect_every_n_frames = max(1, int(round(self.detection_interval / max(0.001, self.frame_interval))))

    def _record_performance(self, timings):
        self._perf_count += 1
        for key, value in timings.items():
            self._perf_totals[key] = self._perf_totals.get(key, 0.0) + value

        now = time.perf_counter()
        if self._perf_count % self.performance_log_interval_frames != 0 or now - self._last_perf_log < 3.0:
            return

        count = max(1, self._perf_count)
        parts = [
            f"{key}={total / count:.1f}ms" if key not in ('fps', 'dropped') else f"{key}={total / count:.1f}"
            for key, total in sorted(self._perf_totals.items())
        ]
        logger.info("performance[camera_test_worker] frames=%s %s", self._perf_count, " ".join(parts))
        self._perf_count = 0
        self._perf_totals = {}
        self._last_perf_log = now

    def run(self):
        self.vision.reset_tracking()
        self._capture_thread = CaptureThread(self.vision)
        self._capture_thread.start()

        while self.running:
            try:
                packet, capture_ms = self._capture_thread.get_latest()
                if packet is None or packet.seq == self._last_processed_seq:
                    self.msleep(5)
                    continue

                self._last_processed_seq = packet.seq
                self._frame_count += 1
                loop_start = time.perf_counter()

                # Detection (frame count based)
                should_detect = (self._frame_count % self._detect_every_n_frames) == 0
                should_display = True  # display every processed frame

                detection_start = time.perf_counter()
                if should_detect:
                    target = self.vision.run_detection_tracked(packet.color_image)
                    self.last_target = target
                    # Use numpy depth_image directly (calculate_object_position now accepts numpy)
                    self.last_object_position = self.vision.calculate_object_position_smoothed(
                        packet.depth_image, packet.color_image, target
                    )
                else:
                    target = self.last_target
                detection_done = time.perf_counter()

                object_position = self.last_object_position

                # Draw
                draw_start = time.perf_counter()
                q_img = None
                if should_display:
                    display_image = packet.color_image.copy()
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
                draw_done = time.perf_counter()

                # Build result
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
                        current_pose = self.controller.get_current_pose_fast()
                        if current_pose:
                            base_coords = self.vision.convert_to_base_coords(end_coords, current_pose)
                            result['base_coords'] = base_coords

                self.result_ready.emit(result)
                emit_done = time.perf_counter()

                # Performance logging
                dropped = self._capture_thread._dropped
                timings = {
                    "capture_thread": capture_ms,
                    "detection_loop": (detection_done - detection_start) * 1000.0 if should_detect else 0.0,
                    "draw_emit": (emit_done - draw_start) * 1000.0,
                    "total": (emit_done - loop_start) * 1000.0,
                    "fps": 1000.0 / max(0.1, (emit_done - loop_start) * 1000.0),
                    "dropped": float(dropped),
                }
                self._record_performance(timings)

            except Exception as e:
                self.result_ready.emit({'status': 'error', 'error_msg': str(e)[:100]})

        self._capture_thread.stop()
        self._capture_thread.join(timeout=3.0)

    def stop(self):
        self.running = False
        if self._capture_thread:
            self._capture_thread.stop()
            self._capture_thread.join(timeout=3.0)

