#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PR-B Prediction Control Policy 单元测试。

覆盖 Task 1-5:
- Task 1: 三种 source（detection / smoothed / prediction）正确写入 TargetObservation
- Task 2: prediction 路径写入 TargetCache 后 read_base() 返回预测 target_base
- Task 3: prediction_age gate（0.6s 拒绝，0.4s 通过）
- Task 4: covariance gate（trace=150 拒绝，trace=50 通过）+ KalmanFilter3D.get_covariance
- Task 5: prediction 时 max_step / gain 缩减；连续 5 次后软停止
- Task 6: D405 kalman_3d_base 检测后 initialized；reset 后 False
"""

import sys
import types

import numpy as np
import pytest

# 与项目内其他 vision 测试保持一致：未安装真实 SDK 时注入桩模块
if "pyrealsense2" not in sys.modules:
    sys.modules["pyrealsense2"] = types.ModuleType("pyrealsense2")

from dobot_move.robot.visual_servo_controller import (
    ServoThread,
    TargetCache,
    TargetObservation,
)
from dobot_move.vision.kalman_filter_3d import KalmanFilter3D
from dobot_move.vision.vision_system import VisionSystem


# ---------------------------------------------------------------------------
# 共享桩
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


def _make_servo_thread(target_cache, vision=None, max_target_age=0.3):
    """绕过 ServoThread.__init__（依赖 get_visual_servo_config），装上所需属性。"""
    thread = object.__new__(ServoThread)
    thread.vision = vision if vision is not None else _AdditiveMockVision()
    thread.target_cache = target_cache
    thread.max_target_age = max_target_age
    # Task 3 / 4 / 5 gates
    thread.prediction_age_gate = 0.5
    thread.covariance_gate = 100.0
    thread.prediction_max_step_ratio = 0.5
    thread.prediction_speed_ratio = 0.7
    thread.max_consecutive_predictions = 5
    thread._consecutive_predictions = 0
    return thread


# ---------------------------------------------------------------------------
# Task 1: 三种 source 正确写入
# ---------------------------------------------------------------------------

def test_task1_smoothed_source_written_to_observation():
    """update_from_detection(source='smoothed') → observation.source == 'smoothed'。"""
    mock_vision = _AdditiveMockVision()
    cache = TargetCache()

    cache.update_from_detection(
        target_end=np.array([1.0, 2.0, 3.0]),
        pose_at_capture=np.array([10.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
        confidence=0.9,
        vision=mock_vision,
        source="smoothed",
    )
    obs = cache.read_observation()
    assert obs is not None
    assert obs.source == "smoothed"
    assert obs.prediction_age == 0.0


def test_task1_detection_source_default_written_to_observation():
    """update_from_detection 默认 source='detection'。"""
    mock_vision = _AdditiveMockVision()
    cache = TargetCache()

    cache.update_from_detection(
        target_end=np.array([1.0, 2.0, 3.0]),
        pose_at_capture=np.array([10.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
        confidence=0.85,
        vision=mock_vision,
    )
    obs = cache.read_observation()
    assert obs is not None
    assert obs.source == "detection"


def test_task1_prediction_source_written_via_update_from_prediction():
    """update_from_prediction → observation.source == 'prediction'。"""
    cache = TargetCache()
    cache.update_from_prediction(
        target_base=np.array([15.0, 25.0, 35.0]),
        confidence=0.6,
        prediction_age=0.12,
    )
    obs = cache.read_observation()
    assert obs is not None
    assert obs.source == "prediction"
    assert obs.prediction_age == pytest.approx(0.12)


def test_task1_smoothed_source_round_trips_through_cache():
    """smoothed 路径：cache 中 target_base 被预计算，observation.source == 'smoothed'。"""
    mock_vision = _AdditiveMockVision()
    cache = TargetCache()
    target_end = np.array([1.0, 2.0, 3.0], dtype=np.float64)
    pose = np.array([10.0, 0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float64)

    cache.update_from_detection(
        target_end=target_end,
        pose_at_capture=pose,
        confidence=0.9,
        vision=mock_vision,
        source="smoothed",
        measurement_time=100.0,
    )
    # target_base = target_end + pose[:3] = [11, 2, 3]
    np.testing.assert_allclose(cache.target_base, [11.0, 2.0, 3.0])
    obs = cache.read_observation()
    assert obs.source == "smoothed"


# ---------------------------------------------------------------------------
# Task 2: prediction 路径写入 TargetCache
# ---------------------------------------------------------------------------

def test_task2_prediction_path_read_base_returns_predicted_target_base():
    """update_from_prediction 后 read_base() 返回预测 target_base。"""
    cache = TargetCache()
    predicted_base = np.array([42.0, 17.0, 8.0], dtype=np.float64)
    # 不传 measurement_time，使其默认为当前 perf_counter（read_base age 判定需要）
    cache.update_from_prediction(
        target_base=predicted_base,
        confidence=0.55,
        prediction_age=0.08,
        covariance=np.eye(3) * 2.0,
    )

    target_base, conf, age = cache.read_base(max_age=1.0)
    assert target_base is not None
    np.testing.assert_allclose(target_base, predicted_base)
    assert conf == pytest.approx(0.55)

    obs = cache.read_observation()
    assert obs is not None
    assert obs.source == "prediction"
    assert obs.prediction_age == pytest.approx(0.08)
    assert obs.covariance is not None
    np.testing.assert_allclose(obs.covariance, np.eye(3) * 2.0)


def test_task2_prediction_path_with_covariance_none():
    """prediction 路径 covariance 缺省为 None。"""
    cache = TargetCache()
    cache.update_from_prediction(
        target_base=np.array([0.0, 0.0, 0.0]),
        confidence=0.5,
        prediction_age=0.05,
    )
    obs = cache.read_observation()
    assert obs.covariance is None


# ---------------------------------------------------------------------------
# Task 3: prediction_age gate
# ---------------------------------------------------------------------------

def test_task3_prediction_age_gate_rejects_when_exceeded():
    """prediction_age=0.6s > gate=0.5s → _resolve_target_base 返回 None。"""
    cache = TargetCache()
    cache.update_from_prediction(
        target_base=np.array([100.0, 200.0, 300.0]),
        confidence=0.6,
        prediction_age=0.6,  # > 0.5 gate
        covariance=np.eye(3) * 10.0,  # trace=30 < 100, 不触发 covariance gate
    )
    servo = _make_servo_thread(cache)

    current_pose = np.array([90.0, 190.0, 290.0, 0.0, 0.0, 0.0])
    target_base, conf, age, convert_ms = servo._resolve_target_base(current_pose)
    assert target_base is None
    assert age == float('inf')


def test_task3_prediction_age_gate_passes_when_within():
    """prediction_age=0.4s < gate=0.5s → _resolve_target_base 返回 target_base。"""
    cache = TargetCache()
    target_base_pred = np.array([100.0, 200.0, 300.0])
    cache.update_from_prediction(
        target_base=target_base_pred,
        confidence=0.6,
        prediction_age=0.4,  # < 0.5 gate
        covariance=np.eye(3) * 10.0,  # trace=30 < 100
    )
    servo = _make_servo_thread(cache)

    current_pose = np.array([90.0, 190.0, 290.0, 0.0, 0.0, 0.0])
    target_base, conf, age, convert_ms = servo._resolve_target_base(current_pose)
    assert target_base is not None
    np.testing.assert_allclose(target_base[:3], target_base_pred)


def test_task3_prediction_age_gate_does_not_apply_to_detection():
    """detection 路径不受 prediction_age gate 影响（prediction_age=0.0）。"""
    mock_vision = _AdditiveMockVision()
    cache = TargetCache()
    cache.update_from_detection(
        target_end=np.array([1.0, 2.0, 3.0]),
        pose_at_capture=np.array([10.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
        confidence=0.9,
        vision=mock_vision,
        source="detection",
    )
    servo = _make_servo_thread(cache)

    current_pose = np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    target_base, conf, age, convert_ms = servo._resolve_target_base(current_pose)
    assert target_base is not None


# ---------------------------------------------------------------------------
# Task 4: covariance gate + KalmanFilter3D.get_covariance
# ---------------------------------------------------------------------------

def test_task4_get_covariance_returns_3x3_copy():
    """KalmanFilter3D.get_covariance() 返回 P[:3,:3] 的拷贝。"""
    kf = KalmanFilter3D()
    kf.update([1.0, 2.0, 3.0])

    cov = kf.get_covariance()
    assert cov.shape == (3, 3)
    # 应与 P[:3,:3] 一致
    np.testing.assert_allclose(cov, kf.P[:3, :3])

    # 返回拷贝：修改不影响内部状态
    cov[0, 0] = 999.0
    cov2 = kf.get_covariance()
    assert cov2[0, 0] != 999.0


def test_task4_covariance_gate_rejects_when_trace_exceeds():
    """covariance trace=150 > gate=100 → _resolve_target_base 返回 None。"""
    cache = TargetCache()
    # trace = 50 * 3 = 150
    cov = np.eye(3) * 50.0
    cache.update_from_prediction(
        target_base=np.array([100.0, 200.0, 300.0]),
        confidence=0.5,
        prediction_age=0.1,  # < 0.5 gate, 不触发 age gate
        covariance=cov,
    )
    servo = _make_servo_thread(cache)

    current_pose = np.array([90.0, 190.0, 290.0, 0.0, 0.0, 0.0])
    target_base, conf, age, convert_ms = servo._resolve_target_base(current_pose)
    assert target_base is None


def test_task4_covariance_gate_passes_when_trace_within():
    """covariance trace=50 < gate=100 → _resolve_target_base 返回 target_base。"""
    cache = TargetCache()
    target_base_pred = np.array([100.0, 200.0, 300.0])
    # trace = 50/3 * 3 ≈ 50
    cov = np.eye(3) * (50.0 / 3.0)
    cache.update_from_prediction(
        target_base=target_base_pred,
        confidence=0.5,
        prediction_age=0.1,
        covariance=cov,
    )
    servo = _make_servo_thread(cache)

    current_pose = np.array([90.0, 190.0, 290.0, 0.0, 0.0, 0.0])
    target_base, conf, age, convert_ms = servo._resolve_target_base(current_pose)
    assert target_base is not None
    np.testing.assert_allclose(target_base[:3], target_base_pred)


def test_task4_covariance_gate_none_covariance_passes():
    """observation.covariance is None → covariance gate 不触发。"""
    cache = TargetCache()
    cache.update_from_prediction(
        target_base=np.array([100.0, 200.0, 300.0]),
        confidence=0.5,
        prediction_age=0.1,
        covariance=None,
    )
    servo = _make_servo_thread(cache)

    current_pose = np.array([90.0, 190.0, 290.0, 0.0, 0.0, 0.0])
    target_base, conf, age, convert_ms = servo._resolve_target_base(current_pose)
    assert target_base is not None


# ---------------------------------------------------------------------------
# Task 5: prediction 时降速/限步长 + 连续 5 次软停止
# ---------------------------------------------------------------------------

def _make_prediction_observation(prediction_age=0.1, covariance=None):
    return TargetObservation(
        measurement_time=100.0,
        published_time=100.05,
        source="prediction",
        confidence=0.6,
        prediction_age=prediction_age,
        covariance=covariance,
    )


def _make_detection_observation():
    return TargetObservation(
        measurement_time=100.0,
        published_time=100.05,
        source="detection",
        confidence=0.9,
        prediction_age=0.0,
        covariance=None,
    )


def test_task5_prediction_reduces_max_step_and_gain():
    """prediction 时 max_step 缩减为 50%，gain 缩减为 70%。"""
    servo = _make_servo_thread(TargetCache())
    obs = _make_prediction_observation()

    max_step_in = 10.0
    gain_in = 0.8
    max_step, gain, should_skip = servo._apply_prediction_policy(obs, max_step_in, gain_in)

    assert should_skip is False
    assert max_step == pytest.approx(5.0)   # 10 * 0.5
    assert gain == pytest.approx(0.56)       # 0.8 * 0.7
    assert servo._consecutive_predictions == 1


def test_task5_detection_does_not_reduce():
    """非 prediction 路径不缩减，_consecutive_predictions 归零。"""
    servo = _make_servo_thread(TargetCache())
    servo._consecutive_predictions = 3  # 预置
    obs = _make_detection_observation()

    max_step_in = 10.0
    gain_in = 0.8
    max_step, gain, should_skip = servo._apply_prediction_policy(obs, max_step_in, gain_in)

    assert should_skip is False
    assert max_step == pytest.approx(10.0)
    assert gain == pytest.approx(0.8)
    assert servo._consecutive_predictions == 0


def test_task5_none_observation_does_not_reduce():
    """observation=None 视为非 prediction，归零计数。"""
    servo = _make_servo_thread(TargetCache())
    servo._consecutive_predictions = 2

    max_step, gain, should_skip = servo._apply_prediction_policy(None, 10.0, 0.8)
    assert should_skip is False
    assert max_step == pytest.approx(10.0)
    assert gain == pytest.approx(0.8)
    assert servo._consecutive_predictions == 0


def test_task5_consecutive_prediction_soft_stop_at_limit():
    """连续 5 次 prediction 后触发软停止（should_skip=True）。"""
    servo = _make_servo_thread(TargetCache())
    obs = _make_prediction_observation()

    # 前 4 次：不跳过，但计数累加
    for i in range(4):
        _, _, should_skip = servo._apply_prediction_policy(obs, 10.0, 0.8)
        assert should_skip is False, f"iter {i+1} 不应跳过"
    assert servo._consecutive_predictions == 4

    # 第 5 次：触发软停止
    _, _, should_skip = servo._apply_prediction_policy(obs, 10.0, 0.8)
    assert should_skip is True
    assert servo._consecutive_predictions == 5


def test_task5_consecutive_predictions_reset_on_detection():
    """prediction 计数在 detection 出现时归零。"""
    servo = _make_servo_thread(TargetCache())
    pred_obs = _make_prediction_observation()
    det_obs = _make_detection_observation()

    # 累加 3 次 prediction
    for _ in range(3):
        servo._apply_prediction_policy(pred_obs, 10.0, 0.8)
    assert servo._consecutive_predictions == 3

    # 一次 detection 归零
    servo._apply_prediction_policy(det_obs, 10.0, 0.8)
    assert servo._consecutive_predictions == 0

    # 再次 prediction 从 1 开始
    servo._apply_prediction_policy(pred_obs, 10.0, 0.8)
    assert servo._consecutive_predictions == 1


# ---------------------------------------------------------------------------
# Task 6: D405 kalman_3d_base
# ---------------------------------------------------------------------------

def _make_minimal_d405_vision():
    """构造带 kalman_3d_base 的最小 VisionSystem（绕过 __init__ 硬件初始化）。"""
    vision = object.__new__(VisionSystem)
    vision.camera_type = "D405"
    vision.kalman_3d = KalmanFilter3D()
    vision.kalman_3d_base = KalmanFilter3D()
    return vision


def _make_minimal_d435i_vision():
    """构造 D435i VisionSystem（kalman_3d_base 应为 None）。"""
    vision = object.__new__(VisionSystem)
    vision.camera_type = "D435i"
    vision.kalman_3d = KalmanFilter3D()
    vision.kalman_3d_base = None
    return vision


def test_task6_d405_detection_initializes_kalman_3d_base():
    """D405 检测后 update_base_kalman 使 kalman_3d_base.initialized == True。"""
    vision = _make_minimal_d405_vision()
    assert vision.kalman_3d_base.initialized is False

    target_base = np.array([100.0, 200.0, 300.0])
    vision.update_base_kalman(target_base)

    assert vision.kalman_3d_base.initialized is True


def test_task6_d435i_kalman_3d_base_is_none_and_update_is_noop():
    """D435i kalman_3d_base 为 None，update_base_kalman 为 no-op。"""
    vision = _make_minimal_d435i_vision()
    assert vision.kalman_3d_base is None

    # 不应抛异常
    vision.update_base_kalman(np.array([1.0, 2.0, 3.0]))


def test_task6_reset_tracking_resets_kalman_3d_base():
    """reset_tracking 后 kalman_3d_base.initialized == False。"""
    vision = _make_minimal_d405_vision()
    vision.update_base_kalman(np.array([100.0, 200.0, 300.0]))
    assert vision.kalman_3d_base.initialized is True

    # 构造 reset_tracking 所需的最小属性
    vision.tracker = None
    vision.tracked_target_id = None
    vision.last_valid_position = None
    vision._kalman_last_time = None

    vision.reset_tracking()
    assert vision.kalman_3d_base.initialized is False
    assert vision.kalman_3d.initialized is False
