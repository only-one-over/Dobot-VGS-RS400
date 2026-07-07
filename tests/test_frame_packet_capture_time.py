"""Task 2 测试：FramePacket 新增 capture_time 字段并在 capture_numpy_packet 中填充。

覆盖场景：
- FramePacket 拥有 capture_time 字段且默认值为 0.0
- capture_time 可显式赋值
- capture_numpy_packet 返回的 packet.capture_time > 0（通过 mock capture_frames）
"""
import sys
import time
import types
from unittest.mock import MagicMock

import numpy as np

# 与项目内其他 vision 测试保持一致：未安装真实 SDK 时注入桩模块，
# 使得 vision_system.py 顶部的 `import pyrealsense2 as rs` 可在无硬件环境下导入。
if "pyrealsense2" not in sys.modules:
    sys.modules["pyrealsense2"] = types.ModuleType("pyrealsense2")

from dobot_move.vision.vision_system import FramePacket, VisionSystem


def test_frame_packet_has_capture_time_default():
    """FramePacket 必须有 capture_time 字段，且默认值为 0.0（向后兼容）。"""
    packet = FramePacket(
        seq=1,
        timestamp=time.time(),
        color_image=None,
        depth_image=None,
    )
    assert hasattr(packet, "capture_time")
    assert packet.capture_time == 0.0


def test_frame_packet_capture_time_can_be_set_explicitly():
    """capture_time 可显式赋值并保留。"""
    t = time.perf_counter()
    packet = FramePacket(
        seq=2,
        timestamp=time.time(),
        color_image=None,
        depth_image=None,
        capture_time=t,
    )
    assert packet.capture_time == t
    assert packet.capture_time > 0


def test_capture_numpy_packet_populates_capture_time():
    """capture_numpy_packet 应在帧数据拷贝完成后注入 perf_counter 时间戳。

    通过 mock capture_frames 返回伪 frame，避免依赖真实硬件。
    """
    # 用 __new__ 绕过 __init__ 的硬件初始化
    vs = VisionSystem.__new__(VisionSystem)

    color_frame = MagicMock()
    color_frame.get_data.return_value = np.zeros((10, 10, 3), dtype=np.uint8)
    depth_frame = MagicMock()
    depth_frame.get_data.return_value = np.zeros((10, 10), dtype=np.uint16)
    vs.capture_frames = MagicMock(return_value=(depth_frame, color_frame))

    before = time.perf_counter()
    packet = vs.capture_numpy_packet(seq=42)
    after = time.perf_counter()

    assert packet is not None
    assert isinstance(packet, FramePacket)
    assert packet.seq == 42
    assert packet.capture_time > 0
    assert before <= packet.capture_time <= after


def test_capture_numpy_packet_returns_none_when_capture_fails():
    """capture_frames 失败时 capture_numpy_packet 应返回 None，不构造 FramePacket。"""
    vs = VisionSystem.__new__(VisionSystem)
    vs.capture_frames = MagicMock(return_value=(None, None))

    packet = vs.capture_numpy_packet(seq=1)
    assert packet is None
