"""Shared startup device readiness and fault-latching rules."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Iterable, Mapping

STATUS_ROBOT_ERR = 111
STATUS_CAMERA_ERR = 112


def connection_error_code(
    robot_connected: bool,
    required_cameras: Iterable[str],
    camera_connected: Mapping[str, bool],
):
    """Return the startup error code, prioritizing robot failures."""
    if not robot_connected:
        return STATUS_ROBOT_ERR
    if any(not camera_connected.get(camera_type, False) for camera_type in required_cameras):
        return STATUS_CAMERA_ERR
    return None


@dataclass
class StartupConnectionState:
    timeout_s: float = 5.0
    required_cameras: set[str] = field(default_factory=set)
    started_at: float | None = None
    deadline_at: float | None = None
    robot_connected: bool = False
    camera_connected: dict[str, bool] = field(default_factory=dict)
    fault_code: int | None = None

    def __post_init__(self):
        self._lock = threading.RLock()

    def begin(self, required_cameras: Iterable[str], now: float | None = None):
        now = time.monotonic() if now is None else float(now)
        with self._lock:
            self.required_cameras = set(required_cameras)
            self.started_at = now
            self.deadline_at = now + max(0.1, float(self.timeout_s))
            self.camera_connected = {
                camera_type: self.camera_connected.get(camera_type, False)
                for camera_type in self.required_cameras
            }

    def update(
        self,
        *,
        robot_connected: bool,
        camera_connected: Mapping[str, bool],
    ):
        with self._lock:
            self.robot_connected = bool(robot_connected)
            for camera_type in self.required_cameras:
                self.camera_connected[camera_type] = bool(camera_connected.get(camera_type, False))

    def current_error(self):
        with self._lock:
            return connection_error_code(
                self.robot_connected,
                self.required_cameras,
                self.camera_connected,
            )

    def latch_if_due(self, now: float | None = None):
        now = time.monotonic() if now is None else float(now)
        with self._lock:
            if self.deadline_at is None or now < self.deadline_at:
                return None
            if self.fault_code is not None:
                return self.fault_code
            error_code = self.current_error()
            if error_code is not None:
                self.fault_code = error_code
            return error_code

    def recheck_fault(self):
        """Refresh or clear a previously latched fault from current device state."""
        with self._lock:
            self.fault_code = self.current_error()
            return self.fault_code

    def snapshot(self):
        with self._lock:
            missing = []
            if not self.robot_connected:
                missing.append("robot")
            missing.extend(
                camera_type
                for camera_type in sorted(self.required_cameras)
                if not self.camera_connected.get(camera_type, False)
            )
            return {
                "started_at_monotonic": self.started_at,
                "deadline_at_monotonic": self.deadline_at,
                "timeout_s": float(self.timeout_s),
                "robot_connected": self.robot_connected,
                "required_cameras": sorted(self.required_cameras),
                "camera_connected": dict(self.camera_connected),
                "missing_devices": missing,
                "fault_latched": self.fault_code is not None,
                "fault_code": self.fault_code,
            }
