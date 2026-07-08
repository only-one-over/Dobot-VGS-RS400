#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Remote REST API server application.

Exposes robot feedback / status / Modbus / production endpoints for external
tablet/MES clients over HTTP. Replaces the legacy monolithic ``remote_api.py``
with a modular, config-driven, token-protected service.

Run via ``python -m dobot_move.remote_api`` or the thin ``remote_api.py`` shim.
"""

from __future__ import annotations

import argparse
import hmac
import json
import logging
import signal
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from ..config import config_manager
from ..runtime.runtime_resilience import atomic_write_json
from .config import get_remote_api_config
from .feedback_worker import FeedbackWorker
from .handlers import (
    build_feedback_all,
    build_health,
    build_production_status,
    build_status,
)
from .modbus_client import read_registers

logger = logging.getLogger(__name__)


# ============================ logging ============================
def setup_remote_api_logging(log_dir) -> Path:
    """Configure rotating file + console logging for the remote_api process.

    Mirrors ``setup_runtime_logging`` but writes to ``remote_api.log``.
    Idempotent: skips handlers whose type is already attached to the root logger.
    """
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "remote_api.log"

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    has_file = any(
        isinstance(handler, RotatingFileHandler) for handler in root.handlers
    )
    if not has_file:
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.INFO)
        root.addHandler(file_handler)

    has_stream = any(
        isinstance(handler, logging.StreamHandler)
        and not isinstance(handler, logging.FileHandler)
        for handler in root.handlers
    )
    if not has_stream:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        stream_handler.setLevel(logging.INFO)
        root.addHandler(stream_handler)

    return log_path


# ============================ HTTP server bridge ============================
class _RemoteApiHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer with a back-reference to the RemoteApiServer app."""

    def __init__(self, server_address, handler_cls, app: "RemoteApiServer"):
        super().__init__(server_address, handler_cls)
        self.app = app


