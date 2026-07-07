import json
import socket
import threading
import time

from dobot_move.gui_ipc_client import RuntimeIpcClient
from dobot_move.runtime_ipc import RuntimeIpcServer, encode_json_line


def _read_json_lines(client, count):
    buffer = bytearray()
    messages = []
    while len(messages) < count:
        chunk = client.recv(65536)
        if not chunk:
            break
        buffer.extend(chunk)
        while b"\n" in buffer and len(messages) < count:
            raw_line, _, remaining = buffer.partition(b"\n")
            buffer = bytearray(remaining)
            if raw_line:
                messages.append(json.loads(raw_line.decode("utf-8")))
    return messages


def test_ipc_client_ping_uses_standard_response():
    handler_threads = []

    def handler(command, data):
        handler_threads.append(threading.current_thread().name)
        return {"command": command, "data": data}

    server = RuntimeIpcServer(handler, port=0)
    assert server.start() is True
    try:
        client = RuntimeIpcClient(port=server.port)
        response = client.request("ping", {"value": 1}, request_id="1001")

        assert response == {
            "id": "1001",
            "ok": True,
            "data": {"command": "ping", "data": {"value": 1}},
            "error": None,
        }
        assert handler_threads == ["RuntimeIpcCommandWorker"]
    finally:
        server.stop()


def test_ipc_handles_half_packet_and_sticky_packets():
    server = RuntimeIpcServer(
        lambda command, data: {"command": command, **data},
        port=0,
    )
    assert server.start() is True
    try:
        with socket.create_connection(("127.0.0.1", server.port), timeout=1.0) as client:
            first = encode_json_line({"id": "a", "cmd": "ping", "data": {}})
            second = encode_json_line(
                {"id": "b", "cmd": "get_status", "data": {"n": 2}}
            )
            client.sendall(first[:5])
            time.sleep(0.02)
            client.sendall(first[5:] + second)

            responses = _read_json_lines(client, 2)

        assert [item["id"] for item in responses] == ["a", "b"]
        assert all(item["ok"] for item in responses)
        assert responses[1]["data"]["n"] == 2
    finally:
        server.stop()


def test_ipc_returns_error_for_invalid_json_and_keeps_connection():
    server = RuntimeIpcServer(lambda command, data: {}, port=0)
    assert server.start() is True
    try:
        with socket.create_connection(("127.0.0.1", server.port), timeout=1.0) as client:
            client.sendall(
                b"{invalid}\n"
                + encode_json_line({"id": "ok", "cmd": "ping", "data": {}})
            )
            responses = _read_json_lines(client, 2)

        assert responses[0]["ok"] is False
        assert responses[0]["error"]["code"] == "INVALID_JSON"
        assert responses[1]["id"] == "ok"
        assert responses[1]["ok"] is True
    finally:
        server.stop()


def test_ipc_command_timeout_does_not_block_network_thread_forever():
    def handler(command, data):
        del command, data
        time.sleep(0.15)
        return {}

    server = RuntimeIpcServer(handler, port=0, command_timeout_s=0.05)
    assert server.start() is True
    try:
        client = RuntimeIpcClient(port=server.port, timeout_s=1.0)
        response = client.request("slow", request_id="slow-1")

        assert response["ok"] is False
        assert response["error"]["code"] == "TIMEOUT"
    finally:
        server.stop()


def test_ipc_client_disconnect_does_not_stop_server():
    server = RuntimeIpcServer(lambda command, data: {"command": command}, port=0)
    assert server.start() is True
    try:
        client = socket.create_connection(("127.0.0.1", server.port), timeout=1.0)
        client.sendall(encode_json_line({"id": "gone", "cmd": "ping", "data": {}}))
        client.close()
        time.sleep(0.05)

        response = RuntimeIpcClient(port=server.port).ping()
        assert response["ok"] is True
    finally:
        server.stop()


def test_ipc_rejects_missing_or_invalid_token_before_command_queue():
    calls = []
    server = RuntimeIpcServer(
        lambda command, data: calls.append((command, data)) or {},
        port=0,
        auth_token="a" * 32,
    )
    assert server.start() is True
    try:
        missing = RuntimeIpcClient(
            port=server.port,
            token_path=None,
        ).ping()
        invalid = RuntimeIpcClient(
            port=server.port,
            auth_token="b" * 32,
            token_path=None,
        ).ping()

        assert missing["error"]["code"] == "UNAUTHORIZED"
        assert invalid["error"]["code"] == "UNAUTHORIZED"
        assert calls == []
    finally:
        server.stop()


def test_ipc_accepts_matching_token():
    server = RuntimeIpcServer(
        lambda command, data: {"command": command},
        port=0,
        auth_token="a" * 32,
    )
    assert server.start() is True
    try:
        response = RuntimeIpcClient(
            port=server.port,
            auth_token="a" * 32,
            token_path=None,
        ).ping()
        assert response["ok"] is True
    finally:
        server.stop()
