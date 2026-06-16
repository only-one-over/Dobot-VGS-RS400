#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Headless runtime agent for unattended Modbus-driven robot operation."""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Optional

from dobot_move.config_manager import (
    get_config,
    get_grasp_flow_file,
    get_modbus_port,
    get_modbus_slave_id,
    get_performance_config,
    get_robot_ip,
)
from dobot_move.modbus_server import STATUS_ROBOT_ERR
from dobot_move.robot_controller import DobotController

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_HEALTH_PATH = PROJECT_ROOT / "runtime_health.json"
DEFAULT_LOG_DIR = PROJECT_ROOT / "logs"


class RobotConnectionState:
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    DEGRADED = "DEGRADED"


def setup_runtime_logging(log_dir: Path = DEFAULT_LOG_DIR, level: int = logging.INFO) -> Path:
    """Configure stdout plus rotating file logging for the runtime process."""
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "runtime.log"

    root = logging.getLogger()
    root.setLevel(level)

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    has_file = any(isinstance(handler, RotatingFileHandler) for handler in root.handlers)
    if not has_file:
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(level)
        root.addHandler(file_handler)

    has_stream = any(
        isinstance(handler, logging.StreamHandler)
        and not isinstance(handler, logging.FileHandler)
        for handler in root.handlers
    )
    if not has_stream:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        stream_handler.setLevel(level)
        root.addHandler(stream_handler)

    return log_path


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


@dataclass
class RobotConnectionSupervisor:
    """Keep Dobot Dashboard/feedback connections alive without touching Modbus."""

    controller: DobotController
    reconnect_delays: tuple[float, ...] = (1.0, 2.0, 5.0, 10.0, 30.0)
    feedback_max_age: float = 0.5
    state: str = RobotConnectionState.DISCONNECTED
    next_attempt_at: float = 0.0
    last_error: str = ""
    last_transition_time: float = field(default_factory=time.time)
    _delay_index: int = 0

    def _set_state(self, state: str) -> None:
        if self.state != state:
            logger.info("robot supervisor state: %s -> %s", self.state, state)
            self.state = state
            self.last_transition_time = time.time()

    def _schedule_reconnect(self, now: float, reason: str) -> None:
        delay = self.reconnect_delays[min(self._delay_index, len(self.reconnect_delays) - 1)]
        self._delay_index = min(self._delay_index + 1, len(self.reconnect_delays) - 1)
        self.next_attempt_at = now + delay
        self.last_error = reason
        self._set_state(RobotConnectionState.DISCONNECTED)
        logger.warning("robot reconnect scheduled in %.1fs: %s", delay, reason)

    def close_robot_connection(self) -> None:
        """Close robot sockets but keep Modbus service alive."""
        try:
            self.controller.stop_feedback()
        except Exception as e:
            logger.warning("stop_feedback during reconnect failed: %s", e)
        try:
            if self.controller.dashboard:
                self.controller.dashboard.close()
        except Exception as e:
            logger.warning("dashboard close during reconnect failed: %s", e)
        self.controller.dashboard = None
        self.controller.is_connected = False
        self.controller.is_enabled = False
        self.controller._last_speed_factor = None

    def _restart_feedback_if_thread_dead(self) -> bool:
        thread = getattr(self.controller, "feed_thread", None)
        if thread is None or thread.is_alive():
            return False
        logger.warning("feedback thread stopped; restarting feedback connection")
        try:
            self.controller.stop_feedback()
            self.controller.start_feedback()
            self.last_error = "feedback thread restarted"
            self._set_state(RobotConnectionState.DEGRADED)
            return True
        except Exception as e:
            self.last_error = f"feedback restart failed: {e}"
            logger.warning(self.last_error)
            self.close_robot_connection()
            return False

    def step(self, now: Optional[float] = None) -> str:
        now = time.time() if now is None else now
        try:
            if not self.controller.is_connected:
                if now < self.next_attempt_at:
                    return self.state

                self._set_state(RobotConnectionState.CONNECTING)
                if self.controller.connect():
                    self._delay_index = 0
                    self.next_attempt_at = 0.0
                    self.last_error = ""
                    self._set_state(RobotConnectionState.CONNECTED)
                else:
                    self.close_robot_connection()
                    self._schedule_reconnect(now, self.controller.last_error or "connect failed")
                return self.state

            self._restart_feedback_if_thread_dead()
            health = self.controller.get_feedback_health(max_age=self.feedback_max_age)
            health_state = health.get("health")
            if health_state == "disconnected":
                self.close_robot_connection()
                self._schedule_reconnect(now, "feedback disconnected")
            elif health_state == "stale":
                self.last_error = "feedback stale"
                self._set_state(RobotConnectionState.DEGRADED)
            else:
                self.last_error = ""
                self._set_state(RobotConnectionState.CONNECTED)
            return self.state
        except Exception as e:
            logger.exception("robot supervisor step failed")
            self.close_robot_connection()
            self._schedule_reconnect(now, str(e))
            return self.state


