#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Task 5 + Task 6 测试：target_base 主路径 / target_end fallback 语义。

覆盖场景：
1. 主路径：update_from_detection 写入 target_base 后，_resolve_target_base
   直接返回该 target_base，不再调用 convert_to_base_coords。
2. Fallback：update_from_detection 收到 pose_at_capture=None 时 target_base
   未写入，_resolve_target_base 退化为 target_end + 最新 current_pose →
   convert_to_base_coords。
3. 两者都 None：_resolve_target_base 返回 None 元组。
"""

import math

import numpy as np

from dobot_move.robot.visual_servo_controller import TargetCache, ServoThread


class _MockVision:
    """最小 vision 桩：记录 convert_to_base_coords 调用并返回固定结果。"""

    def __init__(self, base_result=None):
        self.base_result = (
            np.array([100.0, 200.0, 300.0], dtype=np.float64)
            if base_result is None
            else np.asarray(base_result, dtype=np.float64)
        )
        self.convert_calls = []  # [(end_coords, robot_pose), ...]

    def convert_to_base_coords(self, end_coords, robot_pose):
        self.convert_calls.append((np.asarray(end_coords), np.asarray(robot_pose)))
        return self.base_result


def _make_servo_thread(vision, target_cache, max_target_age=0.3):
    """绕过 ServoThread.__init__（依赖 get_visual_servo_config），仅装 _resolve_target_base 需要的属性。"""
    thread = object.__new__(ServoThread)
    thread.vision = vision
    thread.target_cache = target_cache
    thread.max_target_age = max_target_age
    return thread


def test_main_path_uses_precomputed_target_base():
    """主路径：update_from_detection 写入 target_base → _resolve_target_base 直接返回，不调 convert。"""
    vision = _MockVision()
    cache = TargetCache()
    servo = _make_servo_thread(vision, cache)

    target_end = np.array([10.0, 20.0, 30.0], dtype=np.float64)
    pose_at_capture = np.array([400.0, 0.0, 300.0, 0.0, 90.0, 0.0], dtype=np.float64)
    confidence = 0.92

    cache.update_from_detection(target_end, pose_at_capture, confidence, vision)

    # target_base 已预计算
    assert cache.target_base is not None
    np.testing.assert_allclose(cache.target_base, vision.base_result)
    # update_from_detection 内部调用过一次 convert_to_base_coords
    assert len(vision.convert_calls) == 1
    assert cache.target_capture_time > 0.0

    current_pose = np.array([410.0, 5.0, 310.0, 0.0, 90.0, 0.0], dtype=np.float64)
    target_base, conf, age, convert_ms = servo._resolve_target_base(current_pose)

    # 主路径命中：返回预计算的 target_base
    assert target_base is not None
    np.testing.assert_allclose(target_base, vision.base_result)
    assert conf == confidence
    assert convert_ms == 0.0
    # 主路径不应再次调用 convert_to_base_coords（调用数仍为 1）
    assert len(vision.convert_calls) == 1
    # age 应为有限正数
    assert math.isfinite(age) and age >= 0.0


def test_fallback_path_uses_target_end_and_current_pose():
    """Fallback：pose_at_capture=None → target_base 未写 → _resolve_target_base 用 target_end + 当前 pose 转换。"""
    vision = _MockVision()
    cache = TargetCache()
    servo = _make_servo_thread(vision, cache)

    target_end = np.array([10.0, 20.0, 30.0], dtype=np.float64)
    confidence = 0.85

    # pose_at_capture=None：仅写 target_end，target_base 保持 None
    cache.update_from_detection(target_end, None, confidence, vision)

    assert cache.target_base is None
    assert cache.target_end is not None
    np.testing.assert_allclose(cache.target_end, target_end)
    # update_from_detection 在 pose_at_capture=None 时不调 convert_to_base_coords
    assert len(vision.convert_calls) == 0

    current_pose = np.array([410.0, 5.0, 310.0, 0.0, 90.0, 0.0], dtype=np.float64)
    target_base, conf, age, convert_ms = servo._resolve_target_base(current_pose)

    # Fallback 命中：用 target_end + current_pose 转换
    assert target_base is not None
    np.testing.assert_allclose(target_base, vision.base_result)
    assert conf == confidence
    # fallback 路径应计时
    assert convert_ms >= 0.0
    # 恰好调用一次 convert_to_base_coords，参数为 target_end + current_pose
    assert len(vision.convert_calls) == 1
    np.testing.assert_allclose(vision.convert_calls[0][0], target_end)
    np.testing.assert_allclose(vision.convert_calls[0][1], current_pose)


def test_both_none_returns_none_tuple():
    """两者都 None：_resolve_target_base 返回 None 元组。"""
    vision = _MockVision()
    cache = TargetCache()  # 空 cache：target_end / target_base 均为 None
    servo = _make_servo_thread(vision, cache)

    current_pose = np.array([410.0, 5.0, 310.0, 0.0, 90.0, 0.0], dtype=np.float64)
    target_base, conf, age, convert_ms = servo._resolve_target_base(current_pose)

    assert target_base is None
    assert conf == 0.0
    assert age == float('inf')
    assert convert_ms == 0.0
    assert len(vision.convert_calls) == 0
