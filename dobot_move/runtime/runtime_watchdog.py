#!/usr/bin/env python3
"""Out-of-process watchdog for the unattended Dobot runtime."""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import signal
import subprocess
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Callable, Optional

from ..config.config_manager import get_config, get_robot_ip
from ..runtime.runtime_resilience import (
    RestartWindow,
    RuntimeState,
    SingleInstanceLock,
    atomic_write_json,
)

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SERVICE_STOPPED = "STOPPED"
SERVICE_START_PENDING = "START_PENDING"
SERVICE_STOP_PENDING = "STOP_PENDING"
SERVICE_RUNNING = "RUNNING"
_SERVICE_STATES = {
    1: SERVICE_STOPPED,
    2: SERVICE_START_PENDING,
    3: SERVICE_STOP_PENDING,
    4: SERVICE_RUNNING,
}


class WindowsServiceController:
    """Minimal SCM adapter using the built-in sc.exe command."""

    def __init__(self, service_name: str):
        service_name = str(service_name).strip()
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", service_name):
            raise ValueError("invalid Windows service name")
        self.service_name = service_name

    def _run(self, *arguments, timeout=10.0):
        return subprocess.run(
            ["sc.exe", *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    def query_state(self) -> str:
        result = self._run("query", self.service_name)
        output = f"{result.stdout}\n{result.stderr}"
        match = re.search(
            r"(?:STATE|状态)\s*:\s*(\d+)",
            output,
            flags=re.IGNORECASE,
        )
        if result.returncode != 0 or match is None:
            return "UNKNOWN"
        return _SERVICE_STATES.get(int(match.group(1)), "UNKNOWN")

    def wait_for_state(self, expected: str, timeout_s: float) -> bool:
        deadline = time.monotonic() + max(0.1, float(timeout_s))
        while time.monotonic() < deadline:
            if self.query_state() == expected:
                return True
            time.sleep(0.25)
        return self.query_state() == expected

    def restart(
        self,
        *,
        stop_timeout_s: float,
        terminate_pid: Callable[[int], None],
        pid: int,
    ) -> None:
        state = self.query_state()
        if state != SERVICE_STOPPED:
            self._run("stop", self.service_name)
            if not self.wait_for_state(SERVICE_STOPPED, stop_timeout_s):
                terminate_pid(pid)
                if not self.wait_for_state(SERVICE_STOPPED, 5.0):
                    raise RuntimeError(
                        f"service did not stop: {self.service_name}"
                    )
        result = self._run("start", self.service_name)
        if result.returncode != 0:
            raise RuntimeError(
                f"failed to start service {self.service_name}: "
                f"{result.stderr or result.stdout}"
            )
        if not self.wait_for_state(SERVICE_RUNNING, 15.0):
            raise RuntimeError(
                f"service did not reach RUNNING: {self.service_name}"
            )


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
        restart_mode: str = "task",
        service_name: str = "DobotRuntimeService",
        service_stop_timeout_s: float = 40.0,
        query_service_state: Optional[Callable[[], str]] = None,
        restart_service: Optional[Callable[[int], None]] = None,
    ):
        self.health_path = Path(health_path)
        self.task_name = task_name
        self.stale_after_s = float(stale_after_s)
        self.stop_timeout_s = float(stop_timeout_s)
        self.restart_mode = str(restart_mode).strip().lower()
        if self.restart_mode not in {"task", "service"}:
            raise ValueError("restart_mode must be task or service")
        self.service_name = str(service_name)
        self.service_stop_timeout_s = max(
            self.stop_timeout_s,
            float(service_stop_timeout_s),
        )
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
        self._service_controller = (
            WindowsServiceController(self.service_name)
            if self.restart_mode == "service"
            else None
        )
        self._query_service_state_callback = (
            query_service_state
            or (
                self._service_controller.query_state
                if self._service_controller is not None
                else lambda: "UNKNOWN"
            )
        )
        self._restart_service_callback = (
            restart_service or self._restart_service
        )

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
        from ..robot.dobot_api import DobotApiDashboard

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

    def _restart_service(self, pid: int) -> None:
        self._service_controller.restart(
            stop_timeout_s=self.service_stop_timeout_s,
            terminate_pid=self._terminate_process_callback,
            pid=pid,
        )

    def check_once(self, now: Optional[float] = None) -> str:
        now = time.time() if now is None else float(now)
        if self.lockout_path.exists():
            return "locked_out"

        health = self._read_health()
        if self.restart_mode == "service":
            service_state = self._query_service_state_callback()
            stop_marker_value = (health.get("runtime") or {}).get(
                "stop_marker_path"
            )
            stop_marker_exists = bool(
                stop_marker_value
                and Path(str(stop_marker_value)).exists()
            )
            if (
                service_state == SERVICE_STOPPED
                and stop_marker_exists
            ):
                return "intentionally_stopped"
            if service_state in {
                SERVICE_START_PENDING,
                SERVICE_STOP_PENDING,
            }:
                return "service_transition"
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
        if self.restart_mode == "task" and pid > 0:
            try:
                self._terminate_process_callback(pid)
            except Exception:
                logger.exception("watchdog failed to terminate runtime pid=%d", pid)
        if self.restart_mode == "service":
            self._restart_service_callback(pid)
            logger.warning(
                "watchdog restarted service %s",
                self.service_name,
            )
        else:
            self._restart_task_callback()
            logger.warning("watchdog restarted task %s", self.task_name)
        return "restarted"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Watch the Dobot runtime health file.")
    parser.add_argument("--health-path", type=Path, default=None)
    parser.add_argument("--task-name", default="DobotRuntimeAgent")
    parser.add_argument(
        "--restart-mode",
        choices=("task", "service"),
        default="task",
    )
    parser.add_argument("--service-name", default="DobotRuntimeService")
    parser.add_argument("--service-stop-timeout", type=float, default=40.0)
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--stale-after", type=float, default=15.0)
    parser.add_argument("--stop-timeout", type=float, default=2.0)
    parser.add_argument("--restart-window", type=float, default=600.0)
    parser.add_argument("--restart-limit", type=int, default=3)
    parser.add_argument("--log-dir", type=Path, default=PROJECT_ROOT / "user_data" / "logs")
    parser.add_argument("--lock-path", type=Path, default=PROJECT_ROOT / "user_data" / "runtime_watchdog.lock")
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
        runtime_config.get("health_path", PROJECT_ROOT / "user_data" / "runtime_health.json")
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
        restart_mode=args.restart_mode,
        service_name=args.service_name,
        service_stop_timeout_s=args.service_stop_timeout,
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
