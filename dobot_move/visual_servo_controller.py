#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多线程缓存式视觉伺服控制器

架构:
  FeedbackThread (RobotController 已有, 30004 端口)
    → 持续更新 latest_pose → get_current_pose_from_feedback()

  VisionThread (本模块)
    → 持续采集 D405 图像 + 低频 YOLO / 高频复用 + 3D 定位
    → 更新 TargetCache (target_end + timestamp)
    → 不做 base 坐标转换，避免使用旧 pose

  ServoThread (本模块)
    → 固定周期读取 FeedbackCache + TargetCache
    → 用最新 current_pose 将 target_end 转为 base_coords
    → 计算误差 → ServoP 下发
    → 唯一允许发送 ServoP 的线程

注意: ServoP 仍是队列指令，返回成功只表示指令已发送到队列，
不表示机械臂已完成运动。闭环依赖固定周期持续刷新目标位姿。

这不是硬实时控制，目标是 TCP 条件下稳定实现 10~20Hz 的上位机视觉闭环修正。
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from .motion_safety import validate_servo_p_params

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 线程安全缓存
# ---------------------------------------------------------------------------

@dataclass
class TargetCache:
    """视觉检测目标缓存 — 线程安全

    VisionThread 写入 target_end (末端坐标系)，
    ServoThread 读取 target_end 后用最新 current_pose 转为 base_coords。
    target_base 仅作为 fallback 路径保留。
    """
    target_end: Optional[np.ndarray] = None    # 末端坐标系 [X,Y,Z] (主路径)
    target_base: Optional[np.ndarray] = None   # 基座坐标系 [X,Y,Z,Rx,Ry,Rz] (fallback)
    confidence: float = 0.0
    timestamp: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def clear(self):
        """清空缓存，避免读取上一次伺服残留目标"""
        with self._lock:
            self.target_end = None
            self.target_base = None
            self.confidence = 0.0
            self.timestamp = 0.0

    def update_end(self, target_end, confidence):
        """VisionThread 主路径：缓存末端坐标"""
        with self._lock:
            self.target_end = target_end
            self.confidence = confidence
            self.timestamp = time.monotonic()

    def update_base(self, target_base, confidence):
        """Fallback 路径：缓存基座坐标"""
        with self._lock:
            self.target_base = target_base
            self.confidence = confidence
            self.timestamp = time.monotonic()

    def read_end(self, max_age: float = 0.3):
        """读取末端坐标缓存，超过 max_age 返回 None"""
        with self._lock:
            if self.target_end is None:
                return None, 0.0, float('inf')
            age = time.monotonic() - self.timestamp
            if age > max_age:
                return None, 0.0, age
            return self.target_end.copy(), self.confidence, age

    def read_base(self, max_age: float = 0.3):
        """读取基座坐标缓存 (fallback)，超过 max_age 返回 None"""
        with self._lock:
            if self.target_base is None:
                return None, 0.0, float('inf')
            age = time.monotonic() - self.timestamp
            if age > max_age:
                return None, 0.0, age
            return self.target_base.copy(), self.confidence, age


# ---------------------------------------------------------------------------
# VisionThread — 持续采集 + 低频 YOLO + 3D 定位
# ---------------------------------------------------------------------------

