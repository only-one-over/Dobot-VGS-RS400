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
import threading
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
REMOTE_API_HEALTH_FILE = os.path.join(USER_DATA_DIR, "remote_api_health.json")
LOG_DIR = os.path.join(USER_DATA_DIR, "logs")

# Bundled resources (shipped with the package, updated on replacement)
CONFIG_EXAMPLE_FILE = os.path.join(_MODULE_DIR, "config.example.json")
DEFAULT_GRASP_FLOW_TEMPLATE = os.path.join(_MODULE_DIR, "grasp_flow_modules.default.json")
DEFAULT_ALARM_CODES_DIR = os.path.join(_MODULE_DIR, "files")
DEFAULT_CAMERA_MODEL_PATH = os.path.join(_PACKAGE_DIR, "best.onnx")
SUPPORTED_CAMERA_TYPES = ("D435i", "D405")
_config_cache = None
_cache_valid = False
# 保护 _config_cache / _cache_valid 的多线程访问；
# 使用 RLock 是因为 load_config 在备份恢复路径中会递归调用 save_config
_config_lock = threading.RLock()
_execution_config_snapshot = contextvars.ContextVar(
    "execution_config_snapshot",
    default=None,
)


# ---------------------------------------------------------------------------
# 环境变量覆盖 (deployment override)
#   支持通过环境变量覆盖 config.json 中的关键字段，无需修改文件即可适配不同部署环境。
#   环境变量优先级 > config.json > 代码默认值
#
#   约定：
#     DOBOT_ROBOT_IP       → robot_ip
#     DOBOT_MODBUS_PORT    → modbus_port
#     DOBOT_MODBUS_SLAVE   → modbus_slave_id
#     DOBOT_D435I_MODEL    → camera.models.D435i
#     DOBOT_D405_MODEL     → camera.models.D405
#     DOBOT_REMOTE_API_PORT → remote_api.port
# ---------------------------------------------------------------------------

# 可被环境变量覆盖的配置项映射：env_var → (config_key, coerce_fn)
_ENV_OVERRIDES: dict[str, tuple[str, ...]] = {
    "DOBOT_ROBOT_IP":        ("robot_ip", str),
    "DOBOT_MODBUS_PORT":     ("modbus_port", int),
    "DOBOT_MODBUS_SLAVE":    ("modbus_slave_id", int),
    "DOBOT_D435I_MODEL":     ("camera.models.D435i", str),
    "DOBOT_D405_MODEL":      ("camera.models.D405", str),
    "DOBOT_REMOTE_API_PORT": ("remote_api.port", int),
}

# 运行时生效的覆盖记录（供 check_config / 调试用）
_active_env_overrides: dict[str, str] = {}


def _apply_env_overrides(config: dict) -> dict:
    """Apply environment variable overrides to a config dict in-place."""
    for env_key, (config_path, coerce_fn) in _ENV_OVERRIDES.items():
        env_val = os.environ.get(env_key)
        if env_val is None or env_val.strip() == "":
            continue
        try:
            coerced = coerce_fn(env_val.strip())
        except (ValueError, TypeError):
            logger.warning("环境变量 %s=%r 类型转换失败，已忽略", env_key, env_val)
            continue
        # 支持点分路径（如 camera.models.D435i）
        keys = config_path.split(".")
        d = config
        for k in keys[:-1]:
            if k not in d or not isinstance(d[k], dict):
                d[k] = {}
            d = d[k]
        d[keys[-1]] = coerced
        _active_env_overrides[env_key] = env_val.strip()
        logger.info("配置覆盖 %s ← %s=%s", config_path, env_key, env_val.strip())
    return config


def get_active_env_overrides() -> dict[str, str]:
    """Return a copy of currently active environment overrides."""
    return dict(_active_env_overrides)


