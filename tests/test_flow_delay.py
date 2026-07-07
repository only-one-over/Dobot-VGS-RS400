import sys
import threading
import time
import types

if "pyrealsense2" not in sys.modules:
    sys.modules["pyrealsense2"] = types.ModuleType("pyrealsense2")

from dobot_move.flow.workers import (
    FlowThread,
    validate_grasp_flow_modules,
    wait_for_flow_delay,
    wait_for_flow_delay_or_signal,
)


class _FakeModbusServer:
    def __init__(self, running=True):
        self.running = running

    def is_running(self):
        return self.running


class _DelayOnlyController:
    def __init__(self, modbus_server=None, auto_release=False):
        self._active_flow_thread = None
        self.is_enabled = True
        self.modbus_server = modbus_server
        self.auto_release = auto_release
        self.delay_release_event = threading.Event()
        self.delay_wait_started = False
        self.delay_wait_ended = False
        self.delay_restore_running = None
        self.released = False

    def acquire_motion(self, owner):
        return owner == "flow"

    def release_motion(self, owner):
        self.released = owner == "flow"

    def begin_modbus_delay_wait(self):
        self.delay_release_event.clear()
        self.delay_wait_started = True
        if self.auto_release:
            self.delay_release_event.set()

    def is_modbus_delay_released(self):
        return self.delay_release_event.is_set()

    def end_modbus_delay_wait(self, restore_running=True):
        self.delay_wait_ended = True
        self.delay_restore_running = restore_running
        self.delay_release_event.clear()


def test_flow_delay_waits_for_configured_duration():
    started = time.monotonic()

    assert wait_for_flow_delay(0.03, threading.Event(), poll_interval=0.005)

    assert time.monotonic() - started >= 0.025


def test_flow_delay_stops_promptly():
    stop_event = threading.Event()
    stop_event.set()
    started = time.monotonic()

    assert not wait_for_flow_delay(10.0, stop_event)

    assert time.monotonic() - started < 0.1


def test_flow_delay_does_not_count_paused_time():
    paused = [True]
    resume_timer = threading.Timer(0.04, lambda: paused.__setitem__(0, False))
    resume_timer.start()
    started = time.monotonic()
    try:
        assert wait_for_flow_delay(
            0.03,
            threading.Event(),
            is_paused_ref=paused,
            poll_interval=0.005,
        )
    finally:
        resume_timer.join()

    assert time.monotonic() - started >= 0.06


def test_flow_delay_signal_can_complete_immediately():
    started = time.monotonic()

    result = wait_for_flow_delay_or_signal(
        10.0,
        threading.Event(),
        poll_interval=0.005,
        signal_checker=lambda: True,
    )

    assert result == "signal"
    assert time.monotonic() - started < 0.1


def test_flow_delay_signal_completes_before_timeout():
    signal = threading.Event()
    signal_timer = threading.Timer(0.03, signal.set)
    signal_timer.start()
    try:
        result = wait_for_flow_delay_or_signal(
            0.2,
            threading.Event(),
            poll_interval=0.005,
            signal_checker=signal.is_set,
        )
    finally:
        signal_timer.join()

    assert result == "signal"


def test_flow_delay_without_matching_signal_times_out_normally():
    result = wait_for_flow_delay_or_signal(
        0.03,
        threading.Event(),
        poll_interval=0.005,
        signal_checker=lambda: False,
    )

    assert result == "timeout"


def test_flow_delay_does_not_complete_from_signal_while_paused():
    paused = [True]
    resume_timer = threading.Timer(0.04, lambda: paused.__setitem__(0, False))
    resume_timer.start()
    started = time.monotonic()
    try:
        result = wait_for_flow_delay_or_signal(
            1.0,
            threading.Event(),
            is_paused_ref=paused,
            poll_interval=0.005,
            signal_checker=lambda: True,
        )
    finally:
        resume_timer.join()

    assert result == "signal"
    assert time.monotonic() - started >= 0.035


def test_flow_delay_validation_rejects_invalid_duration():
    modules = [
        {
            "type": "delay",
            "name": "延时",
            "params": {"duration_s": 0},
        }
    ]

    errors = validate_grasp_flow_modules(modules)

    assert errors == ["第1步「延时」：延时时长必须大于0秒"]


def test_flow_delay_validation_accepts_valid_duration():
    modules = [
        {
            "type": "delay",
            "name": "延时",
            "params": {"duration_s": 1.5},
        }
    ]

    assert validate_grasp_flow_modules(modules) == []


def test_flow_delay_validation_rejects_invalid_wait_mode():
    modules = [
        {
            "type": "delay",
            "name": "等待PLC",
            "params": {
                "wait_mode": "unknown",
                "duration_s": 20,
            },
        }
    ]

    errors = validate_grasp_flow_modules(modules)

    assert errors == ["第1步「等待PLC」：延时等待方式无效"]


def test_flow_thread_executes_delay_module_and_finishes():
    controller = _DelayOnlyController()
    results = []
    thread = FlowThread(
        controller,
        vision_d435i=None,
        vision_d405=None,
        grasp_flow_modules=[
            {
                "type": "delay",
                "name": "等待夹具稳定",
                "params": {"duration_s": 0.01},
            }
        ],
        is_paused_ref=[False],
    )
    thread.flow_finished.connect(results.append)

    thread.run()

    assert results == [True]
    assert controller.released
    assert controller._active_flow_thread is None


def test_flow_thread_modbus_signal_finishes_before_timeout():
    controller = _DelayOnlyController(
        _FakeModbusServer(),
        auto_release=True,
    )
    results = []
    logs = []
    thread = FlowThread(
        controller,
        vision_d435i=None,
        vision_d405=None,
        grasp_flow_modules=[
            {
                "type": "delay",
                "name": "等待PLC",
                "params": {
                    "wait_mode": "modbus_or_timeout",
                    "duration_s": 10,
                },
            }
        ],
        is_paused_ref=[False],
    )
    thread.flow_finished.connect(results.append)
    thread.flow_log.connect(logs.append)

    thread.run()

    assert results == [True]
    assert any("收到Modbus信号" in message for message in logs)
    assert controller.delay_wait_started
    assert controller.delay_wait_ended
    assert controller.delay_restore_running is True


def test_flow_thread_modbus_unavailable_times_out_and_continues():
    controller = _DelayOnlyController(_FakeModbusServer(running=False))
    results = []
    logs = []
    thread = FlowThread(
        controller,
        vision_d435i=None,
        vision_d405=None,
        grasp_flow_modules=[
            {
                "type": "delay",
                "name": "等待PLC",
                "params": {
                    "wait_mode": "modbus_or_timeout",
                    "duration_s": 0.01,
                },
            }
        ],
        is_paused_ref=[False],
    )
    thread.flow_finished.connect(results.append)
    thread.flow_log.connect(logs.append)

    thread.run()

    assert results == [True]
    assert any("Modbus服务未运行" in message for message in logs)
    assert any("等待超时" in message for message in logs)
    assert controller.delay_wait_started
    assert controller.delay_wait_ended
