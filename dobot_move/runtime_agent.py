#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Headless runtime agent for unattended Modbus-driven robot operation."""

from __future__ import annotations

import argparse
import ipaddress
import json
import logging
import os
import random
import signal
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Optional

from .config_manager import (
    CONFIG_FILE,
    get_config,
    get_grasp_flow_file,
    get_modbus_port,
    get_modbus_slave_id,
    get_performance_config,
    get_robot_ip,
    get_runtime_config,
)
from .flow_library import FlowLibrary, required_camera_types
from .modbus_server import STATUS_CAMERA_ERR, STATUS_HOOK_ERR, STATUS_ROBOT_ERR
from .robot_controller import DobotController
from .runtime_resilience import (
    RuntimeState,
    RuntimeStateStore,
    SingleInstanceLock,
    atomic_write_json,
    flow_timeout_seconds,
    get_process_metrics,
    module_timeout_seconds,
)
from .startup_connection import StartupConnectionState

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_HEALTH_PATH = PROJECT_ROOT / "runtime_health.json"
DEFAULT_STATE_PATH = PROJECT_ROOT / "runtime_state.json"
DEFAULT_LOCK_PATH = PROJECT_ROOT / "runtime_agent.lock"
DEFAULT_LOG_DIR = PROJECT_ROOT / "logs"


class RobotConnectionState:
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    DEGRADED = "DEGRADED"