class VisionThread:
    """视觉检测线程 — 持续采集图像并更新 TargetCache

    低频 YOLO 策略:
    - 每 yolo_every_n 帧执行一次完整 YOLO 检测
    - 中间帧复用上一帧 target 进行深度计算
    - 连续复用超过 reuse_max_frames 帧时强制 YOLO
    - 丢失帧数超过 max_lost_frames 时强制 YOLO
    - 缓存置信度低于 min_confidence 时强制 YOLO
    """

    def __init__(self, vision, controller, target_cache: TargetCache,
                 yolo_every_n: int = 3, max_lost_frames: int = 3,
                 reuse_max_frames: int = 10, min_confidence: float = 0.3):
        self.vision = vision
        self.controller = controller
        self.target_cache = target_cache
        self.yolo_every_n = max(1, yolo_every_n)
        self.max_lost_frames = max_lost_frames
        self.reuse_max_frames = reuse_max_frames
        self.min_confidence = min_confidence
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._frame_count = 0
        self._lost_count = 0
        self._reuse_count = 0          # 连续复用帧计数
        self._last_target = None       # 上一帧 YOLO 检测结果
        self._last_confidence = 0.0    # 上一帧置信度
        self.target_lost = False       # 相机断线等导致目标丢失标志
        # 耗时统计
        self.last_capture_ms = 0.0
        self.last_detect_ms = 0.0
        self.last_depth_ms = 0.0
        self.last_end_convert_ms = 0.0
        self.last_total_ms = 0.0

    def start(self):
        if self._running:
            return
        self._running = True
        self.vision.reset_tracking()
        self._frame_count = 0
        self._lost_count = 0
        self._reuse_count = 0
        self._last_target = None
        self._last_confidence = 0.0
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info(" 视觉检测线程已启动 (yolo_every_n=%d, reuse_max=%d, min_conf=%.2f)",
                     self.yolo_every_n, self.reuse_max_frames, self.min_confidence)

    def stop(self):
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        logger.info(" 视觉检测线程已停止")

    def _should_run_yolo(self):
        """判断当前帧是否需要执行完整 YOLO"""
        # 第一帧必须 YOLO
        if self._last_target is None:
            return True
        # 丢失帧数超过阈值，强制 YOLO
        if self._lost_count >= self.max_lost_frames:
            return True
        # 连续复用超过上限，强制 YOLO
        if self._reuse_count >= self.reuse_max_frames:
            return True
        # 上一帧置信度过低，强制 YOLO
        if self._last_confidence < self.min_confidence:
            return True
        # 每 yolo_every_n 帧执行一次
        return (self._frame_count % self.yolo_every_n) == 0

    def _loop(self):
        while self._running:
            # ── 0. 相机断线检测 ──
            if not self.vision.is_available:
                logger.warning("相机不可用，退出视觉采集线程")
                self.target_lost = True
                break

            t_start = time.monotonic()

            # ── 1. 捕获帧 ──
            t0 = time.monotonic()
            depth_frame, color_frame = self.vision.capture_frames()
            self.last_capture_ms = (time.monotonic() - t0) * 1000

            if depth_frame is None or color_frame is None:
                time.sleep(0.01)
                continue

            self._frame_count += 1
            color_image = np.asanyarray(color_frame.get_data())

            # ── 2. YOLO 检测 / 复用上一帧 target ──
            target = None
            if self._should_run_yolo():
                # 完整 YOLO 检测
                t0 = time.monotonic()
                target = self.vision.run_detection_tracked(color_image)
                self.last_detect_ms = (time.monotonic() - t0) * 1000

                if target is not None:
                    self._last_target = target
                    self._lost_count = 0
                    self._reuse_count = 0
                else:
                    self._lost_count += 1
            else:
                # 中间帧：复用上一帧 target，YOLO 耗时记为 0
                target = self._last_target
                self.last_detect_ms = 0.0
                self._reuse_count += 1

                if target is None:
                    self._lost_count += 1

            if target is None:
                self.last_total_ms = (time.monotonic() - t_start) * 1000
                continue

            # ── 3. 深度计算 + 3D 定位 ──
            t0 = time.monotonic()
            object_position = self.vision.calculate_object_position_smoothed(
                depth_frame, color_frame, target
            )
            self.last_depth_ms = (time.monotonic() - t0) * 1000

            if object_position is None:
                # 深度计算失败，标记 target 丢失
                self._lost_count += 1
                self.last_total_ms = (time.monotonic() - t_start) * 1000
                continue

            # ── 4. 转换到末端坐标 (不做 base 转换，留给 ServoThread) ──
            t0 = time.monotonic()
            end_coords = self.vision.convert_to_end_coords(
                object_position['camera_coords']
            )
            confidence = object_position.get('confidence', 0.0)
            self._last_confidence = confidence

            # 主路径：缓存末端坐标，ServoThread 用最新 pose 转换
            self.target_cache.update_end(
                target_end=np.array(end_coords[:3], dtype=np.float64),
                confidence=confidence,
            )
            self.last_end_convert_ms = (time.monotonic() - t0) * 1000

            self.last_total_ms = (time.monotonic() - t_start) * 1000
            logger.debug(
                " 视觉线程: capture=%.1fms detect=%.1fms depth=%.1fms "
                "end_convert=%.1fms total=%.1fms",
                self.last_capture_ms, self.last_detect_ms,
                self.last_depth_ms, self.last_end_convert_ms, self.last_total_ms,
            )


