#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Headless runtime agent for unattended Modbus-driven robot operation."""

from __future__ import annotations

import argparse
import ipaddress
import json
import logging
import os
import queue
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

from ..config.config_manager import (
    CONFIG_FILE,
    LOG_DIR,
    RUNTIME_HEALTH_FILE,
    RUNTIME_PUBLICATION_FILE,
    RUNTIME_STATE_FILE,
    USER_DATA_DIR,
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
from ..flow.flow_library import FlowLibrary, required_camera_types
from ..flow.flow_readiness import FlowReadinessResult, check_flow_readiness
from ..communication.modbus_server import (
    CMD_HOOK,
    CMD_RESET,
    CMD_STOP,
    MODE_AUTO,
    MODE_MANUAL,
    STATUS_HOOK_ERR,
    STATUS_ROBOT_ERR,
)
from ..robot.robot_controller import DobotController
from ..runtime.runtime_resilience import (
    RuntimeState,
    RuntimeStateStore,
    SingleInstanceLock,
    atomic_write_json,
    flow_timeout_seconds,
    get_process_metrics,
    module_timeout_seconds,
)
from ..runtime.startup_connection import StartupConnectionState
from ..runtime.runtime_ipc import (
    DEFAULT_IPC_TOKEN_PATH,
    IpcCommandError,
    RuntimeIpcServer,
    load_ipc_token,
)
from ..runtime.runtime_publication import (
    PublicationError,
    RuntimePublicationStore,
)
from ..runtime.runtime_contract import (
    COMMAND_SPECS,
    validate_payload,
)
from ..runtime.production_state import (
    ERROR_STATES,
    MODBUS_STATUS_MAP,
    ProductionState,
)
from ..flow.flow_result import FailureKind, FlowResult
from ..runtime.production_context import ProductionTaskContext
from ..runtime.production_flow_router import ProductionFlowRouter
from ..runtime.recovery_policy import RecoveryPolicy
from ..runtime.reset_strategy import ResetStrategy

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_HEALTH_PATH = Path(RUNTIME_HEALTH_FILE)
DEFAULT_STATE_PATH = Path(RUNTIME_STATE_FILE)
DEFAULT_LOCK_PATH = Path(USER_DATA_DIR) / "runtime_agent.lock"
DEFAULT_LOG_DIR = Path(LOG_DIR)
DEFAULT_PUBLICATION_PATH = Path(RUNTIME_PUBLICATION_FILE)


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
    # PR 3: when True, the supervisor skips request_connect in step() so
    # the runtime honours PLC 40002=1 (manual offline). Cleared by the
    # runtime agent when 40002=0 + 40001=1 triggers re-online.
    manual_offline: bool = False

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
        self.controller.abort_active_flow_for_disconnect(reason, source="robot")
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
            # PR 3: honour manual offline — do not attempt reconnection
            # while the PLC has signalled 40002=1. The runtime agent
            # clears this flag when 40002=0 + 40001=1 re-online fires.
            if self.manual_offline and not self.controller.is_connected:
                return self.state
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
        self._release_event: Optional[threading.Event] = None
        self.task_id: Optional[str] = None
        self.task_mode: Optional[str] = None
        self.last_task_result: Optional[bool] = None
        self.last_task_error = ""
        # PR 3: optional callback invoked from _run_once's finally block
        # after a production task finishes (success or failure). The
        # runtime agent uses this to transition into HOLDING_HOOK on
        # success or FLOW_ERROR on failure. Signature: (success: bool) -> None.
        self.on_production_finished = None

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

    def build_production_request(
        self,
        flow_id: str,
        task_id: str = "",
    ) -> RuntimeExecutionRequest:
        """Build a production-mode execution request for ``flow_id``.

        PR 3 Task 5: thin wrapper over :meth:`build_request` that fixes
        ``mode="production"`` so callers (production state machine) don't
        have to repeat the mode literal. ``task_mode`` is set to
        ``"production"`` by :meth:`start_request` based on
        ``request.mode``, which already coexists with ``"debug"``.

        PR-FIX-2 Task 1: ``task_id`` lets the caller (``start_new_task``)
        share a single UUID between :class:`ProductionTaskContext` and
        :class:`RuntimeExecutionRequest`. When ``task_id`` is empty the
        request falls back to the ``default_factory`` in
        :class:`RuntimeExecutionRequest` (auto-generated UUID) so legacy
        callers keep working.
        """
        request = self.build_request(mode="production", flow_id=flow_id)
        if task_id:
            request.task_id = task_id
        return request

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
                from ..vision.vision_system import VisionSystem

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

    def _run_once(self, request: RuntimeExecutionRequest | None = None) -> Optional[FlowResult]:
        success = False
        failure_status = STATUS_HOOK_ERR
        task_mode = request.mode if request is not None else "production"
        flow_worker = None
        flow = None
        primary_result: Optional[FlowResult] = None
        try:
            from ..flow.flow_executor import FlowExecutor, validate_grasp_flow_modules

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
                # PR-FIX-3 Task 4: classify readiness failure by
                # primary_failure_kind so the production state machine
                # lands in ROBOT_ERROR (111) / CAMERA_ERROR (112) /
                # FLOW_ERROR (110) instead of a generic FLOW_ERROR.
                primary_kind = readiness.primary_failure_kind
                if primary_kind == FailureKind.ROBOT:
                    readiness_code = "ROBOT_NOT_READY"
                elif primary_kind == FailureKind.CAMERA:
                    readiness_code = "CAMERA_NOT_READY"
                else:
                    readiness_code = "READINESS_FAILED"
                primary_result = FlowResult.failure(
                    code=readiness_code,
                    message=readiness.message,
                    failure_kind=primary_kind,
                    recoverable=False,
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

            finished: list[FlowResult] = []
            self.controller._user_index = int(config_snapshot.get("user_index", 0))
            self.controller._tool_index = int(config_snapshot.get("tool_index", 0))
            self._pause_ref = [False]
            self._release_event = threading.Event()
            flow = FlowExecutor(
                self.controller,
                self.vision_d435i,
                self.vision_d405,
                modules,
                self._pause_ref,
            )
            flow.release_event = self._release_event
            self._active_flow = flow
            flow.on_log = lambda msg: logger.info("runtime flow: %s", msg)
            # PR 4: on_finished now receives a FlowResult; capture the
            # whole object so the production state machine can classify
            # the failure (vision_process / robot / camera / flow).
            flow.on_finished = lambda result: finished.append(result)
            module_deadline = [time.monotonic() + module_timeout_seconds(modules[0])] if modules else [float("inf")]

            def on_progress(current, total, name):
                index = max(0, int(current) - 1)
                self.current_module_index = index
                self.current_module_name = str(name)
                self.last_progress_time = time.monotonic()
                if index < len(modules):
                    module_deadline[0] = self.last_progress_time + module_timeout_seconds(modules[index])
                    params = modules[index].get("params") or {}
                    is_delay_release = (
                        modules[index].get("type") == "delay"
                        and params.get("wait_mode") == "modbus_or_timeout"
                    )
                    state = (
                        RuntimeState.WAITING_DELAY
                        if is_delay_release
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
                    # 生产模式下写 40001 状态码
                    if task_mode == "production":
                        try:
                            if is_delay_release:
                                # 进入延时放行：重置并写 40001=5
                                if self._release_event is not None:
                                    self._release_event.clear()
                                self.controller._write_modbus_status(5)
                            else:
                                # 离开延时或非延时模块：写回 40001=4
                                self.controller._write_modbus_status(4)
                        except Exception:
                            logger.exception("on_progress 写 40001 失败")

            flow.on_progress = on_progress
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
                # PR 4: synthesise a non-recoverable FlowResult so the
                # production callback can still classify a timeout.
                primary_result = FlowResult.failure(
                    code="FLOW_TIMEOUT",
                    message=timeout_reason,
                    failure_kind="flow",
                    recoverable=False,
                )
                return primary_result

            primary_result = finished[-1] if finished else None
            if primary_result is None:
                # Flow ended without invoking on_finished (e.g. validation
                # short-circuit). Treat as non-recoverable flow failure.
                primary_result = FlowResult.failure(
                    code="NO_RESULT",
                    message="flow ended without invoking on_finished",
                    failure_kind="flow",
                    recoverable=False,
                )
            success = bool(primary_result.success)
            self.last_task_result = success
        except Exception as e:
            self.last_task_error = str(e)
            logger.exception("runtime flow runner failed")
            self.controller.record_alarm("Runtime流程", "EXCEPTION", "故障", "后台流程执行异常", raw=e)
            # PR 4: synthesise a non-recoverable FlowResult for exceptions
            # raised by the runner itself (not by the flow's modules).
            primary_result = FlowResult.failure(
                code="RUNNER_EXCEPTION",
                message=str(e),
                failure_kind="flow",
                recoverable=False,
            )
        finally:
            self._active_flow = None
            self._pause_ref = None
            self._release_event = None
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
            # PR-FIX-3 Task 5: only the debug path writes 40001 directly
            # via mark_modbus_program_finished. The production path is
            # driven solely by _on_production_flow_finished through the
            # production state machine (_set_production_state) so that
            # 40001 has a single owner during production.
            if task_mode == "debug":
                self.controller.mark_modbus_program_finished(
                    success,
                    failure_status=failure_status,
                )
            # PR 3 / PR 4: notify the production state machine of task
            # completion. The callback receives the structured FlowResult
            # so it can classify the failure (vision_process / robot /
            # camera / flow) and decide whether to dispatch the
            # error-recovery hook.
            if task_mode == "production":
                callback = self.on_production_finished
                if callback is not None:
                    # If the runner returned early (validation / readiness
                    # failure) without synthesising a FlowResult, build a
                    # generic non-recoverable one here so the callback
                    # always receives a well-formed result.
                    result_to_dispatch = primary_result
                    if result_to_dispatch is None:
                        result_to_dispatch = FlowResult.failure(
                            code="RUNNER_EARLY_RETURN",
                            message=self.last_task_error or "flow runner returned early",
                            failure_kind="flow",
                            recoverable=False,
                        )
                    try:
                        callback(result_to_dispatch)
                    except Exception:
                        logger.exception("on_production_finished callback raised")
        return primary_result

    def run_recovery_sync(self, request: RuntimeExecutionRequest) -> FlowResult:
        """PR 4 Task 6 — run a recovery flow synchronously (no new thread).

        Executes the recovery flow's modules in the CURRENT thread,
        returning the structured :class:`FlowResult`. This is the
        serial-execution path used by the production state machine's
        ``ERROR_RECOVERY`` state.

        Deliberately does NOT:
          * dispatch :attr:`on_production_finished` (anti-recursion);
          * call ``mark_modbus_program_finished`` (preserve original
            error code on 40001);
          * transition ``RuntimeState`` (caller owns state).
        """
        from ..flow.flow_executor import FlowExecutor, validate_grasp_flow_modules

        config_snapshot = request.config
        modules = request.modules
        errors = validate_grasp_flow_modules(modules)
        if errors:
            message = "; ".join(errors)
            logger.error("recovery flow validation failed: %s", message)
            self.controller.record_alarm(
                "Recovery流程", "VALIDATION_FAILED", "故障", message
            )
            return FlowResult.failure(
                code="RECOVERY_VALIDATION_FAILED",
                message=message,
                failure_kind="flow",
                recoverable=False,
            )

        self._pause_ref = [False]
        flow = FlowExecutor(
            self.controller,
            self.vision_d435i,
            self.vision_d405,
            modules,
            self._pause_ref,
        )
        self._active_flow = flow
        flow.on_log = lambda msg: logger.info("recovery flow: %s", msg)
        # on_finished is left unset — flow.run() returns the FlowResult
        # directly and we do not want to re-enter the production callback.
        try:
            with use_config_snapshot(config_snapshot):
                return flow.run()
        except Exception as e:
            logger.exception("recovery flow runner raised")
            return FlowResult.failure(
                code="RECOVERY_EXCEPTION",
                message=str(e),
                failure_kind="flow",
                recoverable=False,
            )
        finally:
            self._active_flow = None
            self._pause_ref = None


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
        # Dedicated Stop channel port. ``None`` disables the Stop channel
        # (used by tests that don't need the second listener).
        _raw_stop_port = runtime_config.get("ipc_stop_port", 8766)
        self.ipc_stop_port: Optional[int] = (
            None if _raw_stop_port is None else int(_raw_stop_port)
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
                Path(USER_DATA_DIR) / "runtime_service_stopped.json",
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
        # PR-FIX-2 Task 4: serialize start_new_task's "set STARTING →
        # create context → build_request → start_request → set RUNNING"
        # sequence so two concurrent 40001=3 dispatches can't both pass
        # the state check and double-start a Runner.
        self._task_start_lock = threading.Lock()
        self.maintenance_mode = False
        self.ipc_server = ipc_server or RuntimeIpcServer(
            self._handle_ipc_command,
            host=self.ipc_host,
            port=self.ipc_port,
            command_timeout_s=self.ipc_command_timeout_s,
            auth_token=self.ipc_auth_token,
            stop_port=self.ipc_stop_port,
        )
        # PR-C Task 2: alarm_history alias for the controller's instance so
        # ``_ipc_clear_alarm_history`` can clear the same backing file the
        # controller writes to via ``record_alarm``. Defensive: some test
        # stubs don't expose ``alarm_history``.
        self.alarm_history = getattr(self.controller, "alarm_history", None)
        # PR-C Task 6: handlers dict is an instance attribute so
        # ``_ipc_get_status`` can advertise ``capabilities``.
        self._handlers: dict[str, Any] = self._build_ipc_handlers()
        # PR 3: production state machine. ``flow_router`` is built from
        # the published flow_library's ``flow_roles`` mapping (PR 2);
        # ``reset_strategy`` is stateless and shared. ``production_state``
        # starts at IDLE and is advanced through STANDBY → RUNNING →
        # HOLDING_HOOK → RESETTING → STANDBY by Modbus commands.
        self.production_state: ProductionState = ProductionState.IDLE
        self.production_task: Optional[ProductionTaskContext] = None
        self.manual_offline: bool = False
        # PR-FIX-3 Task 9: deferred re-online flag — set when
        # _handle_reonline is invoked while the robot is disconnected;
        # cleared (and ResetStrategy retried) once supervisor reconnects.
        self._pending_reonline: bool = False
        self.reset_strategy: ResetStrategy = ResetStrategy()
        # PR 5 Task 4: thread-safe command queue + worker thread. The
        # Modbus Event Loop delegate (_on_modbus_command_delegate) only
        # enqueues (cmd, mode, hook_type) here and returns immediately;
        # the daemon worker thread (_command_worker_thread) drains the
        # queue and dispatches via _dispatch_command, keeping all robot
        # motion / flow / reset work off the Modbus Event Loop.
        self._modbus_command_queue: "queue.Queue[Optional[tuple]]" = queue.Queue()
        self._command_worker_thread: Optional[threading.Thread] = None
        self._command_worker_stop = threading.Event()
        # PR 4: recovery policy decides whether the error-recovery hook
        # may run after a primary flow failure. Stateless and shared.
        self.recovery_policy: RecoveryPolicy = RecoveryPolicy()
        try:
            _publication_for_roles = self.publication_store.snapshot()
            _library_for_roles = FlowLibrary(
                _publication_for_roles["flow_library"],
                path="published-flow.json",
            )
            self.flow_router: ProductionFlowRouter = ProductionFlowRouter(
                _library_for_roles.flow_roles
            )
        except Exception:
            logger.exception("failed to build ProductionFlowRouter from publication; using empty roles")
            self.flow_router = ProductionFlowRouter({})
        # Wire the program_runner's production-finished callback so the
        # state machine learns when a production task completes.
        self.program_runner.on_production_finished = self._on_production_flow_finished
        # Register the modbus command delegate + mode-changed callback so
        # the state machine owns 40001=0/1/3 and 40002 0↔1 transitions.
        # Defensive: the controller may be a test stub that doesn't
        # expose ``set_modbus_program_runner`` / ``set_modbus_mode_changed_callback``.
        try:
            self.controller.set_modbus_program_runner(
                self._run_program_from_modbus,
                readiness_checker=self._modbus_main_flow_readiness,
                command_delegate=self._on_modbus_command_delegate,
            )
        except TypeError:
            # Older signature without command_delegate — fall back to
            # the legacy two-arg form so non-PR-3 tests still work.
            self.controller.set_modbus_program_runner(
                self._run_program_from_modbus,
                readiness_checker=self._modbus_main_flow_readiness,
            )
        if hasattr(self.controller, "set_modbus_mode_changed_callback"):
            self.controller.set_modbus_mode_changed_callback(self._on_mode_changed)
        # PR 5 Task 4: register the 40004 (hook_type) change callback so
        # the runtime emits a diagnostic log whenever the PLC changes
        # 40004, even when no production task is running. Defensive: the
        # controller may be a test stub that doesn't expose the setter.
        if hasattr(self.controller, "set_modbus_hook_type_changed_callback"):
            self.controller.set_modbus_hook_type_changed_callback(
                self._on_hook_type_changed
            )
        # PR-FIX-3 Task 6: register the production-finished callback so the
        # controller can route synthesized FlowResults from
        # abort_active_flow_for_disconnect into the state machine instead of
        # writing 40001 directly. Defensive: the controller may be a test
        # stub that doesn't expose the setter.
        if hasattr(self.controller, "set_production_finished_callback"):
            self.controller.set_production_finished_callback(
                self._on_production_flow_finished
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
                self.controller.abort_active_flow_for_disconnect(reason, source="camera")
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
        handler = self._handlers.get(command)
        if handler is None:
            raise IpcCommandError(
                "UNKNOWN_COMMAND",
                f"不支持的命令: {command}",
            )
        # PR-C Task 1: validate payload against COMMAND_SPECS before dispatch.
        ok, reason = validate_payload(command, data)
        if not ok:
            raise IpcCommandError(
                "INVALID_CONFIG",
                f"{command}: {reason}",
            )
        return handler(data)

    def _build_ipc_handlers(self) -> dict[str, Any]:
        """Build the canonical command → handler mapping.

        Stored as ``self._handlers`` so :meth:`_ipc_get_status` can expose
        the supported command list as ``capabilities`` (PR-C Task 6).
        """
        return {
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
            "start_production_flow": self._ipc_start_production_flow,
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
            "safe_stop": self._ipc_safe_stop,
            # PR-C Task 2: hardware-facing handlers.
            "enable_robot": self._ipc_enable_robot,
            "disable_robot": self._ipc_disable_robot,
            "clear_alarms": self._ipc_clear_alarms,
            "connect_robot": self._ipc_connect_robot,
            "set_collision_level": self._ipc_set_collision_level,
            "connect_camera": self._ipc_connect_camera,
            "disconnect_camera": self._ipc_disconnect_camera,
            "start_modbus": self._ipc_start_modbus,
            "stop_modbus": self._ipc_stop_modbus,
            "clear_alarm_history": self._ipc_clear_alarm_history,
        }

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
            # PR-C Task 6: advertise supported commands so the GUI can
            # gray out buttons whose command isn't available.
            "capabilities": list(self._handlers.keys()),
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
        from ..flow.flow_executor import validate_grasp_flow_modules

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
        # PR-C Task 5.4: reject debug flow while a production task is running.
        if self.program_runner.task_mode == "production":
            raise IpcCommandError(
                "RUNTIME_BUSY",
                "生产流程运行中，无法启动调试流程",
            )
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
        from ..runtime.runtime_vision_debug import capture_vision_snapshot

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

    def _ipc_safe_stop(self, _data=None) -> dict[str, Any]:
        """Best-effort software emergency stop usable from the Stop channel.

        Sets the active flow's ``stop_event`` to interrupt in-flight motion
        and then issues ``controller.emergency_stop()`` to drop the robot
        enable state. Never raises ``IpcCommandError`` so the GUI always
        receives a response (failures are reported in ``error``).
        """
        emergency_stop_sent = False
        stop_event_set = False
        error_msg = ""

        # 1. Signal any active flow to stop immediately (mirrors
        #    _ipc_stop_current_task, but tolerant of missing state).
        try:
            flow = getattr(self.controller, "_active_flow_thread", None)
            if flow is not None:
                ctx = getattr(flow, "_ctx", None)
                if ctx is not None:
                    ctx.stop_event.set()
                    stop_event_set = True
                try:
                    flow.stop()
                except Exception:
                    logger.exception("safe_stop: flow.stop() 失败")
        except Exception:
            logger.exception("safe_stop: 设置 stop_event 失败")

        # 2. Drop the robot enable state via the independent EmergencyStop path.
        try:
            self.controller.emergency_stop()
            emergency_stop_sent = True
        except Exception as exc:
            logger.exception("safe_stop: emergency_stop() 失败")
            error_msg = str(exc)

        return {
            "emergency_stop_sent": emergency_stop_sent,
            "stop_event_set": stop_event_set,
            "error": error_msg,
        }

    # -- PR-C Task 2: hardware-facing IPC handlers -------------------------

    def _ipc_enable_robot(self, _data=None) -> dict[str, Any]:
        self.controller.enable_robot()
        return {"enabled": True}

    def _ipc_disable_robot(self, _data=None) -> dict[str, Any]:
        self.controller.disable_robot()
        return {"enabled": False}

    def _ipc_clear_alarms(self, _data=None) -> dict[str, Any]:
        self.controller.clear_error()
        return {"cleared": True}

    def _ipc_connect_robot(self, data=None) -> dict[str, Any]:
        data = data or {}
        ip = str(data.get("ip", "")).strip()
        if ip and hasattr(self.controller, "set_robot_ip"):
            self.controller.set_robot_ip(ip)
        connected = bool(self.controller.connect())
        if not connected:
            raise IpcCommandError(
                "ROBOT_NOT_CONNECTED",
                self.controller.last_error or "connect failed",
            )
        return {"connected": True}

    def _ipc_set_collision_level(self, data=None) -> dict[str, Any]:
        data = data or {}
        level = int(data.get("level"))
        self.controller.set_collision_level(level)
        return {"level": level}

    def _ipc_connect_camera(self, data=None) -> dict[str, Any]:
        data = data or {}
        camera_type = str(data.get("camera_type", "")).strip()
        if camera_type not in ("D435i", "D405"):
            raise IpcCommandError(
                "INVALID_CONFIG",
                f"Unsupported camera type: {camera_type}",
            )
        # ``_ensure_camera`` is the canonical path used by the program runner
        # and startup supervisor; reuse it so the camera is registered in
        # ``program_runner.vision_d435i`` / ``vision_d405``.
        if not self.program_runner._ensure_camera(camera_type):
            raise IpcCommandError(
                "CAMERA_NOT_READY",
                f"{camera_type} camera connection failed",
            )
        return {"connected": True, "camera_type": camera_type}

    def _ipc_disconnect_camera(self, data=None) -> dict[str, Any]:
        data = data or {}
        camera_type = str(data.get("camera_type", "")).strip()
        if camera_type not in ("D435i", "D405"):
            raise IpcCommandError(
                "INVALID_CONFIG",
                f"Unsupported camera type: {camera_type}",
            )
        attr = "vision_d405" if camera_type == "D405" else "vision_d435i"
        lock = self.program_runner._camera_locks[camera_type]
        with lock:
            vision = getattr(self.program_runner, attr)
            if vision is not None:
                try:
                    vision.close()
                except Exception:
                    logger.exception("runtime failed to close %s camera", camera_type)
                setattr(self.program_runner, attr, None)
        return {"disconnected": True, "camera_type": camera_type}

    def _ipc_start_modbus(self, _data=None) -> dict[str, Any]:
        ok = bool(
            self.controller.start_modbus(
                port=self.modbus_port,
                slave_id=self.modbus_slave_id,
            )
        )
        if not ok:
            raise IpcCommandError(
                "INTERNAL_ERROR",
                "Modbus server start failed",
            )
        return {"running": True}

    def _ipc_stop_modbus(self, _data=None) -> dict[str, Any]:
        try:
            self.controller.stop_modbus()
        except Exception as exc:
            raise IpcCommandError("INTERNAL_ERROR", str(exc)) from exc
        return {"running": False}

    def _ipc_clear_alarm_history(self, _data=None) -> dict[str, Any]:
        if self.alarm_history is not None:
            self.alarm_history.clear()
        return {"cleared": True}

    # -- PR-C Task 5: Production flow handler ------------------------------

    def _start_production_request(self, request: RuntimeExecutionRequest) -> dict[str, Any]:
        """Start a production flow request with mutual-exclusion guard.

        Mirrors :meth:`_start_debug_request` but skips the maintenance-mode
        requirement (production is triggered by Modbus / IPC, not debug UI).
        """
        if self.program_runner.task_mode == "debug":
            raise IpcCommandError(
                "RUNTIME_BUSY",
                "调试流程运行中，无法启动生产流程",
            )
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

    def _ipc_start_production_flow(self, data=None) -> dict[str, Any]:
        data = data or {}
        try:
            request = self.program_runner.build_request(
                mode="production",
                flow_id=data.get("flow_id"),
            )
        except KeyError as exc:
            raise IpcCommandError("FLOW_NOT_FOUND", str(exc)) from exc
        except ValueError as exc:
            raise IpcCommandError("INVALID_CONFIG", str(exc)) from exc
        return self._start_production_request(request)

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
        """Modbus 40001=3 production trigger.

        PR-C Task 5.3: routes through the production-flow path so the
        debug/production mutual-exclusion guard applies uniformly. Returns
        ``True`` when a production task was accepted, ``False`` otherwise.

        PR 3: retained as a backward-compat entry point. The state machine
        now routes cmd=3 through :meth:`_handle_hook_command` via the
        command delegate; this method is only reached when no delegate is
        registered (e.g. legacy tests).
        """
        with self._maintenance_lock:
            if self.maintenance_mode:
                logger.warning("维护模式下拒绝Modbus生产流程")
                return False
        # PR-C Task 5: reject when a debug flow owns the runner.
        if self.program_runner.task_mode == "debug":
            logger.warning("调试流程运行中，拒绝Modbus生产流程")
            return False
        try:
            request = self.program_runner.build_request(mode="production")
        except Exception:
            logger.exception("Modbus production build_request failed")
            return False
        return self.program_runner.start_request(request)

    # ------------------------------------------------------------------
    # PR 3 — Production state machine
    # ------------------------------------------------------------------

    def _set_production_state(
        self,
        new_state: ProductionState,
        reason: str = "",
    ) -> None:
        """Transition the production state machine to ``new_state``.

        Logs the transition and writes the PLC-facing 40001 status code
        (via :data:`MODBUS_STATUS_MAP`) when the new state has a mapping.
        States without a mapping (``MANUAL_OFFLINE`` / ``RESETTING`` /
        ``ERROR_RECOVERY``) skip the 40001 write — the caller is
        responsible for any PLC signal in those transitions.

        PR 5 Task 3: emits a structured transition log that includes the
        ``task_id`` (when a task is active) so operators can correlate
        state changes with production tasks in the log stream.
        """
        old_state = self.production_state
        if old_state == new_state:
            return
        task = self.production_task
        task_id = task.task_id if task is not None else None
        logger.info(
            "ProductionState transition: %s → %s (reason=%s, task_id=%s)",
            old_state.value,
            new_state.value,
            reason or "",
            task_id,
        )
        self.production_state = new_state
        if task is not None:
            task.state = new_state.value
        status_code = MODBUS_STATUS_MAP.get(new_state)
        if status_code is not None:
            try:
                self.controller._write_modbus_status(status_code)
            except Exception:
                logger.exception("failed to write 40001 for new production state")

    def _write_production_40001(self, value: int) -> None:
        """Force-write a specific value to 40001 (e.g. 4 for RUNNING)."""
        try:
            self.controller._write_modbus_status(value)
        except Exception:
            logger.exception("failed to write 40001=%d", value)

    # ------------------------------------------------------------------
    # PR 5 Task 4 — PLC diagnostic logging
    # ------------------------------------------------------------------

    # 40001 command value → human-readable name for diagnostic logs.
    _CMD_NAME_MAP: dict[int, str] = {
        0: "pause",
        1: "reset",
        2: "standby",
        3: "start_hook",
        4: "running",
        5: "holding_hook",
        110: "flow_error",
        111: "robot_error",
        112: "camera_error",
    }

    # 40002 mode value → human-readable name for diagnostic logs.
    _MODE_NAME_MAP: dict[int, str] = {0: "auto", 1: "manual"}

    # 40004 hook_type value → human-readable name for diagnostic logs.
    _HOOK_TYPE_NAME_MAP: dict[int, str] = {0: "low_hook", 1: "high_hook"}

    def _log_plc_diagnostic_40001(
        self, cmd: int, mode: int, hook_type: int
    ) -> None:
        """PR 5 Task 4 — emit a diagnostic log for a 40001 command write.

        Format::

            PLC diagnostic: 40001={cmd} (cmd={cmd_name}, mode={mode_name},
            hook_type={hook_type_name}, task_id={task_id})
        """
        task = self.production_task
        task_id = task.task_id if task is not None else None
        logger.info(
            "PLC diagnostic: 40001=%d (cmd=%s, mode=%s, hook_type=%s, task_id=%s)",
            int(cmd),
            self._CMD_NAME_MAP.get(int(cmd), str(cmd)),
            self._MODE_NAME_MAP.get(int(mode), str(mode)),
            self._HOOK_TYPE_NAME_MAP.get(int(hook_type), str(hook_type)),
            task_id,
        )

    def _on_mode_changed(self, old_mode: int, new_mode: int) -> None:
        """40002 mode-change handler (PR 3 Task 10 + Task 11).

        * 0 → 1: manual offline — terminate flow, stop, close robot,
          set ``manual_offline=True``, transition to MANUAL_OFFLINE.
        * 1 → 0: re-online is deferred until 40001=1 arrives (handled
          in :meth:`_handle_reset_command`).

        PR 5 Task 4: emits a PLC diagnostic log for every 40002 change.
        """
        logger.info(
            "PLC diagnostic: 40002 mode %s → %s (old=%s, new=%s, task_id=%s)",
            self._MODE_NAME_MAP.get(int(old_mode), str(old_mode)),
            self._MODE_NAME_MAP.get(int(new_mode), str(new_mode)),
            int(old_mode),
            int(new_mode),
            self.production_task.task_id if self.production_task else None,
        )
        if old_mode == MODE_AUTO and new_mode == MODE_MANUAL:
            self._enter_manual_offline()
        elif old_mode == MODE_MANUAL and new_mode == MODE_AUTO:
            logger.info(
                "40002 1→0：等待 40001=1 触发重新上线 (state=%s)",
                self.production_state.value,
            )

    def _on_hook_type_changed(self, old_hook: int, new_hook: int) -> None:
        """PR 5 Task 4 — 40004 (hook_type) change diagnostic handler.

        Invoked by the Modbus server whenever 40004 changes, regardless
        of whether a production task is running. The running task's
        ``hook_type`` is NOT modified here (per PR 3 latching rule);
        the log simply records the PLC-side change for diagnostics.
        """
        task = self.production_task
        task_id = task.task_id if task is not None else None
        latched = int(task.hook_type) if task is not None else None
        logger.info(
            "PLC diagnostic: 40004 hook_type %s → %s (old=%d, new=%d, "
            "task_id=%s, latched_hook_type=%s)",
            self._HOOK_TYPE_NAME_MAP.get(int(old_hook), str(old_hook)),
            self._HOOK_TYPE_NAME_MAP.get(int(new_hook), str(new_hook)),
            int(old_hook),
            int(new_hook),
            task_id,
            latched,
        )

    def _on_modbus_command_delegate(
        self,
        cmd: int,
        mode: int,
        hook_type: int,
    ) -> bool:
        """PR 3 command delegate — owns 40001 dispatch in auto mode.

        Returns ``True`` when the command was fully handled by the state
        machine; ``False`` lets the controller's default dispatch run.

        PR 5 Task 4: emits a PLC diagnostic log for every 40001 command
        so operators can audit PLC ↔ runtime interactions.

        PR 5 Task 4 (decouple): this delegate now ONLY parses and
        enqueues. It never executes robot motion, flow start, or reset
        synchronously — that work is done by the daemon worker thread
        (:meth:`_command_worker_loop`) via :meth:`_dispatch_command`.
        Manual-mode commands (``mode != MODE_AUTO``) return ``False`` so
        the controller's default handling applies; auto-mode commands
        are enqueued and the delegate returns ``True`` (consumed).
        """
        # PR 5 Task 4: diagnostic log for 40001 commands (kept here for
        # timely logging before enqueue).
        self._log_plc_diagnostic_40001(cmd, mode, hook_type)
        # Manual mode commands always fall through to the controller's
        # default handling (which ignores them).
        if mode != MODE_AUTO:
            return False
        # Enqueue (cmd, mode, hook_type) and return immediately. The
        # worker thread drains the queue and dispatches via
        # _dispatch_command, keeping the Modbus Event Loop non-blocking.
        self._modbus_command_queue.put((cmd, mode, hook_type))
        return True

    def _command_worker_loop(self) -> None:
        """PR 5 Task 4 — daemon worker that drains the command queue.

        Runs in a dedicated thread (``_command_worker_thread``). Blocks
        on :pyattr:`_modbus_command_queue.get`; a ``None`` sentinel
        causes a graceful exit. Each item is dispatched via
        :meth:`_dispatch_command`. Exceptions are logged but never
        propagate (the worker must not die on a single bad command).
        """
        while True:
            item = self._modbus_command_queue.get()
            if item is None:
                # Sentinel: graceful shutdown requested.
                break
            cmd, mode, hook_type = item
            try:
                self._dispatch_command(cmd, mode, hook_type)
            except Exception as e:  # noqa: BLE001 — worker must survive
                logger.exception(
                    "Command worker error: cmd=%s mode=%s hook_type=%s: %s",
                    cmd, mode, hook_type, e,
                )

    def _dispatch_command(self, cmd: int, mode: int, hook_type: int) -> None:
        """PR 5 Task 4 — original delegate dispatch logic, run off the
        Modbus Event Loop by the worker thread.

        Contains the RESETTING guard and cmd==3/0/1 branching that
        previously lived in :meth:`_on_modbus_command_delegate`. The
        mode guard is retained defensively (only auto-mode commands are
        enqueued, but this protects against future callers).
        """
        if mode != MODE_AUTO:
            return
        # RESETTING is a transient state — reject all commands except
        # 40001=0 (hard stop) which is allowed to fall through as a
        # no-op here (the delegate already returned True, so the
        # controller's default path is bypassed by design).
        if self.production_state == ProductionState.RESETTING:
            if cmd == CMD_STOP:
                return
            logger.warning(
                "RESETTING 状态下忽略 40001=%d（复位进行中）",
                cmd,
            )
            return
        if cmd == CMD_HOOK:
            self._handle_hook_command(hook_type)
            return
        if cmd == CMD_STOP:
            self._handle_pause_command()
            return
        if cmd == CMD_RESET:
            # 延时放行检查：如果当前正在延时放行等待中，触发放行而非复位
            if self._is_in_delay_release_wait():
                self._release_delay_wait()
                return
            self._handle_reset_command()
            return

    def _handle_hook_command(self, hook_type: int) -> None:
        """40001=3 dispatch — state-dependent hook command handling.

        * PAUSED → resume current task
        * RUNNING → ignore duplicate command (log only)
        * STARTING → ignore duplicate command (log only); PR-FIX-2 Task 3
        * HOLDING_HOOK → reject command (log only)
        * STANDBY / IDLE → start a new task
        * other states → reject command
        """
        state = self.production_state
        if state == ProductionState.PAUSED:
            self._resume_current_task()
            return
        if state == ProductionState.RUNNING:
            logger.info("40001=3 收到但 state=RUNNING，忽略重复命令")
            return
        if state == ProductionState.STARTING:
            logger.warning("40001=3 收到但 state=STARTING，忽略重复命令（任务启动中）")
            return
        if state == ProductionState.HOLDING_HOOK:
            logger.warning("40001=3 在 HOLDING_HOOK 状态下被拒绝（请先 40001=1 复位）")
            return
        if state in (ProductionState.STANDBY, ProductionState.IDLE):
            self.start_new_task(hook_type)
            return
        logger.warning(
            "40001=3 在 state=%s 下被拒绝",
            state.value,
        )

    def start_new_task(self, hook_type: int) -> None:
        """Create a ProductionTaskContext and start the primary flow.

        PR 3 Task 6.4 + Task 7: ``hook_type`` is latched into the
        :class:`ProductionTaskContext` at creation time. Mid-run 40004
        changes do NOT modify the running task (see
        :meth:`_on_modbus_command_delegate`).

        PR-FIX-2 Task 1-4: the sequence is now atomic and ordered to
        eliminate the race window in which a fast-completing flow could
        fire ``_on_production_flow_finished`` before the context existed.

          1. acquire ``_task_start_lock``
          2. transition to ``STARTING`` (40001 keeps its previous value
             because ``STARTING`` is not in ``MODBUS_STATUS_MAP``)
          3. resolve flow ids
          4. create :class:`ProductionTaskContext` (generates the task_id)
          5. ``build_production_request(flow_id, task_id=context.task_id)``
             so the request reuses the context's UUID
          6. ``start_request`` — on failure roll back (clear context,
             revert to ``STANDBY``); on success advance to ``RUNNING``

        The context is assigned to ``self.production_task`` BEFORE
        ``start_request`` so the finished-callback can always find it.
        """
        with self._maintenance_lock:
            if self.maintenance_mode:
                logger.warning("维护模式下拒绝启动新生产任务")
                return
        if self.program_runner.task_mode == "debug":
            logger.warning("调试流程运行中，拒绝启动新生产任务")
            return
        with self._task_start_lock:
            # PR-FIX-2 Task 5: reject empty production flows before any
            # state transition (no STARTING, no context creation).
            try:
                pending_flow_id = self.flow_router.resolve_primary(hook_type)
                pending_flow = self._get_published_library().get_flow(pending_flow_id)
            except Exception:
                pending_flow = None
            if pending_flow is not None and len(pending_flow.get("modules", [])) == 0:
                logger.error("生产流程 %s 模块为空，拒绝启动", pending_flow_id)
                return
            # PR-FIX-2 Task 3: signal "starting" to the PLC and reject
            # duplicate 40001=3 dispatches via _handle_hook_command.
            self._set_production_state(
                ProductionState.STARTING,
                reason=f"hook={hook_type}",
            )
            try:
                primary_flow_id = self.flow_router.resolve_primary(hook_type)
                recovery_flow_id = self.flow_router.resolve_recovery()
            except ValueError as exc:
                logger.error("无法解析生产流程: %s", exc)
                self._set_production_state(
                    ProductionState.FLOW_ERROR,
                    reason=f"flow resolve failed: {exc}",
                )
                return
            # PR-FIX-2 Task 1+2: create the context FIRST so its task_id
            # is the single source of truth and the finished-callback
            # can find a task even if the flow completes immediately.
            self.production_task = ProductionTaskContext.create(
                hook_type=hook_type,
                primary_flow_id=primary_flow_id,
                recovery_flow_id=recovery_flow_id,
                state=ProductionState.STARTING.value,
            )
            try:
                request = self.program_runner.build_production_request(
                    primary_flow_id,
                    task_id=self.production_task.task_id,
                )
            except Exception:
                logger.exception("build_production_request failed")
                self.production_task = None
                self._set_production_state(
                    ProductionState.FLOW_ERROR,
                    reason="build_production_request failed",
                )
                return
            if not self.program_runner.start_request(request):
                # PR-FIX-2 Task 4: rollback on start_request failure —
                # clear the context and revert to STANDBY so the PLC
                # can retry without a full error reset.
                logger.error(
                    "program_runner.start_request 拒绝了新任务 (task_id=%s)",
                    self.production_task.task_id,
                )
                self.production_task = None
                self._set_production_state(
                    ProductionState.STANDBY,
                    reason="start_request rejected; rolled back",
                )
                return
            # Task accepted — advance to RUNNING.
            self._set_production_state(
                ProductionState.RUNNING,
                reason=f"task_id={self.production_task.task_id} hook={hook_type}",
            )

    def _resume_current_task(self) -> None:
        """40001=3 in PAUSED — resume the paused task (PR 3 Task 9)."""
        task = self.production_task
        if task is None:
            logger.warning("40001=3 PAUSED 但无 production_task；回退到 STANDBY")
            self._set_production_state(ProductionState.STANDBY)
            return
        # Resume the FlowExecutor + robot motion. ``program_runner.resume``
        # returns False when there's no active flow (e.g. the flow exited
        # while paused); we still advance state to RUNNING so the next
        # 40001=0 can pause again.
        try:
            self.program_runner.resume()
        except Exception:
            logger.exception("program_runner.resume raised during PAUSED -> RUNNING")
        try:
            self.controller.continue_motion()
        except Exception:
            logger.exception("controller.continue_motion raised during PAUSED -> RUNNING")
        # Do NOT create a new task_id; do NOT re-read 40004.
        self._set_production_state(
            ProductionState.RUNNING,
            reason=f"resumed task_id={task.task_id}",
        )

    def _is_in_delay_release_wait(self) -> bool:
        """检查当前是否处于延时放行等待状态。

        判据：production_state 为 RUNNING（延时期间不改变生产状态），
        且 program_runner 的 release_event 存在，
        且 program_runner 的当前模块是 delay + modbus_or_timeout。
        """
        if self.production_state != ProductionState.RUNNING:
            return False
        runner = self.program_runner
        if runner is None or runner._release_event is None:
            return False
        # 检查当前模块是否为 delay + modbus_or_timeout
        # 通过 RuntimeState 判断更可靠：WAITING_DELAY 状态表示在延时放行中
        # 但 RuntimeState 在 program_runner 上，不在 agent 上
        # 简化判据：release_event 存在即可能在延时中
        return True

    def _release_delay_wait(self) -> None:
        """放行当前延时等待，让流程继续下一步。"""
        runner = self.program_runner
        if runner is None or runner._release_event is None:
            logger.warning("收到 40001=1 放行命令但无活跃的延时等待")
            return
        logger.info("40001=1 延时放行触发，release_event.set()")
        runner._release_event.set()
        # 放行后重置 release_event 以备下次使用
        # 注意：不能立即 clear，因为 FlowExecutor 还在等待循环中检查
        # clear 操作在 on_progress 下次进入 delay 模块时处理

    def _handle_pause_command(self) -> bool:
        """40001=0 in auto mode — pause when RUNNING (PR 3 Task 8).

        Returns ``True`` when the state machine handled the pause (state
        was RUNNING); ``False`` to fall through to the controller's
        default stop+clear-faults path (used when not in RUNNING state).
        """
        if self.production_state != ProductionState.RUNNING:
            return False
        task = self.production_task
        # Pause the FlowExecutor (sets _pause_ref[0] = True) and the
        # robot motion. Preserve ProductionTaskContext — do NOT clear
        # it, do NOT stop_event.set().
        try:
            self.program_runner.pause()
        except Exception:
            logger.exception("program_runner.pause raised during RUNNING -> PAUSED")
        try:
            self.controller.pause()
        except Exception:
            logger.exception("controller.pause raised during RUNNING -> PAUSED")
        if task is not None and self.program_runner.current_module_index is not None:
            task.paused_at_step = int(self.program_runner.current_module_index)
        self._set_production_state(
            ProductionState.PAUSED,
            reason=f"paused task_id={task.task_id}" if task else "paused",
        )
        return True

    def _handle_reset_command(self) -> bool:
        """40001=1 — state-aware reset via ResetStrategy (PR 3 Task 13).

        Returns ``True`` when the state machine owns this reset (state is
        HOLDING_HOOK / PAUSED / ERROR_STATES / MANUAL_OFFLINE); ``False``
        to fall through to the controller's default ``_modbus_move_initial``
        path (used for IDLE / STANDBY).
        """
        state = self.production_state
        if state == ProductionState.MANUAL_OFFLINE:
            # Re-online flow is triggered separately via 40002=0 + 40001=1.
            # When we reach here, 40002 has already flipped back to 0; run
            # the re-online sequence.
            self._handle_reonline()
            return True
        if state not in (
            ProductionState.HOLDING_HOOK,
            ProductionState.PAUSED,
            *ERROR_STATES,
        ):
            return False
        # Enter RESETTING; prohibit other commands until reset completes.
        self._set_production_state(
            ProductionState.RESETTING,
            reason=f"reset from {state.value}",
        )
        try:
            success = self.reset_strategy.execute(
                source_state=state,
                controller=self.controller,
                program_runner=self.program_runner,
            )
        except Exception:
            logger.exception("ResetStrategy.execute raised")
            success = False
        if success:
            self.production_task = None
            self._set_production_state(
                ProductionState.STANDBY,
                reason="reset complete",
            )
            self._write_production_40001(2)  # STATUS_STANDBY
        else:
            self._set_production_state(
                ProductionState.FLOW_ERROR,
                reason="reset failed",
            )
            self._write_production_40001(110)  # STATUS_HOOK_ERR
        return True

    def _enter_manual_offline(self) -> None:
        """PR 3 Task 10 — 40002 0→1 manual offline sequence."""
        logger.warning("进入手动下线流程 (40002 0→1)")
        # Terminate any active flow.
        try:
            self.program_runner.stop()
        except Exception:
            logger.exception("program_runner.stop failed during manual offline")
        # Stop robot motion.
        try:
            if self.controller.dashboard is not None:
                self.controller.dashboard.Stop()
        except Exception:
            logger.exception("dashboard.Stop failed during manual offline")
        # Clear the production task context.
        self.production_task = None
        # Close the robot connection.
        try:
            self.controller.close_robot_transport()
        except Exception:
            logger.exception("close_robot_transport failed during manual offline")
        # Disable supervisor reconnection.
        self.manual_offline = True
        self.supervisor.manual_offline = True
        self._set_production_state(
            ProductionState.MANUAL_OFFLINE,
            reason="40002 0→1",
        )

    def _handle_reonline(self) -> None:
        """PR 3 Task 11 — 40002=0 + 40001=1 re-online sequence."""
        logger.info("重新上线流程 (MANUAL_OFFLINE + 40002=0 + 40001=1)")
        self.manual_offline = False
        self.supervisor.manual_offline = False
        # Trigger an immediate reconnect attempt.
        try:
            self.supervisor.request_connect()
        except Exception:
            logger.exception("supervisor.request_connect failed during re-online")
        # Once connected: ClearError + EnableRobot + ResetStrategy +
        # standby + 40001=2. The reset strategy runs synchronously; if
        # the robot isn't connected yet, the strategy's motion calls
        # will fail gracefully and we transition to FLOW_ERROR.
        if not self.controller.is_connected:
            logger.warning(
                "重新上线时机器人未连接；复位推迟到下次 supervisor 连接成功"
            )
            self._pending_reonline = True
            return
        try:
            self.reset_strategy.execute(
                source_state=ProductionState.MANUAL_OFFLINE,
                controller=self.controller,
                program_runner=self.program_runner,
            )
        except Exception:
            logger.exception("ResetStrategy.execute failed during re-online")
        self._set_production_state(
            ProductionState.STANDBY,
            reason="re-online complete",
        )
        self._write_production_40001(2)  # STATUS_STANDBY
        # PR-FIX-3 Task 9: defensive clear — the deferred path in tick()
        # also clears this flag, but clear here too in case the flag was
        # left set from a prior deferred attempt that succeeded directly.
        self._pending_reonline = False

    def _on_production_flow_finished(self, result: FlowResult) -> None:
        """PR 3 / PR 4 — program_runner completion callback.

        On success: transition to HOLDING_HOOK (40001=5).

        On failure: classify by ``result.failure_kind`` and decide
        whether the error-recovery hook may run:

          * ``robot``         → ROBOT_ERROR (40001=111), never recover.
          * ``camera``        → CAMERA_ERROR (40001=112), recover if
                                 policy allows and recovery flow does
                                 not need the failed camera.
          * ``vision_process``/``flow``/``protocol``/other
                              → FLOW_ERROR (40001=110), recover if
                                 policy allows.

        Recovery (when allowed) runs synchronously via
        :meth:`RuntimeProgramRunner.run_recovery_sync` in the SAME
        orchestration context — no new async Runner. Recovery success
        does NOT clear the original error code: the final state is
        still FLOW_ERROR (110) / CAMERA_ERROR (112).

        Anti-recursion: if ``production_task.recovery_started`` is
        already ``True``, recovery is skipped and the final error
        state is entered directly.
        """
        if self.production_state not in (
            ProductionState.RUNNING,
            ProductionState.STARTING,
        ):
            logger.info(
                "production flow finished but state=%s; ignoring completion callback",
                self.production_state.value,
            )
            return

        # ---- Success path ------------------------------------------------
        if result.success:
            self._set_production_state(
                ProductionState.HOLDING_HOOK,
                reason="primary flow success",
            )
            # 40001=5 (STATUS_HOOK_OK) is written by
            # mark_modbus_program_finished; reaffirm to be safe.
            self._write_production_40001(5)
            return

        # ---- Failure path: classify by failure_kind ----------------------
        task = self.production_task
        # PR-FIX-3 Task 8: use typed FailureKind instead of string
        # comparison. FailureKind inherits from str, so legacy callers
        # that persisted a string still compare equal, but the state
        # machine branches below are now type-safe.
        if isinstance(result.failure_kind, FailureKind):
            failure_kind = result.failure_kind
        else:
            failure_kind = FailureKind.FLOW
        # Record failure info on the task context for diagnostics / reset.
        if task is not None:
            task.failure_code = result.code
            task.failure_kind = failure_kind.value  # keep ProductionTaskContext.failure_kind as str

        # 111 — robot fault: never attempt recovery.
        if failure_kind == FailureKind.ROBOT:
            self._set_production_state(
                ProductionState.ROBOT_ERROR,
                reason=f"robot failure: code={result.code}",
            )
            # 40001=111 is written by _set_production_state via
            # MODBUS_STATUS_MAP.
            return

        # 110 / 112 — flow or camera failure: pick the final state now
        # so we know where to land after recovery (or if we skip it).
        if failure_kind == FailureKind.CAMERA:
            final_state = ProductionState.CAMERA_ERROR
        else:
            final_state = ProductionState.FLOW_ERROR

        # Anti-recursion: never trigger recovery twice for the same task.
        if task is not None and task.recovery_started:
            logger.warning(
                "recovery_already_started: skipping recovery for failure_kind=%s code=%s",
                failure_kind,
                result.code,
            )
            self._set_production_state(
                final_state,
                reason=f"recovery already attempted (code={result.code})",
            )
            return

        # Consult the recovery policy.
        try:
            can_recover = self.recovery_policy.can_recover(result, self.controller)
        except Exception:
            logger.exception("RecoveryPolicy.can_recover raised; treating as non-recoverable")
            can_recover = False

        if not can_recover:
            self._set_production_state(
                final_state,
                reason=f"non-recoverable: code={result.code} kind={failure_kind}",
            )
            return

        # ---- Enter ERROR_RECOVERY and run the hook synchronously --------
        if task is not None:
            task.recovery_started = True
        self._set_production_state(
            ProductionState.ERROR_RECOVERY,
            reason=f"recovery for {failure_kind}: code={result.code}",
        )

        recovery_flow_id = task.recovery_flow_id if task is not None else None
        recovery_result: Optional[FlowResult] = None
        if recovery_flow_id:
            try:
                recovery_request = self.program_runner.build_production_request(
                    recovery_flow_id
                )
            except Exception:
                logger.exception("build_production_request failed for recovery flow")
                recovery_request = None
            if recovery_request is not None:
                try:
                    recovery_result = self.program_runner.run_recovery_sync(
                        recovery_request
                    )
                except Exception:
                    logger.exception("run_recovery_sync raised")
                    recovery_result = None
        else:
            logger.warning("no recovery_flow_id on task; skipping recovery execution")

        recovery_ok = bool(recovery_result.success) if recovery_result is not None else False
        logger.info(
            "recovery completed: success=%s; original failure_kind=%s code=%s",
            recovery_ok,
            failure_kind,
            result.code,
        )

        # Task 8: recovery success does NOT change the final error code.
        # The runtime still lands in FLOW_ERROR (110) / CAMERA_ERROR (112)
        # so the PLC sees the original failure. Only the task state
        # advances; 40001 is written by _set_production_state via
        # MODBUS_STATUS_MAP.
        self._set_production_state(
            final_state,
            reason=(
                f"recovery success={recovery_ok}; "
                f"original failure_kind={failure_kind} code={result.code}"
            ),
        )

    def _validate_publication_inputs(
        self,
        config: dict[str, Any],
        library: FlowLibrary,
    ) -> list[str]:
        from ..flow.flow_executor import validate_grasp_flow_modules

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

    # ------------------------------------------------------------------
    # PR 5 — Production telemetry (Health JSON production field)
    # ------------------------------------------------------------------

    # Chinese display names for hook_type values. ``None`` maps to ``None``.
    _HOOK_NAME_MAP: dict[int, str] = {0: "低钩子", 1: "高钩子"}

    def _build_production_telemetry(self) -> dict[str, Any]:
        """Build the ``production`` field for the Runtime Health JSON.

        PR 5 Task 1: exposes the production state machine's current
        context (state / task_id / hook_type / hook_name / flow_role /
        flow_id / recovery_started / failure_code) so the GUI Dashboard
        and external monitors can render live production telemetry.

        When no task is active (``production_task is None``) the field
        still reports ``state`` (which mirrors ``production_state``) but
        every task-specific field is ``None``.
        """
        task = self.production_task
        state_value = self.production_state.value
        if task is None:
            return {
                "state": state_value,
                "task_id": None,
                "hook_type": None,
                "hook_name": None,
                "flow_role": None,
                "flow_id": None,
                "recovery_started": None,
                "failure_code": None,
            }
        # Determine the currently-active flow_id and its role. When
        # recovery has started, the active flow is the recovery flow;
        # otherwise it's the primary flow latched at task creation.
        if task.recovery_started and task.recovery_flow_id:
            active_flow_id = task.recovery_flow_id
            active_flow_role: Optional[str] = "error_recovery"
        else:
            active_flow_id = task.primary_flow_id
            active_flow_role = self._reverse_lookup_flow_role(
                task.primary_flow_id
            )
        return {
            "state": state_value,
            "task_id": task.task_id,
            "hook_type": int(task.hook_type),
            "hook_name": self._HOOK_NAME_MAP.get(int(task.hook_type)),
            "flow_role": active_flow_role,
            "flow_id": active_flow_id,
            "recovery_started": bool(task.recovery_started),
            "failure_code": task.failure_code,
        }

    def _reverse_lookup_flow_role(self, flow_id: Optional[str]) -> Optional[str]:
        """Reverse-lookup the flow_role for ``flow_id`` from ``flow_router``.

        Returns ``"low_hook"`` / ``"high_hook"`` / ``"error_recovery"`` when
        ``flow_id`` matches one of the router's role bindings, otherwise
        ``None`` (e.g. the router has no roles configured, or the flow
        was started outside the role mapping).
        """
        if not flow_id:
            return None
        try:
            roles = self.flow_router.flow_roles
        except Exception:
            return None
        for role, fid in roles.items():
            if fid == flow_id:
                return role
        return None

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
            "production": self._build_production_telemetry(),
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
            # PR-FIX-3 Task 10: only direct-write 40001 when not in production.
            # During production, the state machine owns 40001 output.
            if (
                self.controller.modbus_server
                and self.production_state in (
                    ProductionState.MANUAL_OFFLINE,
                    ProductionState.IDLE,
                )
            ):
                self.controller._write_modbus_status(STATUS_ROBOT_ERR)
        supervisor_state = self.supervisor.step()
        # PR-FIX-3 Task 9: continue ResetStrategy after supervisor reconnects.
        if (
            supervisor_state == RobotConnectionState.CONNECTED
            and self._pending_reonline
        ):
            try:
                self.reset_strategy.execute(
                    source_state=ProductionState.MANUAL_OFFLINE,
                    controller=self.controller,
                    program_runner=self.program_runner,
                )
                self._set_production_state(
                    ProductionState.STANDBY,
                    reason="re-online complete (deferred)",
                )
                self._write_production_40001(2)  # STATUS_STANDBY
                self._pending_reonline = False
            except Exception:
                logger.exception(
                    "Deferred ResetStrategy.execute failed; will retry on next tick"
                )
                self._set_production_state(
                    ProductionState.FLOW_ERROR,
                    reason="deferred reset strategy failed",
                )
                # Keep _pending_reonline=True so next tick retries
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
        # PR 3: re-register the runner with the command delegate so the
        # production state machine owns 40001=0/1/3 dispatch. The
        # ``__init__`` already does this, but ``run()`` may be called
        # after a controller swap, so re-register defensively.
        try:
            self.controller.set_modbus_program_runner(
                self._run_program_from_modbus,
                readiness_checker=self._modbus_main_flow_readiness,
                command_delegate=self._on_modbus_command_delegate,
            )
        except TypeError:
            self.controller.set_modbus_program_runner(
                self._run_program_from_modbus,
                readiness_checker=self._modbus_main_flow_readiness,
            )
        if hasattr(self.controller, "set_modbus_mode_changed_callback"):
            self.controller.set_modbus_mode_changed_callback(self._on_mode_changed)
        # PR 5 Task 4: register the 40004 (hook_type) change callback so
        # the runtime emits a diagnostic log whenever the PLC changes
        # 40004, even when no production task is running. Defensive: the
        # controller may be a test stub that doesn't expose the setter.
        if hasattr(self.controller, "set_modbus_hook_type_changed_callback"):
            self.controller.set_modbus_hook_type_changed_callback(
                self._on_hook_type_changed
            )
        # PR-FIX-3 Task 6: re-register the production-finished callback so
        # the controller can route synthesized FlowResults from
        # abort_active_flow_for_disconnect into the state machine. ``run()``
        # may be called after a controller swap, so re-register defensively.
        if hasattr(self.controller, "set_production_finished_callback"):
            self.controller.set_production_finished_callback(
                self._on_production_flow_finished
            )
        # PR 5 Task 4: start the daemon worker thread that drains the
        # command queue. Started before modbus/IPC so commands enqueued
        # by the delegate are processed as soon as they arrive. The
        # worker exits on a None sentinel (see ``stop``).
        if self._command_worker_thread is None or not self._command_worker_thread.is_alive():
            self._command_worker_stop.clear()
            self._command_worker_thread = threading.Thread(
                target=self._command_worker_loop,
                daemon=True,
                name="modbus-cmd-worker",
            )
            self._command_worker_thread.start()
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
        # PR 5 Task 4: gracefully stop the command worker thread. With
        # modbus stopped no new commands can be enqueued; signal the
        # worker with the None sentinel and join so any in-flight
        # command finishes before cameras/controllers are torn down.
        self._command_worker_stop.set()
        try:
            self._modbus_command_queue.put_nowait(None)
        except Exception:
            logger.exception("failed to enqueue worker sentinel during shutdown")
        if self._command_worker_thread is not None:
            try:
                self._command_worker_thread.join(timeout=3.0)
            except Exception:
                logger.exception("command worker join failed during shutdown")
            self._command_worker_thread = None
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
    parser.add_argument("--check-config", action="store_true", help="部署预检：验证配置完整性后退出，不启动 Runtime。")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)

    # 部署预检模式：python runtime_agent.py --check-config
    if args.check_config:
        from ..config.config_manager import check_config
        ok = check_config(verbose=True)
        return 0 if ok else 1

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
