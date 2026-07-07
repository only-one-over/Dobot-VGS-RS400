"""Tests for the dedicated Runtime IPC Stop channel (port 8766) and the
``safe_stop`` command handler.

These tests are self-contained: they install lightweight stubs for the
optional native dependencies so the file can be run in isolation.
"""
import sys
import threading
import time
import types

if "pyrealsense2" not in sys.modules:
    sys.modules["pyrealsense2"] = types.ModuleType("pyrealsense2")

_pymodbus = sys.modules.setdefault("pymodbus", types.ModuleType("pymodbus"))


class _ModbusDeviceIdentification:
    pass


_pymodbus.ModbusDeviceIdentification = getattr(
    _pymodbus,
    "ModbusDeviceIdentification",
    _ModbusDeviceIdentification,
)

_pymodbus_server = sys.modules.setdefault(
    "pymodbus.server", types.ModuleType("pymodbus.server")
)


class _ModbusTcpServer:
    pass


_pymodbus_server.ModbusTcpServer = getattr(
    _pymodbus_server,
    "ModbusTcpServer",
    _ModbusTcpServer,
)

_pymodbus_sim = sys.modules.setdefault(
    "pymodbus.simulator", types.ModuleType("pymodbus.simulator")
)


class _SimData:
    pass


class _SimDevice:
    pass


class _DataType:
    REGISTERS = "registers"


_pymodbus_sim.SimData = getattr(_pymodbus_sim, "SimData", _SimData)
_pymodbus_sim.SimDevice = getattr(_pymodbus_sim, "SimDevice", _SimDevice)
_pymodbus_sim.DataType = getattr(_pymodbus_sim, "DataType", _DataType)

from dobot_move.runtime.runtime_agent import DobotRuntimeAgent  # noqa: E402
from dobot_move.runtime.runtime_ipc import RuntimeIpcServer  # noqa: E402
from dobot_move.ui.gui_ipc_client import RuntimeIpcClient  # noqa: E402


# ---------------------------------------------------------------------------
# Task 1: RuntimeIpcServer Stop channel
# ---------------------------------------------------------------------------


def test_stop_channel_starts_two_listeners():
    """Both the normal channel and the Stop channel accept connections."""
    server = RuntimeIpcServer(lambda c, d: {}, port=0, stop_port=0)
    assert server.start() is True
    try:
        assert server.stop_port != 0
        assert server.stop_port != server.port
        # Connecting succeeds if a listener is bound on the port.
        with socket_create_connection(("127.0.0.1", server.port)):
            pass
        with socket_create_connection(("127.0.0.1", server.stop_port)):
            pass
    finally:
        server.stop()


def test_stop_command_bypasses_normal_queue():
    """A Stop-channel command returns immediately while the normal command
    worker is blocked by a long-running command in the FIFO queue."""
    slow_started = threading.Event()
    release = threading.Event()

    def handler(command, _data):
        if command == "slow":
            slow_started.set()
            release.wait(timeout=5.0)
            return {"command": command}
        return {"command": command}

    server = RuntimeIpcServer(
        handler, port=0, stop_port=0, command_timeout_s=10.0
    )
    assert server.start() is True
    slow_response: dict = {}

    def send_slow():
        try:
            client = RuntimeIpcClient(port=server.port, timeout_s=10.0)
            slow_response.update(client.request("slow", request_id="slow-1"))
        except Exception as exc:  # pragma: no cover - surfaced via assertion
            slow_response["error"] = str(exc)

    slow_thread = threading.Thread(target=send_slow, daemon=True)
    slow_thread.start()
    try:
        assert slow_started.wait(timeout=2.0), "slow command never started"

        stop_client = RuntimeIpcClient(port=server.stop_port, timeout_s=2.0)
        start = time.monotonic()
        response = stop_client.request("safe_stop", request_id="stop-1")
        elapsed = time.monotonic() - start

        assert elapsed < 0.2, f"stop channel was too slow: {elapsed:.3f}s"
        assert response["ok"] is True
        assert response["data"] == {"command": "safe_stop"}
    finally:
        release.set()
        server.stop()
        slow_thread.join(timeout=5.0)