# ---------------------------------------------------------------------------
# ServoThread — 固定周期控制闭环
# ---------------------------------------------------------------------------

class ServoThread:
    """伺服控制线程 — 固定周期读取缓存 + 计算误差 + ServoP

    这是唯一允许发送 ServoP 的线程。
    VisionThread 和 FeedbackCache 只更新缓存，不发送运动指令。

    目标获取优先级:
    1. target_end + 最新 current_pose → convert_to_base_coords (主路径)
    2. target_base (fallback，直接使用)
    """

    def __init__(self, vision, controller, target_cache: TargetCache,
                 servo_period=0.06,
                 servo_p_t=None,
                 servo_p_aheadtime=50,
                 servo_p_gain=500,
                 gain_far=0.8, gain_mid=0.5, gain_near=0.2,
                 threshold_far=50.0, threshold_mid=10.0,
                 converge_threshold=3.0,
                 max_target_age=0.3,
                 max_pose_age=0.1,
                 max_error_mm=300.0,
                 z_safety_limit=0.0,
                 max_step_far=35.0,
                 max_step_mid=18.0,
                 max_step_near=6.0,
                 max_step_fine=2.0,
                 enable_feedforward=False,
                 max_iterations=60,
                 stop_on_converge=False):
        self.vision = vision
        self.controller = controller
        self.target_cache = target_cache
        self.servo_period = servo_period
        self.servo_p_t = servo_p_t
        if self.servo_p_t is None:
            self.servo_p_t = self.servo_period
        self.servo_p_aheadtime = servo_p_aheadtime
        self.servo_p_gain = servo_p_gain
        self.gain_far = gain_far
        self.gain_mid = gain_mid
        self.gain_near = gain_near
        self.threshold_far = threshold_far
        self.threshold_mid = threshold_mid
        self.converge_threshold = converge_threshold
        self.max_target_age = max_target_age
        self.max_pose_age = max_pose_age
        self.max_error_mm = max_error_mm
        self.z_safety_limit = z_safety_limit
        self.max_step_far = max_step_far
        self.max_step_mid = max_step_mid
        self.max_step_near = max_step_near
        self.max_step_fine = max_step_fine
        self.enable_feedforward = enable_feedforward
        self.max_iterations = max_iterations
        self.stop_on_converge = stop_on_converge

        self._consecutive_servo_fail = 0
        self._running = False
        self._thread: Optional[threading.Thread] = None
        # 结果
        self.success = False
        self.final_error_mm = -1.0
        self.iterations = 0
        self._converged = threading.Event()
        self._stop_requested = threading.Event()
        # 耗时统计
        self.last_target_age = 0.0
        self.last_pose_age = 0.0
        self.last_error_mm = 0.0
        self.last_error_xyz = [0.0, 0.0, 0.0]
        self.last_read_cache_ms = 0.0
        self.last_read_pose_ms = 0.0
        self.last_base_convert_ms = 0.0
        self.last_compute_ms = 0.0
        self.last_servo_ms = 0.0
        self.last_total_ms = 0.0
        self.last_hz = 0.0
        self.avg_servo_ms = 0.0
        self.skip_frame_count = 0
        self._servo_ms_history = []  # sliding window for avg_servo_ms

    def start(self):
        if self._running:
            return
        self._running = True
        self._converged.clear()
        self._stop_requested.clear()
        self.success = False
        self.final_error_mm = -1.0
        self.iterations = 0
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info(" 伺服控制线程已启动 (period=%.0fms)", self.servo_period * 1000)

    def stop(self):
        self._stop_requested.set()
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        logger.info(" 伺服控制线程已停止")

    def wait(self, timeout=60.0):
        """等待伺服完成（收敛或超时）"""
        return self._converged.wait(timeout=timeout)

    @property
    def is_running(self):
        return self._running

    def _adaptive_gain(self, error_mm):
        if error_mm > self.threshold_far:
            return self.gain_far
        elif error_mm > self.threshold_mid:
            return self.gain_mid
        else:
            return self.gain_near

    def _adaptive_max_step(self, error_mm):
        if error_mm > self.threshold_far:
            return self.max_step_far
        elif error_mm > self.threshold_mid:
            return self.max_step_mid
        elif error_mm > self.converge_threshold:
            return self.max_step_near
        else:
            return self.max_step_fine

    def _safety_clamp(self, cmd_pos, current_pos, max_step):
        cmd_pos = np.array(cmd_pos, dtype=np.float64)
        current_pos = np.array(current_pos, dtype=np.float64)
        delta = cmd_pos - current_pos
        distance = np.linalg.norm(delta)
        if distance > max_step:
            delta = delta / distance * max_step
            cmd_pos = current_pos + delta
        if cmd_pos[2] < self.z_safety_limit:
            return None
        return cmd_pos

    def _resolve_target_base(self, current_pose):
        """获取基座坐标系目标位置

        优先路径: target_end + 最新 current_pose → convert_to_base_coords
        Fallback: target_base (直接使用)

        Returns:
            (target_base, confidence, target_age, base_convert_ms)
        """
        # ── 主路径: target_end → base_coords ──
        target_end, confidence, target_age = self.target_cache.read_end(
            max_age=self.max_target_age
        )
        if target_end is not None and current_pose is not None:
            t0 = time.monotonic()
            base_coords = self.vision.convert_to_base_coords(target_end, current_pose)
            convert_ms = (time.monotonic() - t0) * 1000
            if base_coords is not None:
                return np.array(base_coords[:6], dtype=np.float64), confidence, target_age, convert_ms

        # ── Fallback: target_base ──
        target_base, confidence, target_age = self.target_cache.read_base(
            max_age=self.max_target_age
        )
        if target_base is not None:
            return target_base, confidence, target_age, 0.0

        return None, 0.0, float('inf'), 0.0

    def _loop(self):
        iteration = 0
        error_mm = -1.0
        hz_counter = 0
        hz_start = time.monotonic()

        while self._running and not self._stop_requested.is_set():
            t_iter_start = time.monotonic()

            # ── 1. 读取当前位姿 ──
            t0 = time.monotonic()
            current_pose = self.controller.get_current_pose_from_feedback(
                max_age=self.max_pose_age
            )
            self.last_read_pose_ms = (time.monotonic() - t0) * 1000

            if current_pose is None:
                logger.debug(" 伺服跳过: 位姿数据过旧")
                self.last_pose_age = float('inf')
                self._sleep_to_next(t_iter_start)
                continue

            pose_age = time.monotonic() - self.controller.last_feed_time
            self.last_pose_age = pose_age

            # ── 2. 读取目标缓存 + 坐标转换 ──
            t0 = time.monotonic()
            target_base, confidence, target_age, base_convert_ms = self._resolve_target_base(current_pose)
            self.last_read_cache_ms = (time.monotonic() - t0) * 1000
            self.last_base_convert_ms = base_convert_ms
            self.last_target_age = target_age

            if target_base is None:
                logger.debug(
                    " 伺服跳过: 目标数据过旧 age=%.0fms > max=%.0fms",
                    target_age * 1000, self.max_target_age * 1000,
                )
                self._sleep_to_next(t_iter_start)
                continue

            # ── 3. 计算误差 ──
            t0 = time.monotonic()
            e = np.array(target_base[:3]) - np.array(current_pose[:3])
            error_mm = np.linalg.norm(e)
            self.last_error_mm = error_mm
            self.last_error_xyz = [float(value) for value in e[:3]]

            # ── 4. 安全检查 ──
            if error_mm > self.max_error_mm:
                logger.warning(
                    " 伺服跳过: 误差异常大 error=%.1fmm > max=%.1fmm",
                    error_mm, self.max_error_mm,
                )
                self.last_compute_ms = (time.monotonic() - t0) * 1000
                self._sleep_to_next(t_iter_start)
                continue

            # ── 5. 收敛判断 ──
            if error_mm < self.converge_threshold:
                logger.info(
                    " ✅ 收敛成功! 误差=%.1fmm, 迭代=%d", error_mm, iteration,
                )
                # 收敛后 hold 当前位姿，避免 ServoP 队列残留导致末端继续小动
                clamped_t, clamped_aheadtime, clamped_gain = validate_servo_p_params(
                    self.servo_p_t, self.servo_p_aheadtime, self.servo_p_gain, self.servo_period,
                )
                self.controller.servo_p(
                    list(current_pose[:6]),
                    t=clamped_t,
                    aheadtime=clamped_aheadtime,
                    gain=clamped_gain,
                )
                if self.stop_on_converge:
                    # 可选：发送 Stop() 清空运动队列
                    try:
                        self.controller.dashboard.Stop()
                    except Exception:
                        pass
                self.success = True
                self.final_error_mm = error_mm
                self.iterations = iteration
                self._running = False
                self._converged.set()
                return

            # ── 6. 计算指令位姿 ──
            gain = self._adaptive_gain(error_mm)
            max_step = self._adaptive_max_step(error_mm)
            cmd_pos = np.array(current_pose[:3]) + e * gain

            # 前馈补偿（默认关闭，需确认 kalman_3d.x[3:6] 为基座坐标系速度后方可启用）
            # TODO: 前馈需要从 VisionThread 的 vision.kalman_3d 读取，
            #       但跨线程访问 kalman 状态需要加锁，暂不实现。

            # 安全钳位
            cmd_pos = self._safety_clamp(cmd_pos, current_pose[:3], max_step)
            if cmd_pos is None:
                logger.warning(" 伺服跳过: Z轴安全检查未通过 (Z < %.1f)", self.z_safety_limit)
                self.last_compute_ms = (time.monotonic() - t0) * 1000
                self._sleep_to_next(t_iter_start)
                continue

            cmd_pose = list(cmd_pos) + list(current_pose[3:])
            self.last_compute_ms = (time.monotonic() - t0) * 1000

            # ── 6.5 队列延迟保护 ──
            if self.last_servo_ms > self.servo_period * 1000:
                logger.warning(
                    " 伺服降频跳帧: last_servo_ms=%.1fms > period=%.1fms",
                    self.last_servo_ms, self.servo_period * 1000,
                )
                self.skip_frame_count += 1
                self._sleep_to_next(t_iter_start)
                continue

            # ── 7. 下发 ServoP ──
            # ServoP 仍是队列指令，返回成功只表示发送成功，不表示运动完成
            t0 = time.monotonic()
            clamped_t, clamped_aheadtime, clamped_gain = validate_servo_p_params(
                self.servo_p_t, self.servo_p_aheadtime, self.servo_p_gain, self.servo_period,
            )
            success = self.controller.servo_p(
                cmd_pose,
                t=clamped_t,
                aheadtime=clamped_aheadtime,
                gain=clamped_gain,
            )
            self.last_servo_ms = (time.monotonic() - t0) * 1000

            if not success:
                self._consecutive_servo_fail += 1
                if self._consecutive_servo_fail >= 3:
                    logger.warning(" 伺服连续%d次失败，暂停1周期", self._consecutive_servo_fail)
                    time.sleep(self.servo_period)
                    self._consecutive_servo_fail = 0
                else:
                    logger.warning(" 伺服跳过: ServoP指令失败 (连续%d次)", self._consecutive_servo_fail)
                self._sleep_to_next(t_iter_start)
                continue

            self._consecutive_servo_fail = 0  # Reset on success

            # Update avg_servo_ms (sliding window of last 20)
            self._servo_ms_history.append(self.last_servo_ms)
            if len(self._servo_ms_history) > 20:
                self._servo_ms_history.pop(0)
            self.avg_servo_ms = sum(self._servo_ms_history) / len(self._servo_ms_history)

            iteration += 1
            self.iterations = iteration

            # ── 8. 频率统计 + 耗时日志 ──
            hz_counter += 1
            hz_elapsed = time.monotonic() - hz_start
            if hz_elapsed >= 1.0:
                self.last_hz = hz_counter / hz_elapsed
                hz_counter = 0
                hz_start = time.monotonic()

            self.last_total_ms = (time.monotonic() - t_iter_start) * 1000
            logger.debug(
                " 伺服: read_cache=%.1fms read_pose=%.1fms base_convert=%.1fms "
                "compute=%.1fms servo=%.1fms total=%.1fms hz=%.1f "
                "target_age=%.0fms pose_age=%.0fms error=%.1fmm",
                self.last_read_cache_ms, self.last_read_pose_ms,
                self.last_base_convert_ms, self.last_compute_ms,
                self.last_servo_ms, self.last_total_ms, self.last_hz,
                target_age * 1000, pose_age * 1000, error_mm,
            )

            # ── 9. 迭代上限 ──
            if iteration >= self.max_iterations:
                logger.warning(
                    " ❌ 视觉伺服超时, 迭代次数=%d, 最终误差=%.1fmm",
                    iteration, error_mm,
                )
                self.success = False
                self.final_error_mm = error_mm
                self.iterations = iteration
                self._running = False
                self._converged.set()
                return

            # ── 10. 等待下一周期 ──
            self._sleep_to_next(t_iter_start)

        # 正常退出或被 stop
        self.success = False
        self.final_error_mm = error_mm if error_mm >= 0 else -1.0
        self.iterations = iteration
        self._converged.set()

    def _sleep_to_next(self, t_iter_start):
        elapsed = time.monotonic() - t_iter_start
        if elapsed > self.servo_period * 1.5:
            logger.warning(
                " 伺服循环超时: elapsed=%.1fms > period*1.5=%.1fms",
                elapsed * 1000, self.servo_period * 1.5 * 1000,
            )
        sleep_time = self.servo_period - elapsed
        if sleep_time > 0:
            time.sleep(sleep_time)


