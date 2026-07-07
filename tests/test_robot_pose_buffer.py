#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for RobotPoseBuffer."""

import threading
import time

import numpy as np
import pytest

from dobot_move.robot.robot_pose_buffer import RobotPoseBuffer


def _pose(*vals):
    return list(vals)


def test_empty_buffer_pose_at_returns_none():
    buf = RobotPoseBuffer()
    pose, ok = buf.pose_at(1.0)
    assert ok is False
    assert pose is None


def test_latest_on_empty_buffer():
    buf = RobotPoseBuffer()
    t, p = buf.latest()
    assert t == 0.0
    assert p is None


def test_single_sample_hit():
    buf = RobotPoseBuffer()
    p0 = _pose(1, 2, 3, 4, 5, 6)
    buf.push(10.0, p0)
    pose, ok = buf.pose_at(10.0)
    assert ok is True
    assert np.allclose(pose, p0)


def test_single_sample_within_extrapolate_window():
    buf = RobotPoseBuffer(extrapolate_limit=0.05)
    p0 = _pose(1, 2, 3, 4, 5, 6)
    buf.push(10.0, p0)
    # 在外推窗口内（t > t0）
    pose, ok = buf.pose_at(10.03)
    assert ok is True
    assert np.allclose(pose, p0)
    # 退化：t 早于 t0 也返回该样本
    pose, ok = buf.pose_at(9.9)
    assert ok is True
    assert np.allclose(pose, p0)


def test_single_sample_beyond_window():
    buf = RobotPoseBuffer(extrapolate_limit=0.05)
    p0 = _pose(1, 2, 3, 4, 5, 6)
    buf.push(10.0, p0)
    # 超出外推窗口
    pose, ok = buf.pose_at(10.1)
    assert ok is False
    assert pose is None


def test_interpolation_two_samples():
    buf = RobotPoseBuffer()
    buf.push(0.0, _pose(0, 0, 0, 0, 0, 0))
    buf.push(1.0, _pose(10, 0, 0, 0, 0, 0))
    pose, ok = buf.pose_at(0.5)
    assert ok is True
    assert np.allclose(pose, [5, 0, 0, 0, 0, 0])


def test_interpolation_at_sample_timestamp():
    buf = RobotPoseBuffer()
    buf.push(0.0, _pose(0, 0, 0, 0, 0, 0))
    buf.push(1.0, _pose(10, 0, 0, 0, 0, 0))
    buf.push(2.0, _pose(20, 0, 0, 0, 0, 0))
    # 命中中间样本点
    pose, ok = buf.pose_at(1.0)
    assert ok is True
    assert np.allclose(pose, [10, 0, 0, 0, 0, 0])


def test_extrapolation_within_window():
    buf = RobotPoseBuffer(extrapolate_limit=0.05)
    buf.push(0.0, _pose(0, 0, 0, 0, 0, 0))
    buf.push(1.0, _pose(10, 0, 0, 0, 0, 0))
    # 速度 10/s，t=1.03 -> pose=10.3
    pose, ok = buf.pose_at(1.03)
    assert ok is True
    assert np.allclose(pose, [10.3, 0, 0, 0, 0, 0])


def test_extrapolation_beyond_window():
    buf = RobotPoseBuffer(extrapolate_limit=0.05)
    buf.push(0.0, _pose(0, 0, 0, 0, 0, 0))
    buf.push(1.0, _pose(10, 0, 0, 0, 0, 0))
    # 超出外推窗口
    pose, ok = buf.pose_at(1.1)
    assert ok is False
    assert pose is None


def test_t_before_oldest_with_multiple_samples():
    buf = RobotPoseBuffer()
    buf.push(1.0, _pose(0, 0, 0, 0, 0, 0))
    buf.push(2.0, _pose(10, 0, 0, 0, 0, 0))
    # t 远早于最旧
    pose, ok = buf.pose_at(0.5)
    assert ok is False
    assert pose is None


def test_capacity_eviction():
    buf = RobotPoseBuffer(capacity=3)
    buf.push(0.0, _pose(0, 0, 0, 0, 0, 0))
    buf.push(1.0, _pose(10, 0, 0, 0, 0, 0))
    buf.push(2.0, _pose(20, 0, 0, 0, 0, 0))
    buf.push(3.0, _pose(30, 0, 0, 0, 0, 0))
    # 只剩最新 3 个
    assert len(buf) == 3
    # 最旧样本（t=0.0）应已被淘汰
    with buf._lock:
        timestamps = [s[0] for s in buf._samples]
    assert timestamps == [1.0, 2.0, 3.0]
    # 查 t=0.0（已被淘汰且早于最旧）应失败
    pose, ok = buf.pose_at(0.0)
    assert ok is False
    # latest 应为 t=3.0
    t, p = buf.latest()
    assert t == 3.0
    assert np.allclose(p, [30, 0, 0, 0, 0, 0])


def test_latest_returns_newest():
    buf = RobotPoseBuffer()
    buf.push(1.0, _pose(1, 1, 1, 1, 1, 1))
    buf.push(2.0, _pose(2, 2, 2, 2, 2, 2))
    buf.push(3.0, _pose(3, 3, 3, 3, 3, 3))
    t, p = buf.latest()
    assert t == 3.0
    assert np.allclose(p, [3, 3, 3, 3, 3, 3])


def test_latest_returns_copy():
    buf = RobotPoseBuffer()
    src = _pose(1, 2, 3, 4, 5, 6)
    buf.push(1.0, src)
    _, p = buf.latest()
    # 修改返回值不应影响内部数据
    p[0] = 999.0
    _, p2 = buf.latest()
    assert np.allclose(p2, [1, 2, 3, 4, 5, 6])


def test_push_copies_pose():
    buf = RobotPoseBuffer()
    src = _pose(1, 2, 3, 4, 5, 6)
    buf.push(1.0, src)
    # 修改源 list 不应影响内部数据
    src[0] = 999.0
    pose, ok = buf.pose_at(1.0)
    assert ok is True
    assert np.allclose(pose, [1, 2, 3, 4, 5, 6])


def test_clear_empties_buffer():
    buf = RobotPoseBuffer()
    buf.push(1.0, _pose(1, 1, 1, 1, 1, 1))
    buf.push(2.0, _pose(2, 2, 2, 2, 2, 2))
    assert len(buf) == 2
    buf.clear()
    assert len(buf) == 0
    # 清空后查询应失败
    pose, ok = buf.pose_at(1.0)
    assert ok is False
    assert pose is None
    # latest 退化为 (0.0, None)
    t, p = buf.latest()
    assert t == 0.0
    assert p is None


def test_concurrent_read_write_smoke():
    buf = RobotPoseBuffer(capacity=100, extrapolate_limit=0.05)
    stop = threading.Event()
    errors = []

    def writer():
        t0 = time.perf_counter()
        i = 0
        while not stop.is_set():
            try:
                ts = t0 + i * 0.001
                buf.push(ts, _pose(i, i, i, 0, 0, 0))
                i += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
                return

    th = threading.Thread(target=writer)
    th.start()
    try:
        t0 = time.perf_counter()
        # 主线程并发查询
        while time.perf_counter() - t0 < 0.2:
            try:
                buf.pose_at(t0 + 0.05)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
                break
            buf.latest()
    finally:
        stop.set()
        th.join(timeout=2.0)

    assert not errors, f"concurrent read/write raised: {errors}"
    assert len(buf) > 0
