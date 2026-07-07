#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置文件管理模块
"""

import json
import logging
import os
import re
import shutil
import uuid
import copy
import contextvars
from contextlib import contextmanager

import numpy as np

logger = logging.getLogger(__name__)

# Path hierarchy (after refactor):
#   _MODULE_DIR   = dobot_move/config/      (this file's directory)
#   _PACKAGE_DIR  = dobot_move/             (main package)
#   _PROJECT_ROOT = dobot_move_python/      (project root, parent of package)
#   USER_DATA_DIR = dobot_move_python/user_data/  (user data, preserved across package updates)
_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_PACKAGE_DIR = os.path.dirname(_MODULE_DIR)
_PROJECT_ROOT = os.path.dirname(_PACKAGE_DIR)
USER_DATA_DIR = os.path.join(_PROJECT_ROOT, "user_data")

# User data files (preserved when replacing dobot_move/)
CONFIG_FILE = os.path.join(USER_DATA_DIR, "config.json")
GRASP_FLOW_FILE = os.path.join(USER_DATA_DIR, "grasp_flow_modules.json")
ALARM_HISTORY_FILE = os.path.join(USER_DATA_DIR, "alarm_history.json")
RUNTIME_HEALTH_FILE = os.path.join(USER_DATA_DIR, "runtime_health.json")
RUNTIME_STATE_FILE = os.path.join(USER_DATA_DIR, "runtime_state.json")
RUNTIME_PUBLICATION_FILE = os.path.join(USER_DATA_DIR, "runtime_publication.json")
RUNTIME_LOCKOUT_FILE = os.path.join(USER_DATA_DIR, "runtime_watchdog_lockout.json")
RUNTIME_IPC_TOKEN_FILE = os.path.join(USER_DATA_DIR, "runtime_ipc.token")
LOG_DIR = os.path.join(USER_DATA_DIR, "logs")

# Bundled resources (shipped with the package, updated on replacement)
CONFIG_EXAMPLE_FILE = os.path.join(_MODULE_DIR, "config.example.json")
DEFAULT_GRASP_FLOW_TEMPLATE = os.path.join(_MODULE_DIR, "grasp_flow_modules.default.json")
DEFAULT_ALARM_CODES_DIR = os.path.join(_MODULE_DIR, "files")
DEFAULT_CAMERA_MODEL_PATH = os.path.join(_PACKAGE_DIR, "best.onnx")
SUPPORTED_CAMERA_TYPES = ("D435i", "D405")
_config_cache = None
_cache_valid = False
_execution_config_snapshot = contextvars.ContextVar(
    "execution_config_snapshot",
    default=None,
)


def _migrate_legacy_paths():
    """Migrate user data from legacy locations to user_data/.

    Called automatically on import. Idempotent: skips files that already exist
    at the new location. Preserves originals (copy, not move) for safety.
    """
    try:
        os.makedirs(USER_DATA_DIR, exist_ok=True)
        os.makedirs(LOG_DIR, exist_ok=True)
    except OSError:
        return

    # (legacy_path, new_path) pairs
    legacy_mappings = [
        # v1: dobot_move/config.json
        (os.path.join(_PACKAGE_DIR, "config.json"), CONFIG_FILE),
        # v1: dobot_move/gui_mixins/grasp_flow_modules.json
        (os.path.join(_PACKAGE_DIR, "gui_mixins", "grasp_flow_modules.json"), GRASP_FLOW_FILE),
        # v1: dobot_move/alarm_history.json
        (os.path.join(_PACKAGE_DIR, "alarm_history.json"), ALARM_HISTORY_FILE),
        # v2: project root locations
        (os.path.join(_PROJECT_ROOT, "config.json"), CONFIG_FILE),
        (os.path.join(_PROJECT_ROOT, "grasp_flow_modules.json"), GRASP_FLOW_FILE),
        (os.path.join(_PROJECT_ROOT, "alarm_history.json"), ALARM_HISTORY_FILE),
        (os.path.join(_PROJECT_ROOT, "runtime_health.json"), RUNTIME_HEALTH_FILE),
        (os.path.join(_PROJECT_ROOT, "runtime_state.json"), RUNTIME_STATE_FILE),
        (os.path.join(_PROJECT_ROOT, "runtime_publication.json"), RUNTIME_PUBLICATION_FILE),
        (os.path.join(_PROJECT_ROOT, "runtime_watchdog_lockout.json"), RUNTIME_LOCKOUT_FILE),
        (os.path.join(_PROJECT_ROOT, "runtime_ipc.token"), RUNTIME_IPC_TOKEN_FILE),
    ]

    for old_path, new_path in legacy_mappings:
        if not os.path.exists(new_path) and os.path.exists(old_path):
            try:
                shutil.copy2(old_path, new_path)
                logger.info("Migrated user data: %s -> %s", old_path, new_path)
            except OSError as e:
                logger.warning("Failed to migrate %s: %s", old_path, e)

    # Seed grasp_flow_modules.json from bundled template if neither legacy nor new exists
    if (not os.path.exists(GRASP_FLOW_FILE)
            and os.path.exists(DEFAULT_GRASP_FLOW_TEMPLATE)):
        try:
            shutil.copy2(DEFAULT_GRASP_FLOW_TEMPLATE, GRASP_FLOW_FILE)
            logger.info("Seeded grasp_flow_modules.json from bundled template")
        except OSError as e:
            logger.warning("Failed to seed grasp_flow_modules.json: %s", e)


_migrate_legacy_paths()

DEFAULT_PERFORMANCE_CONFIG = {
    "flow_wait_poll_interval": 0.05,
    "robot_mode_dashboard_fallback_interval": 1.0,
    "pose_cache_max_age": 0.3,
    "motion_settle_time": 0.15,
    "flow_camera_frames": 10,
    "flow_camera_early_confidence": 0.85,
    "flow_camera_min_confidence": 0.3,
    "flow_detection_cache_ttl": 1.0,
    "feedback_stale_warn_age": 0.5,
    "feedback_stale_fail_age": 2.0,
    "motion_done_speed_threshold": 1.0,
    "motion_done_rotation_speed_threshold": 1.0,
    "motion_done_pose_tolerance": 2.0,
    "motion_done_rotation_tolerance": 2.0,
    "motion_done_stable_samples": 3,
    "motion_done_use_feedback": True,
    "motion_wait_robot_mode_fallback": True,
}

DEFAULT_RUNTIME_CONFIG = {
    "startup_connect_timeout_s": 5.0,
    "camera_retry_interval_s": 10.0,
    "ipc_host": "127.0.0.1",
    "ipc_port": 8765,
    "ipc_command_timeout_s": 5.0,
}


DEFAULT_VISUAL_SERVO_CONFIG = {
    "servo_period": 0.06,
    "gain_far": 0.8,
    "gain_mid": 0.5,
    "gain_near": 0.2,
    "max_step_far": 35.0,
    "max_step_mid": 18.0,
    "max_step_near": 6.0,
    "max_step_fine": 2.0,
    "yolo_every_n": 3,
    "stop_on_converge": False,
}


def get_visual_servo_config():
    """获取视觉伺服配置，优先从 config.json 读取，缺失时使用默认值"""
    config = load_config()
    vs_config = dict(DEFAULT_VISUAL_SERVO_CONFIG)
    perf = config.get("performance", {})
    if isinstance(perf.get("visual_servo"), dict):
        vs_config.update(perf["visual_servo"])
    return vs_config


def load_config():
    """加载配置文件（支持备份恢复）"""
    global _config_cache, _cache_valid
    execution_snapshot = _execution_config_snapshot.get()
    if execution_snapshot is not None:
        return execution_snapshot
    if _cache_valid and _config_cache is not None:
        return _config_cache
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                _config_cache = json.load(f)
            _cache_valid = True
            logger.info("✅ 配置文件加载成功: %s", CONFIG_FILE)
            return _config_cache
        except (json.JSONDecodeError, Exception) as e:
            logger.error("❌ 配置文件加载失败: %s，尝试从备份恢复", e)
            # 尝试从备份恢复
            bak_file = CONFIG_FILE + ".bak"
            if os.path.exists(bak_file):
                try:
                    with open(bak_file, 'r', encoding='utf-8') as f:
                        _config_cache = json.load(f)
                    _cache_valid = True
                    logger.info("✅ 从备份恢复配置成功: %s", bak_file)
                    # 恢复成功后立即保存回主文件
                    save_config(_config_cache)
                    return _config_cache
                except Exception as bak_e:
                    logger.error("❌ 备份文件也损坏: %s", bak_e)
            return {}
    else:
        logger.warning("⚠️ 配置文件不存在，使用默认配置: %s", CONFIG_FILE)
        return {}


def invalidate_config_cache():
    """Invalidate this process's config cache without changing the file."""
    global _config_cache, _cache_valid
    _config_cache = None
    _cache_valid = False


