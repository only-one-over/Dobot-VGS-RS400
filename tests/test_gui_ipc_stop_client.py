"""Task 3/5/6/7 — RuntimeIpcClient Stop channel and convenience methods.

Covers the new ``stop_port`` parameter, ``request_stop`` routing, the
``safe_stop`` / ``stop_current_task`` / ``move_to_point`` / ``test_camera``
convenience methods, and ``RuntimeIpcRequestThread.use_stop_channel``.
"""
from __future__ import annotations

import json
from unittest import mock

from dobot_move.ui.gui_ipc_client import RuntimeIpcClient, RuntimeIpcRequestThread


def _make_response(request_id: str, payload: dict) -> bytes:
    return (json.dumps({"id": request_id, **payload}) + "\n").encode("utf-8")


def _patch_socket(monkeypatch, captured):
    """Patch ``socket.create_connection`` to capture the target port."""

    class _FakeSocket:
        def __init__(self):
            self.sent = bytearray()

        def settimeout(self, _value):
            pass

        def sendall(self, data):
            self.sent.extend(data)

        def recv(self, _size):
            if self.sent:
                # Echo back a success response matching the request id
                request = json.loads(self.sent.decode("utf-8").splitlines()[0])
                response = _make_response(
                    request["id"], {"ok": True, "data": {"echo": request}}
                )
                self.sent.clear()
                return response
            return b""

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def _create_connection(addr, *args, **kwargs):
        host, port = addr
        captured["host"] = host
        captured["port"] = port
        return _FakeSocket()

    monkeypatch.setattr(
        "dobot_move.ui.gui_ipc_client.socket.create_connection",
        _create_connection,
    )


def test_client_accepts_stop_port():
    client = RuntimeIpcClient(host="127.0.0.1", port=8765, stop_port=8766)
    assert client.port == 8765
    assert client.stop_port == 8766


def test_request_uses_normal_port(monkeypatch):
    captured = {}
    _patch_socket(monkeypatch, captured)
    client = RuntimeIpcClient(host="127.0.0.1", port=8765, stop_port=8766)
    client.request("ping")
    assert captured["port"] == 8765


def test_request_stop_uses_stop_port(monkeypatch):
    captured = {}
    _patch_socket(monkeypatch, captured)
    client = RuntimeIpcClient(host="127.0.0.1", port=8765, stop_port=8766)
    client.request_stop("safe_stop")
    assert captured["port"] == 8766


def test_safe_stop_routes_to_stop_channel(monkeypatch):
    captured = {}
    _patch_socket(monkeypatch, captured)
    client = RuntimeIpcClient(host="127.0.0.1", port=8765, stop_port=8766)
    client.safe_stop()
    assert captured["port"] == 8766


def test_stop_current_task_routes_to_normal_channel(monkeypatch):
    """``stop_current_task`` uses the normal FIFO queue per the spec."""
    captured = {}
    _patch_socket(monkeypatch, captured)
    client = RuntimeIpcClient(host="127.0.0.1", port=8765, stop_port=8766)
    client.stop_current_task()
    assert captured["port"] == 8765


def test_move_to_point_sends_correct_data(monkeypatch):
    captured = {}
    _patch_socket(monkeypatch, captured)
    client = RuntimeIpcClient()
    response = client.move_to_point("pointA", "MovL", 25.0)
    assert response["ok"] is True
    echo = response["data"]["echo"]
    assert echo["cmd"] == "move_to_point"
    assert echo["data"] == {
        "point_name": "pointA",
        "motion_type": "MovL",
        "speed": 25.0,
    }


def test_test_camera_d435i(monkeypatch):
    captured = {}
    _patch_socket(monkeypatch, captured)
    client = RuntimeIpcClient()
    response = client.test_camera("D435i")
    echo = response["data"]["echo"]
    assert echo["cmd"] == "test_d435i"


def test_test_camera_d405(monkeypatch):
    captured = {}
    _patch_socket(monkeypatch, captured)
    client = RuntimeIpcClient()
    response = client.test_camera("D405")
    echo = response["data"]["echo"]
    assert echo["cmd"] == "test_d405"


def test_reload_config(monkeypatch):
    _patch_socket(monkeypatch, {})
    client = RuntimeIpcClient()
    response = client.reload_config()
    assert response["ok"] is True


def test_get_publication_status(monkeypatch):
    _patch_socket(monkeypatch, {})
    client = RuntimeIpcClient()
    response = client.get_publication_status()
    assert response["ok"] is True


def test_get_debug_task_status(monkeypatch):
    _patch_socket(monkeypatch, {})
    client = RuntimeIpcClient()
    response = client.get_debug_task_status()
    assert response["ok"] is True


# ---------------------------------------------------------------------------
# RuntimeIpcRequestThread.use_stop_channel
# ---------------------------------------------------------------------------


class _StubClient:
    def __init__(self):
        self.stop_calls = []
        self.normal_calls = []

    def request(self, command, data=None):
        self.normal_calls.append((command, data))
        return {"ok": True, "data": {}}

    def request_stop(self, command, data=None):
        self.stop_calls.append((command, data))
        return {"ok": True, "data": {}}


def test_thread_use_stop_channel_calls_request_stop():
    client = _StubClient()
    thread = RuntimeIpcRequestThread(
        client, "safe_stop", None, None, use_stop_channel=True
    )
    thread.run()
    assert client.stop_calls == [("safe_stop", {})]
    assert client.normal_calls == []


def test_thread_default_uses_normal_channel():
    client = _StubClient()
    thread = RuntimeIpcRequestThread(
        client, "ping", None, None, use_stop_channel=False
    )
    thread.run()
    assert client.normal_calls == [("ping", {})]
    assert client.stop_calls == []
