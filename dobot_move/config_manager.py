#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置文件管理模块
"""

import json
import logging
import os
import numpy as np

logger = logging.getLogger(__name__)

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(_MODULE_DIR, "config.json")
_config_cache = None
_cache_valid = False


def load_config():
    """加载配置文件"""
    global _config_cache, _cache_valid
    if _cache_valid and _config_cache is not None:
        return _config_cache
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                _config_cache = json.load(f)
            _cache_valid = True
            logger.info(f"✅ 配置文件加载成功: {CONFIG_FILE}")
            return _config_cache
        except Exception as e:
            logger.error(f"❌ 配置文件加载失败: {e}")
            return {}
    else:
        logger.warning(f"⚠️ 配置文件不存在，使用默认配置: {CONFIG_FILE}")
        return {}


def save_config(config):
    """保存配置文件"""
    global _config_cache, _cache_valid
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        _config_cache = config
        _cache_valid = True
        logger.info(f"✅ 配置文件保存成功: {CONFIG_FILE}")
        return True
    except Exception as e:
        logger.error(f"❌ 配置文件保存失败: {e}")
        return False


def get_photo_position():
    """获取拍照位置"""
    config = load_config()
    return config.get('photo_position', [250, -150, 300, 0, 0, -68])


def set_photo_position(position):
    """设置拍照位置"""
    config = load_config()
    config['photo_position'] = position
    return save_config(config)


def get_robot_ip():
    """获取机器人IP地址"""
    config = load_config()
    return config.get('robot_ip', "192.168.5.1")


def set_robot_ip(ip):
    """设置机器人IP地址"""
    config = load_config()
    config['robot_ip'] = ip
    return save_config(config)


def get_cart_ip():
    config = load_config()
    return config.get('cart_ip', "192.168.5.2")


def set_cart_ip(ip):
    config = load_config()
    config['cart_ip'] = ip
    return save_config(config)


def get_cart_port():
    config = load_config()
    return config.get('cart_port', 502)


def set_cart_port(port):
    config = load_config()
    config['cart_port'] = port
    return save_config(config)


def get_modbus_port():
    config = load_config()
    return config.get('modbus_port', 502)


def set_modbus_port(port):
    config = load_config()
    config['modbus_port'] = port
    return save_config(config)


def get_config():
    """获取完整配置"""
    return load_config()


def update_config(key, value):
    """更新配置项"""
    config = load_config()
    config[key] = value
    return save_config(config)


from transform_utils import euler2rot as _euler2rot, pose2matrix as _pose2matrix


_DEFAULT_D405_TOOL_BASE_CALIB = [-210, 0, 310, 90, 0, -90]
_DEFAULT_D405_CAM_BASE_CALIB = [-72.76, -10.12, 31.18, 90, 0, -90]


def get_calibration(camera_type="D435i"):
    config = load_config()
    calibration = config.get("calibration", {})
    if "tool_base_calib_pose" in calibration and "cam_base_calib_pose" in calibration:
        old_tool = calibration.pop("tool_base_calib_pose")
        old_cam = calibration.pop("cam_base_calib_pose")
        calibration["D435i"] = {
            "tool_base_calib_pose": old_tool,
            "cam_base_calib_pose": old_cam,
        }
        calibration["D405"] = {
            "tool_base_calib_pose": list(_DEFAULT_D405_TOOL_BASE_CALIB),
            "cam_base_calib_pose": list(_DEFAULT_D405_CAM_BASE_CALIB),
        }
        config["calibration"] = calibration
        save_config(config)
    cam_calib = calibration.get(camera_type, {})
    return cam_calib


def set_calibration(camera_type, tool_base_calib_pose, cam_base_calib_pose):
    global _cache_valid
    config = load_config()
    if "calibration" not in config:
        config["calibration"] = {}
    config["calibration"][camera_type] = {
        "tool_base_calib_pose": tool_base_calib_pose,
        "cam_base_calib_pose": cam_base_calib_pose,
    }
    result = save_config(config)
    _cache_valid = False
    return result


def get_all_calibrations():
    config = load_config()
    return config.get("calibration", {})


def get_camera_handeye_matrix(camera_type="D435i"):
    calib = get_calibration(camera_type)
    tool_base_calib_pose = calib.get("tool_base_calib_pose", [-210, 0, 310, 90, 0, -90])
    cam_base_calib_pose = calib.get("cam_base_calib_pose", [-72.76, -10.12, 31.18, 90, 0, -90])
    T_tool2base = _pose2matrix(*tool_base_calib_pose)
    T_cam2base = _pose2matrix(*cam_base_calib_pose)
    T_cam2gripper = np.linalg.inv(T_tool2base) @ T_cam2base
    return T_cam2gripper


_DEFAULT_POINTS = {
    "d435i": {
        "coords": [0, 0, 0, 0, 0, 0],
        "is_relative": False,
        "relative_to": None,
        "offset": [0, 0, 0, 0, 0, 0],
        "is_default": True,
    },
    "d405": {
        "coords": [0, 0, 0, 0, 0, 0],
        "is_relative": False,
        "relative_to": None,
        "offset": [0, 0, 0, 0, 0, 0],
        "is_default": True,
    },
}


def get_points():
    config = load_config()
    points = config.get("points", None)
    if points is None:
        config["points"] = dict(_DEFAULT_POINTS)
        save_config(config)
        points = config["points"]
    for name, default_data in _DEFAULT_POINTS.items():
        if name not in points:
            points[name] = dict(default_data)
    return points


def set_points(points):
    config = load_config()
    config["points"] = points
    return save_config(config)


def get_point(name):
    points = get_points()
    return points.get(name, None)


def set_point(name, data):
    points = get_points()
    points[name] = data
    return set_points(points)


def add_point(name, coords=None, is_relative=False, relative_to=None, offset=None):
    points = get_points()
    if name in points:
        return False
    points[name] = {
        "coords": coords or [0, 0, 0, 0, 0, 0],
        "is_relative": is_relative,
        "relative_to": relative_to,
        "offset": offset or [0, 0, 0, 0, 0, 0],
        "is_default": False,
    }
    return set_points(points)


def delete_point(name):
    points = get_points()
    if name not in points:
        return False
    if points[name].get("is_default", False):
        return False
    del points[name]
    return set_points(points)


def resolve_point(name, visited=None):
    if visited is None:
        visited = set()
    if name in visited:
        return None
    visited.add(name)
    point = get_point(name)
    if point is None:
        return None
    if not point.get("is_relative", False):
        return list(point.get("coords", [0, 0, 0, 0, 0, 0]))
    base_name = point.get("relative_to")
    if not base_name:
        return list(point.get("coords", [0, 0, 0, 0, 0, 0]))
    base_coords = resolve_point(base_name, visited)
    if base_coords is None:
        return list(point.get("coords", [0, 0, 0, 0, 0, 0]))
    offset = point.get("offset", [0, 0, 0, 0, 0, 0])
    resolved = [base_coords[i] + offset[i] for i in range(6)]
    point["coords"] = list(resolved)
    return resolved
