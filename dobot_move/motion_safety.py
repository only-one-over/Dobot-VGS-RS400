#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
运动安全校验模块 - 统一的运动目标校验网关
"""

import math
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# 工作空间边界 (mm) - CR5 系列默认值
WORKSPACE_X_MIN = 1-900.0
WORKSPACE_X_MAX = 1900.0
WORKSPACE_Y_MIN = -1900.0
WORKSPACE_Y_MAX = 1900.0
WORKSPACE_Z_MIN = -1200.0
WORKSPACE_Z_MAX = 1200.0

# 姿态角边界 (度)
ORIENTATION_MIN = -180.0
ORIENTATION_MAX = 180.0

# 速度/加速度范围
SPEED_MIN = 1.0
SPEED_MAX = 100.0       # v= 百分比
SPEED_ABS_MAX = 2000.0  # speed= mm/s
ACCEL_MIN = 1.0
ACCEL_MAX = 100.0

# 校验结果 code 定义
CODE_OK = 0
CODE_NAN_INF = 1
CODE_LENGTH = 2
CODE_SPEED = 3
CODE_ACCEL = 4
CODE_WORKSPACE = 5
CODE_ORIENTATION = 6
CODE_NOT_CONNECTED = 7
CODE_NOT_ENABLED = 8
CODE_ESTOP = 9
CODE_ALARM = 10
CODE_STALE_FEEDBACK = 11
CODE_RELATIVE_DELTA = 12
CODE_UNPROJECTABLE_RELATIVE = 13


@dataclass
class MotionSafetyConfig:
    """运动安全配置"""
    workspace_x_min: float = -900.0
    workspace_x_max: float = 900.0
    workspace_y_min: float = -900.0
    workspace_y_max: float = 900.0
    workspace_z_min: float = 0.0
    workspace_z_max: float = 1200.0
    orientation_min: float = -180.0
    orientation_max: float = 180.0
    max_delta_xyz: float = 300.0    # 单段 XYZ 偏移上限 (mm)
    max_delta_rot: float = 45.0     # 单段姿态偏移上限 (deg)
    feedback_max_age_normal: float = 0.5   # 普通运动反馈新鲜度 (s)
    feedback_max_age_servo: float = 0.2    # ServoP 反馈新鲜度 (s)
    speed_min: float = 1.0
    speed_max_percent: float = 100.0
    speed_max_abs: float = 2000.0
    accel_min: float = 1.0
    accel_max: float = 100.0


@dataclass
class MotionSafetyState:
    """运动安全状态（只读缓存）"""
    is_connected: bool = False
    is_enabled: bool = False
    software_emergency_active: bool = False
    error_status: int = 0
    robot_mode: int = 0
    feedback_age: float = 999.0  # seconds since last feedback


@dataclass
class MotionValidationResult:
    """运动校验结果"""
    ok: bool
    code: int
    message: str

    def __bool__(self):
        return self.ok


def _ok():
    return MotionValidationResult(ok=True, code=CODE_OK, message="OK")


def _fail(code, message):
    return MotionValidationResult(ok=False, code=code, message=message)


def _get_safety_state(controller):
    """从 controller 缓存读取安全状态，不发任何查询"""
    if hasattr(controller, 'get_motion_safety_state'):
        return controller.get_motion_safety_state()
    # Fallback for controllers without get_motion_safety_state
    return MotionSafetyState(
        is_connected=getattr(controller, 'is_connected', False),
        is_enabled=getattr(controller, 'is_enabled', False),
        software_emergency_active=getattr(controller, 'software_emergency_active', False),
        error_status=0,
        robot_mode=0,
        feedback_age=999.0,
    )


def validate_absolute_pose(controller, pose, speed=None, accel=None, speed_kind="percent", config=None):
    """
    绝对位姿校验。

    Args:
        controller: DobotController 实例
        pose: 目标位姿 [x, y, z, rx, ry, rz]，长度必须严格等于 6
        speed: 速度值
        accel: 加速度值
        speed_kind: "percent" 或 "abs"
        config: MotionSafetyConfig，None 时使用默认值

    Returns:
        MotionValidationResult
    """
    cfg = config or MotionSafetyConfig()

    # 1. 长度严格等于 6
    if pose is None or len(pose) != 6:
        return _fail(CODE_LENGTH, f"pose length must be 6, got {len(pose) if pose is not None else 'None'}")

    # 2. 全部 finite
    for i, v in enumerate(pose):
        if not math.isfinite(v):
            return _fail(CODE_NAN_INF, f"pose[{i}] is not finite: {v}")

    x, y, z, rx, ry, rz = pose

    # 3. 速度/加速度范围
    if speed is not None:
        if not math.isfinite(speed):
            return _fail(CODE_SPEED, f"speed is not finite: {speed}")
        max_speed = cfg.speed_max_percent if speed_kind == "percent" else cfg.speed_max_abs
        if speed < cfg.speed_min or speed > max_speed:
            return _fail(CODE_SPEED, f"speed {speed} out of range [{cfg.speed_min}, {max_speed}]")
    if accel is not None:
        if not math.isfinite(accel):
            return _fail(CODE_ACCEL, f"accel is not finite: {accel}")
        if accel < cfg.accel_min or accel > cfg.accel_max:
            return _fail(CODE_ACCEL, f"accel {accel} out of range [{cfg.accel_min}, {cfg.accel_max}]")

    # 4. 工作空间边界
    if x < cfg.workspace_x_min or x > cfg.workspace_x_max:
        return _fail(CODE_WORKSPACE, f"X {x:.1f} out of range [{cfg.workspace_x_min}, {cfg.workspace_x_max}]")
    if y < cfg.workspace_y_min or y > cfg.workspace_y_max:
        return _fail(CODE_WORKSPACE, f"Y {y:.1f} out of range [{cfg.workspace_y_min}, {cfg.workspace_y_max}]")
    if z < cfg.workspace_z_min or z > cfg.workspace_z_max:
        return _fail(CODE_WORKSPACE, f"Z {z:.1f} out of range [{cfg.workspace_z_min}, {cfg.workspace_z_max}]")

    # 5. 姿态角范围
    for name, val in [("Rx", rx), ("Ry", ry), ("Rz", rz)]:
        if val < cfg.orientation_min or val > cfg.orientation_max:
            return _fail(CODE_ORIENTATION, f"{name} {val:.1f} out of range [{cfg.orientation_min}, {cfg.orientation_max}]")

    # 6. 机器人状态检查（只读缓存，不发查询）
    state = _get_safety_state(controller)
    if not state.is_connected:
        return _fail(CODE_NOT_CONNECTED, "robot not connected")
    if not state.is_enabled:
        return _fail(CODE_NOT_ENABLED, "robot not enabled")
    if state.software_emergency_active:
        return _fail(CODE_ESTOP, "software emergency stop active")
    if state.error_status != 0:
        return _fail(CODE_ALARM, f"robot has error status: {state.error_status}")

    return _ok()


def _validate_absolute_pose_no_state(pose, speed, accel, cfg):
    """校验绝对位姿的几何/数值部分，不检查机器人状态"""
    if pose is None or len(pose) != 6:
        return _fail(CODE_LENGTH, f"pose length must be 6, got {len(pose) if pose is not None else 'None'}")
    for i, v in enumerate(pose):
        if not math.isfinite(v):
            return _fail(CODE_NAN_INF, f"pose[{i}] is not finite: {v}")
    x, y, z, rx, ry, rz = pose
    if x < cfg.workspace_x_min or x > cfg.workspace_x_max:
        return _fail(CODE_WORKSPACE, f"projected X {x:.1f} out of range")
    if y < cfg.workspace_y_min or y > cfg.workspace_y_max:
        return _fail(CODE_WORKSPACE, f"projected Y {y:.1f} out of range")
    if z < cfg.workspace_z_min or z > cfg.workspace_z_max:
        return _fail(CODE_WORKSPACE, f"projected Z {z:.1f} out of range")
    for name, val in [("Rx", rx), ("Ry", ry), ("Rz", rz)]:
        if val < cfg.orientation_min or val > cfg.orientation_max:
            return _fail(CODE_ORIENTATION, f"projected {name} {val:.1f} out of range")
    return _ok()


def validate_relative_delta(controller, offsets, coord_system="user", motion_type="linear",
                            speed=None, accel=None, config=None):
    """
    相对运动偏移校验。

    Args:
        controller: DobotController 实例
        offsets: 偏移量 [dx, dy, dz, drx, dry, drz]
        coord_system: 坐标系
        motion_type: 运动类型
        speed: 速度
        accel: 加速度
        config: MotionSafetyConfig

    Returns:
        MotionValidationResult
    """
    cfg = config or MotionSafetyConfig()

    # 1. 偏移长度严格等于 6
    if offsets is None or len(offsets) != 6:
        return _fail(CODE_LENGTH, f"offsets length must be 6, got {len(offsets) if offsets is not None else 'None'}")

    # 2. 全部 finite
    for i, v in enumerate(offsets):
        if not math.isfinite(v):
            return _fail(CODE_NAN_INF, f"offsets[{i}] is not finite: {v}")

    dx, dy, dz, drx, dry, drz = offsets

    # 3. 单段偏移上限
    for name, val, limit in [("dX", dx, cfg.max_delta_xyz), ("dY", dy, cfg.max_delta_xyz),
                              ("dZ", dz, cfg.max_delta_xyz),
                              ("dRx", drx, cfg.max_delta_rot), ("dRy", dry, cfg.max_delta_rot),
                              ("dRz", drz, cfg.max_delta_rot)]:
        if abs(val) > limit:
            return _fail(CODE_RELATIVE_DELTA, f"{name} {val:.1f} exceeds limit {limit}")

    # 4. 反馈新鲜度检查
    state = _get_safety_state(controller)
    if state.feedback_age > cfg.feedback_max_age_normal:
        return _fail(CODE_STALE_FEEDBACK, f"feedback age {state.feedback_age:.2f}s exceeds {cfg.feedback_max_age_normal}s")

    # 5. 机器人状态检查
    if not state.is_connected:
        return _fail(CODE_NOT_CONNECTED, "robot not connected")
    if not state.is_enabled:
        return _fail(CODE_NOT_ENABLED, "robot not enabled")
    if state.software_emergency_active:
        return _fail(CODE_ESTOP, "software emergency stop active")
    if state.error_status != 0:
        return _fail(CODE_ALARM, f"robot has error status: {state.error_status}")

    # 6. 投影终点校验
    # 读取当前 TCP 位姿
    current_pose = None
    if hasattr(controller, 'latest_pose') and controller.latest_pose is not None:
        current_pose = controller.latest_pose

    if current_pose is None or len(current_pose) < 6:
        return _fail(CODE_UNPROJECTABLE_RELATIVE, "cannot read current TCP pose for projection")

    # 非零 user/tool 坐标系下无法安全投影
    user_index = getattr(controller, '_user_index', 0)
    tool_index = getattr(controller, '_tool_index', 0)
    if user_index != 0 or tool_index != 0:
        return _fail(CODE_UNPROJECTABLE_RELATIVE,
                     f"cannot safely project with user={user_index}, tool={tool_index}")

    # 计算预计终点
    projected = [current_pose[i] + offsets[i] for i in range(6)]

    # 校验终点绝对位姿（不再检查机器人状态，已在上面检查过）
    result = _validate_absolute_pose_no_state(projected, speed, accel, cfg)
    if not result:
        return result

    return _ok()


def validate_motion_target(controller, target, speed=None, accel=None):
    """
    [DEPRECATED] 使用 validate_absolute_pose() 或 validate_relative_delta() 替代。
    保留向后兼容，内部委托 validate_absolute_pose()。
    """
    return validate_absolute_pose(controller, target, speed=speed, accel=accel)


def validate_servo_p_params(t, aheadtime, gain, servo_period):
    """
    ServoP 参数最终防线校验和 clamp。

    Returns:
        (t, aheadtime, gain) clamped values
    """
    t = max(t, servo_period)
    aheadtime = max(20, min(100, int(aheadtime)))
    gain = max(200, min(1000, int(gain)))
    return t, aheadtime, gain