class RuntimeProgramRunner:
    """Run the saved motion flow in a background thread for Modbus command 3."""

    def __init__(self, controller: DobotController):
        self.controller = controller
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

    def __call__(self) -> bool:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                logger.warning("runtime flow runner rejected: previous flow still running")
                return False
            self._thread = threading.Thread(target=self._run_once, name="RuntimeFlowRunner", daemon=True)
            self._thread.start()
            return True

    def _load_modules(self) -> list[dict[str, Any]]:
        path = get_grasp_flow_file()
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ValueError(f"grasp flow file must contain a list: {path}")
        return data

    def _run_once(self) -> None:
        success = False
        try:
            from dobot_move.workers import FlowThread, validate_grasp_flow_modules

            modules = self._load_modules()
            errors = validate_grasp_flow_modules(modules)
            if errors:
                message = "; ".join(errors)
                logger.error("runtime flow validation failed: %s", message)
                self.controller.record_alarm("Runtime流程", "VALIDATION_FAILED", "故障", message)
                return

            finished: list[bool] = []
            flow = FlowThread(self.controller, None, None, modules, [False])
            flow.flow_log.connect(lambda msg: logger.info("runtime flow: %s", msg))
            flow.flow_finished.connect(lambda ok: finished.append(bool(ok)))
            flow.run()
            success = bool(finished[-1]) if finished else False
        except Exception as e:
            logger.exception("runtime flow runner failed")
            self.controller.record_alarm("Runtime流程", "EXCEPTION", "故障", "后台流程执行异常", raw=e)
        finally:
            self.controller.mark_modbus_program_finished(success)