def check_config(verbose: bool = True) -> bool:
    """验证当前配置的完整性，部署后用于预检。

    Returns True if all critical checks pass, False otherwise.
    """
    _active_env_overrides.clear()
    config = load_config()
    config = _apply_env_overrides(config)

    errors: list[str] = []
    warnings: list[str] = []

    # --- 必填项检查 ---
    robot_ip = config.get("robot_ip")
    if not robot_ip:
        errors.append("[必填] robot_ip 未设置（或设置 DOBOT_ROBOT_IP 环境变量）")
    elif not re.match(r'^(\d{1,3}\.){3}\d{1,3}$', str(robot_ip)):
        errors.append(f"[必填] robot_ip 格式无效: {robot_ip}")
    elif not all(0 <= int(p) <= 255 for p in str(robot_ip).split('.')):
        errors.append(f"[必填] robot_ip 范围无效: {robot_ip}")

    modbus_port = config.get("modbus_port", 502)
    if not isinstance(modbus_port, int) or not (1 <= modbus_port <= 65535):
        errors.append(f"[必填] modbus_port 无效: {modbus_port}（应为 1-65535）")

    # --- 相机模型检查 ---
    camera_config = config.get("camera", {})
    models = camera_config.get("models", {}) if isinstance(camera_config, dict) else {}
    for cam_type in SUPPORTED_CAMERA_TYPES:
        model_path = models.get(cam_type) if isinstance(models, dict) else None
        if not model_path:
            warnings.append(f"[选填] camera.models.{cam_type} 未设置，将使用默认模型 {DEFAULT_CAMERA_MODEL_PATH}")
        elif not os.path.isfile(os.path.expanduser(model_path)):
            errors.append(f"[必填] camera.models.{cam_type} 模型文件不存在: {model_path}")

    # --- 标定检查 ---
    calibration = config.get("calibration", {})
    for cam_type in SUPPORTED_CAMERA_TYPES:
        cal = calibration.get(cam_type, {}) if isinstance(calibration, dict) else {}
        if not cal.get("cam_to_flange_pose"):
            warnings.append(f"[选填] calibration.{cam_type} 未标定（手眼矩阵将使用默认值）")

    # --- 拍照位检查 ---
    photo = config.get("photo_position")
    if photo is not None:
        if not isinstance(photo, list) or len(photo) != 6:
            errors.append(f"[必填] photo_position 格式无效（应为 6 元素列表），当前: {photo}")
        elif not all(isinstance(v, (int, float)) for v in photo):
            errors.append(f"[必填] photo_position 包含非数值元素: {photo}")

    # --- 点位检查 ---
    points = config.get("points", {})
    if not isinstance(points, dict):
        warnings.append("[选填] points 不是字典，点位功能不可用")
    else:
        for name in ("initial_point", "d435i", "d405"):
            if name not in points:
                warnings.append(f"[选填] points.{name} 缺失（系统会在首次运行时自动创建）")

    # --- 流程库检查 ---
    if not os.path.exists(GRASP_FLOW_FILE):
        warnings.append(f"[选填] 流程库不存在: {GRASP_FLOW_FILE}（首次运行时从模板创建）")

    # --- 输出结果 ---
    if verbose:
        print("=" * 60)
        print("配置预检 (check_config)")
        print("=" * 60)
        print(f"配置文件: {CONFIG_FILE}")
        if _active_env_overrides:
            print(f"环境变量覆盖: {len(_active_env_overrides)} 项")
            for k, v in _active_env_overrides.items():
                print(f"  {k} = {v}")
        else:
            print("环境变量覆盖: 无")
        print("-" * 60)
        if errors:
            print(f"❌ 错误 ({len(errors)}):")
            for e in errors:
                print(f"   {e}")
        if warnings:
            print(f"⚠️  警告 ({len(warnings)}):")
            for w in warnings:
                print(f"   {w}")
        if not errors and not warnings:
            print("✅ 所有检查通过")
        elif not errors:
            print("✅ 关键检查通过（有警告但不影响启动）")
        print("-" * 60)
        if errors:
            print("❌ 预检失败，请修正以上错误后再启动")
        else:
            print("✅ 预检通过，可以启动")
        print("=" * 60)

    return len(errors) == 0


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
    "tool_index": 0,
    "user_index": 0,
}


