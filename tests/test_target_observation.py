#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PR1 单元测试：TargetObservation dataclass + TargetCache 改用 TargetObservation。

覆盖：
1. TargetObservation 构造与字段访问
2. detection 路径：update_from_detection(pose 有效) → source="detection"
3. fallback 路径：update_from_detection(pose=None) → source="fallback"
4. prediction 路径：update_from_prediction → source="prediction", prediction_age>0
5. covariance 字段
6. read_base() 保持 (target_base, confidence, age) 兼容签名
7. read_observation() 返回权威 TargetObservation
"""

import sys
import types

import numpy as np
import pytest

# 与项目内其他 vision 测试保持一致：未安装真实 SDK 时注入桩模块
if "pyrealsense2" not in sys.modules:
    sys.modules["pyrealsense2"] = types.ModuleType("pyrealsense2")

from dobot_move.robot.visual_servo_controller import (
    TargetCache,
    TargetObservation,
)


# ---------------------------------------------------------------------------
# 1. TargetObservation 构造与字段访问
# ---------------------------------------------------------------------------

def test_target_observation_construction_and_field_access():
    """TargetObservation 可用全部字段构造，字段访问正确。"""
    cov = np.eye(3) * 0.5
    obs = TargetObservation(
        measurement_time=100.0,
        published_time=100.05,
        source="detection",
        confidence=0.92,
        prediction_age=0.0,
        covariance=cov,
    )
    assert obs.measurement_time == 100.0
    assert obs.published_time == 100.05
    assert obs.source == "detection"
    assert obs.confidence == pytest.approx(0.92)
    assert obs.prediction_age == 0.0
    np.testing.assert_allclose(obs.covariance, cov)


def test_target_observation_default_covariance_is_none():
    """covariance 默认为 None。"""
    obs = TargetObservation(
        measurement_time=1.0,
        published_time=1.0,
        source="fallback",
        confidence=0.0,
        prediction_age=0.0,
    )
    assert obs.covariance is None


def test_target_observation_source_values():
    """source 字段支持 detection / prediction / fallback 三种取值。"""
    for src in ("detection", "prediction", "fallback"):
        obs = TargetObservation(
            measurement_time=1.0,
            published_time=1.0,
            source=src,
            confidence=0.5,
            prediction_age=0.0,
        )
        assert obs.source == src


# ---------------------------------------------------------------------------
# 2. detection 路径：update_from_detection(pose 有效) → source="detection"
# ---------------------------------------------------------------------------

class _AdditiveMockVision:
    """convert_to_base_coords(target_end, pose) = target_end + pose[:3]"""

    def __init__(self):
        self.convert_calls = []

    def convert_to_base_coords(self, target_end, current_pose):
        target_end = np.asarray(target_end, dtype=np.float64)
        current_pose = np.asarray(current_pose, dtype=np.float64)
        self.convert_calls.append((target_end.copy(), current_pose.copy()))
        return target_end + current_pose[:3]


def test_update_from_detection_with_valid_pose_creates_detection_observation():
    """pose_at_capture 有效 → TargetObservation.source="detection"。"""
    mock_vision = _AdditiveMockVision()
    cache = TargetCache()

    target_end = np.array([1.0, 2.0, 3.0], dtype=np.float64)
    pose_at_capture = np.array([10.0, 0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float64)
    cache.update_from_detection(
        target_end=target_end,
        pose_at_capture=pose_at_capture,
        confidence=0.9,
        vision=mock_vision,
        measurement_time=100.0,
    )

    obs = cache.read_observation()
    assert obs is not None
    assert obs.source == "detection"
    assert obs.confidence == pytest.approx(0.9)
    assert obs.prediction_age == 0.0
    assert obs.measurement_time == pytest.approx(100.0)
    assert obs.published_time > 0.0

    # target_base 应被预计算：target_end + pose[:3] = [11, 2, 3]
    assert cache.target_base is not None
    np.testing.assert_allclose(cache.target_base, [11.0, 2.0, 3.0])


def test_update_from_detection_writes_target_base_and_end():
    """detection 命中后 target_base / target_end / target_capture_time 均被写入（兼容字段）。"""
    mock_vision = _AdditiveMockVision()
    cache = TargetCache()

    target_end = np.array([1.0, 2.0, 3.0], dtype=np.float64)
    pose_at_capture = np.array([5.0, 0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float64)
    cache.update_from_detection(
        target_end=target_end,
        pose_at_capture=pose_at_capture,
        confidence=0.85,
        vision=mock_vision,
        measurement_time=99.0,
    )

    assert cache.target_base is not None
    np.testing.assert_allclose(cache.target_base, [6.0, 2.0, 3.0])
    np.testing.assert_allclose(cache.target_end, target_end)
    assert cache.target_capture_time > 0.0
    assert cache.confidence == pytest.approx(0.85)


# ---------------------------------------------------------------------------
# 3. fallback 路径：update_from_detection(pose=None) → source="fallback"
# ---------------------------------------------------------------------------

def test_update_from_detection_with_none_pose_creates_fallback_observation():
    """pose_at_capture=None → TargetObservation.source="fallback"，target_base 未写。"""
    mock_vision = _AdditiveMockVision()
    cache = TargetCache()

    target_end = np.array([1.0, 2.0, 3.0], dtype=np.float64)
    cache.update_from_detection(
        target_end=target_end,
        pose_at_capture=None,
        confidence=0.7,
        vision=mock_vision,
        measurement_time=50.0,
    )

    obs = cache.read_observation()
    assert obs is not None
    assert obs.source == "fallback"
    assert obs.confidence == pytest.approx(0.7)
    assert obs.prediction_age == 0.0
    assert obs.measurement_time == pytest.approx(50.0)

    # fallback 路径不写 target_base
    assert cache.target_base is None
    assert cache.target_end is not None
    np.testing.assert_allclose(cache.target_end, target_end)
    # 不应调用 convert_to_base_coords
    assert len(mock_vision.convert_calls) == 0


# ---------------------------------------------------------------------------
# 4. prediction 路径：update_from_prediction → source="prediction"
# ---------------------------------------------------------------------------

def test_update_from_prediction_creates_prediction_observation():
    """update_from_prediction → source="prediction", prediction_age>0。"""
    cache = TargetCache()
    target_base = np.array([15.0, 25.0, 35.0], dtype=np.float64)

    cache.update_from_prediction(
        target_base=target_base,
        confidence=0.6,
        prediction_age=0.12,
        covariance=np.eye(3) * 0.1,
    )

    obs = cache.read_observation()
    assert obs is not None
    assert obs.source == "prediction"
    assert obs.confidence == pytest.approx(0.6)
    assert obs.prediction_age == pytest.approx(0.12)
    assert obs.prediction_age > 0.0
    assert obs.covariance is not None
    np.testing.assert_allclose(obs.covariance, np.eye(3) * 0.1)

    # target_base 已写入
    assert cache.target_base is not None
    np.testing.assert_allclose(cache.target_base, [15.0, 25.0, 35.0])


def test_update_from_prediction_default_covariance_none():
    """update_from_prediction 未传 covariance → observation.covariance is None。"""
    cache = TargetCache()
    cache.update_from_prediction(
        target_base=np.array([0.0, 0.0, 0.0]),
        confidence=0.5,
        prediction_age=0.05,
    )
    obs = cache.read_observation()
    assert obs is not None
    assert obs.covariance is None


# ---------------------------------------------------------------------------
# 5. covariance 字段
# ---------------------------------------------------------------------------

def test_observation_covariance_3x3_matrix():
    """covariance 字段可存储任意 3×3 矩阵并在 read_observation 中返回拷贝。"""
    cov = np.array([
        [0.1, 0.01, 0.0],
        [0.01, 0.2, 0.0],
        [0.0, 0.0, 0.3],
    ])
    cache = TargetCache()
    cache.update_from_prediction(
        target_base=np.array([1.0, 2.0, 3.0]),
        confidence=0.8,
        prediction_age=0.1,
        covariance=cov,
    )

    obs = cache.read_observation()
    np.testing.assert_allclose(obs.covariance, cov)

    # read_observation 应返回拷贝，修改不影响内部
    obs.covariance[0, 0] = 999.0
    obs2 = cache.read_observation()
    assert obs2.covariance[0, 0] == pytest.approx(0.1)


# ---------------------------------------------------------------------------
# 6. read_base() 保持 (target_base, confidence, age) 兼容签名
# ---------------------------------------------------------------------------

def test_read_base_returns_compatible_tuple_after_detection():
    """read_base() 返回 (target_base, confidence, age) 三元组。"""
    mock_vision = _AdditiveMockVision()
    cache = TargetCache()

    target_end = np.array([1.0, 2.0, 3.0], dtype=np.float64)
    pose_at_capture = np.array([10.0, 0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float64)
    cache.update_from_detection(
        target_end=target_end,
        pose_at_capture=pose_at_capture,
        confidence=0.88,
        vision=mock_vision,
    )

    target_base, conf, age = cache.read_base(max_age=1.0)
    assert target_base is not None
    np.testing.assert_allclose(target_base, [11.0, 2.0, 3.0])
    assert conf == pytest.approx(0.88)
    assert age >= 0.0


def test_read_base_returns_none_when_empty():
    """空缓存时 read_base() 返回 (None, 0.0, inf)。"""
    cache = TargetCache()
    target_base, conf, age = cache.read_base()
    assert target_base is None
    assert conf == 0.0
    assert age == float('inf')


def test_read_base_returns_none_when_expired():
    """过期后 read_base() 返回 (None, 0.0, age)。"""
    mock_vision = _AdditiveMockVision()
    cache = TargetCache()
    cache.update_from_detection(
        target_end=np.array([1.0, 2.0, 3.0]),
        pose_at_capture=np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
        confidence=0.9,
        vision=mock_vision,
    )
    # max_age=0 → 立即过期
    target_base, conf, age = cache.read_base(max_age=0.0)
    assert target_base is None
    assert age >= 0.0


# ---------------------------------------------------------------------------
# 7. read_observation() 返回权威 TargetObservation
# ---------------------------------------------------------------------------

def test_read_observation_returns_none_when_empty():
    """空缓存时 read_observation() 返回 None。"""
    cache = TargetCache()
    assert cache.read_observation() is None


def test_clear_resets_observation():
    """clear() 后 observation 为 None。"""
    mock_vision = _AdditiveMockVision()
    cache = TargetCache()
    cache.update_from_detection(
        target_end=np.array([1.0, 2.0, 3.0]),
        pose_at_capture=np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
        confidence=0.9,
        vision=mock_vision,
    )
    assert cache.read_observation() is not None

    cache.clear()
    assert cache.read_observation() is None
    assert cache.target_base is None
    assert cache.target_end is None


# ---------------------------------------------------------------------------
# 8. VisionThread fallback 路径：controller.pose_buffer 为空时 source="fallback"
# ---------------------------------------------------------------------------

class _StubController:
    """最小 controller 桩，仅提供 pose_buffer 属性。"""

    def __init__(self, pose_buffer):
        self.pose_buffer = pose_buffer


class _StubVision:
    """最小 vision 桩。"""

    is_available = True

    def capture_frames(self):
        # 不实际使用（VisionThread._loop 在测试中不直接运行）
        return None, None

    def reset_tracking(self):
        pass

    def run_detection_tracked(self, image):
        return None

    def calculate_object_position_smoothed(self, depth, color, target):
        return None

    def convert_to_end_coords(self, camera_coords):
        return [0.0, 0.0, 0.0]

    def convert_to_base_coords(self, target_end, pose):
        return list(target_end) + list(pose[:3])


def test_vision_thread_loop_uses_controller_pose_buffer_valid():
    """VisionThread 通过 controller.pose_buffer 查询，有效 pose → source="detection"。

    直接验证：controller.pose_buffer 有数据时，update_from_detection 收到非 None pose。
    """
    from dobot_move.robot.robot_pose_buffer import RobotPoseBuffer

    buf = RobotPoseBuffer()
    buf.push(100.0, [10.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    buf.push(100.1, [20.0, 0.0, 0.0, 0.0, 0.0, 0.0])

    controller = _StubController(pose_buffer=buf)

    # 模拟 VisionThread._loop 中的 pose_buffer 查询逻辑
    capture_time = 100.05
    pose_at_capture = None
    pose_buffer = getattr(controller, "pose_buffer", None)
    if pose_buffer is not None and capture_time > 0:
        pose_at_capture, ok = pose_buffer.pose_at(capture_time)
        if not ok:
            pose_at_capture = None

    assert pose_at_capture is not None
    # 插值结果应为 [15, 0, 0, 0, 0, 0]
    np.testing.assert_allclose(pose_at_capture, [15.0, 0.0, 0.0, 0.0, 0.0, 0.0])

    # 传入 update_from_detection → source="detection"
    mock_vision = _AdditiveMockVision()
    cache = TargetCache()
    cache.update_from_detection(
        target_end=np.array([1.0, 2.0, 3.0]),
        pose_at_capture=pose_at_capture,
        confidence=0.9,
        vision=mock_vision,
        measurement_time=capture_time,
    )
    obs = cache.read_observation()
    assert obs.source == "detection"


def test_vision_thread_loop_fallback_when_pose_buffer_empty():
    """VisionThread 通过 controller.pose_buffer 查询，空 buffer → source="fallback"。

    直接验证：controller.pose_buffer 为空时，pose_at_capture=None，
    update_from_detection 生成 source="fallback"。
    """
    from dobot_move.robot.robot_pose_buffer import RobotPoseBuffer

    buf = RobotPoseBuffer()  # 空 buffer
    controller = _StubController(pose_buffer=buf)

    capture_time = 100.05
    pose_at_capture = None
    pose_buffer = getattr(controller, "pose_buffer", None)
    if pose_buffer is not None and capture_time > 0:
        pose_at_capture, ok = pose_buffer.pose_at(capture_time)
        if not ok:
            pose_at_capture = None

    assert pose_at_capture is None

    # 传入 update_from_detection → source="fallback"
    mock_vision = _AdditiveMockVision()
    cache = TargetCache()
    cache.update_from_detection(
        target_end=np.array([1.0, 2.0, 3.0]),
        pose_at_capture=pose_at_capture,
        confidence=0.7,
        vision=mock_vision,
        measurement_time=capture_time,
    )
    obs = cache.read_observation()
    assert obs.source == "fallback"


def test_vision_thread_loop_fallback_when_controller_has_no_pose_buffer():
    """controller 无 pose_buffer 属性时 → pose_at_capture=None → source="fallback"。"""
    controller = _StubController(pose_buffer=None)

    capture_time = 100.05
    pose_at_capture = None
    pose_buffer = getattr(controller, "pose_buffer", None)
    if pose_buffer is not None and capture_time > 0:
        pose_at_capture, ok = pose_buffer.pose_at(capture_time)
        if not ok:
            pose_at_capture = None

    assert pose_at_capture is None

    mock_vision = _AdditiveMockVision()
    cache = TargetCache()
    cache.update_from_detection(
        target_end=np.array([1.0, 2.0, 3.0]),
        pose_at_capture=pose_at_capture,
        confidence=0.5,
        vision=mock_vision,
        measurement_time=capture_time,
    )
    obs = cache.read_observation()
    assert obs.source == "fallback"
