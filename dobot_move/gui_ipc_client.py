"""Synchronous short-lived Runtime IPC client for future GUI workers."""

from __future__ import annotations

import json
import socket
import uuid
from pathlib import Path
from typing import Any

from .runtime_ipc import (
    DEFAULT_IPC_HOST,
    DEFAULT_IPC_PORT,
    DEFAULT_IPC_TOKEN_PATH,
    encode_json_line,
    load_ipc_token,
)
from .qt_compat import QThread, pyqtSignal


class RuntimeIpcClient:
    def __init__(
        self,
        host: str = DEFAULT_IPC_HOST,
        port: int = DEFAULT_IPC_PORT,
        *,
        timeout_s: float = 3.0,
        auth_token: str | None = None,
        token_path: Path | str | None = DEFAULT_IPC_TOKEN_PATH,
    ):
        self.host = str(host)
        self.port = int(port)
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
            (self.host, self.port),
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


class RuntimeIpcRequestThread(QThread):
    """Run one short IPC request without blocking the Qt event loop."""

    completed = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, client, command, data=None, parent=None):
        super().__init__(parent)
        self.client = client
        self.command = str(command)
        self.data = dict(data or {})

    def run(self):
        try:
            self.completed.emit(self.client.request(self.command, self.data))
        except Exception as exc:
            self.failed.emit(str(exc))
