#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Task 9.1 集成测试：视觉-机器人时间对齐端到端行为。

验证 RobotPoseBuffer / TargetCache / ServoThread 在「采集时刻位姿预计算
target_base」这条主路径上的协作：

  - RobotPoseBuffer 提供按时间插值的采集时刻位姿
  - TargetCache 在检测时刻用该位姿预计算 target_base
  - ServoThread 主路径直接消费 target_base，不再做坐标转换
  - 缓冲不可用时退化到 target_end + 最新 pose 的 fallback 路径

覆盖场景：
1. 命中插值——target_base 用采集时刻位姿计算（非"最新"位姿）
2. 缓冲不可用 fallback——退化为 target_end + 最新 pose
3. ServoThread 主路径消费预计算 target_base，不再调用 convert_to_base_coords
4. 时间对齐减少运动误差——使用采集时刻位姿，而非伺服时刻最新位姿

不依赖硬件：使用 mock vision / mock controller。
"""

import sys
import types

import numpy as np
import pytest

# 与项目内其他 vision 测试保持一致：未安装真实 SDK 时注入桩模块，
# 使得 visual_servo_controller 间接 import 链中若出现 rs 也不致导入失败。
if "pyrealsense2" not in sys.modules:
    sys.modules["pyrealsense2"] = types.ModuleType("pyrealsense2")

from dobot_move.robot.robot_pose_buffer import RobotPoseBuffer
from dobot_move.robot.visual_servo_controller import TargetCache, ServoThread


class _AdditiveMockVision:
    """可记录调用的 mock vision。

    convert_to_base_coords(target_end, current_pose) 返回 target_end + current_pose[:3]
    ——简单相加模型，便于断言传入的 pose 是否为采集时刻插值位姿。
    """

    def __init__(self):
        self.convert_calls = []  # [(target_end, current_pose), ...]

    def convert_to_base_coords(self, target_end, current_pose):
        target_end = np.asarray(target_end, dtype=np.float64)
        current_pose = np.asarray(current_pose, dtype=np.float64)
        self.convert_calls.append((target_end.copy(), current_pose.copy()))
        return target_end + current_pose[:3]


def _make_servo_thread(vision, target_cache, max_target_age=0.3):
    """绕过 ServoThread.__init__（依赖 get_visual_servo_config），仅装 _resolve_target_base 需要的属性。

    与 tests/test_target_base_semantic.py 中的工厂保持一致。
    """
    thread = object.__new__(ServoThread)
    thread.vision = vision
    thread.target_cache = target_cache
    thread.max_target_age = max_target_age
    return thread


# ---------------------------------------------------------------------------
# 场景 1: 命中插值——target_base 用采集时刻位姿计算
# ---------------------------------------------------------------------------

def test_scenario1_hit_interpolation_uses_capture_pose():
    """RobotPoseBuffer 命中插值 → TargetCache 用插值位姿预计算 target_base。

    构造：
      - buffer push (t=100.0, [0,0,0,0,0,0]) 和 (t=100.1, [10,0,0,0,0,0])
      - mock vision: convert_to_base_coords(end, pose) = end + pose[:3]
      - buffer.pose_at(100.05) → 插值位姿 [5,0,0,0,0,0]
    断言：
      - target_cache.target_base == [1+5, 2+0, 3+0] = [6, 2, 3]
        （用了采集时刻的插值位姿，而非"最新"位姿 [10,0,0]）
    """
    buf = RobotPoseBuffer()
    buf.push(100.0, [0, 0, 0, 0, 0, 0])
    buf.push(100.1, [10, 0, 0, 0, 0, 0])

    # 查询采集时刻位姿（命中区间中点 → 线性插值）
    pose_at_capture, ok = buf.pose_at(100.05)
    assert ok is True
    np.testing.assert_allclose(pose_at_capture, [5, 0, 0, 0, 0, 0])

    mock_vision = _AdditiveMockVision()
    target_cache = TargetCache()

    target_end = np.array([1.0, 2.0, 3.0], dtype=np.float64)
    target_cache.update_from_detection(
        target_end=target_end,
        pose_at_capture=pose_at_capture,
        confidence=0.9,
        vision=mock_vision,
    )

    # target_base = target_end + pose_at_capture[:3] = [1+5, 2+0, 3+0] = [6, 2, 3]
    assert target_cache.target_base is not None
    np.testing.assert_allclose(target_cache.target_base, [6, 2, 3])

    # update_from_detection 内部恰好调用一次 convert_to_base_coords
    assert len(mock_vision.convert_calls) == 1
    # 传入的 pose 应为采集时刻插值位姿 [5,0,0,...]，而非最新位姿 [10,0,0,...]
    np.testing.assert_allclose(mock_vision.convert_calls[0][1], [5, 0, 0, 0, 0, 0])


# ---------------------------------------------------------------------------
# 场景 2: 缓冲不可用 fallback——退化为最新 pose
# ---------------------------------------------------------------------------

def test_scenario2_buffer_unavailable_fallback_to_latest_pose():
    """RobotPoseBuffer 不可用 → target_base 未写，ServoThread fallback 用最新 pose 转换。

    构造：
      - buffer 为空（pose_at 返回 (None, False)）
      - update_from_detection(target_end=[1,2,3], pose_at_capture=None, confidence=0.9, vision=mock)
    断言：
      - target_cache.target_base is None（未写入）
      - target_cache.target_end == [1,2,3]（仅 update_end）
      - 模拟 ServoThread fallback：convert_to_base_coords([1,2,3], latest_pose) 得到 base
    """
    # 空缓冲：pose_at 返回 (None, False)
    buf = RobotPoseBuffer()
    pose_at_capture, ok = buf.pose_at(100.0)
    assert ok is False
    assert pose_at_capture is None

    mock_vision = _AdditiveMockVision()
    target_cache = TargetCache()

    target_end = np.array([1.0, 2.0, 3.0], dtype=np.float64)
    target_cache.update_from_detection(
        target_end=target_end,
        pose_at_capture=None,  # 缓冲不可用
        confidence=0.9,
        vision=mock_vision,
    )

    # target_base 未写入；target_end 已写入（update_end 路径）
    assert target_cache.target_base is None
    assert target_cache.target_end is not None
    np.testing.assert_allclose(target_cache.target_end, [1, 2, 3])
    # pose_at_capture=None 时 update_from_detection 不应调用 convert_to_base_coords
    assert len(mock_vision.convert_calls) == 0

    # 模拟 ServoThread fallback：用最新 pose 转换 target_end
    latest_pose = np.array([100.0, 50.0, 25.0, 0.0, 0.0, 0.0], dtype=np.float64)
    base_coords = mock_vision.convert_to_base_coords(target_end, latest_pose)
    np.testing.assert_allclose(base_coords, [101.0, 52.0, 28.0])
    # fallback 路径下应调用一次 convert_to_base_coords
    assert len(mock_vision.convert_calls) == 1


# ---------------------------------------------------------------------------
# 场景 3: ServoThread 主路径消费预计算 target_base
# ---------------------------------------------------------------------------

def test_scenario3_servo_main_path_consumes_precomputed_target_base():
    """ServoThread 主路径：target_base 已预计算 → _resolve_target_base 直接返回，不调 convert。

    构造：
      - update_from_detection 写入 target_base=[6, 2, 3]
      - 调用 _resolve_target_base(current_pose)
    断言：
      - 返回 base_coords == [6, 2, 3]
      - convert_to_base_coords 调用次数 == 1（仅 update_from_detection 内部那次，主路径不再调用）
    """
    mock_vision = _AdditiveMockVision()
    target_cache = TargetCache()
    servo = _make_servo_thread(mock_vision, target_cache)

    target_end = np.array([1.0, 2.0, 3.0], dtype=np.float64)
    pose_at_capture = np.array([5.0, 0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float64)
    target_cache.update_from_detection(
        target_end=target_end,
        pose_at_capture=pose_at_capture,
        confidence=0.9,
        vision=mock_vision,
    )

    # update_from_detection 调用过一次 convert_to_base_coords，target_base=[6,2,3]
    assert len(mock_vision.convert_calls) == 1
    assert target_cache.target_base is not None
    np.testing.assert_allclose(target_cache.target_base, [6, 2, 3])

    # 伺服时刻的最新 pose（不论取何值都不应再触发转换）
    current_pose = np.array([20.0, 0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float64)
    target_base, conf, age, convert_ms = servo._resolve_target_base(current_pose)

    # 主路径命中：返回预计算的 target_base
    assert target_base is not None
    np.testing.assert_allclose(target_base, [6, 2, 3])
    assert conf == 0.9
    # 主路径不再转换，convert_ms 应为 0
    assert convert_ms == 0.0
    # 主路径不应再次调用 convert_to_base_coords（调用数仍为 1）
    assert len(mock_vision.convert_calls) == 1


# ---------------------------------------------------------------------------
# 场景 4: 时间对齐减少运动误差
# ---------------------------------------------------------------------------

def test_scenario4_time_alignment_reduces_motion_error():
    """时间对齐：target_base 用采集时刻位姿，而非伺服时刻最新位姿。

    构造：
      - buffer push (t=100.0, [0,...]) → (t=100.1, [10,0,0,...]) → (t=100.2, [20,0,0,...])
      - 帧采集时刻 t_capture = 100.1（对应位姿 [10,0,0,...]）
      - 伺服时刻 t_servo = 100.2（buffer.latest() 返回 [20,0,0,...]）
      - mock vision: convert_to_base_coords(end, pose) = end + pose[:3]
    断言：
      - 新逻辑（采集时刻位姿）的 target_base 用的是 t=100.1 的位姿 [10,0,0,...]
        即 target_base = target_end + [10,0,0] = [11, 2, 3]
      - 而非 t=100.2 的 [20,0,0,...]（旧逻辑会得到 [21, 2, 3]）
    """
    buf = RobotPoseBuffer()
    buf.push(100.0, [0, 0, 0, 0, 0, 0])
    buf.push(100.1, [10, 0, 0, 0, 0, 0])
    buf.push(100.2, [20, 0, 0, 0, 0, 0])

    # 帧采集时刻 t=100.1（命中样本点）
    t_capture = 100.1
    pose_at_capture, ok = buf.pose_at(t_capture)
    assert ok is True
    np.testing.assert_allclose(pose_at_capture, [10, 0, 0, 0, 0, 0])

    # 伺服时刻 t=100.2，最新位姿为 [20,0,0,...]
    _, latest_pose = buf.latest()
    np.testing.assert_allclose(latest_pose, [20, 0, 0, 0, 0, 0])

    target_end = np.array([1.0, 2.0, 3.0], dtype=np.float64)

    # ── 新逻辑（采集时刻位姿）：用 pose_at_capture=[10,0,0,...] 转换 ──
    mock_vision_new = _AdditiveMockVision()
    target_cache_new = TargetCache()
    target_cache_new.update_from_detection(
        target_end=target_end,
        pose_at_capture=pose_at_capture,
        confidence=0.9,
        vision=mock_vision_new,
    )
    # 新逻辑 target_base = target_end + [10,0,0] = [11, 2, 3]
    assert target_cache_new.target_base is not None
    np.testing.assert_allclose(target_cache_new.target_base, [11, 2, 3])
    # 转换用的 pose 应为 t=100.1 的 [10,0,0,...]，而非 t=100.2 的 [20,0,0,...]
    np.testing.assert_allclose(mock_vision_new.convert_calls[0][1], [10, 0, 0, 0, 0, 0])

    # ── 旧逻辑（用最新 pose）：直接在伺服时刻用 latest_pose=[20,0,0,...] 转换 target_end ──
    mock_vision_old = _AdditiveMockVision()
    old_base = mock_vision_old.convert_to_base_coords(target_end, latest_pose)
    # 旧逻辑 base = target_end + [20,0,0] = [21, 2, 3]
    np.testing.assert_allclose(old_base, [21, 2, 3])

    # ── 误差对比：新逻辑 [11,2,3] vs 旧逻辑 [21,2,3]，差值 10mm 来源于
    #    采集→伺服期间机器人继续运动产生的位姿漂移
    delta = np.asarray(target_cache_new.target_base) - np.asarray(old_base)
    motion_error_reduction = float(np.linalg.norm(delta))
    assert motion_error_reduction == pytest.approx(10.0, abs=1e-6)
