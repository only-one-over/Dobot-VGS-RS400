#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pure-Python flow executor — no Qt dependency.

This module contains the flow execution logic that previously lived in
``FlowThread(QThread)``. By removing the QThread base class and
``pyqtSignal`` dependencies, the Runtime backend (``runtime_agent.py``)
can run without importing Qt at all.

Qt-aware callers (GUI) should use ``FlowThread`` from ``qt_workers.py``,
which wraps ``FlowExecutor`` and re-exposes Qt signals.
"""

import logging
import math
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np

from ..config.config_manager import (
    get_point,
    set_point,
    resolve_point,
    get_performance_config,
    get_visual_servo_config,
)
from ..vision.vision_system import FramePacket
from ..robot.arc_motion_controller import ArcMotionController
from ..robot.visual_servo_controller import VisualServoController

try:
    import cv2
except ImportError:
    cv2 = None

logger = logging.getLogger(__name__)


@dataclass
class FlowRunContext:
    """Unified context for a single flow execution run."""
    run_id: str
    start_time: float
    current_module_index: int = -1
    stop_event: threading.Event = field(default_factory=threading.Event)
    module_timings: list = field(default_factory=list)
    motion_generation: int = 0

    def increment_motion_generation(self):
        self.motion_generation += 1


def normalize_module_type(module: dict) -> dict:
    """Keep saved flows compatible after renaming force_arc to arc_motion."""
    if module.get("type") == "force_arc":
        module["type"] = "arc_motion"
    return module


def build_force_guard(params: dict):
    """Build normalized force guard config from a flow module params dict."""
    guard = params.get("force_guard") or {}
    if not guard or not guard.get("enabled"):
        return None
    try:
        threshold_n = float(guard.get("threshold_n", 0))
        baseline_samples = int(guard.get("baseline_samples", 3))
        baseline_interval = float(guard.get("baseline_interval", 0.02))
        debounce_samples = int(guard.get("debounce_samples", 1))
    except (TypeError, ValueError):
        threshold_n = 0.0
        baseline_samples = 3
        baseline_interval = 0.02
        debounce_samples = 1
    return {
        "enabled": True,
        "mode": "resultant_delta",
        "threshold_n": threshold_n,
        "baseline_samples": baseline_samples,
        "baseline_interval": baseline_interval,
        "debounce_samples": debounce_samples,
    }


def coerce_float_vector(value, min_len, label):
    """Convert list/tuple/numpy vectors to a plain float list with minimum length."""
    if value is None:
        raise ValueError(f"{label}长度不足")
    try:
        vector = np.asarray(value, dtype=float).reshape(-1).tolist()
    except (TypeError, ValueError) as e:
        raise ValueError(f"{label}格式无效: {e}") from e
    if len(vector) < min_len:
        raise ValueError(f"{label}长度不足: 需要至少{min_len}个值，实际{len(vector)}个")
    return vector


def wait_for_flow_delay_or_signal(
    duration_s,
    stop_event,
    is_paused_ref=None,
    poll_interval=0.05,
    signal_checker=None,
):
    """Wait until timeout, stop, or an optional external signal matches."""
    duration_s = float(duration_s)
    if not math.isfinite(duration_s) or duration_s <= 0:
        raise ValueError("延时时长必须是大于0的有限数值")

    poll_interval = max(0.001, float(poll_interval))
    remaining = duration_s
    last_tick = time.monotonic()

    while remaining > 0:
        if stop_event.is_set():
            return "stopped"

        now = time.monotonic()
        paused = bool(is_paused_ref and is_paused_ref[0])
        if not paused:
            remaining -= max(0.0, now - last_tick)
        last_tick = now

        if not paused and signal_checker is not None:
            try:
                if signal_checker():
                    return "signal"
            except Exception:
                logger.debug("延时模块读取外部信号失败", exc_info=True)

        if remaining <= 0:
            return "timeout"
        stop_event.wait(min(poll_interval, remaining) if not paused else poll_interval)

    return "timeout"


def wait_for_flow_delay(duration_s, stop_event, is_paused_ref=None, poll_interval=0.05):
    """Wait for a flow delay while remaining responsive to pause and stop."""
    result = wait_for_flow_delay_or_signal(
        duration_s,
        stop_event,
        is_paused_ref=is_paused_ref,
        poll_interval=poll_interval,
    )
    return result != "stopped"


def validate_grasp_flow_modules(modules: list) -> list:
    """Validate grasp flow module configuration before execution.

    Returns a list of error strings. Empty list means validation passed.
    """
    errors = []
    has_camera_before = set()  # camera types seen so far
    camera_point_names = {"D435i": "d435i", "D405": "d405"}

    for i, module in enumerate(modules):
        normalize_module_type(module)
        step = i + 1
        name = module.get("name", f"模块{step}")
        mtype = module.get("type", "")
        params = module.get("params", {})

        if mtype in ("move", "arc_motion", "relative_move", "relative_path"):
            guard = build_force_guard(params)
            if guard is not None and float(guard.get("threshold_n", 0)) <= 0:
                errors.append(f"第{step}步「{name}」：TCP力阈值必须大于0N")

        if mtype == "move":
            target = params.get("target", "")
            if target == "camera_detected":
                camera_type = "D435i"  # default assumption
                if camera_type not in has_camera_before and "D405" not in has_camera_before:
                    errors.append(f"第{step}步「{name}」：目标为 camera_detected，但前面没有相机识别模块")
                motion_type = params.get("motion_type", "")
                point_name = str(params.get("point_name", ""))
                if motion_type == "MovL" and not point_name.strip():
                    errors.append(f"第{step}步「{name}」：直线运动目标为 camera_detected，但未指定目标点位")
                expected_points = {camera_point_names.get(cam) for cam in has_camera_before}
                expected_points.discard(None)
                if point_name and point_name.lower() in set(camera_point_names.values()) and point_name.lower() not in expected_points:
                    expected_text = " 或 ".join(sorted(expected_points)) if expected_points else "前序相机点位"
                    errors.append(
                        f"第{step}步「{name}」：目标点位 '{point_name}' 与前序相机识别不一致，应使用 {expected_text}"
                    )
            elif target == "initial_position":
                from ..config.config_manager import get_point
                if not get_point("initial_point"):
                    errors.append(f"第{step}步「{name}」：初始位置点位 initial_point 不存在")
            elif target == "saved_point":
                from ..config.config_manager import get_point
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

        elif mtype == "delay":
            try:
                duration_s = float(params.get("duration_s", 0))
            except (TypeError, ValueError):
                duration_s = 0.0
            if not math.isfinite(duration_s) or duration_s <= 0:
                errors.append(f"第{step}步「{name}」：延时时长必须大于0秒")
            elif duration_s > 3600:
                errors.append(f"第{step}步「{name}」：延时时长不能超过3600秒")
            wait_mode = params.get("wait_mode", "time")
            if wait_mode not in ("time", "modbus_or_timeout"):
                errors.append(f"第{step}步「{name}」：延时等待方式无效")

    return errors


class FlowExecutor:
    """Pure-Python flow executor — no QThread base, no pyqtSignal.

    Replaces Qt signals with optional callbacks:
      - ``on_log(str)``           — flow log messages
      - ``on_finished(bool)``     — completion status
      - ``on_progress(int, int, str)`` — module progress (current, total, name)

    All callbacks default to ``None`` (silent). Qt callers should use
    ``FlowThread`` from ``qt_workers.py`` which wires these callbacks to
    ``pyqtSignal.emit``.
    """

    def __init__(
        self,
        controller,
        vision_d435i,
        vision_d405,
        grasp_flow_modules,
        is_paused_ref,
        camera_test_workers=None,
    ):
        self.controller = controller
        self.vision_d435i = vision_d435i
        self.vision_d405 = vision_d405
        self.grasp_flow_modules = grasp_flow_modules
        self.is_paused_ref = is_paused_ref
        self.camera_test_workers = camera_test_workers or {}
        self._stop_requested = False
        self._ctx: Optional[FlowRunContext] = None
        self.performance_config = get_performance_config()
        self.active_visual_servo = None
        self.last_visual_servo_telemetry = {}
        # Callback hooks (None = silent)
        self.on_log: Optional[Callable[[str], None]] = None
        self.on_finished: Optional[Callable[[bool], None]] = None
        self.on_progress: Optional[Callable[[int, int, str], None]] = None

    def get_visual_servo_telemetry(self):
        controller = self.active_visual_servo
        if controller is None:
            return dict(self.last_visual_servo_telemetry)
        servo = getattr(controller, "servo_thread", None)
        vision = getattr(controller, "vision_thread", None)
        if servo is None:
            return dict(self.last_visual_servo_telemetry)
        telemetry = {
            "running": bool(getattr(servo, "_running", False)),
            "error_mm": float(getattr(servo, "last_error_mm", 0.0)),
            "error_xyz_mm": list(
                getattr(servo, "last_error_xyz", [0.0, 0.0, 0.0])
            ),
            "final_error_mm": float(getattr(servo, "final_error_mm", -1.0)),
            "iterations": int(getattr(servo, "iterations", 0)),
            "period_ms": float(getattr(servo, "servo_period", 0.0)) * 1000.0,
            "loop_hz": float(getattr(servo, "last_hz", 0.0)),
            "target_age_ms": float(getattr(servo, "last_target_age", 0.0)) * 1000.0,
            "pose_age_ms": float(getattr(servo, "last_pose_age", 0.0)) * 1000.0,
            "servo_ms": float(getattr(servo, "last_servo_ms", 0.0)),
            "average_servo_ms": float(getattr(servo, "avg_servo_ms", 0.0)),
            "control_total_ms": float(getattr(servo, "last_total_ms", 0.0)),
            "capture_ms": float(getattr(vision, "last_capture_ms", 0.0)) if vision else 0.0,
            "inference_ms": float(getattr(vision, "last_detect_ms", 0.0)) if vision else 0.0,
            "depth_ms": float(getattr(vision, "last_depth_ms", 0.0)) if vision else 0.0,
            "vision_total_ms": float(getattr(vision, "last_total_ms", 0.0)) if vision else 0.0,
        }
        self.last_visual_servo_telemetry = telemetry
        return dict(telemetry)

    def _fail_module(self, ctx, module_index, module_name, reason):
        """Unified failure handler: record timing, emit log/signal, write alarm."""
        module_elapsed = time.perf_counter() - ctx.start_time - sum(t[2] for t in ctx.module_timings)
        ctx.module_timings.append((module_index + 1, module_name, module_elapsed, 0.0, 0.0, 0.0))
        if self.on_log:
            self.on_log(f"❌ 模块{module_index + 1}失败: {reason}")
        self.controller.record_alarm("流程执行", f"模块{module_index + 1}", "故障", reason)
        if self.on_finished:
            self.on_finished(False)

    def _log_force_guard_if_triggered(self, module_index, module_name):
        if getattr(self.controller, "_last_motion_completion_reason", None) != "force_triggered":
            return False
        event = getattr(self.controller, "_last_force_guard_event", None) or {}
        delta_n = float(event.get("delta_n", 0.0))
        threshold_n = float(event.get("threshold_n", 0.0))
        pose = event.get("pose")
        pose_text = ""
        if pose:
            pose_text = f", 当前点=[{pose[0]:.1f},{pose[1]:.1f},{pose[2]:.1f}]"
        if self.on_log:
            self.on_log(
                f"✅ 模块{module_index + 1}「{module_name}」TCP力触发停止: "
                f"{delta_n:.2f}N >= {threshold_n:.2f}N，继续下一步{pose_text}"
            )
        return True

    def _get_camera_test_worker(self, camera_type):
        worker = self.camera_test_workers.get(camera_type)
        if worker is None or not hasattr(worker, "get_flow_detection_snapshot"):
            return None
        if not bool(getattr(worker, "running", False)):
            return None
        try:
            if hasattr(worker, "isRunning") and not worker.isRunning():
                return None
        except Exception:
            return None
        return worker

    def _detect_camera_object_from_camera_test_worker(self, worker, camera_type, ctx, max_frames, early_confidence):
        """Reuse live camera-test detection snapshots so the flow does not open a second camera pipeline."""
        if hasattr(worker, "set_flow_detection_enabled"):
            worker.set_flow_detection_enabled(True)
        try:
            best_result = None
            best_confidence = 0.0
            best_frame = 0
            processed_frames = 0
            no_frame_polls = 0
            no_detection_frames = 0
            no_position_frames = 0
            start_snapshot = worker.get_flow_detection_snapshot() or {}
            start_seq = int(start_snapshot.get("seq", -1) or -1)
            last_seq = start_seq
            deadline = time.perf_counter() + max(3.0, float(max_frames) * 0.5)

            if self.on_log:
                self.on_log(f"{camera_type} 相机测试运行中，流程复用测试线程实时识别")

            while processed_frames < max_frames and time.perf_counter() < deadline:
                if ctx.stop_event.is_set():
                    return {
                        "object_position": None,
                        "confidence": 0.0,
                        "failure_reason": "用户停止",
                        "processed_frames": processed_frames,
                    }

                snapshot = worker.get_flow_detection_snapshot()
                if not snapshot:
                    no_frame_polls += 1
                    time.sleep(0.01)
                    continue

                seq = int(snapshot.get("seq", -1) or -1)
                if seq <= last_seq or seq <= start_seq:
                    no_frame_polls += 1
                    time.sleep(0.01)
                    continue

                last_seq = seq
                processed_frames += 1
                target = snapshot.get("target")
                object_position = snapshot.get("object_position")

                if target is None:
                    no_detection_frames += 1
                    if self.on_log:
                        self.on_log(
                            f"📊 {camera_type} 测试帧{processed_frames}/{max_frames}: 未检测到目标"
                        )
                    continue

                if (
                    not object_position
                    or len(object_position.get("camera_coords", [])) < 3
                ):
                    no_position_frames += 1
                    target_score = float(target.get("score", target.get("confidence", 0.0)) or 0.0)
                    if self.on_log:
                        self.on_log(
                            f"📊 {camera_type} 测试帧{processed_frames}/{max_frames}: "
                            f"检测到目标(score={target_score:.2f})，但深度/掩膜坐标计算失败"
                        )
                    continue

                conf = float(object_position.get("confidence", snapshot.get("confidence", 0.0)) or 0.0)
                source = object_position.get("source", "camera_test")
                if self.on_log:
                    self.on_log(
                        f"📊 {camera_type} 测试帧{processed_frames}/{max_frames}: "
                        f"置信度={conf:.2f} 来源={source}"
                    )
                if conf > best_confidence:
                    best_result = object_position
                    best_confidence = conf
                    best_frame = processed_frames
                if best_confidence >= early_confidence:
                    if self.on_log:
                        self.on_log(f"✅ 置信度充足({best_confidence:.2f})，提前退出")
                    break

            if best_result is not None:
                return {
                    "object_position": best_result,
                    "confidence": best_confidence,
                    "best_frame": best_frame,
                    "processed_frames": processed_frames,
                    "failure_reason": "",
                }

            if processed_frames == 0:
                reason = f"{camera_type} 相机测试未产生新的识别帧(no_frame_polls={no_frame_polls})"
            elif no_position_frames > 0:
                reason = (
                    f"检测到目标但深度/掩膜坐标计算失败"
                    f"(无检测{no_detection_frames}帧 坐标失败{no_position_frames}帧)"
                )
            else:
                reason = f"未检测到物品(处理{processed_frames}帧)"
            return {
                "object_position": None,
                "confidence": best_confidence,
                "processed_frames": processed_frames,
                "failure_reason": reason,
            }
        finally:
            if hasattr(worker, "set_flow_detection_enabled"):
                worker.set_flow_detection_enabled(False)

    def _detect_camera_object_for_flow(self, vision, camera_type, ctx, max_frames, early_confidence):
        """Run flow camera detection through the same numpy packet path as camera test."""
        worker = self._get_camera_test_worker(camera_type)
        if worker is not None:
            return self._detect_camera_object_from_camera_test_worker(
                worker,
                camera_type,
                ctx,
                max_frames,
                early_confidence,
            )

        # Lazy import: 纯 Python 采集线程，无 Qt 依赖。
        from ..vision.capture_worker import CaptureWorker

        vision.reset_tracking()
        capture_thread = CaptureWorker(vision)
        capture_thread.start()

        best_result = None
        best_confidence = 0.0
        best_frame = 0
        last_seq = -1
        processed_frames = 0
        no_frame_polls = 0
        no_detection_frames = 0
        no_position_frames = 0
        deadline = time.perf_counter() + max(3.0, float(max_frames) * 0.5)

        try:
            while processed_frames < max_frames and time.perf_counter() < deadline:
                if ctx.stop_event.is_set():
                    return {
                        "object_position": None,
                        "confidence": 0.0,
                        "failure_reason": "用户停止",
                        "processed_frames": processed_frames,
                    }

                packet, capture_ms = capture_thread.get_latest()
                if packet is None or packet.seq == last_seq:
                    no_frame_polls += 1
                    time.sleep(0.005)
                    continue

                last_seq = packet.seq
                processed_frames += 1

                target = vision.run_detection_tracked(packet.color_image)
                if target is None:
                    no_detection_frames += 1
                    if self.on_log:
                        self.on_log(
                            f"📊 {camera_type} 帧{processed_frames}/{max_frames}: 未检测到目标"
                        )
                    continue

                object_position = vision.calculate_object_position_smoothed(
                    packet.depth_image,
                    packet.color_image,
                    target,
                )
                if (
                    not object_position
                    or len(object_position.get("camera_coords", [])) < 3
                ):
                    no_position_frames += 1
                    target_score = float(target.get("score", target.get("confidence", 0.0)) or 0.0)
                    if self.on_log:
                        self.on_log(
                            f"📊 {camera_type} 帧{processed_frames}/{max_frames}: "
                            f"检测到目标(score={target_score:.2f})，但深度/掩膜坐标计算失败"
                        )
                    continue

                conf = float(object_position.get("confidence", target.get("score", 0.0)) or 0.0)
                source = object_position.get("source", "unknown")
                if self.on_log:
                    self.on_log(
                        f"📊 {camera_type} 帧{processed_frames}/{max_frames}: "
                        f"置信度={conf:.2f} 来源={source} capture={capture_ms:.1f}ms"
                    )
                if conf > best_confidence:
                    best_result = object_position
                    best_confidence = conf
                    best_frame = processed_frames
                if best_confidence >= early_confidence:
                    if self.on_log:
                        self.on_log(f"✅ 置信度充足({best_confidence:.2f})，提前退出")
                    break

            if best_result is not None:
                return {
                    "object_position": best_result,
                    "confidence": best_confidence,
                    "best_frame": best_frame,
                    "processed_frames": processed_frames,
                    "failure_reason": "",
                }

            if processed_frames == 0:
                reason = f"{camera_type} 未获取到有效图像帧(no_frame_polls={no_frame_polls})"
            elif no_position_frames > 0:
                reason = (
                    f"检测到目标但深度/掩膜坐标计算失败"
                    f"(无检测{no_detection_frames}帧, 坐标失败{no_position_frames}帧)"
                )
            else:
                reason = f"未检测到物品(处理{processed_frames}帧)"
            return {
                "object_position": None,
                "confidence": best_confidence,
                "processed_frames": processed_frames,
                "failure_reason": reason,
            }
        finally:
            capture_thread.stop()
            capture_thread.join(timeout=1.0)

    def _set_camera_test_flow_active(self, active):
        seen = set()
        for worker in self.camera_test_workers.values():
            if worker is None or id(worker) in seen:
                continue
            seen.add(id(worker))
            if hasattr(worker, "set_flow_active"):
                try:
                    worker.set_flow_active(active)
                except Exception:
                    logger.exception("failed to update camera-test flow mode")

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
                if self.on_log:
                    self.on_log("❌ 无法获取运动控制权，可能有其他操作正在执行")
                if self.on_finished:
                    self.on_finished(False)
                return

            self._set_camera_test_flow_active(True)
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
                        time.sleep(0.1)

                    module = normalize_module_type(module)
                    name = module.get("name", f"模块{i+1}")
                    force_guard = build_force_guard(module.get("params", {}))
                    if self.on_progress:
                        self.on_progress(i + 1, total, name)

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
                            if self.on_log:
                                self.on_log(f"🔄 检测到机器人模式{robot_mode}，自动同步使能状态")

                    stop_checker = lambda: ctx.stop_event.is_set()

                    if module['type'] == "move":
                        if module['params']['target'] == "initial_position":
                            if not self.controller.move_to_initial_position(
                                verify_start_pose=False,
                                verify_end_pose=False,
                                wait_poll_interval=wait_poll_interval,
                                force_guard=force_guard,
                            ):
                                self._fail_module(ctx, i, name, "移动到初始位置失败")
                                return
                            self._log_force_guard_if_triggered(i, name)
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
                                    force_guard=force_guard,
                                )
                                if not success:
                                    self._fail_module(ctx, i, name, "直线运动失败")
                                    return
                                self._log_force_guard_if_triggered(i, name)
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
                                force_guard=force_guard,
                            )
                            if not success:
                                self._fail_module(ctx, i, name, f"移动到点位 '{point_name}' 失败")
                                return
                            self._log_force_guard_if_triggered(i, name)
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
                            # 位姿缓冲区由 RobotController 拥有，在 _store_feedback_packet 中 push；
                            # 此处补充 push 当前位姿作为退化兜底（feedback 线程可能尚未 push 最新帧）。
                            self.controller.pose_buffer.push(time.perf_counter(), current_pose)

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
                            if self.on_log:
                                self.on_log(
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
                            try:
                                prepared_force_guard = self.controller.prepare_force_guard(force_guard)
                            except RuntimeError as e:
                                self._fail_module(ctx, i, name, f"力到位保护准备失败: {e}")
                                return
                            cmd_start = time.perf_counter()
                            arc_command_id = fa_ctrl.execute(set_speed=False)
                            cmd_elapsed = time.perf_counter() - cmd_start
                            arc_length = abs(center_offset_z * np.deg2rad(sweep_angle))
                            timeout = min(max(arc_length / 20.0 + 5.0, 5.0), 60.0)
                            wait_start = time.perf_counter()
                            if not self.controller.wait_for_motion_completion(
                                timeout=timeout,
                                poll_interval=wait_poll_interval,
                                stop_checker=stop_checker,
                                command_id=arc_command_id,
                                force_guard=prepared_force_guard,
                            ):
                                self._fail_module(ctx, i, name, "圆弧运动等待完成失败")
                                return
                            wait_elapsed = time.perf_counter() - wait_start
                            if not self._log_force_guard_if_triggered(i, name):
                                if self.on_log:
                                    self.on_log(f"✅ 模块{i+1}圆弧运动完成")
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
                        if self.on_log:
                            self.on_log(
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
                            force_guard=force_guard,
                        )
                        cmd_elapsed = time.perf_counter() - cmd_start
                        wait_elapsed = 0.0
                        if not success:
                            self._fail_module(ctx, i, name, "相对移动失败")
                            return
                        if not self._log_force_guard_if_triggered(i, name):
                            if self.on_log:
                                self.on_log(f"✅ 模块{i+1}相对移动完成")
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
                        if force_guard is not None and execution_mode == "queued":
                            if self.on_log:
                                self.on_log("  已启用TCP力到位保护，连续相对路径自动改为逐段等待模式")
                            execution_mode = "stop_each"
                        segments = p.get('segments', [])

                        if not segments:
                            self._fail_module(ctx, i, name, "连续相对路径段列表为空")
                            return

                        active_segments = [s for s in segments if s.get('enabled', True)]
                        if not active_segments:
                            self._fail_module(ctx, i, name, "所有路径段均已禁用")
                            return

                        if self.on_log:
                            self.on_log(f"  连续相对路径: {len(active_segments)}/{len(segments)}段有效, 模式={execution_mode}")
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
                            if self.on_log:
                                self.on_log(f"  队列模式: {queued_count}段已下发, 等待完成...")
                            wait_ok = self.controller.wait_for_motion_completion(
                                timeout=60,
                                stop_checker=lambda: ctx.stop_event.is_set(),
                                command_id=self.controller._last_command_id,
                            )
                            if not wait_ok:
                                self._fail_module(ctx, i, name, "队列模式运动等待超时或被停止")
                                return
                            if self.on_log:
                                self.on_log(f"  队列模式完成")

                        else:
                            # stop_each mode: each segment waits for completion
                            for seg_idx, seg in enumerate(segments):
                                if not seg.get('enabled', True):
                                    if self.on_log:
                                        self.on_log(f"  段{seg_idx+1}: 已禁用，跳过")
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
                                    wait_poll_interval=wait_poll_interval,
                                    force_guard=force_guard,
                                )
                                seg_elapsed = time.perf_counter() - seg_start

                                if not success:
                                    self._fail_module(ctx, i, name, f"第{seg_idx+1}段相对移动失败: offsets={offsets}")
                                    return

                                seg_name = seg.get('name', f'段{seg_idx+1}')
                                if self._log_force_guard_if_triggered(i, f"{name}/段{seg_idx+1}"):
                                    break
                                logger.info("relative_path seg %d/%d: name=%s offsets=%s coord=%s speed=%d cp=%d r=%d elapsed=%.3fs", seg_idx + 1, len(segments), seg_name, offsets, seg_coord, seg_speed, seg_cp, seg_r, seg_elapsed)
                                if self.on_log:
                                    self.on_log(f"  段{seg_idx+1}/{len(segments)}「{seg_name}」: [{offsets[0]:.1f},{offsets[1]:.1f},{offsets[2]:.1f}] coord={seg_coord} speed={seg_speed}% cp={seg_cp} r={seg_r} elapsed={seg_elapsed:.3f}s")

                        ctx.increment_motion_generation()
                        cmd_elapsed = time.perf_counter() - module_start - camera_elapsed
                        wait_elapsed = 0.0

                    elif module['type'] == "delay":
                        p = module.get('params', {})
                        try:
                            duration_s = float(p.get('duration_s', 0))
                        except (TypeError, ValueError):
                            duration_s = 0.0
                        if not math.isfinite(duration_s) or duration_s <= 0 or duration_s > 3600:
                            self._fail_module(ctx, i, name, "延时时长必须大于0秒且不超过3600秒")
                            return

                        wait_mode = p.get('wait_mode', 'time')
                        signal_checker = None
                        if wait_mode == "modbus_or_timeout":
                            if self.on_log:
                                self.on_log(
                                    f"⏱️ 最长等待 {duration_s:.1f} 秒，"
                                    "延时期间40001=5，收到40001=1时提前通过"
                                )

                            modbus_server = getattr(self.controller, "modbus_server", None)
                            if modbus_server is None or not modbus_server.is_running():
                                if self.on_log:
                                    self.on_log("  Modbus服务未运行，将等待至超时后继续")

                            self.controller.begin_modbus_delay_wait()
                            signal_checker = self.controller.is_modbus_delay_released
                        elif wait_mode == "time":
                            if self.on_log:
                                self.on_log(f"⏱️ 延时 {duration_s:.1f} 秒")
                        else:
                            self._fail_module(ctx, i, name, "延时等待方式无效")
                            return

                        wait_start = time.perf_counter()
                        try:
                            wait_result = wait_for_flow_delay_or_signal(
                                duration_s,
                                ctx.stop_event,
                                self.is_paused_ref,
                                poll_interval=min(wait_poll_interval, 0.05),
                                signal_checker=signal_checker,
                            )
                        finally:
                            if wait_mode == "modbus_or_timeout":
                                self.controller.end_modbus_delay_wait(
                                    restore_running=not ctx.stop_event.is_set()
                                )
                        if wait_result == "stopped":
                            self._fail_module(ctx, i, name, "用户停止（延时中）")
                            return
                        wait_elapsed = time.perf_counter() - wait_start
                        cmd_elapsed = 0.0
                        if wait_result == "signal":
                            if self.on_log:
                                self.on_log(
                                    f"✅ 模块{i+1}收到Modbus信号，等待{wait_elapsed:.1f}秒后提前完成"
                                )
                        elif wait_mode == "modbus_or_timeout":
                            if self.on_log:
                                self.on_log(
                                    f"✅ 模块{i+1}等待超时，继续下一步"
                                )
                        else:
                            if self.on_log:
                                self.on_log(f"✅ 模块{i+1}延时完成")

                    elif module['type'] == "camera":
                        camera_type = module['params'].get('camera_type', 'D435i')
                        if camera_type == "D405":
                            vision_to_use = self.vision_d405
                        else:
                            vision_to_use = self.vision_d435i

                        if vision_to_use is None:
                            self._fail_module(ctx, i, name, f"{camera_type} 相机未连接，无法识别物体")
                            return

                        camera_start = time.perf_counter()
                        N_FRAMES = max(1, int(self.performance_config.get("flow_camera_frames", 10)))
                        early_confidence = float(self.performance_config.get("flow_camera_early_confidence", 0.85))
                        detection_result = self._detect_camera_object_for_flow(
                            vision_to_use,
                            camera_type,
                            ctx,
                            max_frames=N_FRAMES,
                            early_confidence=early_confidence,
                        )
                        best_result = detection_result.get("object_position")
                        best_confidence = float(detection_result.get("confidence", 0.0))
                        camera_elapsed = time.perf_counter() - camera_start
                        if not best_result:
                            reason = detection_result.get("failure_reason") or "未检测到物品"
                            if not str(reason).startswith("相机识别失败"):
                                reason = f"相机识别失败：{reason}"
                            self._fail_module(ctx, i, name, reason)
                            return

                        min_confidence = float(self.performance_config.get("flow_camera_min_confidence", 0.3))
                        if not best_result or best_confidence < min_confidence:
                            self._fail_module(ctx, i, name, f"多帧检测失败，最高置信度={best_confidence:.2f}")
                            return

                        object_position = best_result
                        if self.on_log:
                            self.on_log(f"✅ 最终结果: 置信度={best_confidence:.2f}")

                        try:
                            camera_coords = coerce_float_vector(
                                object_position.get('camera_coords'),
                                3,
                                "相机坐标",
                            )
                        except ValueError as e:
                            self._fail_module(ctx, i, name, str(e))
                            return
                        try:
                            end_coords = coerce_float_vector(
                                vision_to_use.convert_to_end_coords(camera_coords),
                                3,
                                "末端坐标",
                            )
                        except Exception as e:
                            self._fail_module(ctx, i, name, f"相机坐标转末端坐标失败: {e}")
                            return
                        current_pose = self.controller.get_current_pose_fast(max_age=pose_cache_max_age)
                        try:
                            current_pose = coerce_float_vector(
                                current_pose,
                                6,
                                "机器人当前位姿",
                            )
                        except ValueError as e:
                            self._fail_module(ctx, i, name, str(e))
                            return
                        # 位姿缓冲区由 RobotController 拥有（_store_feedback_packet 中 push）；
                        # 此处补充 push 作为退化兜底，确保后续视觉伺服能查到当前时刻位姿。
                        self.controller.pose_buffer.push(time.perf_counter(), current_pose)
                        try:
                            base_coords = coerce_float_vector(
                                vision_to_use.convert_to_base_coords(end_coords, current_pose),
                                3,
                                "基座坐标",
                            )
                        except Exception as e:
                            self._fail_module(ctx, i, name, f"末端坐标转基座坐标失败: {e}")
                            return

                        point_name = "d435i" if camera_type == "D435i" else "d405"
                        point_data = get_point(point_name) or {"coords": [0]*6, "is_relative": False, "relative_to": None, "offset": [0]*6, "is_default": True}
                        point_data["coords"] = base_coords[:3] + current_pose[3:6]
                        set_point(point_name, point_data)
                        if self.on_log:
                            self.on_log(
                                f"📍 已更新点位 {point_name}: "
                                f"base=[{float(base_coords[0]):.1f},{float(base_coords[1]):.1f},{float(base_coords[2]):.1f}]"
                            )

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
                        self.active_visual_servo = servo_ctrl
                        # pose_buffer 由 RobotController 拥有，VisionThread 通过
                        # controller.pose_buffer 直接查询，无需 FlowExecutor 注入。

                        def servo_log(msg):
                            if self.on_log:
                                self.on_log(msg)

                        try:
                            success, final_error, iterations = servo_ctrl.servo_to_target(
                                log_callback=servo_log,
                            )
                        finally:
                            self.get_visual_servo_telemetry()
                            self.active_visual_servo = None

                        if not success:
                            self._fail_module(ctx, i, name, f"视觉伺服失败，最终误差={final_error:.1f}mm")
                            return

                        if self.on_log:
                            self.on_log(f"✅ 视觉伺服完成，误差={final_error:.1f}mm，迭代={iterations}次")
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
                    if module['type'] not in ("move", "arc_motion", "relative_move", "relative_path", "joint_move", "delay"):
                        cmd_elapsed = module_elapsed
                    ctx.module_timings.append((i + 1, name, module_elapsed, camera_elapsed, cmd_elapsed, wait_elapsed))
                    logger.info("flow module %s/%s finished: %s total=%.3fs camera=%.3fs cmd=%.3fs wait=%.3fs", i + 1, total, name, module_elapsed, camera_elapsed, cmd_elapsed, wait_elapsed)
                    if module_elapsed > 1.0:
                        if module['type'] == "move":
                            logger.warning("flow module %s/%s SLOW: %s total=%.3fs speed_set=%.3fs cmd=%.3fs motion_wait=%.3fs camera=%.3fs", i + 1, total, name, module_elapsed, speed_set_elapsed, command_send_elapsed, motion_wait_elapsed, camera_elapsed)
                        else:
                            logger.warning("flow module %s/%s SLOW: %s total=%.3fs cmd=%.3fs wait=%.3fs camera=%.3fs", i + 1, total, name, module_elapsed, cmd_elapsed, wait_elapsed, camera_elapsed)

                if self.on_log:
                    self.on_log("✅ 抓取流程执行完成")
                total_elapsed = time.perf_counter() - flow_start
                summary = "; ".join(
                    f"{idx}.{module_name}={elapsed:.2f}s(cmd={cmd:.2f}s,wait={wait:.2f}s)"
                    for idx, module_name, elapsed, _, cmd, wait in ctx.module_timings
                )
                logger.info("flow finished total=%.3fs modules=[%s]", total_elapsed, summary)
                for idx, module_name, elapsed, cam_elapsed, cmd_e, wait_e in ctx.module_timings:
                    if elapsed > 0.5:
                        logger.info("  模块%d.%s: total=%.3fs cmd=%.3fs wait=%.3fs camera=%.3fs", idx, module_name, elapsed, cmd_e, wait_e, cam_elapsed)
                if self.on_log:
                    self.on_log(f"流程总耗时 {total_elapsed:.2f}s")
                if self.on_finished:
                    self.on_finished(True)
            finally:
                self._set_camera_test_flow_active(False)
                self.controller.release_motion("flow")
                self._ctx = None
                self.controller._active_flow_thread = None
        except Exception as e:
            logger.exception("流程异常")
            if self.on_log:
                self.on_log(f"❌ 流程异常: {e}")
            if self.on_finished:
                self.on_finished(False)