# ---------------------------------------------------------------------------
# VisualServoController — 顶层控制器
# ---------------------------------------------------------------------------

class VisualServoController:
    """多线程缓存式视觉伺服控制器

    用法:
        ctrl = VisualServoController(vision=d405, controller=robot)
        success, error, iters = ctrl.servo_to_target()
        ctrl.stop()
    """

    def __init__(self, vision, controller,
                 # ServoP 参数
                 servo_period=None,
                 servo_p_t=None,
                 servo_p_aheadtime=50,
                 servo_p_gain=500,
                 # 增益
                 gain_far=None, gain_mid=None, gain_near=None,
                 threshold_far=50.0, threshold_mid=10.0,
                 # 收敛
                 converge_threshold=3.0,
                 max_iterations=60,
                 # 安全
                 max_target_age=0.3,
                 max_pose_age=0.1,
                 max_error_mm=300.0,
                 z_safety_limit=0.0,
                 # 前馈
                 enable_feedforward=False,
                 # YOLO 频率
                 yolo_every_n=None,
                 # 收敛后行为
                 stop_on_converge=None,
                 # 自适应步长
                 max_step_far=None,
                 max_step_mid=None,
                 max_step_near=None,
                 max_step_fine=None):
        self.vision = vision
        self.controller = controller

        _vs_defaults = get_visual_servo_config()

        # 共享目标缓存
        self.target_cache = TargetCache()

        # 视觉线程
        self.vision_thread = VisionThread(
            vision=vision,
            controller=controller,
            target_cache=self.target_cache,
            yolo_every_n=yolo_every_n if yolo_every_n is not None else _vs_defaults.get("yolo_every_n", 3),
        )

        # 伺服线程 (需要 vision 做 base 坐标转换)
        _servo_period = servo_period if servo_period is not None else _vs_defaults.get("servo_period", 0.06)
        effective_t = servo_p_t if servo_p_t is not None else _servo_period
        self.servo_thread = ServoThread(
            vision=vision,
            controller=controller,
            target_cache=self.target_cache,
            servo_period=_servo_period,
            servo_p_t=effective_t,
            servo_p_aheadtime=servo_p_aheadtime,
            servo_p_gain=servo_p_gain,
            gain_far=gain_far if gain_far is not None else _vs_defaults.get("gain_far", 0.8),
            gain_mid=gain_mid if gain_mid is not None else _vs_defaults.get("gain_mid", 0.5),
            gain_near=gain_near if gain_near is not None else _vs_defaults.get("gain_near", 0.2),
            threshold_far=threshold_far, threshold_mid=threshold_mid,
            converge_threshold=converge_threshold,
            max_target_age=max_target_age,
            max_pose_age=max_pose_age,
            max_error_mm=max_error_mm,
            z_safety_limit=z_safety_limit,
            max_step_far=max_step_far if max_step_far is not None else _vs_defaults.get("max_step_far", 35.0),
            max_step_mid=max_step_mid if max_step_mid is not None else _vs_defaults.get("max_step_mid", 18.0),
            max_step_near=max_step_near if max_step_near is not None else _vs_defaults.get("max_step_near", 6.0),
            max_step_fine=max_step_fine if max_step_fine is not None else _vs_defaults.get("max_step_fine", 2.0),
            enable_feedforward=enable_feedforward,
            max_iterations=max_iterations,
            stop_on_converge=stop_on_converge if stop_on_converge is not None else _vs_defaults.get("stop_on_converge", False),
        )

    def servo_to_target(self, log_callback=None):
        """启动多线程视觉伺服，阻塞等待结果

        Args:
            log_callback: 日志回调

        Returns:
            (success, final_error_mm, iterations)
        """
        # 清空缓存，避免读取上一次伺服残留目标
        self.target_cache.clear()

        # 启动视觉线程
        self.vision_thread.start()

        # 等待目标缓存有数据（最多等 5 秒）
        wait_start = time.monotonic()
        while time.monotonic() - wait_start < 5.0:
            target_end, _, _ = self.target_cache.read_end(max_age=1.0)
            if target_end is not None:
                break
            # 也检查 fallback 路径
            target_base, _, _ = self.target_cache.read_base(max_age=1.0)
            if target_base is not None:
                break
            time.sleep(0.05)
        else:
            if log_callback:
                log_callback("❌ 视觉伺服启动失败: 5秒内未检测到目标")
            self.vision_thread.stop()
            return False, -1.0, 0

        if log_callback:
            log_callback("🎯 目标已锁定，启动伺服闭环...")

        # 启动伺服线程
        self.servo_thread.start()

        # 阻塞等待伺服完成
        timeout = self.servo_thread.max_iterations * self.servo_thread.servo_period + 10.0
        self.servo_thread.wait(timeout=timeout)

        # 停止所有线程
        self.vision_thread.stop()
        self.servo_thread.stop()

        success = self.servo_thread.success
        final_error = self.servo_thread.final_error_mm
        iterations = self.servo_thread.iterations

        # ── 分段统计日志 ──
        logger.info(
            " 视觉伺服统计: success=%s error=%.1fmm iterations=%d\n"
            "  VisionThread: capture=%.1fms detect=%.1fms depth=%.1fms "
            "end_convert=%.1fms total=%.1fms\n"
            "  ServoThread: read_pose=%.1fms base_convert=%.1fms "
            "servo=%.1fms total=%.1fms hz=%.1f avg_servo=%.1fms skip=%d",
            success, final_error, iterations,
            self.vision_thread.last_capture_ms,
            self.vision_thread.last_detect_ms,
            self.vision_thread.last_depth_ms,
            self.vision_thread.last_end_convert_ms,
            self.vision_thread.last_total_ms,
            self.servo_thread.last_read_pose_ms,
            self.servo_thread.last_base_convert_ms,
            self.servo_thread.last_servo_ms,
            self.servo_thread.last_total_ms,
            self.servo_thread.last_hz,
            self.servo_thread.avg_servo_ms,
            self.servo_thread.skip_frame_count,
        )

        if log_callback:
            if success:
                log_callback(f"✅ 视觉伺服完成! 误差={final_error:.1f}mm, 迭代={iterations}次")
            else:
                log_callback(f"❌ 视觉伺服失败, 最终误差={final_error:.1f}mm, 迭代={iterations}次")

        return success, final_error, iterations

    def stop(self):
        """紧急停止所有线程"""
        self.vision_thread.stop()
        self.servo_thread.stop()