def reload_config():
    """Reload config.json into this process and return the new snapshot."""
    invalidate_config_cache()
    return load_config()


@contextmanager
def use_config_snapshot(config):
    """Pin config reads in the current execution context to one snapshot."""
    if not isinstance(config, dict):
        raise TypeError("config snapshot must be a dict")
    token = _execution_config_snapshot.set(copy.deepcopy(config))
    try:
        yield
    finally:
        _execution_config_snapshot.reset(token)


def save_config(config):
    """保存配置文件（原子写入 + 备份）"""
    global _config_cache, _cache_valid
    execution_snapshot = _execution_config_snapshot.get()
    if execution_snapshot is not None:
        updated = copy.deepcopy(config)
        execution_snapshot.clear()
        execution_snapshot.update(updated)
        return True
    try:
        # 写入前备份旧文件
        if os.path.exists(CONFIG_FILE):
            bak_file = CONFIG_FILE + ".bak"
            try:
                shutil.copy2(CONFIG_FILE, bak_file)
            except Exception as e:
                logger.warning("备份配置文件失败: %s", e)
        
        # tempfile.mkstemp may spin for a very long time on Windows when the
        # directory reports writable but rejects files created with mode 0o600.
        dir_name = os.path.dirname(CONFIG_FILE)
        tmp_path = None
        try:
            for _ in range(10):
                candidate = os.path.join(
                    dir_name,
                    f".{os.path.basename(CONFIG_FILE)}.{uuid.uuid4().hex}.tmp",
                )
                try:
                    with open(candidate, 'x', encoding='utf-8') as f:
                        tmp_path = candidate
                        json.dump(config, f, indent=2, ensure_ascii=False)
                        f.flush()
                        os.fsync(f.fileno())
                    break
                except FileExistsError:
                    continue
            if tmp_path is None:
                raise FileExistsError("无法创建唯一的配置临时文件")
            os.replace(tmp_path, CONFIG_FILE)
            tmp_path = None
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        
        _config_cache = config
        _cache_valid = True
        logger.info("✅ 配置文件保存成功: %s", CONFIG_FILE)
        return True
    except Exception as e:
        logger.error("❌ 配置文件保存失败: %s", e)
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


