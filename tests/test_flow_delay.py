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
        self.released = False

    def acquire_motion(self, owner):
        return owner == "flow"

    def release_motion(self, owner):
        self.released = owner == "flow"


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


def test_flow_delay_times_out_normally():
    result = wait_for_flow_delay_or_signal(
        0.03,
        threading.Event(),
        poll_interval=0.005,
    )

    assert result == "timeout"


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

    assert errors == ["第1步「等待PLC」：延时等待方式无效（仅支持 time）"]


def test_flow_delay_validation_rejects_modbus_or_timeout_mode():
    """PR 7: modbus_or_timeout 模式已移除，校验应拒绝该模式。"""
    modules = [
        {
            "type": "delay",
            "name": "等待PLC",
            "params": {
                "wait_mode": "modbus_or_timeout",
                "duration_s": 10,
            },
        }
    ]

    errors = validate_grasp_flow_modules(modules)

    assert errors == ["第1步「等待PLC」：延时等待方式无效（仅支持 time）"]


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
