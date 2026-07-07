import socket

import pytest

import dobot_move.robot.dobot_api as api_module


class _FakeSocket:
    def __init__(self, *, connect_error=None, send_error=None):
        self.connect_error = connect_error
        self.send_error = send_error
        self.timeout_calls = []
        self.connected_to = None
        self.closed = False
        self.sent = []

    def settimeout(self, value):
        self.timeout_calls.append(value)

    def connect(self, address):
        self.connected_to = address
        if self.connect_error is not None:
            raise self.connect_error

    def setsockopt(self, *args):
        del args

    def sendall(self, data):
        if self.send_error is not None:
            raise self.send_error
        self.sent.append(data)

    def recv(self, size):
        del size
        return b"0,{},RobotMode();"

    def shutdown(self, how):
        del how

    def close(self):
        self.closed = True


def test_socket_connect_timeout_is_set_before_connect(monkeypatch):
    fake_socket = _FakeSocket()
    monkeypatch.setattr(api_module.socket, "socket", lambda: fake_socket)

    client = api_module.DobotApiDashboard(
        "192.0.2.1",
        29999,
        connect_timeout=1.25,
        io_timeout=2.5,
    )

    assert fake_socket.connected_to == ("192.0.2.1", 29999)
    assert fake_socket.timeout_calls == [1.25, 2.5]
    client.close()


def test_failed_connect_closes_candidate_and_raises(monkeypatch):
    fake_socket = _FakeSocket(connect_error=socket.timeout("timed out"))
    monkeypatch.setattr(api_module.socket, "socket", lambda: fake_socket)

    with pytest.raises(socket.timeout):
        api_module.DobotApiDashboard(
            "192.0.2.1",
            29999,
            connect_timeout=0.2,
        )

    assert fake_socket.closed is True


def test_send_failure_does_not_enter_sdk_reconnect_loop(monkeypatch):
    fake_socket = _FakeSocket(send_error=OSError("network down"))
    monkeypatch.setattr(api_module.socket, "socket", lambda: fake_socket)
    client = api_module.DobotApiDashboard("192.0.2.1", 29999)
    reconnect_called = []
    monkeypatch.setattr(
        client,
        "reConnect",
        lambda *args: reconnect_called.append(args),
    )

    with pytest.raises(OSError, match="network down"):
        client.send_data("RobotMode()")

    assert reconnect_called == []


def test_feedback_reader_preserves_socket_timeout(monkeypatch):
    fake_socket = _FakeSocket()
    fake_socket.recv = lambda size: b""
    monkeypatch.setattr(api_module.socket, "socket", lambda: fake_socket)
    feedback = api_module.DobotApiFeedBack(
        "192.0.2.1",
        30004,
        connect_timeout=0.5,
        io_timeout=0.75,
    )

    with pytest.raises(ConnectionError, match="feedback socket closed"):
        feedback.feedBackData()

    assert fake_socket.timeout_calls[:2] == [0.5, 0.75]