def get_grasp_flow_file():
    return GRASP_FLOW_FILE


def get_robot_ip():
    """获取机器人IP地址"""
    config = load_config()
    return config.get('robot_ip', "192.168.5.1")


def set_robot_ip(ip):
    """设置机器人IP地址，带格式校验"""
    ip_pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
    if not re.match(ip_pattern, ip):
        logger.error("IP 地址格式无效: %s", ip)
        return False
    parts = ip.split('.')
    if not all(0 <= int(p) <= 255 for p in parts):
        logger.error("IP 地址范围无效: %s", ip)
        return False
    config = load_config()
    config['robot_ip'] = ip
    return save_config(config)


def get_modbus_port():
    config = load_config()
    return config.get('modbus_port', 502)


def set_modbus_port(port):
    config = load_config()
    config['modbus_port'] = port
    return save_config(config)


def get_modbus_slave_id():
    """获取Modbus从站地址"""
    config = load_config()
    return config.get('modbus_slave_id', 5)


def set_modbus_slave_id(slave_id):
    """设置Modbus从站地址"""
    config = load_config()
    config['modbus_slave_id'] = int(slave_id)
    return save_config(config)


def get_hook_target():
    """获取提钩目标位姿（从配置文件读取，替代原Modbus寄存器传入）"""
    config = load_config()
    target = config.get('hook_target', None)
    if target is None:
        # 默认提钩目标：使用 photo_position 作为默认值
        target = {
            "x": 0.0, "y": 0.0, "z": 0.0,
            "rx": 0.0, "ry": 0.0, "rz": 0.0,
            "speed_mm_s": 50.0,
        }
        config['hook_target'] = target
        save_config(config)
    return target


def set_hook_target(target):
    """设置提钩目标位姿"""
    config = load_config()
    config['hook_target'] = target
    return save_config(config)


def get_config():
    """获取完整配置"""
    return load_config()


def get_performance_config():
    config = load_config()
    performance = dict(DEFAULT_PERFORMANCE_CONFIG)
    if isinstance(config.get("performance"), dict):
        performance.update(config["performance"])
    return performance


def get_runtime_config():
    config = load_config()
    runtime = dict(DEFAULT_RUNTIME_CONFIG)
    if isinstance(config.get("runtime"), dict):
        runtime.update(config["runtime"])
    return runtime


def _validate_camera_type(camera_type):
    if camera_type not in SUPPORTED_CAMERA_TYPES:
        raise ValueError(f"不支持的相机类型: {camera_type}")


