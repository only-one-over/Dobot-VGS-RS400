#!/usr/bin/env python3
"""Out-of-process watchdog for the unattended Dobot runtime."""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import subprocess
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Callable, Optional

from dobot_move.config_manager import get_config, get_robot_ip
from dobot_move.runtime_resilience import (
    RestartWindow,
    RuntimeState,
    SingleInstanceLock,
    atomic_write_json,
)

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parent


def setup_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not any(isinstance(handler, RotatingFileHandler) for handler in root.handlers):
        handler = RotatingFileHandler(
            log_dir / "runtime_watchdog.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
            )
        )
        root.addHandler(handler)


class RuntimeWatchdog:
    def __init__(
        self,
        health_path: Path,
        task_name: str = "DobotRuntimeAgent",
        stale_after_s: float = 15.0,
        stop_timeout_s: float = 2.0,
        restart_window_s: float = 600.0,
        restart_limit: int = 3,
        state_dir: Optional[Path] = None,
        stop_robot: Optional[Callable[[], None]] = None,
        terminate_process: Optional[Callable[[int], None]] = None,
        restart_task: Optional[Callable[[], None]] = None,
    ):
        self.health_path = Path(health_path)
        self.task_name = task_name
        self.stale_after_s = float(stale_after_s)
        self.stop_timeout_s = float(stop_timeout_s)
        state_dir = Path(state_dir or self.health_path.parent)
        self.restart_window = RestartWindow(
            state_dir / "runtime_watchdog_restarts.json",
            window_s=restart_window_s,
            max_restarts=restart_limit,
        )
        self.lockout_path = state_dir / "runtime_watchdog_lockout.json"
        self._stop_robot_callback = stop_robot or self._stop_robot
        self._terminate_process_callback = terminate_process or self._terminate_process
        self._restart_task_callback = restart_task or self._restart_task

    def _read_health(self) -> dict[str, Any]:
        try:
            with open(self.health_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _flow_was_active(health: dict[str, Any]) -> bool:
        runtime_state = str((health.get("runtime") or {}).get("state", ""))
        flow_running = bool((health.get("flow") or {}).get("running", False))
        return flow_running or runtime_state in {
            RuntimeState.RUNNING.value,
            RuntimeState.WAITING_DELAY.value,
        }

    def _stop_robot(self) -> None:
        from dobot_move.dobot_api import DobotApiDashboard

        dashboard = None
        try:
            dashboard = DobotApiDashboard(get_robot_ip(), 29999)
            socket_dobot = getattr(dashboard, "socket_dobot", None)
            if socket_dobot not in (None, 0) and hasattr(socket_dobot, "settimeout"):
                socket_dobot.settimeout(self.stop_timeout_s)
            dashboard.Stop()
            logger.warning("watchdog sent independent Stop()")
        finally:
            if dashboard is not None:
                try:
                    dashboard.close()
                except Exception:
                    pass

    def _terminate_process(self, pid: int) -> None:
        if pid <= 0 or pid == os.getpid():
            return
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return
        deadline = time.monotonic() + self.stop_timeout_s
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except OSError:
                return
            time.sleep(0.1)
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                check=False,
                capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        else:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass

    def _restart_task(self) -> None:
        subprocess.run(
            ["schtasks", "/Run", "/TN", self.task_name],
            check=False,
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    def check_once(self, now: Optional[float] = None) -> str:
        now = time.time() if now is None else float(now)
        if self.lockout_path.exists():
            return "locked_out"

        health = self._read_health()
        heartbeat = float(health.get("timestamp", 0.0) or 0.0)
        if heartbeat > 0 and now - heartbeat <= self.stale_after_s:
            return "healthy"

        if not self.restart_window.allow_and_record(now):
            atomic_write_json(
                self.lockout_path,
                {
                    "locked_at": now,
                    "reason": "restart limit exceeded",
                    "task_name": self.task_name,
                },
                durable=True,
            )
            logger.critical("watchdog restart limit exceeded; manual recovery required")
            return "locked_out"

        if self._flow_was_active(health):
            try:
                self._stop_robot_callback()
            except Exception:
                logger.exception("watchdog independent Stop() failed")

        pid = int((health.get("process") or {}).get("pid", 0) or 0)
        if pid > 0:
            try:
                self._terminate_process_callback(pid)
            except Exception:
                logger.exception("watchdog failed to terminate runtime pid=%d", pid)
        self._restart_task_callback()
        logger.warning("watchdog restarted task %s", self.task_name)
        return "restarted"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Watch the Dobot runtime health file.")
    parser.add_argument("--health-path", type=Path, default=None)
    parser.add_argument("--task-name", default="DobotRuntimeAgent")
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--stale-after", type=float, default=15.0)
    parser.add_argument("--stop-timeout", type=float, default=2.0)
    parser.add_argument("--restart-window", type=float, default=600.0)
    parser.add_argument("--restart-limit", type=int, default=3)
    parser.add_argument("--log-dir", type=Path, default=PROJECT_ROOT / "logs")
    parser.add_argument("--lock-path", type=Path, default=PROJECT_ROOT / "runtime_watchdog.lock")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    setup_logging(args.log_dir)
    instance_lock = SingleInstanceLock(args.lock_path)
    if not instance_lock.acquire():
        logger.error("another runtime watchdog instance is already running")
        return 2
    stop_event = threading.Event()

    def request_stop(signum, _frame):
        logger.info("watchdog stop signal received: %s", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    config = get_config()
    runtime_config = config.get("runtime", {}) if isinstance(config.get("runtime"), dict) else {}
    health_path = args.health_path or Path(
        runtime_config.get("health_path", PROJECT_ROOT / "runtime_health.json")
    )
    if not health_path.is_absolute():
        health_path = PROJECT_ROOT / health_path
    watchdog = RuntimeWatchdog(
        health_path,
        task_name=args.task_name,
        stale_after_s=args.stale_after,
        stop_timeout_s=args.stop_timeout,
        restart_window_s=args.restart_window,
        restart_limit=args.restart_limit,
    )
    try:
        stop_event.wait(max(30.0, args.stale_after))
        while not stop_event.is_set():
            watchdog.check_once()
            stop_event.wait(max(0.5, args.interval))
        return 0
    finally:
        instance_lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
