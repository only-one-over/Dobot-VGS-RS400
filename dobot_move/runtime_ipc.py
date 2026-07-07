"""Local JSON Lines IPC server for Runtime commands."""

from __future__ import annotations

import json
import logging
import queue
import secrets
import socket
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

DEFAULT_IPC_HOST = "127.0.0.1"
DEFAULT_IPC_PORT = 8765
MAX_JSON_LINE_BYTES = 1024 * 1024
DEFAULT_IPC_TOKEN_PATH = Path(__file__).resolve().parent.parent / "runtime_ipc.token"


def load_ipc_token(path=None, *, required=False) -> str | None:
    """Load a local IPC token without ever logging its value."""
    token_path = Path(path or DEFAULT_IPC_TOKEN_PATH)
    try:
        token = token_path.read_text(encoding="utf-8").strip()
    except OSError:
        if required:
            raise ValueError(f"IPC token file is unavailable: {token_path}")
        return None
    if len(token) < 32:
        raise ValueError("IPC token must contain at least 32 characters")
    return token


class IpcCommandError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = str(code)
        self.message = str(message)


@dataclass
class _QueuedCommand:
    request_id: Any
    command: str
    data: dict[str, Any]
    response_queue: queue.Queue


def encode_json_line(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode("utf-8")


class RuntimeIpcServer:
    """Loopback-only server with network and command execution separation."""

    def __init__(
        self,
        command_handler: Callable[[str, dict[str, Any]], dict[str, Any] | None],
        *,
        host: str = DEFAULT_IPC_HOST,
        port: int = DEFAULT_IPC_PORT,
        command_timeout_s: float = 5.0,
        max_line_bytes: int = MAX_JSON_LINE_BYTES,
        auth_token: str | None = None,
    ):
        self.command_handler = command_handler
        self.host = str(host)
        self.port = int(port)
        self.command_timeout_s = max(0.1, float(command_timeout_s))
        self.max_line_bytes = max(1024, int(max_line_bytes))
        self._auth_token = str(auth_token) if auth_token else None
        self._running = threading.Event()
        self._listener = None
        self._accept_thread = None
        self._command_thread = None
        self._command_queue: queue.Queue = queue.Queue()
        self._clients: set[socket.socket] = set()
        self._client_threads: set[threading.Thread] = set()
        self._clients_lock = threading.Lock()
        self.last_error = ""

    @property
    def is_running(self) -> bool:
        return self._running.is_set()

    def start(self) -> bool:
        if self.is_running:
            return True
        if self.host not in {"127.0.0.1", "localhost"}:
            self.last_error = "IPC只允许绑定localhost"
            return False

        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind((self.host, self.port))
            listener.listen(8)
            listener.settimeout(0.5)
        except OSError as exc:
            listener.close()
            self.last_error = str(exc)
            logger.error("Runtime IPC bind failed: %s", exc)
            return False

        self._listener = listener
        self.port = int(listener.getsockname()[1])
        self.last_error = ""
        self._running.set()
        self._command_thread = threading.Thread(
            target=self._command_loop,
            name="RuntimeIpcCommandWorker",
            daemon=True,
        )
        self._accept_thread = threading.Thread(
            target=self._accept_loop,
            name="RuntimeIpcAccept",
            daemon=True,
        )
        self._command_thread.start()
        self._accept_thread.start()
        logger.info("Runtime IPC listening on %s:%d", self.host, self.port)
        return True

    def stop(self) -> None:
        if not self.is_running and self._listener is None:
            return
        self._running.clear()
        listener = self._listener
        self._listener = None
        if listener is not None:
            try:
                listener.close()
            except OSError:
                pass
        with self._clients_lock:
            clients = list(self._clients)
        for client in clients:
            try:
                client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                client.close()
            except OSError:
                pass
        self._command_queue.put(None)
        for thread in (self._accept_thread, self._command_thread):
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=2.0)
        self._accept_thread = None
        self._command_thread = None
        logger.info("Runtime IPC stopped")

    def snapshot(self) -> dict[str, Any]:
        with self._clients_lock:
            client_count = len(self._clients)
        return {
            "running": self.is_running,
            "host": self.host,
            "port": self.port,
            "clients": client_count,
            "queue_depth": self._command_queue.qsize(),
            "last_error": self.last_error,
            "authentication_required": self._auth_token is not None,
        }

    def _accept_loop(self) -> None:
        while self.is_running:
            try:
                client, _address = self._listener.accept()
            except socket.timeout:
                continue
            except (OSError, AttributeError):
                break
            client.settimeout(0.5)
            thread = threading.Thread(
                target=self._client_loop,
                args=(client,),
                name="RuntimeIpcClient",
                daemon=True,
            )
            with self._clients_lock:
                self._clients.add(client)
                self._client_threads.add(thread)
            thread.start()

    def _client_loop(self, client: socket.socket) -> None:
        buffer = bytearray()
        try:
            while self.is_running:
                try:
                    chunk = client.recv(65536)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not chunk:
                    break
                buffer.extend(chunk)
                if len(buffer) > self.max_line_bytes and b"\n" not in buffer:
                    self._send_response(
                        client,
                        self._error_response(
                            None,
                            "REQUEST_TOO_LARGE",
                            "JSON消息超过大小限制",
                        ),
                    )
                    break
                while b"\n" in buffer:
                    raw_line, _, remaining = buffer.partition(b"\n")
                    buffer = bytearray(remaining)
                    if not raw_line.strip():
                        continue
                    if len(raw_line) > self.max_line_bytes:
                        response = self._error_response(
                            None,
                            "REQUEST_TOO_LARGE",
                            "JSON消息超过大小限制",
                        )
                    else:
                        response = self._dispatch_line(bytes(raw_line))
                    if not self._send_response(client, response):
                        return
        finally:
            with self._clients_lock:
                self._clients.discard(client)
                self._client_threads.discard(threading.current_thread())
            try:
                client.close()
            except OSError:
                pass

    def _dispatch_line(self, raw_line: bytes) -> dict[str, Any]:
        try:
            payload = json.loads(raw_line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return self._error_response(None, "INVALID_JSON", str(exc))
        if not isinstance(payload, dict):
            return self._error_response(
                None,
                "INVALID_REQUEST",
                "请求根节点必须是对象",
            )

        request_id = payload.get("id")
        command = payload.get("cmd")
        data = payload.get("data", {})
        if request_id is None:
            return self._error_response(
                None,
                "INVALID_REQUEST",
                "缺少请求id",
            )
        if not isinstance(command, str) or not command.strip():
            return self._error_response(
                request_id,
                "INVALID_REQUEST",
                "cmd必须是非空字符串",
            )
        if not isinstance(data, dict):
            return self._error_response(
                request_id,
                "INVALID_REQUEST",
                "data必须是对象",
            )
        if self._auth_token is not None:
            supplied_token = payload.get("auth")
            if not isinstance(supplied_token, str) or not secrets.compare_digest(
                supplied_token,
                self._auth_token,
            ):
                return self._error_response(
                    request_id,
                    "UNAUTHORIZED",
                    "Runtime IPC authentication failed",
                )

        response_queue: queue.Queue = queue.Queue(maxsize=1)
        self._command_queue.put(
            _QueuedCommand(
                request_id=request_id,
                command=command.strip(),
                data=data,
                response_queue=response_queue,
            )
        )
        try:
            return response_queue.get(timeout=self.command_timeout_s)
        except queue.Empty:
            return self._error_response(
                request_id,
                "TIMEOUT",
                "Runtime命令执行超时",
            )

    def _command_loop(self) -> None:
        while self.is_running or not self._command_queue.empty():
            try:
                item = self._command_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if item is None:
                break
            try:
                data = self.command_handler(item.command, item.data)
                response = {
                    "id": item.request_id,
                    "ok": True,
                    "data": data if isinstance(data, dict) else {},
                    "error": None,
                }
            except IpcCommandError as exc:
                response = self._error_response(
                    item.request_id,
                    exc.code,
                    exc.message,
                )
            except Exception as exc:
                logger.exception("Runtime IPC command failed: %s", item.command)
                response = self._error_response(
                    item.request_id,
                    "INTERNAL_ERROR",
                    str(exc),
                )
            try:
                item.response_queue.put_nowait(response)
            except queue.Full:
                pass

    @staticmethod
    def _error_response(request_id, code, message):
        return {
            "id": request_id,
            "ok": False,
            "data": None,
            "error": {
                "code": str(code),
                "message": str(message),
            },
        }

    @staticmethod
    def _send_response(client, response) -> bool:
        try:
            client.sendall(encode_json_line(response))
            return True
        except OSError:
            return False
