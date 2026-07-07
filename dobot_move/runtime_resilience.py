"""Reliability primitives shared by the unattended runtime and watchdog."""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
import uuid
from enum import Enum
from pathlib import Path
from typing import Any, Optional


class RuntimeState(str, Enum):
    STARTING = "STARTING"
    READY = "READY"
    RUNNING = "RUNNING"
    WAITING_DELAY = "WAITING_DELAY"
    MAINTENANCE_REQUESTED = "MAINTENANCE_REQUESTED"
    MAINTENANCE = "MAINTENANCE"
    DEGRADED = "DEGRADED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    STOPPING = "STOPPING"


ACTIVE_STATES = {RuntimeState.RUNNING.value, RuntimeState.WAITING_DELAY.value}


def atomic_write_json(
    path: Path,
    payload: dict[str, Any],
    durable: bool = False,
) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.flush()
        if durable:
            os.fsync(handle.fileno())
    os.replace(tmp_path, path)


class RuntimeStateStore:
    """Persist diagnostic runtime state without ever resuming a saved flow."""

    SCHEMA_VERSION = 1

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._data: dict[str, Any] = {}

    def _load_unlocked(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else {}
        except Exception:
            corrupt_path = self.path.with_name(
                f"{self.path.name}.corrupt.{int(time.time())}"
            )
            try:
                os.replace(self.path, corrupt_path)
            except OSError:
                pass
            return {"corrupt_state_file": str(corrupt_path)}

    def begin_boot(self) -> bool:
        """Start a boot record and return whether operator recovery is required."""
        with self._lock:
            previous = self._load_unlocked()
            previous_state = str(previous.get("state", ""))
            recovery_required = bool(previous) and (
                not bool(previous.get("clean_shutdown", False))
                or previous_state in ACTIVE_STATES
                or bool(previous.get("corrupt_state_file"))
            )
            now = time.time()
            self._data = {
                "schema_version": self.SCHEMA_VERSION,
                "boot_id": uuid.uuid4().hex,
                "pid": os.getpid(),
                "started_at": now,
                "updated_at": now,
                "clean_shutdown": False,
                "state": (
                    RuntimeState.RECOVERY_REQUIRED.value
                    if recovery_required
                    else RuntimeState.STARTING.value
                ),
                "flow_id": None,
                "module_index": None,
                "module_name": None,
                "last_error": "",
                "previous_boot_id": previous.get("boot_id"),
                "previous_state": previous_state or None,
            }
            atomic_write_json(self.path, self._data, durable=True)
            return recovery_required

    def transition(self, state: RuntimeState | str, **updates: Any) -> dict[str, Any]:
        with self._lock:
            state_value = state.value if isinstance(state, RuntimeState) else str(state)
            changed = self._data.get("state") != state_value or any(
                self._data.get(key) != value for key, value in updates.items()
            )
            if not changed:
                return dict(self._data)
            self._data.update(updates)
            self._data["state"] = state_value
            self._data["updated_at"] = time.time()
            atomic_write_json(self.path, self._data, durable=True)
            return dict(self._data)

    def mark_clean_shutdown(self) -> dict[str, Any]:
        with self._lock:
            self._data["clean_shutdown"] = True
            self._data["state"] = RuntimeState.STOPPING.value
            self._data["updated_at"] = time.time()
            atomic_write_json(self.path, self._data, durable=True)
            return dict(self._data)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._data)


class SingleInstanceLock:
    """Cross-platform non-blocking process lock backed by a small lock file."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._handle = None

    def acquire(self) -> bool:
        if self._handle is not None:
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+", encoding="ascii")
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, IOError):
            handle.close()
            return False
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        self._handle = handle
        return True

    def release(self) -> None:
        handle = self._handle
        self._handle = None
        if handle is None:
            return
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except (OSError, IOError):
            pass
        handle.close()

    def __enter__(self):
        if not self.acquire():
            raise RuntimeError(f"another runtime instance owns {self.path}")
        return self

    def __exit__(self, exc_type, exc, tb):
        self.release()


class RestartWindow:
    """Persistent rolling-window restart limiter used by the external watchdog."""

    def __init__(self, path: Path, window_s: float = 600.0, max_restarts: int = 3):
        self.path = Path(path)
        self.window_s = float(window_s)
        self.max_restarts = int(max_restarts)

    def _recent(self, now: float) -> list[float]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            values = data.get("restart_times", []) if isinstance(data, dict) else []
        except Exception:
            values = []
        return [
            float(value)
            for value in values
            if now - float(value) <= self.window_s
        ]

    def allow_and_record(self, now: Optional[float] = None) -> bool:
        now = time.time() if now is None else float(now)
        recent = self._recent(now)
        if len(recent) >= self.max_restarts:
            return False
        recent.append(now)
        atomic_write_json(
            self.path,
            {"restart_times": recent, "updated_at": now},
            durable=True,
        )
        return True


def get_process_metrics(path: Path) -> dict[str, Any]:
    disk = shutil.disk_usage(Path(path).resolve().parent)
    rss_mb = None
    try:
        import psutil  # Optional; no runtime dependency is required.

        rss_mb = psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
    except Exception:
        try:
            import resource

            rss = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
            rss_mb = rss / 1024.0
        except Exception:
            pass
    return {
        "pid": os.getpid(),
        "thread_count": threading.active_count(),
        "rss_mb": round(rss_mb, 2) if rss_mb is not None else None,
        "disk_free_mb": round(disk.free / (1024 * 1024), 1),
    }


def module_timeout_seconds(module: dict[str, Any]) -> float:
    """Conservative per-module deadline for hang detection."""
    module_type = str(module.get("type", ""))
    params = module.get("params") or {}
    if module_type == "delay":
        return max(5.0, float(params.get("duration_s", 1.0)) + 5.0)
    if module_type == "camera":
        return 30.0
    if module_type == "visual_servo":
        period = float(params.get("servo_period", 0.06))
        iterations = int(params.get("max_iterations", 60))
        return max(20.0, period * iterations * 3.0 + 10.0)
    if module_type == "relative_path":
        segments = len(params.get("segments") or [])
        return max(60.0, segments * 30.0)
    if module_type in {"move", "relative_move", "joint_move", "arc_motion"}:
        return 90.0
    return 60.0


def flow_timeout_seconds(modules: list[dict[str, Any]]) -> float:
    total = sum(module_timeout_seconds(module) for module in modules)
    return max(60.0, total * 1.2 + 30.0)