def normalize_camera_model_path(model_path):
    if not isinstance(model_path, str) or not model_path.strip():
        raise ValueError("模型路径不能为空")
    return os.path.abspath(os.path.expanduser(model_path.strip()))


def validate_camera_model_path(model_path):
    normalized = normalize_camera_model_path(model_path)
    if os.path.splitext(normalized)[1].lower() != ".onnx":
        raise ValueError("模型文件必须是 .onnx 格式")
    if not os.path.isfile(normalized):
        raise FileNotFoundError(f"模型文件不存在: {normalized}")
    return normalized


def get_camera_model_path(camera_type):
    """Return the configured model path, or the bundled model for legacy configs."""
    _validate_camera_type(camera_type)
    config = load_config()
    camera_config = config.get("camera", {})
    models = camera_config.get("models", {}) if isinstance(camera_config, dict) else {}
    configured_path = models.get(camera_type) if isinstance(models, dict) else None
    if not configured_path:
        return DEFAULT_CAMERA_MODEL_PATH
    return normalize_camera_model_path(configured_path)


def resolve_camera_model_path(camera_type, model_path=None):
    """Resolve and validate an explicit or camera-specific ONNX model path."""
    _validate_camera_type(camera_type)
    selected_path = model_path if model_path is not None else get_camera_model_path(camera_type)
    return validate_camera_model_path(selected_path)


def set_camera_model_path(camera_type, model_path):
    """Persist one camera's model without changing the other camera settings."""
    _validate_camera_type(camera_type)
    normalized = validate_camera_model_path(model_path)
    config = load_config()
    camera_config = config.get("camera")
    if not isinstance(camera_config, dict):
        camera_config = {}
    models = camera_config.get("models")
    if not isinstance(models, dict):
        models = {}
    models[camera_type] = normalized
    camera_config["models"] = models
    config["camera"] = camera_config
    if not save_config(config):
        raise OSError("保存相机模型配置失败")
    return normalized


def update_config(key, value):
    """更新配置项"""
    config = load_config()
    config[key] = value
    return save_config(config)


from ..robot.transform_utils import euler2rot as _euler2rot, pose2matrix as _pose2matrix


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
    "initial_point": {
        "coords": [250, -150, 300, 0, 0, -68],
        "is_relative": False,
        "relative_to": None,
        "offset": [0, 0, 0, 0, 0, 0],
        "is_default": True,
    },
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
        config["points"] = {name: dict(data) for name, data in _DEFAULT_POINTS.items()}
        config["points"]["initial_point"]["coords"] = list(
            config.get("photo_position", _DEFAULT_POINTS["initial_point"]["coords"])
        )
        save_config(config)
        points = config["points"]
    changed = False
    for name, default_data in _DEFAULT_POINTS.items():
        if name not in points:
            points[name] = dict(default_data)
            if name == "initial_point":
                points[name]["coords"] = list(config.get("photo_position", default_data["coords"]))
            changed = True
    if changed:
        config["points"] = points
        save_config(config)
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
        return None
    coords = list(point.get("coords", [0, 0, 0, 0, 0, 0]))
    offset = point.get("offset", [0, 0, 0, 0, 0, 0])
    if all(abs(float(v)) < 1e-9 for v in coords) and any(abs(float(v)) > 1e-9 for v in offset):
        coords = list(offset)
    resolved = [base_coords[i] + coords[i] for i in range(6)]
    return resolved


def get_initial_point():
    pose = resolve_point("initial_point")
    if pose and len(pose) >= 6:
        return pose[:6]
    return list(get_photo_position())


class ConfigService:
    """Debounced config write service for UI layer."""
    _instance = None

    def __init__(self):
        from ..ui.qt_compat import QTimer
        self._pending = {}
        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._flush_pending)

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def set(self, key, value):
        self._pending[key] = value
        self._timer.start()

    def set_ip(self, key, value):
        self.set(key, value)

    def set_point(self, name, data):
        self.flush()
        set_point(name, data)

    def add_point(self, name, coords=None, is_relative=False, relative_to=None, offset=None):
        self.flush()
        add_point(name, coords, is_relative, relative_to, offset)

    def delete_point(self, name):
        self.flush()
        delete_point(name)

    def flush(self):
        if self._pending:
            self._timer.stop()
            self._flush_pending()

    def _flush_pending(self):
        if not self._pending:
            return
        config = load_config()
        for key, value in self._pending.items():
            config[key] = value
        save_config(config)
        self._pending.clear()