class RepeatedLogFilter(logging.Filter):
    """Throttle identical log templates while preserving periodic evidence."""

    def __init__(self, window_s=10.0, burst=5, repeat_every=100):
        super().__init__()
        self.window_s = float(window_s)
        self.burst = int(burst)
        self.repeat_every = int(repeat_every)
        self._lock = threading.Lock()
        self._entries = {}

    def filter(self, record):
        key = (record.name, record.levelno, str(record.msg))
        now = time.monotonic()
        with self._lock:
            started, count = self._entries.get(key, (now, 0))
            if now - started > self.window_s:
                started, count = now, 0
            count += 1
            self._entries[key] = (started, count)
            return count <= self.burst or count % self.repeat_every == 0


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
        file_handler.addFilter(RepeatedLogFilter())
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
        stream_handler.addFilter(RepeatedLogFilter())
        root.addHandler(stream_handler)

    return log_path


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
    stable_reset_seconds: float = 10.0
    reconnect_jitter_ratio: float = 0.0
    connected_since: float = 0.0
    _delay_index: int = 0
    _motion_abort_issued: bool = False
    _connect_thread: Optional[threading.Thread] = field(default=None, init=False, repr=False)
    _connect_result: Optional[tuple[bool, str]] = field(default=None, init=False, repr=False)
    _connect_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _shutting_down: bool = field(default=False, init=False, repr=False)

    def _set_state(self, state: str) -> None:
        if self.state != state:
            logger.info("robot supervisor state: %s -> %s", self.state, state)
            self.state = state
            self.last_transition_time = time.time()

    def _schedule_reconnect(self, now: float, reason: str) -> None:
        delay = self.reconnect_delays[min(self._delay_index, len(self.reconnect_delays) - 1)]
        if self.reconnect_jitter_ratio > 0:
            jitter = delay * self.reconnect_jitter_ratio
            delay = max(0.1, delay + random.uniform(-jitter, jitter))
        self._delay_index = min(self._delay_index + 1, len(self.reconnect_delays) - 1)
        self.next_attempt_at = now + delay
        self.last_error = reason
        self._set_state(RobotConnectionState.DISCONNECTED)
        logger.warning("robot reconnect scheduled in %.1fs: %s", delay, reason)

    def _abort_active_flow(self, reason: str) -> None:
        flow = getattr(self.controller, "_active_flow_thread", None)
        if flow is None or self._motion_abort_issued:
            return
        self._motion_abort_issued = True
        ctx = getattr(flow, "_ctx", None)
        if ctx is not None:
            ctx.stop_event.set()
        try:
            if self.controller.dashboard:
                self.controller.dashboard.Stop()
        except Exception:
            logger.exception("feedback failure Stop() failed")
        self.controller.record_alarm(
            "Runtime反馈",
            "FEEDBACK_DISCONNECTED",
            "故障",
            reason,
            "检查机器人网络和30004反馈连接，重新复位后再启动流程",
        )
        self.controller._write_modbus_status(STATUS_ROBOT_ERR)

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

    def _connect_worker(self) -> None:
        ok = False
        error = ""
        try:
            ok = bool(self.controller.connect())
            error = "" if ok else (self.controller.last_error or "connect failed")
        except Exception as exc:
            error = str(exc)
            logger.exception("robot background connect failed")
        if self._shutting_down and ok:
            self.close_robot_connection()
            ok = False
            error = "runtime stopping"
        with self._connect_lock:
            self._connect_result = (ok, error)

    def _consume_connect_result(self, now: float) -> bool:
        with self._connect_lock:
            result = self._connect_result
            self._connect_result = None
        if result is None:
            return False
        ok, error = result
        if ok and self.controller.is_connected:
            self.next_attempt_at = 0.0
            self.last_error = ""
            self.connected_since = now
            self._set_state(RobotConnectionState.CONNECTED)
        else:
            self.close_robot_connection()
            self._schedule_reconnect(now, error or "connect failed")
        return True

    def request_connect(self, now: Optional[float] = None) -> str:
        now = time.time() if now is None else now
        self._consume_connect_result(now)
        thread = self._connect_thread
        if thread is not None and thread.is_alive():
            self._set_state(RobotConnectionState.CONNECTING)
            return self.state
        if self.controller.is_connected or now < self.next_attempt_at or self._shutting_down:
            return self.state
        self._set_state(RobotConnectionState.CONNECTING)
        self._connect_thread = threading.Thread(
            target=self._connect_worker,
            name="RuntimeRobotConnect",
            daemon=True,
        )
        self._connect_thread.start()
        return self.state

    def step(self, now: Optional[float] = None) -> str:
        now = time.time() if now is None else now
        try:
            if not self.controller.is_connected:
                return self.request_connect(now)

            self._restart_feedback_if_thread_dead()
            health = self.controller.get_feedback_health(max_age=self.feedback_max_age)
            health_state = health.get("health")
            if health_state == "disconnected":
                self._abort_active_flow("流程运行期间机器人反馈断流，已先停止运动")
                self.close_robot_connection()
                self._schedule_reconnect(now, "feedback disconnected")
            elif health_state == "stale":
                self.last_error = "feedback stale"
                self._set_state(RobotConnectionState.DEGRADED)
            else:
                self.last_error = ""
                self._set_state(RobotConnectionState.CONNECTED)
                if (
                    self.connected_since > 0
                    and now - self.connected_since >= self.stable_reset_seconds
                ):
                    self._delay_index = 0
                if getattr(self.controller, "_active_flow_thread", None) is None:
                    self._motion_abort_issued = False
            return self.state
        except Exception as e:
            logger.exception("robot supervisor step failed")
            self.close_robot_connection()
            self._schedule_reconnect(now, str(e))
            return self.state

    def shutdown(self) -> None:
        self._shutting_down = True
        self.close_robot_connection()


