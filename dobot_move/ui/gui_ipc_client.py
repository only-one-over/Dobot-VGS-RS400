"""Synchronous short-lived Runtime IPC client for future GUI workers."""

from __future__ import annotations

import json
import socket
import uuid
from pathlib import Path
from typing import Any

from ..runtime.runtime_ipc import (
    DEFAULT_IPC_HOST,
    DEFAULT_IPC_PORT,
    DEFAULT_STOP_PORT,
    DEFAULT_IPC_TOKEN_PATH,
    encode_json_line,
    load_ipc_token,
)
from ..ui.qt_compat import QThread, pyqtSignal


class RuntimeIpcClient:
    def __init__(
        self,
        host: str = DEFAULT_IPC_HOST,
        port: int = DEFAULT_IPC_PORT,
        *,
        stop_port: int = DEFAULT_STOP_PORT,
        timeout_s: float = 3.0,
        auth_token: str | None = None,
        token_path: Path | str | None = DEFAULT_IPC_TOKEN_PATH,
    ):
        self.host = str(host)
        self.port = int(port)
        self.stop_port = int(stop_port)
        self.timeout_s = max(0.1, float(timeout_s))
        self.auth_token = str(auth_token) if auth_token else None
        self.token_path = Path(token_path) if token_path else None

    def _get_auth_token(self) -> str | None:
        if self.auth_token:
            return self.auth_token
        if self.token_path is None:
            return None
        return load_ipc_token(self.token_path, required=False)

    def request(
        self,
        command: str,
        data: dict[str, Any] | None = None,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        return self._send(self.port, command, data, request_id=request_id)

    def request_stop(
        self,
        command: str,
        data: dict[str, Any] | None = None,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Send a command via the dedicated Stop channel (port 8766).

        Stop-channel commands bypass the normal FIFO queue so they execute
        immediately even when a long-running command is blocking the
        command worker thread.
        """
        return self._send(self.stop_port, command, data, request_id=request_id)

    def _send(self, port: int, command: str, data, *, request_id) -> dict[str, Any]:
        request_id = request_id or uuid.uuid4().hex
        payload = {
            "id": request_id,
            "cmd": str(command),
            "data": dict(data or {}),
        }
        auth_token = self._get_auth_token()
        if auth_token:
            payload["auth"] = auth_token
        with socket.create_connection(
            (self.host, port),
            timeout=self.timeout_s,
        ) as client:
            client.settimeout(self.timeout_s)
            client.sendall(encode_json_line(payload))
            buffer = bytearray()
            while b"\n" not in buffer:
                chunk = client.recv(65536)
                if not chunk:
                    raise ConnectionError("Runtime IPC连接提前关闭")
                buffer.extend(chunk)
        raw_line, _, _remaining = buffer.partition(b"\n")
        response = json.loads(raw_line.decode("utf-8"))
        if not isinstance(response, dict):
            raise ValueError("Runtime IPC响应必须是对象")
        if response.get("id") != request_id:
            raise ValueError("Runtime IPC响应id不匹配")
        return response

    def ping(self) -> dict[str, Any]:
        return self.request("ping")

    def safe_stop(self) -> dict[str, Any]:
        """High-priority software emergency stop via the Stop channel.

        Calls ``controller.emergency_stop()`` on the Runtime side to drop
        the robot enable state. Use this for the "安全停止" button.
        """
        return self.request_stop("safe_stop")

    def stop_current_task(self) -> dict[str, Any]:
        """Normal motion stop via the normal channel (dashboard.Stop()).

        Distinct from :meth:`safe_stop`: this only stops the current
        motion without dropping the robot enable state. Routed through
        the normal FIFO queue per the spec.
        """
        return self.request("stop_current_task")

    def move_to_point(
        self,
        point_name: str,
        motion_type: str = "MovJ",
        speed: float = 10.0,
    ) -> dict[str, Any]:
        return self.request(
            "move_to_point",
            {
                "point_name": str(point_name),
                "motion_type": str(motion_type),
                "speed": float(speed),
            },
        )

    def test_camera(self, camera_type: str) -> dict[str, Any]:
        command = "test_d405" if camera_type == "D405" else "test_d435i"
        return self.request(command)

    def reload_config(self) -> dict[str, Any]:
        return self.request("reload_config")

    def publish_config_sync(self, timeout: float = 3.0) -> tuple[bool, str]:
        """同步调用 publish_config IPC 并等待响应。

        用于运行前必须确保发布完成的场景。

        Args:
            timeout: 超时秒数，默认 3 秒

        Returns:
            (True, response_json_str) 成功
            (False, error_msg) 失败或超时
        """
        saved_timeout = self.timeout_s
        self.timeout_s = max(0.1, float(timeout))
        try:
            response = self.request("publish_config")
            if isinstance(response, dict):
                if response.get("ok") or response.get("published"):
                    return True, json.dumps(response, ensure_ascii=False)
                error = response.get("error", "unknown error")
                return False, str(error)
            return True, str(response)
        except socket.timeout:
            return False, "timeout"
        except (ConnectionError, OSError) as e:
            return False, str(e)
        except Exception as e:
            return False, f"unexpected error: {e}"
        finally:
            self.timeout_s = saved_timeout

    def get_publication_status(self) -> dict[str, Any]:
        return self.request("get_publication_status")

    def get_debug_task_status(self) -> dict[str, Any]:
        return self.request("get_debug_task_status")


class RuntimeIpcRequestThread(QThread):
    """Run one short IPC request without blocking the Qt event loop."""

    completed = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, client, command, data=None, parent=None, *, use_stop_channel: bool = False):
        super().__init__(parent)
        self.client = client
        self.command = str(command)
        self.data = dict(data or {})
        self.use_stop_channel = bool(use_stop_channel)

    def run(self):
        try:
            if self.use_stop_channel:
                response = self.client.request_stop(self.command, self.data)
            else:
                response = self.client.request(self.command, self.data)
            self.completed.emit(response)
        except Exception as exc:
            self.failed.emit(str(exc))
