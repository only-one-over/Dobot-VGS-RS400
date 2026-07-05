"""Shared startup device readiness and fault-latching rules."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Iterable, Mapping


@dataclass
class StartupConnectionState:
    timeout_s: float = 5.0
    required_cameras: set[str] = field(default_factory=set)
    started_at: float | None = None
    deadline_at: float | None = None
    robot_connected: bool = False
    camera_connected: dict[str, bool] = field(default_factory=dict)

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

    def snapshot(self):
        with self._lock:
            now = time.monotonic()
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
                "deadline_elapsed": bool(
                    self.deadline_at is not None and now >= self.deadline_at
                ),
                "timeout_s": float(self.timeout_s),
                "robot_connected": self.robot_connected,
                "required_cameras": sorted(self.required_cameras),
                "camera_connected": dict(self.camera_connected),
                "missing_devices": missing,
                "fault_latched": False,
                "fault_code": None,
            }