class DobotRuntimeAgent:
    """Unattended production runtime: Modbus server + robot reconnect watchdog."""

    def __init__(
        self,
        controller: Optional[DobotController] = None,
        health_path: Path = DEFAULT_HEALTH_PATH,
        startup_delay: float = 10.0,
        poll_interval: float = 1.0,
    ):
        config = get_config()
        performance = get_performance_config()
        runtime_config = config.get("runtime", {}) if isinstance(config.get("runtime"), dict) else {}

        self.controller = controller or DobotController(get_robot_ip())
        self.health_path = Path(runtime_config.get("health_path", str(health_path)))
        self.startup_delay = float(runtime_config.get("startup_delay", startup_delay))
        self.poll_interval = float(runtime_config.get("poll_interval", poll_interval))
        self.modbus_port = int(runtime_config.get("modbus_port", get_modbus_port()))
        self.modbus_slave_id = int(runtime_config.get("modbus_slave_id", get_modbus_slave_id()))
        self.supervisor = RobotConnectionSupervisor(
            self.controller,
            feedback_max_age=float(performance.get("feedback_stale_warn_age", 0.5)),
        )
        self.program_runner = RuntimeProgramRunner(self.controller)
        self.stop_event = threading.Event()
        self.last_error = ""

    def ensure_modbus_running(self) -> bool:
        try:
            stats = self.controller.get_modbus_stats()
            if stats.get("is_running"):
                return True
        except Exception:
            pass

        logger.info("starting Modbus TCP server on port %s slave_id=%s", self.modbus_port, self.modbus_slave_id)
        ok = bool(self.controller.start_modbus(port=self.modbus_port, slave_id=self.modbus_slave_id))
        if not ok:
            self.last_error = "Modbus server start failed"
            logger.error(self.last_error)
        return ok

    def build_health_payload(self) -> dict[str, Any]:
        try:
            feedback = self.controller.get_feedback_health()
        except Exception as e:
            feedback = {"health": "error", "error": str(e)}

        try:
            modbus_stats = self.controller.get_modbus_stats()
        except Exception as e:
            modbus_stats = {"is_running": False, "error": str(e)}

        return {
            "timestamp": time.time(),
            "timestamp_iso": datetime.now().isoformat(timespec="seconds"),
            "runtime": {
                "running": not self.stop_event.is_set(),
                "startup_delay": self.startup_delay,
                "poll_interval": self.poll_interval,
                "last_error": self.last_error or self.supervisor.last_error,
            },
            "robot": {
                "ip": self.controller.robot_ip,
                "supervisor_state": self.supervisor.state,
                "connected": bool(self.controller.is_connected),
                "enabled": bool(self.controller.is_enabled),
                "feedback": feedback,
                "last_error": self.controller.last_error,
            },
            "modbus": modbus_stats,
            "last_command": {
                "value": getattr(self.controller, "_last_modbus_command", None),
                "timestamp": getattr(self.controller, "_last_modbus_command_time", 0.0),
            },
        }

    def write_health(self) -> None:
        atomic_write_json(self.health_path, self.build_health_payload())

    def tick(self) -> None:
        if not self.ensure_modbus_running():
            if self.controller.modbus_server:
                self.controller._write_modbus_status(STATUS_ROBOT_ERR)
        self.supervisor.step()
        self.write_health()

    def run(self) -> None:
        self.controller.set_modbus_program_runner(self.program_runner)
        self.ensure_modbus_running()
        self.write_health()

        if self.startup_delay > 0:
            logger.info("runtime startup delay %.1fs for network/robot boot stabilization", self.startup_delay)
            self.stop_event.wait(self.startup_delay)

        while not self.stop_event.is_set():
            self.tick()
            self.stop_event.wait(self.poll_interval)

    def stop(self) -> None:
        self.stop_event.set()
        try:
            self.controller.stop_modbus()
        except Exception as e:
            logger.warning("stop_modbus during runtime shutdown failed: %s", e)
        self.supervisor.close_robot_connection()
        self.write_health()


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Dobot unattended runtime agent.")
    parser.add_argument("--startup-delay", type=float, default=None, help="Seconds to wait before robot reconnect loop starts.")
    parser.add_argument("--poll-interval", type=float, default=1.0, help="Runtime watchdog interval in seconds.")
    parser.add_argument("--health-path", type=Path, default=DEFAULT_HEALTH_PATH, help="Path to runtime health JSON.")
    parser.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR, help="Directory for runtime.log.")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    setup_runtime_logging(args.log_dir)

    agent = DobotRuntimeAgent(
        health_path=args.health_path,
        startup_delay=10.0 if args.startup_delay is None else args.startup_delay,
        poll_interval=args.poll_interval,
    )

    def _stop(signum, _frame):
        logger.info("runtime stop signal received: %s", signum)
        agent.stop()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    try:
        agent.run()
        return 0
    except Exception:
        logger.exception("runtime agent crashed")
        try:
            agent.write_health()
        except Exception:
            pass
        return 1
    finally:
        agent.stop()


if __name__ == "__main__":
    raise SystemExit(main())
