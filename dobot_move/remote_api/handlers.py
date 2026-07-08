"""Response builders for remote_api endpoints."""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


def parse_feedback(fb: Any) -> dict[str, Any]:
    """Parse a 30004 numpy structured array into a dict."""
    robot_mode = int(fb["RobotMode"][0])
    enable_status = int(fb["EnableStatus"][0])
    running_status = int(fb["RunningStatus"][0])
    error_status = int(fb["ErrorStatus"][0])
    current_command_id = int(fb["CurrentCommandId"][0])
    speed_scaling = float(fb["SpeedScaling"][0])
    pose = fb["ToolVectorActual"][0].tolist()
    q_actual = fb["QActual"][0].tolist()
    q_target = fb["QTarget"][0].tolist()
    tcp_speed = fb["TCPSpeedActual"][0].tolist()
    tool_vector_target = fb["ToolVectorTarget"][0].tolist()
    tcp_force = fb["ActualTCPForce"][0].tolist()
    return {
        "robot_mode": robot_mode,
        "enable_status": enable_status,
        "running_status": running_status,
        "error_status": error_status,
        "current_command_id": current_command_id,
        "speed_scaling": speed_scaling,
        "pose": pose,
        "q_actual": q_actual,
        "q_target": q_target,
        "tcp_speed_actual": tcp_speed,
        "tool_vector_target": tool_vector_target,
        "force": {
            "fx": tcp_force[0], "fy": tcp_force[1], "fz": tcp_force[2],
            "mx": tcp_force[3], "my": tcp_force[4], "mz": tcp_force[5],
        },
    }


def build_status(
    fb: Any,
    health: str,
    age: float,
    error: str,
    robot_ip: str,
) -> dict[str, Any]:
    """Build /api/v1/status response data."""
    if fb is None:
        return {
            "dobot_available": False,
            "controller_created": False,
            "is_connected": False,
            "is_enabled": False,
            "motion_busy": False,
            "robot_ip": robot_ip,
        }
    p = parse_feedback(fb)
    return {
        "dobot_available": True,
        "controller_created": True,
        "is_connected": True,
        "is_enabled": p["enable_status"] == 1,
        "motion_busy": p["running_status"] == 1,
        "robot_ip": robot_ip,
    }


def build_feedback_all(
    fb: Any,
    health: str,
    age: float,
    error: str,
    robot_ip: str,
) -> dict[str, Any]:
    """Build /api/v1/feedback/all response data."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if fb is None:
        return {
            "timestamp": timestamp,
            "is_connected": False,
            "is_enabled": False,
            "robot_ip": robot_ip,
            "motion_busy": False,
            "software_emergency_active": False,
            "pose": None,
            "robot_mode": None,
            "force": None,
            "feedback_health": {"health": "disconnected", "age": 999.0},
            "safety_state": {
                "is_connected": False, "is_enabled": False,
                "emergency_stopped": False, "error_status": False,
                "robot_mode": None, "feedback_age": 999.0, "health": "disconnected",
            },
            "q_actual": None, "q_target": None, "tcp_speed_actual": None,
            "tool_vector_target": None, "speed_scaling": None,
            "running_status": None, "error_status": None,
            "enable_status": None, "current_command_id": None,
        }
    p = parse_feedback(fb)
    robot_mode = p["robot_mode"]
    is_enabled = p["enable_status"] == 1
    is_connected = True
    motion_busy = p["running_status"] == 1
    has_error = p["error_status"] == 1
    emergency_stopped = robot_mode == 9
    return {
        "timestamp": timestamp,
        "is_connected": is_connected,
        "is_enabled": is_enabled,
        "robot_ip": robot_ip,
        "motion_busy": motion_busy,
        "software_emergency_active": emergency_stopped,
        "pose": p["pose"],
        "robot_mode": robot_mode,
        "force": p["force"],
        "feedback_health": {"health": health, "age": round(age, 3)},
        "safety_state": {
            "is_connected": is_connected, "is_enabled": is_enabled,
            "emergency_stopped": emergency_stopped, "error_status": has_error,
            "robot_mode": robot_mode, "feedback_age": round(age, 3), "health": health,
        },
        "q_actual": p["q_actual"],
        "q_target": p["q_target"],
        "tcp_speed_actual": p["tcp_speed_actual"],
        "tool_vector_target": p["tool_vector_target"],
        "speed_scaling": p["speed_scaling"],
        "running_status": p["running_status"],
        "error_status": p["error_status"],
        "enable_status": p["enable_status"],
        "current_command_id": p["current_command_id"],
    }


def build_health(
    uptime_s: float,
    feedback_health: str,
    request_count: int,
    error_count: int,
    last_error: str = "",
) -> dict[str, Any]:
    """Build /api/v1/health response data (免认证)."""
    status = "ok" if feedback_health != "disconnected" else "degraded"
    return {
        "status": status,
        "uptime_s": round(uptime_s, 1),
        "feedback_health": feedback_health,
        "request_count": request_count,
        "error_count": error_count,
        "last_error": last_error,
    }


def build_production_status(health_path: str, stale_threshold_s: float = 3.0) -> dict[str, Any]:
    """Build /api/v1/production/status response data by reading runtime_health.json.

    Handles three cases:
    - File missing: runtime_state="offline"
    - File corrupt (JSON parse error): runtime_state="unknown"
    - File stale (timestamp older than stale_threshold_s): runtime_state="offline"
    - File fresh: extract runtime_state, production_state, flow, robot, modbus
    """
    if not os.path.exists(health_path):
        return {"runtime_state": "offline", "health_age_s": None}

    try:
        with open(health_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("读取 runtime_health.json 失败: %s", e)
        return {"runtime_state": "unknown", "health_age_s": None, "error": str(e)}

    timestamp = payload.get("timestamp")
    if not isinstance(timestamp, (int, float)):
        return {"runtime_state": "unknown", "health_age_s": None}

    age_s = time.time() - float(timestamp)
    if age_s > stale_threshold_s:
        return {"runtime_state": "offline", "health_age_s": round(age_s, 1)}

    runtime = payload.get("runtime", {}) or {}
    robot = payload.get("robot", {}) or {}
    modbus = payload.get("modbus", {}) or {}
    flow = payload.get("flow", {}) or {}
    production = payload.get("production", {}) or {}

    return {
        "runtime_state": runtime.get("state", "unknown"),
        "maintenance": runtime.get("maintenance", False),
        "robot_connected": bool(robot.get("connected", False)),
        "robot_enabled": bool(robot.get("enabled", False)),
        "modbus_running": bool(modbus.get("is_running", False)),
        "production_state": production.get("state", "unknown"),
        "current_flow": flow.get("module_name", ""),
        "module_index": flow.get("module_index"),
        "failure_latched": bool(flow.get("failure_latched", False)),
        "health_age_s": round(age_s, 1),
    }
