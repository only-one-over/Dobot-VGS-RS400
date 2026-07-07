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
    reload_config,
    resolve_point,
    use_config_snapshot,
)
from .flow_library import FlowLibrary, required_camera_types
from .flow_readiness import FlowReadinessResult, check_flow_readiness
from .modbus_server import STATUS_HOOK_ERR, STATUS_ROBOT_ERR
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
from .runtime_ipc import (
    DEFAULT_IPC_TOKEN_PATH,
    IpcCommandError,
    RuntimeIpcServer,
    load_ipc_token,
)
from .runtime_publication import (
    PublicationError,
    RuntimePublicationStore,
)

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_HEALTH_PATH = PROJECT_ROOT / "runtime_health.json"
DEFAULT_STATE_PATH = PROJECT_ROOT / "runtime_state.json"
DEFAULT_LOCK_PATH = PROJECT_ROOT / "runtime_agent.lock"
DEFAULT_LOG_DIR = PROJECT_ROOT / "logs"
DEFAULT_PUBLICATION_PATH = PROJECT_ROOT / "runtime_publication.json"


class RobotConnectionState:
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    DEGRADED = "DEGRADED"


@dataclass
class RuntimeExecutionRequest:
    mode: str
    flow_id: str
    flow_name: str
    modules: list[dict[str, Any]]
    config: dict[str, Any]
    revision: str
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex)


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
    _connect_result: Optional[tuple[int, bool, str]] = field(default=None, init=False, repr=False)
    _connect_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _connect_generation: int = field(default=0, init=False, repr=False)
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
        self.controller.abort_active_flow_for_disconnect(reason)
        self.controller.record_alarm(
            "Runtime反馈",
            "FEEDBACK_DISCONNECTED",
            "故障",
            reason,
            "检查机器人网络和30004反馈连接，设备恢复后重新触发流程",
        )

    def close_robot_connection(self) -> None:
        """Close robot sockets but keep Modbus service alive."""
        try:
            self.controller.close_robot_transport()
        except Exception as e:
            logger.warning("close robot transport failed: %s", e)

    def _connect_worker(self, generation: int) -> None:
        ok = False
        error = ""
        try:
            self.close_robot_connection()
            ok = bool(self.controller.connect())
            error = "" if ok else (self.controller.last_error or "connect failed")
        except Exception as exc:
            error = str(exc)
            logger.exception("robot background connect failed")
        if not ok:
            self.close_robot_connection()
        if self._shutting_down and ok:
            self.close_robot_connection()
            ok = False
            error = "runtime stopping"
        with self._connect_lock:
            if generation != self._connect_generation:
                logger.info(
                    "discarding stale robot connect result generation=%d current=%d",
                    generation,
                    self._connect_generation,
                )
                return
            self._connect_result = (generation, ok, error)

    def _consume_connect_result(self, now: float) -> bool:
        with self._connect_lock:
            result = self._connect_result
            self._connect_result = None
        if result is None:
            return False
        generation, ok, error = result
        if generation != self._connect_generation:
            return False
        if ok and self.controller.is_connected:
            self.next_attempt_at = 0.0
            self.last_error = ""
            self.connected_since = now
            self._set_state(RobotConnectionState.CONNECTED)
        else:
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
        with self._connect_lock:
            self._connect_generation += 1
            generation = self._connect_generation
            self._connect_result = None
        self._connect_thread = threading.Thread(
            target=self._connect_worker,
            args=(generation,),
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

            thread = getattr(self.controller, "feed_thread", None)
            if thread is not None and not thread.is_alive():
                self._abort_active_flow("机器人反馈线程退出，当前流程已停止")
                self.controller.is_connected = False
                self._schedule_reconnect(now, "feedback thread stopped")
                return self.state
            health = self.controller.get_feedback_health(max_age=self.feedback_max_age)
            health_state = health.get("health")
            if health_state == "disconnected":
                self._abort_active_flow("流程运行期间机器人反馈断流，已先停止运动")
                self.controller.is_connected = False
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
            self.controller.is_connected = False
            self._schedule_reconnect(now, str(e))
            return self.state

    def shutdown(self) -> None:
        self._shutting_down = True
        with self._connect_lock:
            self._connect_generation += 1
            self._connect_result = None
        self.close_robot_connection()


class RuntimeProgramRunner:
    """Run the saved motion flow in a background thread for Modbus command 3."""

    def __init__(
        self,
        controller: DobotController,
        state_store: Optional[RuntimeStateStore] = None,
        camera_preflight_attempts: int = 3,
        publication_provider=None,
    ):
        self.controller = controller
        self.state_store = state_store
        self.camera_preflight_attempts = max(1, int(camera_preflight_attempts))
        self.publication_provider = publication_provider
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
        self.active_required_cameras: set[str] = set()
        self.current_revision: Optional[str] = None
        self.next_revision: Optional[str] = None
        self._active_flow = None
        self._pause_ref: Optional[list[bool]] = None
        self.task_id: Optional[str] = None
        self.task_mode: Optional[str] = None
        self.last_task_result: Optional[bool] = None
        self.last_task_error = ""

    def __call__(self) -> bool:
        request = self.build_request(mode="production")
        return self.start_request(request)

    def build_request(
        self,
        *,
        mode: str,
        flow_id: str | None = None,
        step_index: int | None = None,
        modules: list[dict[str, Any]] | None = None,
        flow_name: str | None = None,
    ) -> RuntimeExecutionRequest:
        config, library, revision = self._load_execution_snapshot(flow_id)
        if modules is None:
            flow = library.get_flow(flow_id) if flow_id else library.get_main_flow()
            selected_modules = library.snapshot_modules(flow["id"])
            selected_flow_id = flow["id"]
            selected_flow_name = flow["name"]
            if step_index is not None:
                if step_index < 0 or step_index >= len(selected_modules):
                    raise ValueError("step_index is out of range")
                module = selected_modules[step_index]
                params = module.get("params") or {}
                if (
                    module.get("type") == "move"
                    and params.get("target") == "camera_detected"
                ):
                    raise ValueError(
                        "camera_detected step requires prior flow context"
                    )
                selected_modules = [module]
                selected_flow_name = f"{selected_flow_name} / step {step_index + 1}"
        else:
            selected_modules = list(modules)
            selected_flow_id = flow_id or "adhoc-debug"
            selected_flow_name = flow_name or "Ad-hoc debug"
        return RuntimeExecutionRequest(
            mode=str(mode),
            flow_id=selected_flow_id,
            flow_name=selected_flow_name,
            modules=selected_modules,
            config=config,
            revision=revision,
        )

    def start_request(self, request: RuntimeExecutionRequest) -> bool:
        with self._lock:
            if self.orphaned_flow:
                logger.error("runtime flow runner locked: previous timed-out flow did not exit")
                return False
            if self._thread is not None and self._thread.is_alive():
                logger.warning("runtime flow runner rejected: previous flow still running")
                return False
            self.failure_latched = False
            self.task_id = request.task_id
            self.task_mode = request.mode
            self.last_task_result = None
            self.last_task_error = ""
            self._thread = threading.Thread(
                target=self._run_once,
                args=(request,),
                name="RuntimeFlowRunner",
                daemon=True,
            )
            self._thread.start()
            return True

    def pause(self) -> bool:
        if self._pause_ref is None or self._active_flow is None:
            return False
        self._pause_ref[0] = True
        self.controller.pause()
        return True

    def resume(self) -> bool:
        if self._pause_ref is None or self._active_flow is None:
            return False
        self.controller.continue_motion()
        self._pause_ref[0] = False
        return True

    def stop(self) -> bool:
        flow = self._active_flow
        if flow is None:
            return False
        flow.stop()
        return True

    def _load_modules(self) -> list[dict[str, Any]]:
        _config, library, revision = self._load_execution_snapshot()
        self.next_revision = revision
        main_flow = library.get_main_flow()
        self.main_flow_id = main_flow["id"]
        self.main_flow_name = main_flow["name"]
        return library.snapshot_modules(main_flow["id"])

    def _load_execution_snapshot(
        self,
        flow_id: str | None = None,
    ) -> tuple[dict[str, Any], FlowLibrary, str]:
        if self.publication_provider is None:
            config = get_config()
            library = FlowLibrary.load(get_grasp_flow_file())
            revision = "legacy-draft"
        else:
            publication = self.publication_provider()
            config = publication["config"]
            library = FlowLibrary(
                publication["flow_library"],
                path="published-flow.json",
            )
            revision = str(publication["revision"])
        if flow_id is not None:
            library.get_flow(flow_id)
        return config, library, revision

    def _required_camera_types(self, modules: list[dict[str, Any]]) -> set[str]:
        return required_camera_types(modules)

    def check_main_flow_readiness(self):
        modules = self._load_modules()
        return check_flow_readiness(
            self.controller,
            self.vision_d435i,
            self.vision_d405,
            modules,
        )

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
                camera_config = (
                    self.publication_provider()["config"]
                    if self.publication_provider is not None
                    else get_config()
                )
                with use_config_snapshot(camera_config):
                    vision = VisionSystem(
                        camera_type=camera_type,
                        serial_number=serial,
                    )
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

    def close_cameras(self) -> None:
        self._closing = True
        self._close_camera_instances()

    def reload_cameras(self) -> None:
        self._close_camera_instances()
        self._closing = False
        self._camera_serials = None

    def _close_camera_instances(self) -> None:
        for camera_type, attr in (
            ("D435i", "vision_d435i"),
            ("D405", "vision_d405"),
        ):
            with self._camera_locks[camera_type]:
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
            "current_revision": self.current_revision,
            "next_revision": self.next_revision,
            "task_id": self.task_id,
            "task_mode": self.task_mode,
            "paused": bool(self._pause_ref and self._pause_ref[0]),
            "last_task_result": self.last_task_result,
            "last_task_error": self.last_task_error,
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

    def _run_once(self, request: RuntimeExecutionRequest | None = None) -> None:
        success = False
        failure_status = STATUS_HOOK_ERR
        task_mode = request.mode if request is not None else "production"
        flow_worker = None
        flow = None
        try:
            from .workers import FlowThread, validate_grasp_flow_modules

            if request is not None:
                config_snapshot = request.config
                modules = request.modules
                revision = request.revision
                self.main_flow_id = request.flow_id
                self.main_flow_name = request.flow_name
                task_mode = request.mode
                self.task_id = request.task_id
                self.task_mode = task_mode
            elif self.publication_provider is None:
                config_snapshot = get_config()
                modules = self._load_modules()
                revision = "legacy-draft"
                task_mode = "production"
            else:
                config_snapshot, library, revision = self._load_execution_snapshot()
                main_flow = library.get_main_flow()
                self.main_flow_id = main_flow["id"]
                self.main_flow_name = main_flow["name"]
                modules = library.snapshot_modules(main_flow["id"])
                task_mode = "production"
            self.current_revision = revision
            self.next_revision = revision
            errors = validate_grasp_flow_modules(modules)
            if errors:
                message = "; ".join(errors)
                logger.error("runtime flow validation failed: %s", message)
                self.controller.record_alarm("Runtime流程", "VALIDATION_FAILED", "故障", message)
                return

            readiness = check_flow_readiness(
                self.controller,
                self.vision_d435i,
                self.vision_d405,
                modules,
            )
            if not readiness.ok:
                self.controller.record_alarm(
                    "Runtime流程",
                    "DEVICE_NOT_READY",
                    "故障",
                    readiness.message,
                )
                return

            self.current_flow_id = uuid.uuid4().hex
            self.active_required_cameras = self._required_camera_types(modules)
            self.current_module_index = None
            self.current_module_name = None
            self.last_progress_time = time.monotonic()
            self._transition(
                RuntimeState.MAINTENANCE
                if task_mode == "debug"
                else RuntimeState.RUNNING,
                flow_id=self.current_flow_id,
                module_index=None,
                module_name=None,
                last_error="",
            )

            finished: list[bool] = []
            self.controller._user_index = int(config_snapshot.get("user_index", 0))
            self.controller._tool_index = int(config_snapshot.get("tool_index", 0))
            self._pause_ref = [False]
            flow = FlowThread(
                self.controller,
                self.vision_d435i,
                self.vision_d405,
                modules,
                self._pause_ref,
            )
            self._active_flow = flow
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
                    if task_mode == "debug":
                        state = RuntimeState.MAINTENANCE
                    self._transition(
                        state,
                        flow_id=self.current_flow_id,
                        module_index=index,
                        module_name=self.current_module_name,
                    )

            if hasattr(flow, "flow_module_progress"):
                flow.flow_module_progress.connect(on_progress)
            def run_flow_with_snapshot():
                with use_config_snapshot(config_snapshot):
                    flow.run()

            flow_worker = threading.Thread(
                target=run_flow_with_snapshot,
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
            self.last_task_result = success
        except Exception as e:
            self.last_task_error = str(e)
            logger.exception("runtime flow runner failed")
            self.controller.record_alarm("Runtime流程", "EXCEPTION", "故障", "后台流程执行异常", raw=e)
        finally:
            self._active_flow = None
            self._pause_ref = None
            self.active_required_cameras = set()
            if task_mode == "debug":
                self.failure_latched = False
                self._transition(
                    RuntimeState.MAINTENANCE,
                    flow_id=None,
                    module_index=None,
                    module_name=None,
                    last_error="" if success else self.last_task_error,
                )
            elif success:
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
            if task_mode != "debug":
                self.controller.mark_modbus_program_finished(
                    success,
                    failure_status=failure_status,
                )


class DobotRuntimeAgent:
    """Unattended production runtime: Modbus server + robot reconnect watchdog."""

    def __init__(
        self,
        controller: Optional[DobotController] = None,
        health_path: Path = DEFAULT_HEALTH_PATH,
        state_path: Path = DEFAULT_STATE_PATH,
        startup_delay: float = 10.0,
        poll_interval: float = 1.0,
        ipc_server: Optional[RuntimeIpcServer] = None,
    ):
        draft_config = get_config()
        draft_runtime = get_runtime_config()
        raw_draft_runtime = draft_config.get("runtime", {})
        if isinstance(raw_draft_runtime, dict):
            draft_runtime.update(raw_draft_runtime)
        self.publication_path = Path(
            draft_runtime.get("publication_path", str(DEFAULT_PUBLICATION_PATH))
        )
        self.publication_store = RuntimePublicationStore(self.publication_path)
        config = self.publication_store.snapshot()["config"]
        with use_config_snapshot(config):
            performance = get_performance_config()
            runtime_config = get_runtime_config()
        raw_runtime = config.get("runtime", {})
        if isinstance(raw_runtime, dict):
            runtime_config.update(raw_runtime)

        self.controller = controller or DobotController(
            str(config.get("robot_ip", "192.168.5.1")),
            enforce_single_instance=True,
        )
        self.health_path = Path(runtime_config.get("health_path", str(health_path)))
        self.state_path = Path(runtime_config.get("state_path", str(state_path)))
        self.startup_delay = float(runtime_config.get("startup_delay", startup_delay))
        self.poll_interval = float(runtime_config.get("poll_interval", poll_interval))
        self.modbus_port = int(
            runtime_config.get("modbus_port", config.get("modbus_port", 502))
        )
        self.modbus_slave_id = int(
            runtime_config.get(
                "modbus_slave_id",
                config.get("modbus_slave_id", 5),
            )
        )
        self.disk_free_min_mb = float(runtime_config.get("disk_free_min_mb", 512))
        self.camera_preflight_attempts = int(runtime_config.get("camera_retry_count", 3))
        self.startup_connect_timeout_s = float(
            runtime_config.get("startup_connect_timeout_s", 5.0)
        )
        self.camera_retry_interval_s = float(
            runtime_config.get("camera_retry_interval_s", 10.0)
        )
        self.ipc_host = str(runtime_config.get("ipc_host", "127.0.0.1"))
        self.ipc_port = int(runtime_config.get("ipc_port", 8765))
        self.ipc_command_timeout_s = float(
            runtime_config.get("ipc_command_timeout_s", 5.0)
        )
        self.service_mode = str(
            os.environ.get("DOBOT_SERVICE_MODE", "")
        ).strip().lower() in {"1", "true", "yes", "on"}
        self.service_name = str(
            os.environ.get("DOBOT_SERVICE_NAME", "")
        ).strip()
        self.service_stop_marker_path = Path(
            runtime_config.get(
                "service_stop_marker_path",
                PROJECT_ROOT / "runtime_service_stopped.json",
            )
        )
        if self.service_mode:
            self.service_stop_marker_path.unlink(missing_ok=True)
        token_path_value = (
            os.environ.get("DOBOT_IPC_TOKEN_FILE")
            or runtime_config.get("ipc_token_path")
            or DEFAULT_IPC_TOKEN_PATH
        )
        self.ipc_token_path = Path(token_path_value)
        self.ipc_auth_token = load_ipc_token(
            self.ipc_token_path,
            required=self.service_mode
            or bool(runtime_config.get("ipc_require_token", False)),
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
            publication_provider=self.publication_store.snapshot,
        )
        self.stop_event = threading.Event()
        self.last_error = ""
        self.stop_reason = ""
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
        self._flow_device_abort_reported = False
        self._pending_camera_reload_revision: Optional[str] = None
        self._maintenance_lock = threading.RLock()
        self.maintenance_mode = False
        self.ipc_server = ipc_server or RuntimeIpcServer(
            self._handle_ipc_command,
            host=self.ipc_host,
            port=self.ipc_port,
            command_timeout_s=self.ipc_command_timeout_s,
            auth_token=self.ipc_auth_token,
        )

    def _refresh_startup_requirements(self, force=False) -> None:
        publication = self.publication_store.snapshot()
        library = FlowLibrary(
            publication["flow_library"],
            path="published-flow.json",
        )
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

    def _robot_connection_ready(self) -> bool:
        if (
            not self.controller.is_connected
            or self.controller.dashboard is None
        ):
            return False
        try:
            return self.controller.get_feedback_health().get("health") == "ok"
        except Exception:
            return False

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
        flow_running = self.program_runner.snapshot()["running"]
        required_cameras = (
            self.program_runner.active_required_cameras
            if flow_running
            else self.startup_connection.required_cameras
        )
        missing = [
            camera_type
            for camera_type in required_cameras
            if not status.get(camera_type)
        ]
        if flow_running and missing:
            if not self._flow_device_abort_reported:
                self._flow_device_abort_reported = True
                reason = f"流程运行中相机断线: {', '.join(sorted(missing))}"
                self.controller.abort_active_flow_for_disconnect(reason)
                self.controller.record_alarm(
                    "Runtime相机",
                    "CAMERA_DISCONNECTED",
                    "故障",
                    reason,
                    "后台继续重连，恢复后需重新触发流程",
                )
            return
        if not flow_running:
            self._flow_device_abort_reported = False
        for camera_type in required_cameras:
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
            robot_connected=self._robot_connection_ready(),
            camera_connected=self._camera_connection_status(),
        )

    def _handle_ipc_command(
        self,
        command: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        handlers = {
            "ping": self._ipc_ping,
            "get_status": self._ipc_get_status,
            "enter_maintenance": self._ipc_enter_maintenance,
            "exit_maintenance": self._ipc_exit_maintenance,
            "reload_config": self._ipc_reload_config,
            "publish_config": self._ipc_publish_config,
            "get_publication_status": self._ipc_get_publication_status,
            "validate_flow": self._ipc_validate_flow,
            "get_current_pose": self._ipc_get_current_pose,
            "get_runtime_logs": self._ipc_get_runtime_logs,
            "start_debug_flow": self._ipc_start_debug_flow,
            "run_step": self._ipc_run_step,
            "move_to_point": self._ipc_move_to_point,
            "pause_debug_flow": self._ipc_pause_debug_flow,
            "resume_debug_flow": self._ipc_resume_debug_flow,
            "stop_debug_flow": self._ipc_stop_debug_flow,
            "get_debug_task_status": self._ipc_get_debug_task_status,
            "test_d405": self._ipc_test_d405,
            "test_d435i": self._ipc_test_d435i,
            "test_detection": self._ipc_test_detection,
            "get_vision_snapshot": self._ipc_get_vision_snapshot,
            "get_visual_servo_telemetry": self._ipc_get_visual_servo_telemetry,
            "stop_current_task": self._ipc_stop_current_task,
        }
        handler = handlers.get(command)
        if handler is None:
            raise IpcCommandError(
                "UNKNOWN_COMMAND",
                f"不支持的命令: {command}",
            )
        return handler(data)

    def _ipc_ping(self, _data=None) -> dict[str, Any]:
        return {
            "pong": True,
            "runtime_state": self.state_store.snapshot().get(
                "state",
                RuntimeState.STARTING.value,
            ),
        }

    def _ipc_get_status(self, _data=None) -> dict[str, Any]:
        state = self.state_store.snapshot()
        flow = self.program_runner.snapshot()
        cameras = self._camera_connection_status()
        try:
            modbus_running = bool(
                self.controller.get_modbus_stats().get("is_running")
            )
        except Exception:
            modbus_running = False
        flow_running = bool(flow.get("running"))
        return {
            "runtime_state": state.get(
                "state",
                RuntimeState.STARTING.value,
            ),
            "maintenance": self.maintenance_mode,
            "recovery_required": self.recovery_required,
            "robot_connected": bool(self.controller.is_connected),
            "robot_enabled": bool(self.controller.is_enabled),
            "d405_connected": cameras["D405"],
            "d435i_connected": cameras["D435i"],
            "modbus_running": modbus_running,
            "current_flow": flow.get("main_flow_name") if flow_running else None,
            "current_step": flow.get("module_name") if flow_running else None,
            "flow_running": flow_running,
            "last_error": self.last_error or self.supervisor.last_error,
            "publication": self.publication_store.status(),
            "current_task_revision": flow.get("current_revision"),
            "next_task_revision": self.publication_store.status()["revision"],
        }

    def _ipc_enter_maintenance(self, _data=None) -> dict[str, Any]:
        with self._maintenance_lock:
            state = str(self.state_store.snapshot().get("state", ""))
            if self.maintenance_mode:
                return {
                    "runtime_state": RuntimeState.MAINTENANCE.value,
                    "already_active": True,
                }
            if self.recovery_required:
                raise IpcCommandError(
                    "RECOVERY_REQUIRED",
                    "Runtime处于恢复锁状态，需先由PLC执行复位",
                )
            if state == RuntimeState.STOPPING.value:
                raise IpcCommandError(
                    "RUNTIME_BUSY",
                    "Runtime正在停止",
                )
            if self._runtime_motion_busy():
                raise IpcCommandError(
                    "RUNTIME_BUSY",
                    "生产流程或Modbus运动正在运行，请先停止当前任务",
                )

            self.maintenance_mode = True
            self.state_store.transition(RuntimeState.MAINTENANCE_REQUESTED)
            self.controller.set_runtime_maintenance(True)
            if self._runtime_motion_busy():
                self.controller.set_runtime_maintenance(False)
                self.maintenance_mode = False
                self.state_store.transition(state or RuntimeState.DEGRADED.value)
                raise IpcCommandError(
                    "RUNTIME_BUSY",
                    "生产流程已在维护切换期间启动",
                )
            self.state_store.transition(
                RuntimeState.MAINTENANCE,
                flow_id=None,
                module_index=None,
                module_name=None,
                last_error="",
            )
            return {
                "runtime_state": RuntimeState.MAINTENANCE.value,
                "already_active": False,
            }

    def _ipc_exit_maintenance(self, _data=None) -> dict[str, Any]:
        with self._maintenance_lock:
            if not self.maintenance_mode:
                return {
                    "runtime_state": self.state_store.snapshot().get(
                        "state",
                        RuntimeState.READY.value,
                    ),
                    "already_inactive": True,
                }
            self.controller.set_runtime_maintenance(False)
            self.maintenance_mode = False
            state = (
                RuntimeState.READY
                if self.controller.is_connected
                else RuntimeState.DEGRADED
            )
            self.state_store.transition(
                state,
                flow_id=None,
                module_index=None,
                module_name=None,
                last_error="",
            )
            return {
                "runtime_state": state.value,
                "already_inactive": False,
                "auto_resumed": False,
            }

    def _ipc_reload_config(self, _data=None) -> dict[str, Any]:
        if self.program_runner.snapshot().get("running"):
            raise IpcCommandError(
                "RUNTIME_BUSY",
                "流程运行期间不允许重载配置",
            )
        if (
            not self.publication_store.path.exists()
            and self.publication_store.status()["revision"] == "legacy-draft"
        ):
            publication = self.publication_store.snapshot()
        else:
            try:
                publication = self.publication_store.reload_published()
            except PublicationError as exc:
                raise IpcCommandError("INVALID_CONFIG", str(exc)) from exc
        if publication["revision"] == "legacy-draft":
            config = reload_config()
            self.controller._user_index = int(config.get("user_index", 0))
            self.controller._tool_index = int(config.get("tool_index", 0))
        self.program_runner.next_revision = publication["revision"]
        self.program_runner._camera_serials = None
        self._pending_camera_reload_revision = publication["revision"]
        self._refresh_startup_requirements(force=True)
        return {
            "reloaded": True,
            "applies_to_running_task": False,
            "main_flow_id": self._startup_main_flow_id,
            "main_flow_name": self._startup_main_flow_name,
            "revision": publication["revision"],
        }

    def _ipc_publish_config(self, _data=None) -> dict[str, Any]:
        try:
            publication = self.publication_store.publish_drafts(
                self._validate_publication_inputs
            )
        except PublicationError as exc:
            raise IpcCommandError("INVALID_CONFIG", str(exc)) from exc
        self.program_runner.next_revision = publication["revision"]
        self.program_runner._camera_serials = None
        self._pending_camera_reload_revision = publication["revision"]
        self._refresh_startup_requirements(force=True)
        return {
            **self.publication_store.status(),
            "published": True,
            "applies_to_running_task": False,
        }

    def _ipc_get_publication_status(self, _data=None) -> dict[str, Any]:
        flow = self.program_runner.snapshot()
        status = self.publication_store.status()
        return {
            **status,
            "current_task_revision": flow.get("current_revision"),
            "next_task_revision": status["revision"],
            "publication_load_error": self.publication_store.load_error,
        }

    def _require_maintenance(self) -> None:
        if not self.maintenance_mode:
            raise IpcCommandError(
                "NOT_IN_MAINTENANCE",
                "Runtime is not in maintenance mode",
            )

    def _require_debug_robot(self) -> None:
        if not self.controller.is_connected or self.controller.dashboard is None:
            raise IpcCommandError(
                "ROBOT_NOT_CONNECTED",
                "Robot is not connected",
            )
        if not self.controller.is_enabled:
            raise IpcCommandError(
                "ROBOT_NOT_ENABLED",
                "Robot is not enabled",
            )

    def _get_published_library(self) -> FlowLibrary:
        publication = self.publication_store.snapshot()
        return FlowLibrary(
            publication["flow_library"],
            path="published-flow.json",
        )

    def _ipc_validate_flow(self, data=None) -> dict[str, Any]:
        from .workers import validate_grasp_flow_modules

        data = data or {}
        library = self._get_published_library()
        flow_id = str(data.get("flow_id") or library.main_flow_id)
        try:
            flow = library.get_flow(flow_id)
        except KeyError as exc:
            raise IpcCommandError("FLOW_NOT_FOUND", str(exc)) from exc
        errors = validate_grasp_flow_modules(flow["modules"])
        return {
            "valid": not errors,
            "flow_id": flow["id"],
            "flow_name": flow["name"],
            "module_count": len(flow["modules"]),
            "required_cameras": sorted(required_camera_types(flow["modules"])),
            "errors": errors,
            "revision": self.publication_store.status()["revision"],
        }

    def _ipc_get_current_pose(self, _data=None) -> dict[str, Any]:
        if not self.controller.is_connected:
            raise IpcCommandError(
                "ROBOT_NOT_CONNECTED",
                "Robot is not connected",
            )
        pose = self.controller.get_current_pose_fast(
            max_age=1.0,
            fallback=False,
        )
        if not pose:
            raise IpcCommandError("TIMEOUT", "No fresh robot pose is available")
        return {"pose": list(pose), "source": "feedback_cache"}

    def _ipc_get_runtime_logs(self, data=None) -> dict[str, Any]:
        data = data or {}
        try:
            limit = max(1, min(1000, int(data.get("limit", 200))))
        except (TypeError, ValueError) as exc:
            raise IpcCommandError("INVALID_CONFIG", "limit must be an integer") from exc
        path = DEFAULT_LOG_DIR / "runtime.log"
        if not path.exists():
            return {"lines": [], "path": str(path)}
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()[-limit:]
        return {"lines": [line.rstrip("\r\n") for line in lines], "path": str(path)}

    def _start_debug_request(self, request: RuntimeExecutionRequest) -> dict[str, Any]:
        self._require_maintenance()
        self._require_debug_robot()
        readiness = check_flow_readiness(
            self.controller,
            self.program_runner.vision_d435i,
            self.program_runner.vision_d405,
            request.modules,
        )
        if not readiness.ok:
            if any(item in {"D405", "D435i"} for item in readiness.missing_devices):
                raise IpcCommandError("CAMERA_NOT_READY", readiness.message)
            raise IpcCommandError("ROBOT_NOT_CONNECTED", readiness.message)
        if not self.program_runner.start_request(request):
            raise IpcCommandError(
                "TASK_ALREADY_RUNNING",
                "Another Runtime task is already running",
            )
        return {
            "accepted": True,
            "task_id": request.task_id,
            "flow_id": request.flow_id,
            "flow_name": request.flow_name,
            "revision": request.revision,
        }

    def _ipc_start_debug_flow(self, data=None) -> dict[str, Any]:
        data = data or {}
        try:
            request = self.program_runner.build_request(
                mode="debug",
                flow_id=data.get("flow_id"),
            )
        except KeyError as exc:
            raise IpcCommandError("FLOW_NOT_FOUND", str(exc)) from exc
        except ValueError as exc:
            raise IpcCommandError("INVALID_CONFIG", str(exc)) from exc
        return self._start_debug_request(request)

    def _ipc_run_step(self, data=None) -> dict[str, Any]:
        data = data or {}
        try:
            step_index = int(data.get("step_index"))
            request = self.program_runner.build_request(
                mode="debug",
                flow_id=data.get("flow_id"),
                step_index=step_index,
            )
        except (TypeError, ValueError) as exc:
            raise IpcCommandError("INVALID_CONFIG", str(exc)) from exc
        except KeyError as exc:
            raise IpcCommandError("FLOW_NOT_FOUND", str(exc)) from exc
        return self._start_debug_request(request)

    def _ipc_move_to_point(self, data=None) -> dict[str, Any]:
        data = data or {}
        point_name = str(data.get("point_name", "")).strip()
        if not point_name:
            raise IpcCommandError("INVALID_CONFIG", "point_name is required")
        module = {
            "type": "move",
            "name": f"Debug move: {point_name}",
            "params": {
                "target": "saved_point",
                "point_name": point_name,
                "motion_type": str(data.get("motion_type", "MovJ")),
                "speed": int(data.get("speed", 10)),
            },
        }
        try:
            request = self.program_runner.build_request(
                mode="debug",
                modules=[module],
                flow_name=module["name"],
            )
            with use_config_snapshot(request.config):
                if resolve_point(point_name) is None:
                    raise ValueError(f"point does not exist: {point_name}")
        except (TypeError, ValueError) as exc:
            raise IpcCommandError("INVALID_CONFIG", str(exc)) from exc
        return self._start_debug_request(request)

    def _ipc_pause_debug_flow(self, _data=None) -> dict[str, Any]:
        self._require_maintenance()
        if self.program_runner.task_mode != "debug" or not self.program_runner.pause():
            raise IpcCommandError("RUNTIME_BUSY", "No debug flow is running")
        return {"paused": True, "task_id": self.program_runner.task_id}

    def _ipc_resume_debug_flow(self, _data=None) -> dict[str, Any]:
        self._require_maintenance()
        if self.program_runner.task_mode != "debug" or not self.program_runner.resume():
            raise IpcCommandError("RUNTIME_BUSY", "No paused debug flow is running")
        return {"paused": False, "task_id": self.program_runner.task_id}

    def _ipc_stop_debug_flow(self, _data=None) -> dict[str, Any]:
        self._require_maintenance()
        if self.program_runner.task_mode != "debug":
            raise IpcCommandError("RUNTIME_BUSY", "No debug flow is running")
        result = self._ipc_stop_current_task()
        return {**result, "task_id": self.program_runner.task_id}

    def _ipc_get_debug_task_status(self, _data=None) -> dict[str, Any]:
        snapshot = self.program_runner.snapshot()
        return {
            key: snapshot.get(key)
            for key in (
                "running",
                "task_id",
                "task_mode",
                "paused",
                "flow_id",
                "main_flow_id",
                "main_flow_name",
                "module_index",
                "module_name",
                "last_task_result",
                "last_task_error",
                "current_revision",
            )
        }

    def _get_debug_vision(self, camera_type: str):
        if camera_type not in {"D405", "D435i"}:
            raise IpcCommandError(
                "INVALID_CONFIG",
                f"Unsupported camera type: {camera_type}",
            )
        vision = (
            self.program_runner.vision_d405
            if camera_type == "D405"
            else self.program_runner.vision_d435i
        )
        if vision is None or not getattr(vision, "is_available", False):
            raise IpcCommandError(
                "CAMERA_NOT_READY",
                f"{camera_type} is not ready",
            )
        return vision

    def _capture_debug_snapshot(
        self,
        camera_type: str,
        *,
        include_color: bool,
        include_depth: bool,
        include_mask: bool,
        run_detection: bool,
    ) -> dict[str, Any]:
        from .runtime_vision_debug import capture_vision_snapshot

        self._require_maintenance()
        if self.program_runner.snapshot().get("running"):
            raise IpcCommandError(
                "RUNTIME_BUSY",
                "Vision capture is unavailable while a flow is running",
            )
        vision = self._get_debug_vision(camera_type)
        lock = self.program_runner._camera_locks[camera_type]
        with lock:
            try:
                return capture_vision_snapshot(
                    vision,
                    self.controller,
                    camera_type=camera_type,
                    include_color=include_color,
                    include_depth=include_depth,
                    include_mask=include_mask,
                    run_detection=run_detection,
                )
            except Exception as exc:
                raise IpcCommandError("INTERNAL_ERROR", str(exc)) from exc

    def _ipc_test_d405(self, _data=None) -> dict[str, Any]:
        return self._capture_debug_snapshot(
            "D405",
            include_color=False,
            include_depth=False,
            include_mask=False,
            run_detection=False,
        )

    def _ipc_test_d435i(self, _data=None) -> dict[str, Any]:
        return self._capture_debug_snapshot(
            "D435i",
            include_color=False,
            include_depth=False,
            include_mask=False,
            run_detection=False,
        )

    def _ipc_test_detection(self, data=None) -> dict[str, Any]:
        data = data or {}
        return self._capture_debug_snapshot(
            str(data.get("camera_type", "D405")),
            include_color=False,
            include_depth=False,
            include_mask=False,
            run_detection=True,
        )

    def _ipc_get_vision_snapshot(self, data=None) -> dict[str, Any]:
        data = data or {}
        return self._capture_debug_snapshot(
            str(data.get("camera_type", "D405")),
            include_color=bool(data.get("include_color", True)),
            include_depth=bool(data.get("include_depth", False)),
            include_mask=bool(data.get("include_mask", True)),
            run_detection=bool(data.get("run_detection", True)),
        )

    def _ipc_get_visual_servo_telemetry(self, _data=None) -> dict[str, Any]:
        flow = self.program_runner._active_flow
        if flow is None or not hasattr(flow, "get_visual_servo_telemetry"):
            return {"active": False, "telemetry": {}}
        return {
            "active": bool(getattr(flow, "active_visual_servo", None)),
            "telemetry": flow.get_visual_servo_telemetry(),
            "task_id": self.program_runner.task_id,
        }

    def _ipc_stop_current_task(self, _data=None) -> dict[str, Any]:
        flow = getattr(self.controller, "_active_flow_thread", None)
        flow_running = bool(self.program_runner.snapshot().get("running"))
        if flow is not None:
            ctx = getattr(flow, "_ctx", None)
            if ctx is not None:
                ctx.stop_event.set()
            try:
                flow.stop()
            except Exception:
                logger.exception("IPC停止当前流程标志设置失败")

        stop_sent = False
        if self.controller.dashboard is not None:
            try:
                with self.controller._temp_timeout(2.0):
                    self.controller.dashboard.Stop()
                stop_sent = True
            except Exception:
                logger.exception("IPC Stop()失败")
        return {
            "stop_requested": bool(flow is not None or flow_running or stop_sent),
            "flow_was_running": flow_running,
            "stop_sent": stop_sent,
        }

    def _modbus_main_flow_readiness(self):
        with self._maintenance_lock:
            if self.maintenance_mode:
                return FlowReadinessResult(
                    ok=False,
                    missing_devices=("runtime",),
                    reasons=("Runtime处于维护模式",),
                )
        return self.program_runner.check_main_flow_readiness()

    def _runtime_motion_busy(self) -> bool:
        if self.program_runner.snapshot().get("running"):
            return True
        if getattr(self.controller, "_active_flow_thread", None) is not None:
            return True
        modbus_thread = getattr(self.controller, "_modbus_exec_thread", None)
        return bool(modbus_thread is not None and modbus_thread.is_alive())

    def _run_program_from_modbus(self) -> bool:
        with self._maintenance_lock:
            if self.maintenance_mode:
                logger.warning("维护模式下拒绝Modbus生产流程")
                return False
        return self.program_runner()

    def _validate_publication_inputs(
        self,
        config: dict[str, Any],
        library: FlowLibrary,
    ) -> list[str]:
        from .workers import validate_grasp_flow_modules

        errors: list[str] = []
        try:
            ipaddress.ip_address(str(config.get("robot_ip", "")))
        except ValueError:
            errors.append("robot_ip is invalid")
        try:
            port = int(config.get("modbus_port", 502))
            if not 1 <= port <= 65535:
                errors.append("modbus_port must be between 1 and 65535")
        except (TypeError, ValueError):
            errors.append("modbus_port must be an integer")
        camera_config = config.get("camera", {})
        models = (
            camera_config.get("models", {})
            if isinstance(camera_config, dict)
            else {}
        )
        if isinstance(models, dict):
            for camera_type in ("D405", "D435i"):
                configured = models.get(camera_type)
                if not configured:
                    continue
                model_path = Path(str(configured))
                if model_path.suffix.lower() != ".onnx":
                    errors.append(f"{camera_type} model must be an ONNX file")
                elif not model_path.is_file():
                    errors.append(f"{camera_type} model does not exist: {model_path}")
        for flow in library.flows:
            for error in validate_grasp_flow_modules(flow["modules"]):
                errors.append(f"{flow['name']}: {error}")
        return errors

    def validate_startup_inputs(self) -> list[str]:
        publication = self.publication_store.snapshot()
        library = FlowLibrary(
            publication["flow_library"],
            path="published-flow.json",
        )
        errors = self._validate_publication_inputs(
            publication["config"],
            library,
        )
        if self.publication_store.load_error:
            errors.append(self.publication_store.load_error)
        return errors

    def _validate_legacy_startup_inputs(self) -> list[str]:
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
                "maintenance": self.maintenance_mode,
                "startup_delay": self.startup_delay,
                "startup_connect_timeout_s": self.startup_connect_timeout_s,
                "poll_interval": self.poll_interval,
                "last_error": self.last_error or self.supervisor.last_error,
                "startup_errors": list(self.startup_errors),
                "service_mode": self.service_mode,
                "service_name": self.service_name or None,
                "stop_reason": self.stop_reason,
                "stop_marker_path": (
                    str(self.service_stop_marker_path)
                    if self.service_mode
                    else None
                ),
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
            "ipc": self.ipc_server.snapshot(),
            "publication": {
                **self.publication_store.status(),
                "current_task_revision": runner.get("current_revision"),
                "next_task_revision": self.publication_store.status()["revision"],
                "load_error": self.publication_store.load_error,
            },
            "flow": runner,
            "startup_connection": {
                **self.startup_connection.snapshot(),
                "main_flow_id": self._startup_main_flow_id,
                "main_flow_name": self._startup_main_flow_name,
                "fault_latched": False,
                "fault_code": None,
                "controller_fault_code": None,
                "retrying": (
                    self.supervisor.state == RobotConnectionState.CONNECTING
                    or any(
                        thread.is_alive()
                        for thread in self._startup_camera_threads.values()
                    )
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
        if (
            self._pending_camera_reload_revision
            and not self.program_runner.snapshot()["running"]
        ):
            self.program_runner.reload_cameras()
            self._pending_camera_reload_revision = None
        if not self.ensure_modbus_running():
            if self.controller.modbus_server:
                self.controller._write_modbus_status(STATUS_ROBOT_ERR)
        supervisor_state = self.supervisor.step()
        self._update_startup_connection()
        metrics = get_process_metrics(self.health_path)
        if self.maintenance_mode:
            maintenance_error = ""
            if metrics["disk_free_mb"] < self.disk_free_min_mb:
                maintenance_error = (
                    f"disk free space low: {metrics['disk_free_mb']}MB "
                    f"< {self.disk_free_min_mb}MB"
                )
            self.state_store.transition(
                RuntimeState.MAINTENANCE,
                last_error=maintenance_error,
            )
        elif metrics["disk_free_mb"] < self.disk_free_min_mb:
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
        self.controller.set_modbus_program_runner(
            self._run_program_from_modbus,
            readiness_checker=self._modbus_main_flow_readiness,
        )
        if not self.stop_event.is_set() and not self.ipc_server.start():
            self.last_error = (
                f"Runtime IPC启动失败: {self.ipc_server.last_error}"
            )
            logger.error(self.last_error)
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

    def request_stop(self, reason="requested") -> None:
        self.stop_reason = str(reason)
        if self.service_mode:
            try:
                atomic_write_json(
                    self.service_stop_marker_path,
                    {
                        "timestamp": time.time(),
                        "service_name": self.service_name,
                        "reason": self.stop_reason,
                    },
                )
            except Exception:
                logger.exception("failed to write service stop marker")
        self.stop_event.set()

    def stop(self, clean=True) -> None:
        if self._stopped:
            return
        self._stopped = True
        if not self.stop_reason:
            self.stop_reason = "clean_shutdown" if clean else "crash_shutdown"
        self.stop_event.set()
        self.ipc_server.stop()
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
        self.controller.set_runtime_maintenance(False)
        self.maintenance_mode = False
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
            agent.request_stop(f"signal:{signum}")

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