class RuntimeProgramRunner:
    """Run the saved motion flow in a background thread for Modbus command 3."""

    def __init__(
        self,
        controller: DobotController,
        state_store: Optional[RuntimeStateStore] = None,
        camera_preflight_attempts: int = 3,
    ):
        self.controller = controller
        self.state_store = state_store
        self.camera_preflight_attempts = max(1, int(camera_preflight_attempts))
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self.vision_d435i = None
        self.vision_d405 = None
        self._camera_locks = {
            "D435i": threading.Lock(),
            "D405": threading.Lock(),
        }
        self._camera_serials: Optional[dict[str, str]] = None
        self.current_flow_id: Optional[str] = None
        self.main_flow_id: Optional[str] = None
        self.main_flow_name: Optional[str] = None
        self.current_module_index: Optional[int] = None
        self.current_module_name: Optional[str] = None
        self.last_progress_time = 0.0
        self.orphaned_flow = False
        self.failure_latched = False
        self._closing = False

    def __call__(self) -> bool:
        with self._lock:
            if self.orphaned_flow:
                logger.error("runtime flow runner locked: previous timed-out flow did not exit")
                return False
            if self._thread is not None and self._thread.is_alive():
                logger.warning("runtime flow runner rejected: previous flow still running")
                return False
            self.failure_latched = False
            self._thread = threading.Thread(target=self._run_once, name="RuntimeFlowRunner", daemon=True)
            self._thread.start()
            return True

    def _load_modules(self) -> list[dict[str, Any]]:
        library = FlowLibrary.load(get_grasp_flow_file())
        main_flow = library.get_main_flow()
        self.main_flow_id = main_flow["id"]
        self.main_flow_name = main_flow["name"]
        return library.snapshot_modules(main_flow["id"])

    def _required_camera_types(self, modules: list[dict[str, Any]]) -> set[str]:
        return required_camera_types(modules)

    def _detect_camera_serials(self) -> dict[str, str]:
        if self._camera_serials is not None:
            return dict(self._camera_serials)
        serials: dict[str, str] = {}
        try:
            import pyrealsense2 as rs

            ctx = rs.context()
            for dev in ctx.query_devices():
                name = dev.get_info(rs.camera_info.name)
                serial = dev.get_info(rs.camera_info.serial_number)
                logger.info("runtime found RealSense device: %s serial=%s", name, serial)
                if "D405" in name:
                    serials["D405"] = serial
                elif "D435" in name:
                    serials["D435i"] = serial
                else:
                    serials.setdefault("D435i", serial)
        except Exception as e:
            logger.warning("runtime camera serial detection failed: %s", e)
        self._camera_serials = dict(serials)
        return serials

    def _ensure_camera(self, camera_type: str) -> bool:
        if camera_type not in self._camera_locks:
            raise ValueError(f"不支持的相机类型: {camera_type}")
        with self._camera_locks[camera_type]:
            return self._ensure_camera_unlocked(camera_type)

    def _ensure_camera_unlocked(self, camera_type: str) -> bool:
        attr = "vision_d405" if camera_type == "D405" else "vision_d435i"
        vision = getattr(self, attr)
        if vision is not None and getattr(vision, "is_available", True):
            if self._camera_preflight_ok(vision):
                return True
        if vision is not None:
            try:
                vision.close()
            except Exception:
                logger.exception("runtime failed to close stale %s camera", camera_type)
            setattr(self, attr, None)

        for attempt in range(1, self.camera_preflight_attempts + 1):
            if self._closing:
                return False
            try:
                from .vision_system import VisionSystem

                self._camera_serials = None
                serial = self._detect_camera_serials().get(camera_type)
                logger.info(
                    "runtime connecting %s camera attempt=%d%s",
                    camera_type,
                    attempt,
                    f" serial={serial}" if serial else "",
                )
                vision = VisionSystem(camera_type=camera_type, serial_number=serial)
                if self._camera_preflight_ok(vision):
                    if self._closing:
                        vision.close()
                        return False
                    setattr(self, attr, vision)
                    return True
                vision.close()
            except Exception:
                logger.exception(
                    "runtime %s camera initialization/preflight failed attempt=%d",
                    camera_type,
                    attempt,
                )
            time.sleep(min(0.2 * attempt, 1.0))

        self.controller.record_alarm(
            "Runtime相机",
            camera_type,
            "故障",
            f"{camera_type} 相机连续{self.camera_preflight_attempts}次预检失败",
        )
        return False

    def _camera_preflight_ok(self, vision) -> bool:
        for _ in range(self.camera_preflight_attempts):
            try:
                depth_frame, color_frame = vision.capture_frames()
                if depth_frame is not None and color_frame is not None:
                    return True
            except Exception:
                logger.debug("runtime camera preflight capture failed", exc_info=True)
            time.sleep(0.05)
        return False

    def _ensure_required_cameras(self, modules: list[dict[str, Any]]) -> bool:
        ok = True
        for camera_type in sorted(self._required_camera_types(modules)):
            ok = self._ensure_camera(camera_type) and ok
        return ok

    def close_cameras(self) -> None:
        self._closing = True
        for attr in ("vision_d435i", "vision_d405"):
            vision = getattr(self, attr)
            if vision is None:
                continue
            try:
                vision.close()
            except Exception:
                logger.exception("runtime failed to close %s", attr)
            setattr(self, attr, None)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            running = self._thread is not None and self._thread.is_alive()
        return {
            "running": running,
            "flow_id": self.current_flow_id,
            "main_flow_id": self.main_flow_id,
            "main_flow_name": self.main_flow_name,
            "module_index": self.current_module_index,
            "module_name": self.current_module_name,
            "last_progress_time": self.last_progress_time,
            "orphaned_flow": self.orphaned_flow,
            "failure_latched": self.failure_latched,
            "cameras": {
                "D435i": self.vision_d435i is not None,
                "D405": self.vision_d405 is not None,
            },
        }

    def _transition(self, state: RuntimeState, **updates: Any) -> None:
        if self.state_store is not None:
            self.state_store.transition(state, **updates)

    def _stop_flow_best_effort(self, flow, reason: str) -> None:
        try:
            flow.stop()
        except Exception:
            logger.exception("runtime failed to request flow stop")
        try:
            if self.controller.dashboard:
                self.controller.dashboard.Stop()
        except Exception:
            logger.exception("runtime flow watchdog Stop() failed")
        self.controller.record_alarm(
            "Runtime流程看门狗",
            "FLOW_TIMEOUT",
            "故障",
            reason,
            "检查阻塞模块和设备通信，执行复位后再启动",
        )

    def _run_once(self) -> None:
        success = False
        failure_status = STATUS_HOOK_ERR
        flow_worker = None
        flow = None
        try:
            from .workers import FlowThread, validate_grasp_flow_modules

            modules = self._load_modules()
            errors = validate_grasp_flow_modules(modules)
            if errors:
                message = "; ".join(errors)
                logger.error("runtime flow validation failed: %s", message)
                self.controller.record_alarm("Runtime流程", "VALIDATION_FAILED", "故障", message)
                return

            if not self._ensure_required_cameras(modules):
                failure_status = STATUS_CAMERA_ERR
                return

            self.current_flow_id = uuid.uuid4().hex
            self.current_module_index = None
            self.current_module_name = None
            self.last_progress_time = time.monotonic()
            self._transition(
                RuntimeState.RUNNING,
                flow_id=self.current_flow_id,
                module_index=None,
                module_name=None,
                last_error="",
            )

            finished: list[bool] = []
            flow = FlowThread(self.controller, self.vision_d435i, self.vision_d405, modules, [False])
            flow.flow_log.connect(lambda msg: logger.info("runtime flow: %s", msg))
            flow.flow_finished.connect(lambda ok: finished.append(bool(ok)))
            module_deadline = [time.monotonic() + module_timeout_seconds(modules[0])] if modules else [float("inf")]

            def on_progress(current, total, name):
                index = max(0, int(current) - 1)
                self.current_module_index = index
                self.current_module_name = str(name)
                self.last_progress_time = time.monotonic()
                if index < len(modules):
                    module_deadline[0] = self.last_progress_time + module_timeout_seconds(modules[index])
                    params = modules[index].get("params") or {}
                    state = (
                        RuntimeState.WAITING_DELAY
                        if modules[index].get("type") == "delay"
                        and params.get("wait_mode") == "modbus_or_timeout"
                        else RuntimeState.RUNNING
                    )
                    self._transition(
                        state,
                        flow_id=self.current_flow_id,
                        module_index=index,
                        module_name=self.current_module_name,
                    )

            if hasattr(flow, "flow_module_progress"):
                flow.flow_module_progress.connect(on_progress)
            flow_worker = threading.Thread(
                target=flow.run,
                name=f"FlowExecution-{self.current_flow_id[:8]}",
                daemon=True,
            )
            flow_worker.start()
            flow_deadline = time.monotonic() + flow_timeout_seconds(modules)
            timeout_reason = ""
            while flow_worker.is_alive():
                now = time.monotonic()
                if now > flow_deadline:
                    timeout_reason = "流程超过动态总超时时间"
                    break
                if now > module_deadline[0]:
                    timeout_reason = (
                        f"模块超时: index={self.current_module_index} "
                        f"name={self.current_module_name}"
                    )
                    break
                flow_worker.join(timeout=0.1)

            if timeout_reason:
                self._stop_flow_best_effort(flow, timeout_reason)
                flow_worker.join(timeout=5.0)
                if flow_worker.is_alive():
                    self.orphaned_flow = True
                    logger.critical("timed-out flow thread did not exit after stop request")
                self._transition(RuntimeState.DEGRADED, last_error=timeout_reason)
                return

            success = bool(finished[-1]) if finished else False
        except Exception as e:
            logger.exception("runtime flow runner failed")
            self.controller.record_alarm("Runtime流程", "EXCEPTION", "故障", "后台流程执行异常", raw=e)
        finally:
            if success:
                self.failure_latched = False
                self._transition(
                    RuntimeState.READY,
                    flow_id=None,
                    module_index=None,
                    module_name=None,
                    last_error="",
                )
            elif not self.orphaned_flow:
                self.failure_latched = True
                self._transition(
                    RuntimeState.DEGRADED,
                    flow_id=None,
                    module_index=None,
                    module_name=None,
                    last_error="流程执行失败",
                )
            self.controller.mark_modbus_program_finished(success, failure_status=failure_status)


