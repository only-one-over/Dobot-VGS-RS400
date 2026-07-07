"""Task 1 测试：D435i max_camera_z_mm 硬编码修复。

覆盖场景：
- D435i 默认上限为 2200.0
- D405 默认上限为 800.0
- 配置 camera.max_camera_z_mm=1500.0 时两种相机类型都用 1500.0
- D435i z=510mm 不被 _reject_camera_z_over_limit 丢弃
"""
import sys
import types

import pytest

# 与项目内其他 vision 测试保持一致：未安装真实 SDK 时注入桩模块，
# 使得 vision_system.py 顶部的 `import pyrealsense2 as rs` 可在无硬件环境下导入。
if "pyrealsense2" not in sys.modules:
    sys.modules["pyrealsense2"] = types.ModuleType("pyrealsense2")

from dobot_move.vision.vision_system import resolve_max_camera_z_mm, VisionSystem


def test_d435i_default_max_camera_z_mm():
    """D435i 在无显式配置时应使用 2200.0（对应 max_depth=2.2m）。"""
    assert resolve_max_camera_z_mm("D435i", {}) == 2200.0


def test_d405_default_max_camera_z_mm():
    """D405 在无显式配置时应使用 800.0（对应 max_depth=0.8m）。"""
    assert resolve_max_camera_z_mm("D405", {}) == 800.0


def test_config_max_camera_z_mm_overrides_both_camera_types():
    """配置 camera.max_camera_z_mm=1500.0 时 D435i 与 D405 都应使用 1500.0。"""
    config = {"camera": {"max_camera_z_mm": 1500.0}}
    assert resolve_max_camera_z_mm("D435i", config) == 1500.0
    assert resolve_max_camera_z_mm("D405", config) == 1500.0


def test_config_missing_camera_section_uses_defaults():
    """配置中无 camera 段时回退到相机类型默认值。"""
    assert resolve_max_camera_z_mm("D435i", {"performance": {}}) == 2200.0
    assert resolve_max_camera_z_mm("D405", {"performance": {}}) == 800.0


def test_config_invalid_max_camera_z_mm_raises():
    """非法值（无法转 float）应抛出异常，避免静默使用错误上限。"""
    with pytest.raises((TypeError, ValueError)):
        resolve_max_camera_z_mm("D435i", {"camera": {"max_camera_z_mm": "not-a-number"}})


class _DummyVisionSystem:
    """最小桩对象，仅持有 max_camera_z_mm 属性以复用 _reject_camera_z_over_limit。"""

    def __init__(self, max_z_mm):
        self.max_camera_z_mm = max_z_mm


def test_d435i_510mm_not_rejected():
    """D435i z=510mm 不应被 _reject_camera_z_over_limit 丢弃。

    回归：原硬编码 500.0 时，510mm 会被误判越界并返回 None。
    """
    dummy = _DummyVisionSystem(resolve_max_camera_z_mm("D435i", {}))
    result = {
        "center_x": 320,
        "center_y": 240,
        "depth": 0.510,
        "camera_coords": [0.0, 0.0, 510.0],
    }
    out = VisionSystem._reject_camera_z_over_limit(dummy, result)
    assert out is not None
    assert out["camera_coords"][2] == 510.0


def test_d435i_far_over_limit_rejected():
    """D435i z 远超 2200mm 仍应被过滤。"""
    dummy = _DummyVisionSystem(resolve_max_camera_z_mm("D435i", {}))
    result = {
        "center_x": 320,
        "center_y": 240,
        "depth": 3.0,
        "camera_coords": [0.0, 0.0, 3000.0],
    }
    out = VisionSystem._reject_camera_z_over_limit(dummy, result)
    assert out is None


def test_d405_510mm_not_rejected_with_config_override():
    """D405 配置 max_camera_z_mm=1500 时，510mm 不应被丢弃。"""
    config = {"camera": {"max_camera_z_mm": 1500.0}}
    dummy = _DummyVisionSystem(resolve_max_camera_z_mm("D405", config))
    result = {
        "center_x": 320,
        "center_y": 240,
        "depth": 0.510,
        "camera_coords": [0.0, 0.0, 510.0],
    }
    out = VisionSystem._reject_camera_z_over_limit(dummy, result)
    assert out is not None
