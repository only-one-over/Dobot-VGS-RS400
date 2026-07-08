"""Side-effect-free readiness checks used before starting a flow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..flow.flow_library import required_camera_types
from .flow_result import FailureKind


@dataclass(frozen=True)
class FlowReadinessResult:
    ok: bool
    missing_devices: tuple[str, ...]
    reasons: tuple[str, ...]

    @property
    def message(self) -> str:
        return "；".join(self.reasons) if self.reasons else "设备已就绪"

    @property
    def primary_failure_kind(self) -> FailureKind:
        """Infer the primary FailureKind from missing_devices.

        Priority: robot > camera > flow. When both robot and camera are
        missing, robot takes precedence (it's the more fundamental
        prerequisite).
        """
        if "robot" in self.missing_devices:
            return FailureKind.ROBOT
        if "D435i" in self.missing_devices or "D405" in self.missing_devices:
            return FailureKind.CAMERA
        return FailureKind.FLOW


def check_flow_readiness(
    controller,
    vision_d435i,
    vision_d405,
    modules: list[dict[str, Any]],
    *,
    feedback_max_age: float = 0.5,
) -> FlowReadinessResult:
    """Inspect cached state only; never query hardware or capture a frame."""
    missing: list[str] = []
    reasons: list[str] = []

    if not getattr(controller, "is_connected", False) or getattr(
        controller, "dashboard", None
    ) is None:
        missing.append("robot")
        reasons.append("机器人未连接")
    else:
        try:
            feedback = controller.get_feedback_health(max_age=feedback_max_age)
            feedback_state = feedback.get("health")
        except Exception as exc:
            feedback_state = "error"
            reasons.append(f"机器人反馈状态读取失败: {exc}")
        if feedback_state != "ok":
            if "robot" not in missing:
                missing.append("robot")
            if not reasons or not reasons[-1].startswith("机器人反馈状态读取失败"):
                reasons.append(f"机器人反馈不健康: {feedback_state}")

    cameras = {
        "D435i": vision_d435i,
        "D405": vision_d405,
    }
    for camera_type in sorted(required_camera_types(modules)):
        vision = cameras[camera_type]
        if vision is None:
            missing.append(camera_type)
            reasons.append(f"{camera_type} 未连接")
        elif not getattr(vision, "is_available", True):
            missing.append(camera_type)
            reasons.append(f"{camera_type} 当前不可用")

    return FlowReadinessResult(
        ok=not missing,
        missing_devices=tuple(missing),
        reasons=tuple(reasons),
    )
