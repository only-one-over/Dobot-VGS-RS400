#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Task 2 测试：capture_time 前移 + frame_timestamp_ms 字段。

覆盖：
1. capture_time 在 wait_for_frames 返回后立即记录（numpy 拷贝之前）
2. frame_timestamp_ms 从 depth_frame.get_timestamp() 提取
3. FramePacket 拥有 frame_timestamp_ms 字段且默认值为 0.0
4. depth_frame.get_timestamp() 异常时 frame_timestamp_ms 为 0.0
"""

import sys
import time
import types
from unittest.mock import MagicMock

import numpy as np

if "pyrealsense2" not in sys.modules:
    sys.modules["pyrealsense2"] = types.ModuleType("pyrealsense2")

from dobot_move.vision.vision_system import FramePacket, VisionSystem


def test_frame_packet_has_frame_timestamp_ms_default():
    """FramePacket 必须有 frame_timestamp_ms 字段，默认值为 0.0。"""
    packet = FramePacket(
        seq=1,
        timestamp=time.time(),
        color_image=None,
        depth_image=None,
    )
    assert hasattr(packet, "frame_timestamp_ms")
    assert packet.frame_timestamp_ms == 0.0


def test_capture_time_recorded_before_numpy_copy():
    """capture_time 应在 wait_for_frames 返回后立即记录，先于 numpy 拷贝。

    通过在 get_data() 中插入延迟，验证 capture_time 早于 numpy 拷贝完成时刻。
    """
    vs = VisionSystem.__new__(VisionSystem)

    numpy_copy_done_time = []

    color_frame = MagicMock()
    color_frame.get_data.side_effect = lambda: (
        numpy_copy_done_time.append(time.perf_counter()),
        np.zeros((10, 10, 3), dtype=np.uint8),
        )[1]
    depth_frame = MagicMock()
    depth_frame.get_data.side_effect = lambda: (
        numpy_copy_done_time.append(time.perf_counter()),
        np.zeros((10, 10), dtype=np.uint16),
        )[1]
    depth_frame.get_timestamp.return_value = 12345.6
    vs.capture_frames = MagicMock(return_value=(depth_frame, color_frame))

    packet = vs.capture_numpy_packet(seq=42)

    assert packet is not None
    # capture_time 应该早于 numpy 拷贝完成时刻
    for copy_time in numpy_copy_done_time:
        assert packet.capture_time <= copy_time, (
            f"capture_time ({packet.capture_time}) 应早于 numpy 拷贝完成 ({copy_time})"
        )


def test_frame_timestamp_ms_extracted_from_depth_frame():
    """frame_timestamp_ms 应从 depth_frame.get_timestamp() 提取。"""
    vs = VisionSystem.__new__(VisionSystem)

    color_frame = MagicMock()
    color_frame.get_data.return_value = np.zeros((10, 10, 3), dtype=np.uint8)
    depth_frame = MagicMock()
    depth_frame.get_data.return_value = np.zeros((10, 10), dtype=np.uint16)
    depth_frame.get_timestamp.return_value = 98765.4
    vs.capture_frames = MagicMock(return_value=(depth_frame, color_frame))

    packet = vs.capture_numpy_packet(seq=1)

    assert packet is not None
    assert packet.frame_timestamp_ms == 98765.4


def test_frame_timestamp_ms_zero_on_exception():
    """depth_frame.get_timestamp() 异常时 frame_timestamp_ms 应为 0.0。"""
    vs = VisionSystem.__new__(VisionSystem)

    color_frame = MagicMock()
    color_frame.get_data.return_value = np.zeros((10, 10, 3), dtype=np.uint8)
    depth_frame = MagicMock()
    depth_frame.get_data.return_value = np.zeros((10, 10), dtype=np.uint16)
    depth_frame.get_timestamp.side_effect = RuntimeError("sensor error")
    vs.capture_frames = MagicMock(return_value=(depth_frame, color_frame))

    packet = vs.capture_numpy_packet(seq=1)

    assert packet is not None
    assert packet.frame_timestamp_ms == 0.0


def test_capture_time_is_perf_counter_domain():
    """capture_time 应为 perf_counter 域（单调递增、正值）。"""
    vs = VisionSystem.__new__(VisionSystem)

    color_frame = MagicMock()
    color_frame.get_data.return_value = np.zeros((10, 10, 3), dtype=np.uint8)
    depth_frame = MagicMock()
    depth_frame.get_data.return_value = np.zeros((10, 10), dtype=np.uint16)
    depth_frame.get_timestamp.return_value = 1000.0
    vs.capture_frames = MagicMock(return_value=(depth_frame, color_frame))

    before = time.perf_counter()
    packet = vs.capture_numpy_packet(seq=1)
    after = time.perf_counter()

    assert packet is not None
    assert before <= packet.capture_time <= after
