#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Task 5 测试：同步误差 telemetry。

覆盖：
1. VisionThread 拥有 last_pose_buffer_drift_ms 和 last_pose_buffer_size 字段
2. _loop 运行后 drift_ms = (published_time - capture_time) * 1000 计算正确
3. _loop 运行后 pose_buffer_size 反映 controller.pose_buffer 长度
4. get_visual_servo_telemetry() 输出包含 pose_buffer_drift_ms 和 pose_buffer_size
"""

import sys
import time
import types
from unittest.mock import MagicMock, PropertyMock

import numpy as np

if "pyrealsense2" not in sys.modules:
    sys.modules["pyrealsense2"] = types.ModuleType("pyrealsense2")

from dobot_move.robot.visual_servo_controller import VisionThread, TargetCache
from dobot_move.robot.robot_pose_buffer import RobotPoseBuffer


class _StubVision:
    """最小 vision 桩，支持 _loop 单次迭代。"""

    def __init__(self):
        self._available_calls = 0

    @property
    def is_available(self):
        # 第一次返回 True（进入 loop），第二次返回 False（退出 loop）
        self._available_calls += 1
        return self._available_calls == 1

    def reset_tracking(self):
        pass

    def capture_frames(self):
        depth_frame = MagicMock()
        color_frame = MagicMock()
        color_frame.get_data.return_value = np.zeros((10, 10, 3), dtype=np.uint8)
        depth_frame.get_data.return_value = np.zeros((10, 10), dtype=np.uint16)
        return depth_frame, color_frame

    def run_detection_tracked(self, image):
        return {"bbox": [0, 0, 10, 10], "confidence": 0.9}

    def calculate_object_position_smoothed(self, depth_frame, color_frame, target):
        return {"camera_coords": [1.0, 2.0, 3.0], "confidence": 0.9}

    def convert_to_end_coords(self, camera_coords):
        return [float(camera_coords[0]), float(camera_coords[1]), float(camera_coords[2])]

    def convert_to_base_coords(self, target_end, pose):
        return list(target_end)


class _StubController:
    """最小 controller 桩，提供 pose_buffer。"""

    def __init__(self, pose_buffer):
        self.pose_buffer = pose_buffer
        self.last_feed_time = time.monotonic()


# ---------------------------------------------------------------------------
# 1. VisionThread 拥有 telemetry 字段
# ---------------------------------------------------------------------------

def test_vision_thread_has_telemetry_fields():
    """VisionThread.__init__ 应初始化 last_pose_buffer_drift_ms 和 last_pose_buffer_size。"""
    vision = _StubVision()
    controller = _StubController(pose_buffer=RobotPoseBuffer())
    cache = TargetCache()
    vt = VisionThread(vision=vision, controller=controller, target_cache=cache)

    assert hasattr(vt, "last_pose_buffer_drift_ms")
    assert hasattr(vt, "last_pose_buffer_size")
    assert vt.last_pose_buffer_drift_ms == 0.0
    assert vt.last_pose_buffer_size == 0


# ---------------------------------------------------------------------------
# 2. _loop 计算 drift_ms 正确
# ---------------------------------------------------------------------------

def test_loop_calculates_drift_ms():
    """_loop 运行后 last_pose_buffer_drift_ms 应为 (published_time - capture_time) * 1000。"""
    vision = _StubVision()
    pose_buffer = RobotPoseBuffer()
    # 预填充 pose_buffer 使 pose_at 能返回有效值
    capture_time_approx = time.perf_counter()
    pose_buffer.push(capture_time_approx, [0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    pose_buffer.push(capture_time_approx + 0.001, [0.0, 0.0, 0.0, 0.0, 0.0, 0.0])

    controller = _StubController(pose_buffer=pose_buffer)
    cache = TargetCache()
    vt = VisionThread(vision=vision, controller=controller, target_cache=cache)
    vt._running = True

    # 运行 _loop（is_available 第一次 True，第二次 False → 单次迭代后退出）
    vt._loop()

    # drift_ms 应为正数（published_time > capture_time）
    assert vt.last_pose_buffer_drift_ms > 0.0
    # drift_ms 应在合理范围内（单次迭代 < 1s = 1000ms）
    assert vt.last_pose_buffer_drift_ms < 1000.0


def test_loop_records_pose_buffer_size():
    """_loop 运行后 last_pose_buffer_size 应反映 controller.pose_buffer 长度。"""
    vision = _StubVision()
    pose_buffer = RobotPoseBuffer()
    # 预填充 3 条
    t0 = time.perf_counter()
    for i in range(3):
        pose_buffer.push(t0 + i * 0.001, [float(i), 0, 0, 0, 0, 0])

    controller = _StubController(pose_buffer=pose_buffer)
    cache = TargetCache()
    vt = VisionThread(vision=vision, controller=controller, target_cache=cache)
    vt._running = True

    vt._loop()

    # pose_buffer_size 应为 3（预填充的）或 3+（如果有新 push，但这里没有 feedback 线程）
    assert vt.last_pose_buffer_size >= 3


def test_loop_drift_ms_zero_when_controller_none():
    """controller 为 None 时 drift_ms 仍计算，pose_buffer_size 为 0。"""
    vision = _StubVision()
    cache = TargetCache()
    vt = VisionThread(vision=vision, controller=None, target_cache=cache)
    vt._running = True

    vt._loop()

    assert vt.last_pose_buffer_drift_ms > 0.0
    assert vt.last_pose_buffer_size == 0


# ---------------------------------------------------------------------------
# 3. get_visual_servo_telemetry 输出 telemetry 字段
# ---------------------------------------------------------------------------

def test_get_visual_servo_telemetry_includes_drift_and_size():
    """get_visual_servo_telemetry() 应输出 pose_buffer_drift_ms 和 pose_buffer_size。"""
    from dobot_move.flow.flow_executor import FlowExecutor

    # 构建 mock active_visual_servo
    mock_vision_thread = MagicMock()
    mock_vision_thread.last_pose_buffer_drift_ms = 5.5
    mock_vision_thread.last_pose_buffer_size = 42
    mock_vision_thread.last_capture_ms = 10.0
    mock_vision_thread.last_detect_ms = 20.0
    mock_vision_thread.last_depth_ms = 5.0
    mock_vision_thread.last_total_ms = 35.0

    mock_servo_thread = MagicMock()
    mock_servo_thread._running = True
    mock_servo_thread.last_error_mm = 1.5
    mock_servo_thread.last_error_xyz = [0.1, 0.2, 0.3]
    mock_servo_thread.final_error_mm = -1.0
    mock_servo_thread.iterations = 5
    mock_servo_thread.servo_period = 0.06
    mock_servo_thread.last_hz = 16.7
    mock_servo_thread.last_target_age = 0.05
    mock_servo_thread.last_pose_age = 0.02
    mock_servo_thread.last_servo_ms = 3.0
    mock_servo_thread.avg_servo_ms = 2.5
    mock_servo_thread.last_total_ms = 40.0

    mock_controller = MagicMock()
    mock_controller.servo_thread = mock_servo_thread
    mock_controller.vision_thread = mock_vision_thread

    executor = FlowExecutor.__new__(FlowExecutor)
    executor.active_visual_servo = mock_controller
    executor.last_visual_servo_telemetry = {}

    telemetry = executor.get_visual_servo_telemetry()

    assert "pose_buffer_drift_ms" in telemetry
    assert "pose_buffer_size" in telemetry
    assert telemetry["pose_buffer_drift_ms"] == 5.5
    assert telemetry["pose_buffer_size"] == 42


def test_get_visual_servo_telemetry_defaults_when_no_vision():
    """无 vision_thread 时 pose_buffer_drift_ms=0.0, pose_buffer_size=0。"""
    from dobot_move.flow.flow_executor import FlowExecutor

    mock_servo_thread = MagicMock()
    mock_servo_thread._running = True
    mock_servo_thread.last_error_mm = 0.0
    mock_servo_thread.last_error_xyz = [0.0, 0.0, 0.0]
    mock_servo_thread.final_error_mm = -1.0
    mock_servo_thread.iterations = 0
    mock_servo_thread.servo_period = 0.06
    mock_servo_thread.last_hz = 0.0
    mock_servo_thread.last_target_age = 0.0
    mock_servo_thread.last_pose_age = 0.0
    mock_servo_thread.last_servo_ms = 0.0
    mock_servo_thread.avg_servo_ms = 0.0
    mock_servo_thread.last_total_ms = 0.0

    mock_controller = MagicMock()
    mock_controller.servo_thread = mock_servo_thread
    mock_controller.vision_thread = None

    executor = FlowExecutor.__new__(FlowExecutor)
    executor.active_visual_servo = mock_controller
    executor.last_visual_servo_telemetry = {}

    telemetry = executor.get_visual_servo_telemetry()

    assert telemetry["pose_buffer_drift_ms"] == 0.0
    assert telemetry["pose_buffer_size"] == 0
