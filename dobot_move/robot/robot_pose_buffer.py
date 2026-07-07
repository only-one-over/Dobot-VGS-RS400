#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
机器人位姿环形缓冲区 - 线程安全的时间索引位姿存储与插值/外推。

存储 (timestamp, pose) 二元组，支持按时间查询位姿：
- 命中区间：线性插值
- 略晚于最新：基于最新两端速度线性外推
- 单样本退化：直接返回该样本
"""

import bisect
import logging
from collections import deque
from threading import Lock

import numpy as np

logger = logging.getLogger(__name__)


class RobotPoseBuffer:
    """线程安全的位姿环形缓冲区。"""

    def __init__(self, capacity=200, extrapolate_limit=0.05):
        # capacity: 最多存储多少个位姿样本
        # extrapolate_limit: 允许外推的时间窗口（秒），默认 50ms
        self._capacity = int(capacity)
        self._extrapolate_limit = float(extrapolate_limit)
        self._samples = deque(maxlen=self._capacity)
        self._lock = Lock()

    def push(self, timestamp: float, pose):
        """写入一个 (timestamp, pose) 样本。

        timestamp 为 time.perf_counter() 单调秒。
        pose 为 6 元素数组 [X,Y,Z,Rx,Ry,Rz]（numpy 数组或 list）。
        超过容量时滚动淘汰最旧样本。内部 copy pose 以避免外部修改。
        """
        arr = np.array(pose, dtype=float)
        with self._lock:
            self._samples.append((float(timestamp), arr))

    def pose_at(self, t: float):
        """按时间 t 查询位姿。返回 (pose, ok)。

        - 命中区间（存在 t1 <= t <= t2）：返回线性插值 pose, ok=True
        - t 略晚于最新时间戳且在 extrapolate_limit 内：线性外推, ok=True
        - 单样本且 t <= t0 + extrapolate_limit：退化返回该样本, ok=True
        - 其他情况（空 / 超出外推窗口 / t 远早于最旧）：返回 (None, False)
        """
        t = float(t)
        with self._lock:
            n = len(self._samples)
            if n == 0:
                return (None, False)

            if n == 1:
                t0, p0 = self._samples[0]
                if t <= t0 + self._extrapolate_limit:
                    return (p0.copy(), True)
                return (None, False)

            # n >= 2：构建时间戳列表用于二分查找包围区间
            timestamps = [s[0] for s in self._samples]
            idx = bisect.bisect_right(timestamps, t)

            if idx == 0:
                # t 早于最旧时间戳，无法回溯
                return (None, False)

            if idx >= n:
                # t >= t_latest，尝试外推
                t_prev, p_prev = self._samples[-2]
                t_latest, p_latest = self._samples[-1]
                if t - t_latest > self._extrapolate_limit:
                    return (None, False)
                dt = t_latest - t_prev
                if dt <= 0:
                    # 时间戳重复，无法算速度，退化为返回最新
                    return (p_latest.copy(), True)
                v = (p_latest - p_prev) / dt
                pose = p_latest + v * (t - t_latest)
                return (pose.copy(), True)

            # idx in [1, n-1]：命中区间 [idx-1, idx]
            t1, p1 = self._samples[idx - 1]
            t2, p2 = self._samples[idx]
            dt = t2 - t1
            if dt <= 0:
                return (p2.copy(), True)
            alpha = (t - t1) / dt
            pose = p1 + alpha * (p2 - p1)
            return (pose.copy(), True)

    def latest(self):
        """返回最新 (timestamp, pose) 或 (0.0, None)。线程安全。"""
        with self._lock:
            if not self._samples:
                return (0.0, None)
            t, p = self._samples[-1]
            return (t, p.copy())

    def clear(self):
        """清空缓冲区。"""
        with self._lock:
            self._samples.clear()

    def __len__(self):
        with self._lock:
            return len(self._samples)