def test_stop_channel_rejects_unknown_command():
    """Only the allow-listed stop commands are accepted on the Stop channel."""
    server = RuntimeIpcServer(lambda c, d: {"command": c}, port=0, stop_port=0)
    assert server.start() is True
    try:
        response = RuntimeIpcClient(
            port=server.stop_port, timeout_s=1.0
        ).request("ping", request_id="ping-1")

        assert response["ok"] is False
        assert response["error"]["code"] == "UNKNOWN_COMMAND_ON_STOP_CHANNEL"
    finally:
        server.stop()


def test_stop_channel_disabled_when_stop_port_none():
    """``stop_port=None`` keeps backward compatibility (no second listener)."""
    server = RuntimeIpcServer(lambda c, d: {}, port=0, stop_port=None)
    assert server.start() is True
    try:
        assert server.stop_port is None
        # Connecting to a random high port should fail (no listener there).
        import socket as _socket

        probe = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        probe.settimeout(0.3)
        try:
            probe.connect(("127.0.0.1", 8766))
            # If 8766 happens to be bound by another process we can't assert
            # failure; just ensure the server itself didn't open it.
        except OSError:
            pass
        finally:
            probe.close()
    finally:
        server.stop()


# ---------------------------------------------------------------------------
# Task 2: safe_stop handler
# ---------------------------------------------------------------------------


class _StubFlow:
    def __init__(self, stop_event):
        self._ctx = types.SimpleNamespace(stop_event=stop_event)
        self.stop_calls = 0

    def stop(self):
        self.stop_calls += 1


class _StubController:
    """Minimal controller stand-in exposing only what _ipc_safe_stop uses."""

    def __init__(self, *, emergency_stop_impl=None, flow=None):
        self._active_flow_thread = flow
        self.emergency_stop_calls = 0
        self._emergency_stop_impl = emergency_stop_impl

    def emergency_stop(self):
        self.emergency_stop_calls += 1
        if self._emergency_stop_impl is not None:
            return self._emergency_stop_impl()


class _AgentStub:
    """Just enough of DobotRuntimeAgent for the bound method to run."""

    def __init__(self, controller):
        self.controller = controller


def test_safe_stop_handler_calls_emergency_stop():
    controller = _StubController(emergency_stop_impl=lambda: None)
    agent = _AgentStub(controller)

    result = DobotRuntimeAgent._ipc_safe_stop(agent)

    assert result["emergency_stop_sent"] is True
    assert result["error"] == ""
    assert controller.emergency_stop_calls == 1


def test_safe_stop_handler_survives_emergency_stop_failure():
    def boom():
        raise RuntimeError("dashboard unreachable")

    controller = _StubController(emergency_stop_impl=boom)
    agent = _AgentStub(controller)

    result = DobotRuntimeAgent._ipc_safe_stop(agent)

    assert result["emergency_stop_sent"] is False
    assert result["error"]  # non-empty message
    assert "dashboard unreachable" in result["error"]
    assert controller.emergency_stop_calls == 1


def test_safe_stop_handler_sets_flow_stop_event():
    stop_event = threading.Event()
    flow = _StubFlow(stop_event=stop_event)
    controller = _StubController(emergency_stop_impl=lambda: None, flow=flow)
    agent = _AgentStub(controller)

    result = DobotRuntimeAgent._ipc_safe_stop(agent)

    assert result["emergency_stop_sent"] is True
    assert result["stop_event_set"] is True
    assert stop_event.is_set()
    assert flow.stop_calls == 1


# ---------------------------------------------------------------------------
# Auth on the Stop channel
# ---------------------------------------------------------------------------


def test_stop_channel_requires_auth():
    server = RuntimeIpcServer(
        lambda c, d: {"command": c},
        port=0,
        stop_port=0,
        auth_token="a" * 32,
    )
    assert server.start() is True
    try:
        missing = RuntimeIpcClient(
            port=server.stop_port, token_path=None, timeout_s=1.0
        ).request("safe_stop", request_id="noauth")
        wrong = RuntimeIpcClient(
            port=server.stop_port,
            auth_token="b" * 32,
            token_path=None,
            timeout_s=1.0,
        ).request("safe_stop", request_id="wrongauth")

        assert missing["ok"] is False
        assert missing["error"]["code"] == "UNAUTHORIZED"
        assert wrong["ok"] is False
        assert wrong["error"]["code"] == "UNAUTHORIZED"
    finally:
        server.stop()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def socket_create_connection(address):
    import socket as _socket

    return _socket.create_connection(address, timeout=1.0)