DEFAULT_REMOTE_API_CONFIG = {
    "host": "0.0.0.0",
    "port": 8000,
    "token": "",
    "feedback_port": 30004,
    "feedback_reconnect_interval_s": 2.0,
    "feedback_stale_ok_s": 0.3,
    "feedback_stale_fail_s": 2.0,
    "modbus_client_timeout_s": 3.0,
    "modbus_host": "127.0.0.1",
    "allowed_ips": [],
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


DEFAULT_CAMERA_CONFIG = {
    # 是否执行 RealSense 深度→彩色对齐（align.process），CPU 重活。
    # 诊断 16fps 瓶颈时可设为 false 跳过对齐做对比。默认 true 保持原行为。
    "enable_align": True,
    # 是否执行深度滤波链（spatial/temporal/hole_filling），CPU 重活。
    # 诊断时可设为 false 跳过滤波做对比。默认 true 保持原行为。
    "enable_depth_filter": True,
}


DEFAULT_PIPELINE_CONFIG = {
    # 是否启用 PositionWorker 异步化（高风险，默认禁用）。
    # 启用后 InferenceWorker 只跑 run_detection_tracked（GPU 推理），
    # calculate_object_position_smoothed（深度对齐 + 点云 + Kalman）由独立
    # PositionWorker 线程执行，避免 CPU 位置计算阻塞 GPU 推理，提升 inference_fps。
    # 注意：启用后 run_detection_tracked 与 calculate_object_position_smoothed 会
    # 并发访问 VisionSystem 的 kalman_3d / _kalman_last_time / last_valid_position
    # 等状态，存在潜在线程安全风险（仅诊断/实验用，生产环境保持 false）。
    "position_worker_enabled": False,
}


DEFAULT_MOTION_SAFETY_CONFIG = {
    # 工作空间边界 (mm) - CR20A 机器人默认值
    "workspace_x_min": -1900.0,
    "workspace_x_max": 1900.0,
    "workspace_y_min": -1900.0,
    "workspace_y_max": 1900.0,
    "workspace_z_min": -1200.0,
    "workspace_z_max": 1200.0,
    # 姿态角边界 (度)
    "orientation_min": -360.0,
    "orientation_max": 360.0,
    # 单段运动偏移上限
    "max_delta_xyz": 800.0,   # 单段 XYZ 偏移上限 (mm)
    "max_delta_rot": 90.0,    # 单段姿态偏移上限 (度)
    # 速度/加速度范围
    "speed_min": 1.0,
    "speed_max_percent": 100.0,
    "speed_max_abs": 2000.0,
    "accel_min": 1.0,
    "accel_max": 100.0,
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
    """加载配置文件（支持备份恢复 + 环境变量覆盖）

    单一数据源：永远读 user_data/config.json 草稿文件。
    use_config_snapshot 已废弃为 no-op shim，不再切换快照。
    """
    global _config_cache, _cache_valid
    with _config_lock:
        if _cache_valid and _config_cache is not None:
            return _config_cache
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    _config_cache = json.load(f)
                _cache_valid = True
                logger.info("✅ 配置文件加载成功: %s", CONFIG_FILE)
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
                    except Exception as bak_e:
                        logger.error("❌ 备份文件也损坏: %s", bak_e)
                        _config_cache = {}
                else:
                    _config_cache = {}
        else:
            logger.warning("⚠️ 配置文件不存在，使用默认配置: %s", CONFIG_FILE)
            _config_cache = {}

        # 应用环境变量覆盖（不写回文件，仅影响内存）
        # 注意：用 `is not None` 判断，确保空 dict 也应用环境变量覆盖
        if _config_cache is not None:
            _config_cache = _apply_env_overrides(_config_cache)
            _cache_valid = True
        return _config_cache


def invalidate_config_cache():
    """Invalidate this process's config cache without changing the file."""
    global _config_cache, _cache_valid
    with _config_lock:
        _config_cache = None
        _cache_valid = False


def reload_config():
    """Reload config.json into this process and return the new snapshot."""
    invalidate_config_cache()
    return load_config()


@contextmanager
def use_config_snapshot(config):
    """Deprecated no-op shim.

    单一数据源模型下，load_config() 永远读 user_data/config.json 草稿文件。
    此函数保留为向后兼容 shim，不再激活任何 ContextVar。
    传入的 config 参数被忽略。
    """
    del config  # 参数忽略，仅保留签名兼容
    yield


def save_config(config):
    """保存配置文件（原子写入 + 备份）

    单一数据源：永远写 user_data/config.json 草稿文件。
    """
    global _config_cache, _cache_valid
    with _config_lock:
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
    initial_point = config.get("points", {}).get("initial_point")
    if initial_point is not None:
        initial_point["coords"] = list(position)
    return save_config(config)


def get_grasp_flow_file():
    return GRASP_FLOW_FILE


def get_robot_ip():
    """获取机器人IP地址"""
    config = load_config()
    return config.get('robot_ip', "192.168.1.50")


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


def set_motion_safety_config(config_dict: dict) -> bool:
    """保存运动安全配置，带字段校验。

    Args:
        config_dict: 包含 15 个数值字段的 dict（见 DEFAULT_MOTION_SAFETY_CONFIG）

    Returns:
        True 保存成功，False 校验失败

    Raises:
        ValueError: 字段非数值 / min > max / 必填字段缺失
    """
    if not isinstance(config_dict, dict):
        raise ValueError("config_dict 必须为 dict")

    # 字段白名单（与 DEFAULT_MOTION_SAFETY_CONFIG 的 key 一致）
    allowed_keys = set(DEFAULT_MOTION_SAFETY_CONFIG.keys())

    # 过滤掉未知 key（如用户误传的 _note 字段）
    filtered = {}
    for k, v in config_dict.items():
        if k not in allowed_keys:
            continue
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            raise ValueError(f"字段 {k} 必须为数值，当前: {v!r}")
        filtered[k] = float(v)

    # 必填字段检查（至少 15 个字段都应在 filtered 中）
    missing = allowed_keys - set(filtered.keys())
    if missing:
        raise ValueError(f"缺少必填字段: {sorted(missing)}")

    # min <= max 校验
    pair_checks = [
        ("workspace_x_min", "workspace_x_max", "X"),
        ("workspace_y_min", "workspace_y_max", "Y"),
        ("workspace_z_min", "workspace_z_max", "Z"),
        ("orientation_min", "orientation_max", "姿态角"),
        ("speed_min", "speed_max_percent", "速度百分比"),
        ("accel_min", "accel_max", "加速度"),
    ]
    for min_key, max_key, label in pair_checks:
        if filtered[min_key] > filtered[max_key]:
            raise ValueError(f"{label} 最小值不能大于最大值: {min_key}={filtered[min_key]}, {max_key}={filtered[max_key]}")

    # 正数范围校验（speed/accel/delta 必须 > 0）
    positive_fields = [
        "max_delta_xyz", "max_delta_rot",
        "speed_min", "speed_max_percent", "speed_max_abs",
        "accel_min", "accel_max",
    ]
    for field in positive_fields:
        if filtered[field] <= 0:
            raise ValueError(f"字段 {field} 必须为正数，当前: {filtered[field]}")

    # 写入 config
    config = load_config()
    config["motion_safety"] = filtered
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


def get_tool_index() -> int:
    """获取工具坐标系索引（runtime.tool_index），默认 0（法兰坐标系）。"""
    return int(get_runtime_config().get("tool_index", 0))


def set_tool_index(idx: int) -> None:
    """写入 runtime.tool_index。重启 Runtime 后生效。"""
    config = load_config()
    if not isinstance(config.get("runtime"), dict):
        config["runtime"] = {}
    config["runtime"]["tool_index"] = int(idx)
    save_config(config)


def get_user_index() -> int:
    """获取用户坐标系索引（runtime.user_index），默认 0（基坐标系）。"""
    return int(get_runtime_config().get("user_index", 0))


def set_user_index(idx: int) -> None:
    """写入 runtime.user_index。重启 Runtime 后生效。"""
    config = load_config()
    if not isinstance(config.get("runtime"), dict):
        config["runtime"] = {}
    config["runtime"]["user_index"] = int(idx)
    save_config(config)


def get_remote_api_config():
    config = load_config()
    remote_api = dict(DEFAULT_REMOTE_API_CONFIG)
    if isinstance(config.get("remote_api"), dict):
        remote_api.update(config["remote_api"])
    return remote_api


def get_camera_config():
    """获取相机配置，优先从 config.json 读取，缺失时使用默认值。

    返回的 dict 至少包含 enable_align / enable_depth_filter 两个键
    （来自 DEFAULT_CAMERA_CONFIG），并合并 config["camera"] 中的其它字段
    （如 models / depth_range / max_camera_z_mm）。
    """
    config = load_config()
    camera = dict(DEFAULT_CAMERA_CONFIG)
    if isinstance(config.get("camera"), dict):
        camera.update(config["camera"])
    return camera


def get_pipeline_config():
    """获取流水线配置，优先从 config.json 读取，缺失时使用默认值。

    返回的 dict 至少包含 position_worker_enabled 键（来自
    DEFAULT_PIPELINE_CONFIG），并合并 config["pipeline"] 中的其它字段。
    """
    config = load_config()
    pipeline = dict(DEFAULT_PIPELINE_CONFIG)
    if isinstance(config.get("pipeline"), dict):
        pipeline.update(config["pipeline"])
    return pipeline


def get_motion_safety_config():
    """获取运动安全配置，优先从 config.json 读取，缺失时使用默认值。

    返回的 dict 包含 15 个字段：6 个 workspace 边界、2 个 delta 上限、
    2 个姿态角边界、3 个速度范围、2 个加速度范围。
    feedback_max_age_normal / feedback_max_age_servo 不在此处（属运行时性能参数）。
    """
    config = load_config()
    motion_safety = dict(DEFAULT_MOTION_SAFETY_CONFIG)
    if isinstance(config.get("motion_safety"), dict):
        motion_safety.update(config["motion_safety"])
    return motion_safety


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


# 新默认 cam_to_flange_pose 由旧默认值计算：
#   inv(pose2matrix(-210,0,310,90,0,-90)) @ pose2matrix(-72.76,-10.12,31.18,90,0,-90)
_DEFAULT_CAM_TO_FLANGE_POSE = [10.12, -278.82, -137.24, 0.0, 0.0, 0.0]


def _rot2euler(R, degree=True):
    """旋转矩阵 -> 欧拉角 (ZYX，与 euler2rot 互逆)。"""
    sy = np.sqrt(R[0, 0] ** 2 + R[1, 0] ** 2)
    singular = sy < 1e-6
    if not singular:
        rx = np.arctan2(R[2, 1], R[2, 2])
        ry = np.arctan2(-R[2, 0], sy)
        rz = np.arctan2(R[1, 0], R[0, 0])
    else:
        rx = np.arctan2(-R[1, 2], R[1, 1])
        ry = np.arctan2(-R[2, 0], sy)
        rz = 0.0
    if degree:
        rx, ry, rz = np.degrees([rx, ry, rz])
    return rx, ry, rz


def _matrix2pose(T, degree=True):
    """4x4 齐次变换矩阵 -> 位姿 [x, y, z, rx, ry, rz]。"""
    x, y, z = T[:3, 3]
    rx, ry, rz = _rot2euler(T[:3, :3], degree)
    return [float(x), float(y), float(z), float(rx), float(ry), float(rz)]


def _tool_cam_base_to_flange(tool_base_calib_pose, cam_base_calib_pose):
    """旧双位姿格式迁移为 cam_to_flange_pose:
    cam_to_flange = inv(T_tool2base) @ T_cam2base
    """
    T_tool2base = _pose2matrix(*tool_base_calib_pose)
    T_cam2base = _pose2matrix(*cam_base_calib_pose)
    T_cam2flange = np.linalg.inv(T_tool2base) @ T_cam2base
    return _matrix2pose(T_cam2flange)


def get_calibration(camera_type="D435i"):
    config = load_config()
    calibration = config.get("calibration", {})
    if not isinstance(calibration, dict):
        calibration = {}
    migrated = False

    # 旧版单相机格式：tool_base_calib_pose / cam_base_calib_pose 直接位于 calibration 根下
    if "tool_base_calib_pose" in calibration and "cam_base_calib_pose" in calibration:
        old_tool = calibration.pop("tool_base_calib_pose")
        old_cam = calibration.pop("cam_base_calib_pose")
        calibration["D435i"] = {
            "cam_to_flange_pose": _tool_cam_base_to_flange(old_tool, old_cam),
        }
        calibration["D405"] = {
            "cam_to_flange_pose": list(_DEFAULT_CAM_TO_FLANGE_POSE),
        }
        migrated = True

    # 旧版双位姿格式：每个相机条目下有 tool_base_calib_pose + cam_base_calib_pose
    for cam_type, calib in list(calibration.items()):
        if not isinstance(calib, dict):
            continue
        if "tool_base_calib_pose" in calib and "cam_base_calib_pose" in calib:
            old_tool = calib.pop("tool_base_calib_pose")
            old_cam = calib.pop("cam_base_calib_pose")
            calib["cam_to_flange_pose"] = _tool_cam_base_to_flange(old_tool, old_cam)
            migrated = True

    if migrated:
        config["calibration"] = calibration
        save_config(config)

    cam_calib = calibration.get(camera_type, {})
    return cam_calib


def set_calibration(camera_type, cam_to_flange_pose):
    global _cache_valid
    config = load_config()
    if "calibration" not in config:
        config["calibration"] = {}
    config["calibration"][camera_type] = {
        "cam_to_flange_pose": cam_to_flange_pose,
    }
    result = save_config(config)
    with _config_lock:
        _cache_valid = False
    return result


def get_all_calibrations():
    config = load_config()
    return config.get("calibration", {})


def get_camera_handeye_matrix(camera_type="D435i"):
    calib = get_calibration(camera_type)
    cam_to_flange_pose = calib.get("cam_to_flange_pose", _DEFAULT_CAM_TO_FLANGE_POSE)
    T_cam2flange = _pose2matrix(*cam_to_flange_pose)
    return T_cam2flange


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
    global _config_cache
    config = load_config()
    points = config.get("points", None)
    if points is None:
        config["points"] = {name: dict(data) for name, data in _DEFAULT_POINTS.items()}
        config["points"]["initial_point"]["coords"] = list(
            config.get("photo_position", _DEFAULT_POINTS["initial_point"]["coords"])
        )
        with _config_lock:
            _config_cache = config
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
        with _config_lock:
            _config_cache = config
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
    # 如果 point 是 list 格式，直接返回（不支持相对点位）
    if isinstance(point, list):
        return list(point)
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