# ============================ request handler ============================
class APIHandler(BaseHTTPRequestHandler):
    """REST API request handler: routing + token middleware + CORS."""

    # ---- response helpers ----
    def _send_json(self, obj, status: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_ok(self, data) -> None:
        self._send_json({"code": 0, "data": data})

    def _send_error(self, msg: str, status: int = 400) -> None:
        self._send_json({"code": -1, "msg": msg}, status=status)

    def _send_redirect(self, new_path: str) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        location = new_path
        if parsed.query:
            location = f"{new_path}?{parsed.query}"
        self.send_response(301)
        self.send_header("Location", location)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

    # ---- token middleware ----
    def _check_token(self) -> bool:
        """Validate ``Authorization: Bearer <token>`` against configured token.

        Empty configured token skips authentication (open mode).
        """
        app = self.server.app
        expected = app.config.get("token", "") or ""
        if not expected:
            return True
        auth = self.headers.get("Authorization", "") or ""
        prefix = "Bearer "
        if not auth.startswith(prefix):
            return False
        provided = auth[len(prefix):]
        return hmac.compare_digest(provided, expected)

    # ---- routing ----
    def do_GET(self) -> None:
        app = self.server.app
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path

        # legacy paths -> 301 redirect preserving query string
        legacy_redirects = {
            "/api/status": "/api/v1/status",
            "/api/feedback/all": "/api/v1/feedback/all",
            "/api/modbus/registers": "/api/v1/modbus/registers",
        }
        if path in legacy_redirects:
            self._send_redirect(legacy_redirects[path])
            app.record_request(ok=True)
            return

        # public health endpoint (no auth)
        if path == "/api/v1/health":
            uptime, req_count, err_count, last_err = app.get_stats()
            _fb, health, _age, _err = app.feedback_worker.get_snapshot()
            data = build_health(uptime, health, req_count, err_count, last_err)
            self._send_ok(data)
            app.record_request(ok=True)
            return

        # token required for everything below
        if not self._check_token():
            self._send_error("未授权: token 无效或缺失", status=401)
            app.record_request(ok=False, error="auth failed")
            return

        try:
            if path == "/api/v1/status":
                fb, health, age, err = app.feedback_worker.get_snapshot()
                data = build_status(fb, health, age, err, app.robot_ip)
                self._send_ok(data)
            elif path == "/api/v1/feedback/all":
                fb, health, age, err = app.feedback_worker.get_snapshot()
                data = build_feedback_all(fb, health, age, err, app.robot_ip)
                self._send_ok(data)
            elif path == "/api/v1/modbus/registers":
                host = app.config.get("modbus_host", "127.0.0.1")
                timeout = float(app.config.get("modbus_client_timeout_s", 3.0))
                data = read_registers(host, app.modbus_port, app.modbus_slave_id, timeout)
                self._send_ok(data)
            elif path == "/api/v1/production/status":
                data = build_production_status(app.runtime_health_path)
                self._send_ok(data)
            else:
                self._send_error(f"未知路径: {path}")
                app.record_request(ok=False, error=f"unknown path {path}")
                return
            app.record_request(ok=True)
        except Exception as e:  # noqa: BLE001 - top-level guard for HTTP handlers
            logger.exception("处理请求 %s 失败", path)
            self._send_error(f"内部错误: {e}", status=500)
            app.record_request(ok=False, error=str(e))

    def log_message(self, fmt, *args) -> None:
        logger.info("HTTP %s %s", self.address_string(), fmt % args if args else "")


# ============================ server orchestrator ============================
class RemoteApiServer:
    """Owns the feedback worker, HTTP server, and health-file writer."""

    def __init__(
        self,
        config: dict,
        robot_ip: str,
        modbus_port: int,
        modbus_slave_id: int,
        runtime_health_path: str,
        remote_api_health_path: str,
    ) -> None:
        self.config = config
        self.robot_ip = robot_ip
        self.modbus_port = modbus_port
        self.modbus_slave_id = modbus_slave_id
        self.runtime_health_path = runtime_health_path
        self.remote_api_health_path = remote_api_health_path

        self.feedback_worker = FeedbackWorker(
            robot_ip=robot_ip,
            feedback_port=int(config.get("feedback_port", 30004)),
            reconnect_interval_s=float(config.get("feedback_reconnect_interval_s", 2.0)),
            stale_ok_s=float(config.get("feedback_stale_ok_s", 0.3)),
            stale_fail_s=float(config.get("feedback_stale_fail_s", 2.0)),
        )

        # statistics
        self._start_time = time.monotonic()
        self._request_count = 0
        self._error_count = 0
        self._last_error = ""
        self._stats_lock = threading.Lock()

        # http server (deferred to start())
        self._http_server: Optional[_RemoteApiHTTPServer] = None

        # health writer thread
        self._health_stop_event = threading.Event()
        self._health_thread: Optional[threading.Thread] = None

        self._stopped = False

    # ---- statistics helpers ----
    def record_request(self, ok: bool, error: str = "") -> None:
        with self._stats_lock:
            self._request_count += 1
            if not ok:
                self._error_count += 1
                self._last_error = error

    def get_stats(self) -> tuple[float, int, int, str]:
        with self._stats_lock:
            uptime = time.monotonic() - self._start_time
            return (
                uptime,
                self._request_count,
                self._error_count,
                self._last_error,
            )

    # ---- health file ----
    def _write_health(self, status: str = "running") -> None:
        _fb, feedback_health, _age, _err = self.feedback_worker.get_snapshot()
        uptime, req_count, err_count, last_err = self.get_stats()
        payload = {
            "status": status,
            "timestamp": time.time(),
            "uptime_s": round(uptime, 1),
            "feedback_health": feedback_health,
            "request_count": req_count,
            "error_count": err_count,
            "last_error": last_err,
            "host": self.config.get("host"),
            "port": self.config.get("port"),
            "robot_ip": self.robot_ip,
        }
        try:
            atomic_write_json(Path(self.remote_api_health_path), payload)
        except Exception:
            logger.warning("写入 remote_api_health 失败", exc_info=True)

    def _health_loop(self) -> None:
        self._write_health("running")
        while not self._health_stop_event.wait(1.0):
            self._write_health("running")

    # ---- lifecycle ----
    def start(self) -> None:
        host = self.config.get("host", "0.0.0.0")
        port = int(self.config.get("port", 8000))
        self._http_server = _RemoteApiHTTPServer((host, port), APIHandler, self)

        if self._stopped:
            # stop() was called before start(); tear down and return.
            try:
                self._http_server.server_close()
            except Exception:
                pass
            return

        self.feedback_worker.start()
        self._health_thread = threading.Thread(
            target=self._health_loop,
            daemon=True,
            name="remote-api-health",
        )
        self._health_thread.start()

        logger.info("=" * 50)
        logger.info("REST API 服务已启动: http://%s:%d", host, port)
        logger.info("端点:")
        logger.info("  GET /api/v1/health           - 服务健康 (免认证)")
        logger.info("  GET /api/v1/status            - 连接/使能/运动状态")
        logger.info("  GET /api/v1/feedback/all      - 完整反馈快照")
        logger.info("  GET /api/v1/modbus/registers  - Modbus 寄存器")
        logger.info("  GET /api/v1/production/status - 产线/运行时状态")
        logger.info("机器人 IP: %s", self.robot_ip)
        logger.info("Modbus: %s:%d (slave_id=%d)",
                    self.config.get("modbus_host", "127.0.0.1"),
                    self.modbus_port, self.modbus_slave_id)
        logger.info("=" * 50)

        try:
            # serve_forever blocks the main thread
            self._http_server.serve_forever()
        finally:
            if not self._stopped:
                self.stop()

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True

        # shutdown() must run in a different thread than serve_forever()
        # to avoid deadlock; fire-and-forget a daemon to signal the loop.
        if self._http_server is not None:
            threading.Thread(
                target=self._http_server.shutdown,
                daemon=True,
                name="remote-api-http-shutdown",
            ).start()

        try:
            self.feedback_worker.stop(timeout=5.0)
        except Exception:
            logger.warning("feedback worker 停止失败", exc_info=True)

        self._health_stop_event.set()
        if self._health_thread is not None:
            self._health_thread.join(timeout=2.0)

        # final health snapshot with stopped status
        self._write_health(status="stopped")
        logger.info("REST API 服务已停止")


# ============================ entrypoint ============================
def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Dobot remote REST API server.")
    parser.add_argument("--host", default=None, help="Bind host (overrides config).")
    parser.add_argument("--port", type=int, default=None, help="Bind port (overrides config).")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    setup_remote_api_logging(config_manager.LOG_DIR)

    config = get_remote_api_config()
    if args.host is not None:
        config["host"] = args.host
    if args.port is not None:
        config["port"] = args.port

    robot_ip = config_manager.get_robot_ip()
    modbus_port = config_manager.get_modbus_port()
    modbus_slave_id = config_manager.get_modbus_slave_id()
    runtime_health_path = config_manager.RUNTIME_HEALTH_FILE
    remote_api_health_path = config_manager.REMOTE_API_HEALTH_FILE

    server = RemoteApiServer(
        config,
        robot_ip,
        modbus_port,
        modbus_slave_id,
        runtime_health_path,
        remote_api_health_path,
    )

    def _stop(signum, _frame):
        logger.info("remote_api stop signal received: %s", signum)
        server.stop()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    server.start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