class DobotRuntimeAgent:
    """Unattended production runtime: Modbus server + robot reconnect watchdog."""

    def __init__(
        self,
        controller: Optional[DobotController] = None,
        health_path: Path = DEFAULT_HEALTH_PATH,
        state_path: Path = DEFAULT_STATE_PATH,
        startup_delay: float = 10.0,
        poll_interval: float = 1.0,
    ):
        config = get_config()
        performance = get_performance_config()
        runtime_config = get_runtime_config()
        raw_runtime = config.get("runtime", {})
        if isinstance(raw_runtime, dict):
            runtime_config.update(raw_runtime)

        self.controller = controller or DobotController(
            get_robot_ip(),
            enforce_single_instance=True,
        )
        self.health_path = Path(runtime_config.get("health_path", str(health_path)))
        self.state_path = Path(runtime_config.get("state_path", str(state_path)))
        self.startup_delay = float(runtime_config.get("startup_delay", startup_delay))
        self.poll_interval = float(runtime_config.get("poll_interval", poll_interval))
        self.modbus_port = int(runtime_config.get("modbus_port", get_modbus_port()))
        self.modbus_slave_id = int(runtime_config.get("modbus_slave_id", get_modbus_slave_id()))
        self.disk_free_min_mb = float(runtime_config.get("disk_free_min_mb", 512))
        self.camera_preflight_attempts = int(runtime_config.get("camera_retry_count", 3))
        self.startup_connect_timeout_s = float(
            runtime_config.get("startup_connect_timeout_s", 5.0)
        )
        self.camera_retry_interval_s = float(
            runtime_config.get("camera_retry_interval_s", 10.0)
        )
        self.state_store = RuntimeStateStore(self.state_path)
        self.supervisor = RobotConnectionSupervisor(
            self.controller,
            feedback_max_age=float(performance.get("feedback_stale_warn_age", 0.5)),
            stable_reset_seconds=float(runtime_config.get("reconnect_stable_seconds", 10.0)),
            reconnect_jitter_ratio=float(runtime_config.get("reconnect_jitter_ratio", 0.2)),
        )
        self.program_runner = RuntimeProgramRunner(
            self.controller,
            state_store=self.state_store,
            camera_preflight_attempts=self.camera_preflight_attempts,
        )
        self.stop_event = threading.Event()
        self.last_error = ""
        self.recovery_required = False
        self._state_initialized = False
        self._stopped = False
        self.startup_errors: list[str] = []
        self.startup_connection = StartupConnectionState(
            timeout_s=self.startup_connect_timeout_s
        )
        self._startup_main_flow_id: Optional[str] = None
        self._startup_main_flow_name: Optional[str] = None
        self._startup_camera_threads: dict[str, threading.Thread] = {}
        self._startup_camera_next_attempt: dict[str, float] = {}

    def _refresh_startup_requirements(self, force=False) -> None:
        library = FlowLibrary.load(get_grasp_flow_file())
        main_flow = library.get_main_flow()
        flow_id = main_flow["id"]
        cameras = required_camera_types(main_flow.get("modules", []))
        if (
            force
            or flow_id != self._startup_main_flow_id
            or main_flow["name"] != self._startup_main_flow_name
            or cameras != self.startup_connection.required_cameras
        ):
            self._startup_main_flow_id = flow_id
            self._startup_main_flow_name = main_flow["name"]
            self.program_runner.main_flow_id = flow_id
            self.program_runner.main_flow_name = main_flow["name"]
            self.startup_connection.begin(cameras)
            logger.info(
                "startup connection check: main_flow=%s required_cameras=%s deadline=%.1fs",
                main_flow["name"],
                sorted(cameras),
                self.startup_connect_timeout_s,
            )

    def _camera_connection_status(self) -> dict[str, bool]:
        return {
            "D435i": bool(
                self.program_runner.vision_d435i is not None
                and getattr(self.program_runner.vision_d435i, "is_available", True)
            ),
            "D405": bool(
                self.program_runner.vision_d405 is not None
                and getattr(self.program_runner.vision_d405, "is_available", True)
            ),
        }

    def _current_startup_connection_error(self):
        self.startup_connection.update(
            robot_connected=bool(self.controller.is_connected),
            camera_connected=self._camera_connection_status(),
        )
        return self.startup_connection.recheck_fault()

    def _camera_connect_worker(self, camera_type: str) -> None:
        try:
            self.program_runner._ensure_camera(camera_type)
        except Exception:
            logger.exception("startup %s camera connection worker failed", camera_type)
        finally:
            self._startup_camera_next_attempt[camera_type] = (
                time.monotonic() + self.camera_retry_interval_s
            )

    def _start_required_camera_connections(self) -> None:
        now = time.monotonic()
        status = self._camera_connection_status()
        for camera_type in self.startup_connection.required_cameras:
            if status.get(camera_type):
                continue
            thread = self._startup_camera_threads.get(camera_type)
            if thread is not None and thread.is_alive():
                continue
            if now < self._startup_camera_next_attempt.get(camera_type, 0.0):
                continue
            thread = threading.Thread(
                target=self._camera_connect_worker,
                args=(camera_type,),
                name=f"Runtime{camera_type}Connect",
                daemon=True,
            )
            self._startup_camera_threads[camera_type] = thread
            thread.start()

    def _update_startup_connection(self) -> None:
        try:
            self._refresh_startup_requirements()
        except Exception:
            logger.exception("failed to refresh startup main-flow requirements")
        self._start_required_camera_connections()
        self.startup_connection.update(
            robot_connected=bool(self.controller.is_connected),
            camera_connected=self._camera_connection_status(),
        )
        was_latched = self.startup_connection.fault_code is not None
        error_code = self.startup_connection.latch_if_due()
        if error_code is None:
            return
        self.controller.set_startup_connection_fault(
            error_code,
            ready_checker=self._current_startup_connection_error,
        )
        if not was_latched:
            snapshot = self.startup_connection.snapshot()
            self.controller.record_alarm(
                "启动自动连接",
                str(error_code),
                "故障",
                f"启动连接超时，缺失设备: {', '.join(snapshot['missing_devices'])}",
                "检查机器人、相机、模型与网络；设备恢复后由PLC写40001=0复查",
            )

    def validate_startup_inputs(self) -> list[str]:
        errors = []
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as handle:
                config = json.load(handle)
            if not isinstance(config, dict):
                errors.append("config.json根节点必须是对象")
            else:
                try:
                    ipaddress.ip_address(str(config.get("robot_ip", "")))
                except ValueError:
                    errors.append("robot_ip不是有效IP地址")
                port = int(config.get("modbus_port", get_modbus_port()))
                if not 1 <= port <= 65535:
                    errors.append("modbus_port必须在1到65535之间")
        except Exception as e:
            errors.append(f"config.json不可用: {e}")
        try:
            library = FlowLibrary.load(get_grasp_flow_file(), migrate=False)
            library.get_main_flow()
        except Exception as e:
            errors.append(f"流程文件不可用: {e}")
        return errors

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

        state = self.state_store.snapshot()
        runner = self.program_runner.snapshot()
        metrics = get_process_metrics(self.health_path)
        now = time.time()
        feedback_timestamp = float(feedback.get("timestamp", 0.0) or 0.0)
        return {
            "schema_version": 2,
            "timestamp": time.time(),
            "timestamp_iso": datetime.now().isoformat(timespec="seconds"),
            "boot_id": state.get("boot_id"),
            "runtime": {
                "running": not self.stop_event.is_set(),
                "state": state.get("state", RuntimeState.STARTING.value),
                "recovery_required": self.recovery_required,
                "startup_delay": self.startup_delay,
                "startup_connect_timeout_s": self.startup_connect_timeout_s,
                "poll_interval": self.poll_interval,
                "last_error": self.last_error or self.supervisor.last_error,
                "startup_errors": list(self.startup_errors),
            },
            "robot": {
                "ip": self.controller.robot_ip,
                "supervisor_state": self.supervisor.state,
                "connected": bool(self.controller.is_connected),
                "enabled": bool(self.controller.is_enabled),
                "feedback": feedback,
                "feedback_age_s": (
                    round(max(0.0, now - feedback_timestamp), 3)
                    if feedback_timestamp > 0
                    else None
                ),
                "feedback_thread_alive": bool(
                    getattr(self.controller, "feed_thread", None)
                    and self.controller.feed_thread.is_alive()
                ),
                "last_error": self.controller.last_error,
            },
            "modbus": {
                **modbus_stats,
                "thread_alive": bool(
                    getattr(getattr(self.controller, "modbus_server", None), "_server_thread", None)
                    and self.controller.modbus_server._server_thread.is_alive()
                ),
            },
            "flow": runner,
            "startup_connection": {
                **self.startup_connection.snapshot(),
                "main_flow_id": self._startup_main_flow_id,
                "main_flow_name": self._startup_main_flow_name,
                "controller_fault_code": (
                    self.controller.get_startup_connection_fault()
                    if hasattr(self.controller, "get_startup_connection_fault")
                    else None
                ),
            },
            "process": metrics,
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
        supervisor_state = self.supervisor.step()
        self._update_startup_connection()
        metrics = get_process_metrics(self.health_path)
        if metrics["disk_free_mb"] < self.disk_free_min_mb:
            self.last_error = (
                f"disk free space low: {metrics['disk_free_mb']}MB "
                f"< {self.disk_free_min_mb}MB"
            )
            if not self.recovery_required:
                self.state_store.transition(RuntimeState.DEGRADED, last_error=self.last_error)
        elif (
            not self.program_runner.snapshot()["running"]
            and not self.program_runner.snapshot()["failure_latched"]
            and not self.recovery_required
        ):
            desired = (
                RuntimeState.READY
                if supervisor_state == RobotConnectionState.CONNECTED
                else RuntimeState.DEGRADED
            )
            self.state_store.transition(desired, last_error=self.supervisor.last_error)
        self.write_health()

    def run(self) -> None:
        self.recovery_required = self.state_store.begin_boot()
        self.startup_errors = self.validate_startup_inputs()
        self.recovery_required = self.recovery_required or bool(self.startup_errors)
        if self.startup_errors:
            self.last_error = "; ".join(self.startup_errors)
            self.state_store.transition(
                RuntimeState.RECOVERY_REQUIRED,
                last_error=self.last_error,
            )
        self._state_initialized = True
        self.controller.set_modbus_program_runner(self.program_runner)
        self.ensure_modbus_running()
        self.controller.set_runtime_recovery_required(
            self.recovery_required,
            on_cleared=self._on_recovery_cleared,
        )
        startup_requirements_ready = True
        try:
            self._refresh_startup_requirements(force=True)
        except Exception:
            startup_requirements_ready = False
            logger.exception("startup main-flow requirements are unavailable")
        if not self.stop_event.is_set():
            self.supervisor.request_connect()
            if startup_requirements_ready:
                self._start_required_camera_connections()
        self.write_health()

        if self.startup_delay > 0:
            logger.warning(
                "runtime.startup_delay=%.1f 已弃用；首次设备连接已立即开始",
                self.startup_delay,
            )

        while not self.stop_event.is_set():
            try:
                self.tick()
            except Exception as e:
                self.last_error = f"runtime tick failed: {e}"
                logger.exception(self.last_error)
                try:
                    self.state_store.transition(
                        RuntimeState.DEGRADED,
                        last_error=self.last_error,
                    )
                except Exception:
                    pass
            self.stop_event.wait(self.poll_interval)

    def _on_recovery_cleared(self) -> None:
        self.startup_errors = self.validate_startup_inputs()
        if self.startup_errors:
            self.recovery_required = True
            self.last_error = "; ".join(self.startup_errors)
            self.state_store.transition(
                RuntimeState.RECOVERY_REQUIRED,
                last_error=self.last_error,
            )
            self.controller.set_runtime_recovery_required(True)
            return
        self.recovery_required = False
        self.last_error = ""
        state = (
            RuntimeState.READY
            if self.controller.is_connected
            else RuntimeState.DEGRADED
        )
        self.state_store.transition(state, last_error="")

    def request_stop(self) -> None:
        self.stop_event.set()

    def stop(self, clean=True) -> None:
        if self._stopped:
            return
        self._stopped = True
        self.stop_event.set()
        if self._state_initialized:
            try:
                self.state_store.transition(RuntimeState.STOPPING)
            except Exception:
                pass
        flow = getattr(self.controller, "_active_flow_thread", None)
        if flow is not None:
            ctx = getattr(flow, "_ctx", None)
            if ctx is not None:
                ctx.stop_event.set()
            try:
                if self.controller.dashboard:
                    self.controller.dashboard.Stop()
            except Exception:
                logger.exception("runtime shutdown Stop() failed")
        try:
            self.controller.stop_modbus()
        except Exception as e:
            logger.warning("stop_modbus during runtime shutdown failed: %s", e)
        self.program_runner.close_cameras()
        self.supervisor.shutdown()
        if hasattr(self.controller, "release_control_lease"):
            self.controller.release_control_lease()
        if clean and self._state_initialized:
            try:
                self.state_store.mark_clean_shutdown()
            except Exception:
                logger.exception("failed to mark clean runtime shutdown")
        try:
            self.write_health()
        except Exception:
            logger.exception("failed to write final runtime health")


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Dobot unattended runtime agent.")
    parser.add_argument("--startup-delay", type=float, default=None, help="Deprecated compatibility option; initial connection starts immediately.")
    parser.add_argument("--poll-interval", type=float, default=1.0, help="Runtime watchdog interval in seconds.")
    parser.add_argument("--health-path", type=Path, default=DEFAULT_HEALTH_PATH, help="Path to runtime health JSON.")
    parser.add_argument("--state-path", type=Path, default=DEFAULT_STATE_PATH, help="Path to durable runtime state JSON.")
    parser.add_argument("--lock-path", type=Path, default=DEFAULT_LOCK_PATH, help="Path to the single-instance lock file.")
    parser.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR, help="Directory for runtime.log.")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    setup_runtime_logging(args.log_dir)
    instance_lock = SingleInstanceLock(args.lock_path)
    if not instance_lock.acquire():
        logger.error("another runtime instance is already running")
        return 2

    try:
        agent = DobotRuntimeAgent(
            health_path=args.health_path,
            state_path=args.state_path,
            startup_delay=0.0 if args.startup_delay is None else args.startup_delay,
            poll_interval=args.poll_interval,
        )

        def _stop(signum, _frame):
            logger.info("runtime stop signal received: %s", signum)
            agent.request_stop()

        signal.signal(signal.SIGINT, _stop)
        signal.signal(signal.SIGTERM, _stop)

        clean_exit = True
        try:
            agent.run()
            return 0
        except Exception:
            clean_exit = False
            logger.exception("runtime agent crashed")
            try:
                agent.write_health()
            except Exception:
                pass
            return 1
        finally:
            agent.stop(clean=clean_exit)
    finally:
        instance_lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
