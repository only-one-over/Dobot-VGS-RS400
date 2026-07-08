#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Task 3 测试：measurement_age 替代 publication_age。

覆盖：
1. TargetObservation.measurement_age 属性基于 perf_counter 计算
2. read_base 使用 measurement_age 判定新鲜度
3. read_end 使用 measurement_age 判定新鲜度
4. detection 写入后 100ms 读取，age≈0.1s
5. prediction 路径 measurement_age 与 published_age 不同时以 measurement_age 为准
"""

import sys
import time
import types

import numpy as np
import pytest

if "pyrealsense2" not in sys.modules:
    sys.modules["pyrealsense2"] = types.ModuleType("pyrealsense2")

from dobot_move.robot.visual_servo_controller import (
    TargetCache,
    TargetObservation,
)


class _AdditiveMockVision:
    """convert_to_base_coords(target_end, pose) = target_end + pose[:3]"""

    def convert_to_base_coords(self, target_end, current_pose):
        target_end = np.asarray(target_end, dtype=np.float64)
        current_pose = np.asarray(current_pose, dtype=np.float64)
        return target_end + current_pose[:3]


# ---------------------------------------------------------------------------
# 1. measurement_age 属性
# ---------------------------------------------------------------------------

def test_measurement_age_property():
    """TargetObservation.measurement_age 基于 perf_counter 计算年龄。"""
    t = time.perf_counter()
    obs = TargetObservation(
        measurement_time=t,
        published_time=t + 0.001,
        source="detection",
        confidence=0.9,
        prediction_age=0.0,
    )
    age = obs.measurement_age
    assert age >= 0.0
    # 刚创建，age 应该很小
    assert age < 1.0


def test_measurement_age_grows_over_time():
    """measurement_age 随时间增长。"""
    t_old = time.perf_counter() - 0.5
    obs = TargetObservation(
        measurement_time=t_old,
        published_time=t_old + 0.001,
        source="detection",
        confidence=0.9,
        prediction_age=0.0,
    )
    age = obs.measurement_age
    assert age >= 0.4  # 至少 0.4s（留些余量）


# ---------------------------------------------------------------------------
# 2. read_base 使用 measurement_age
# ---------------------------------------------------------------------------

def test_read_base_uses_measurement_age():
    """read_base 应使用 measurement_age 而非 published_age 判定新鲜度。"""
    mock_vision = _AdditiveMockVision()
    cache = TargetCache()

    # measurement_time 设为较旧的过去时刻
    old_measurement = time.perf_counter() - 0.5
    cache.update_from_detection(
        target_end=np.array([1.0, 2.0, 3.0]),
        pose_at_capture=np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
        confidence=0.9,
        vision=mock_vision,
        measurement_time=old_measurement,
    )

    # max_age=0.3 → measurement_age≈0.5 > 0.3 → 应返回 None
    target_base, conf, age = cache.read_base(max_age=0.3)
    assert target_base is None
    assert age > 0.3


def test_read_base_fresh_measurement_age():
    """measurement_age 在 max_age 内时 read_base 返回有效值。"""
    mock_vision = _AdditiveMockVision()
    cache = TargetCache()

    # measurement_time 设为当前时刻
    now = time.perf_counter()
    cache.update_from_detection(
        target_end=np.array([1.0, 2.0, 3.0]),
        pose_at_capture=np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
        confidence=0.9,
        vision=mock_vision,
        measurement_time=now,
    )

    target_base, conf, age = cache.read_base(max_age=1.0)
    assert target_base is not None
    np.testing.assert_allclose(target_base, [1.0, 2.0, 3.0])
    assert conf == pytest.approx(0.9)
    assert age < 1.0


# ---------------------------------------------------------------------------
# 3. read_end 使用 measurement_age
# ---------------------------------------------------------------------------

def test_read_end_uses_measurement_age():
    """read_end 应使用 measurement_age 判定新鲜度。"""
    cache = TargetCache()

    old_measurement = time.perf_counter() - 0.5
    cache.update_from_detection(
        target_end=np.array([1.0, 2.0, 3.0]),
        pose_at_capture=None,  # fallback 路径，仅写 target_end
        confidence=0.7,
        vision=_AdditiveMockVision(),
        measurement_time=old_measurement,
    )

    target_end, conf, age = cache.read_end(max_age=0.3)
    assert target_end is None
    assert age > 0.3


# ---------------------------------------------------------------------------
# 4. detection 写入后 100ms 读取，age≈0.1s
# ---------------------------------------------------------------------------

def test_measurement_age_approx_100ms():
    """detection 写入后约 100ms 读取，measurement_age≈0.1s。"""
    mock_vision = _AdditiveMockVision()
    cache = TargetCache()

    t0 = time.perf_counter()
    cache.update_from_detection(
        target_end=np.array([1.0, 2.0, 3.0]),
        pose_at_capture=np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
        confidence=0.9,
        vision=mock_vision,
        measurement_time=t0,
    )

    time.sleep(0.1)

    target_base, conf, age = cache.read_base(max_age=1.0)
    assert target_base is not None
    # age 应该约为 0.1s，允许 ±50ms 的误差
    assert 0.05 < age < 0.2, f"age 应约为 0.1s，实际: {age}"


# ---------------------------------------------------------------------------
# 5. prediction 路径 measurement_age 为准
# ---------------------------------------------------------------------------

def test_prediction_path_uses_measurement_age():
    """prediction 路径：measurement_age 与 published_age 不同时以 measurement_age 为准。

    measurement_time 设为过去，published_time 设为当前，
    read_base 的 age 应反映 measurement_age（较旧）而非 published_age（较新）。
    """
    cache = TargetCache()

    old_measurement = time.perf_counter() - 0.5
    # update_from_prediction 内部用 perf_counter 作为 published_time
    cache.update_from_prediction(
        target_base=np.array([10.0, 20.0, 30.0]),
        confidence=0.6,
        prediction_age=0.3,
        measurement_time=old_measurement,
    )

    # max_age=0.3 → measurement_age≈0.5 > 0.3 → 应过期
    target_base, conf, age = cache.read_base(max_age=0.3)
    assert target_base is None
    assert age > 0.3, f"age 应反映 measurement_age (≈0.5s)，实际: {age}"

    # max_age=1.0 → 应有效
    target_base, conf, age = cache.read_base(max_age=1.0)
    assert target_base is not None
    np.testing.assert_allclose(target_base, [10.0, 20.0, 30.0])
    assert conf == pytest.approx(0.6)
