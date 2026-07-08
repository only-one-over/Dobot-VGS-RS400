"""Regression tests for Modbus hook command handling and relative queued motion."""
import asyncio
import importlib
import sys
import threading
import time
import types


def _install_pymodbus_stub():
    pymodbus = types.ModuleType("pymodbus")

    class ModbusDeviceIdentification:
        pass

    pymodbus.ModbusDeviceIdentification = ModbusDeviceIdentification

    server = types.ModuleType("pymodbus.server")

    class ModbusTcpServer:
        pass

    server.ModbusTcpServer = ModbusTcpServer

    simulator = types.ModuleType("pymodbus.simulator")

    class SimData:
        def __init__(self, *args, **kwargs):
            pass

    class SimDevice:
        def __init__(self, *args, **kwargs):
            pass

    class DataType:
        REGISTERS = "registers"

    simulator.SimData = SimData
    simulator.SimDevice = SimDevice
    simulator.DataType = DataType

    sys.modules["pymodbus"] = pymodbus
    sys.modules["pymodbus.server"] = server
    sys.modules["pymodbus.simulator"] = simulator


def _real_modules():
    sys.modules.pop("dobot_move.communication.modbus_server", None)
    try:
        modbus_server = importlib.import_module("dobot_move.communication.modbus_server")
    except ImportError as exc:
        if "pymodbus" not in str(exc):
            raise
        _install_pymodbus_stub()
        sys.modules.pop("dobot_move.communication.modbus_server", None)
        modbus_server = importlib.import_module("dobot_move.communication.modbus_server")
    robot_controller = importlib.import_module("dobot_move.robot.robot_controller")
    robot_controller = importlib.reload(robot_controller)
    return modbus_server, robot_controller


class _FakeStatusServer:
    def __init__(self):
        self.calls = []

    def update_status_registers(self, **kwargs):
        self.calls.append(kwargs)


class _FakeRelativeDashboard:
    def __init__(self):
        self.calls = []

    def _record(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))
        return "0,{0},42;"

    def RelMovLUser(self, *args, **kwargs):
        return self._record("RelMovLUser", *args, **kwargs)

    def RelMovLTool(self, *args, **kwargs):
        return self._record("RelMovLTool", *args, **kwargs)

    def RelMovJUser(self, *args, **kwargs):
        return self._record("RelMovJUser", *args, **kwargs)

    def RelMovJTool(self, *args, **kwargs):
        return self._record("RelMovJTool", *args, **kwargs)


class _FakeStopDashboard:
    def __init__(self):
        self.calls = []

    def Stop(self):
        self.calls.append("Stop")
        return "0,{0},0;"

    def Pause(self):
        self.calls.append("Pause")
        return "0,{0},0;"

    def ClearError(self):
        self.calls.append("ClearError")
        return "0,{0},0;"

    def EmergencyStop(self, mode):
        self.calls.append(("EmergencyStop", mode))
        return "0,{0},0;"

    def EnableRobot(self):
        self.calls.append("EnableRobot")
        return "0,{0},0;"


def _controller_with_fake_relative_dashboard():
    _, robot_controller = _real_modules()
    controller = robot_controller.DobotController("192.168.1.50")
    controller.is_connected = True
    controller._user_index = 1
    controller._tool_index = 2
    controller.dashboard = _FakeRelativeDashboard()
    return controller


def test_modbus_wire_address_zero_hook_triggers_command_with_mode():
    modbus_server, _ = _real_modules()
    calls = []
    server = modbus_server.DobotModbusServer(
        on_command_callback=lambda cmd, mode=0, hook_type=0: calls.append((cmd, mode))
    )

    asyncio.run(
        server._action_callback(
            function_code=16,
            start_address=0,
            address=0,
            count=1,
            current_registers=[0, modbus_server.MODE_MANUAL, 0],
            set_values=[modbus_server.CMD_HOOK],
        )
    )

    assert calls == [(modbus_server.CMD_HOOK, modbus_server.MODE_MANUAL)]


def test_modbus_display_address_hook_is_still_accepted():
    modbus_server, _ = _real_modules()
    calls = []
    server = modbus_server.DobotModbusServer(
        on_command_callback=lambda cmd, mode=0, hook_type=0: calls.append((cmd, mode))
    )

    asyncio.run(
        server._action_callback(
            function_code=16,
            start_address=modbus_server.REG_CMD_STATUS,
            address=modbus_server.REG_CMD_STATUS,
            count=1,
            current_registers=[0, modbus_server.MODE_MANUAL, 0],
            set_values=[modbus_server.CMD_HOOK],
        )
    )

    assert calls == [(modbus_server.CMD_HOOK, modbus_server.MODE_MANUAL)]


def test_modbus_wire_address_zero_reset_triggers_command_with_mode():
    modbus_server, _ = _real_modules()
    calls = []
    server = modbus_server.DobotModbusServer(
        on_command_callback=lambda cmd, mode=0, hook_type=0: calls.append((cmd, mode))
    )

    asyncio.run(
        server._action_callback(
            function_code=16,
            start_address=0,
            address=0,
            count=1,
            current_registers=[0, modbus_server.MODE_AUTO, 0],
            set_values=[modbus_server.CMD_RESET],
        )
    )

    assert calls == [(modbus_server.CMD_RESET, modbus_server.MODE_AUTO)]


def test_modbus_wire_address_zero_status_2_does_not_trigger_command():
    modbus_server, _ = _real_modules()
    calls = []
    server = modbus_server.DobotModbusServer(
        on_command_callback=lambda cmd, mode=0, hook_type=0: calls.append((cmd, mode))
    )

    asyncio.run(
        server._action_callback(
            function_code=16,
            start_address=0,
            address=0,
            count=1,
            current_registers=[0, modbus_server.MODE_AUTO, 0],
            set_values=[modbus_server.STATUS_STANDBY],
        )
    )

    assert calls == []


def test_internal_status_write_2_does_not_trigger_initial_command():
    modbus_server, _ = _real_modules()
    calls = []
    server = modbus_server.DobotModbusServer(
        on_command_callback=lambda cmd, mode=0, hook_type=0: calls.append((cmd, mode))
    )
    server._mark_internal_status_write(0, [modbus_server.STATUS_STANDBY, modbus_server.MODE_AUTO])

    asyncio.run(
        server._action_callback(
            function_code=16,
            start_address=0,
            address=0,
            count=2,
            current_registers=[0, modbus_server.MODE_AUTO, 0],
            set_values=[modbus_server.STATUS_STANDBY, modbus_server.MODE_AUTO],
        )
    )

    assert calls == []


def test_internal_status_write_0_does_not_trigger_stop_command():
    modbus_server, _ = _real_modules()
    calls = []
    server = modbus_server.DobotModbusServer(
        on_command_callback=lambda cmd, mode=0, hook_type=0: calls.append((cmd, mode))
    )
    server._mark_internal_status_write(0, [modbus_server.STATUS_IDLE, modbus_server.MODE_AUTO])

    asyncio.run(
        server._action_callback(
            function_code=16,
            start_address=0,
            address=0,
            count=2,
            current_registers=[modbus_server.STATUS_HOOK_OK, modbus_server.MODE_AUTO, 0],
            set_values=[modbus_server.STATUS_IDLE, modbus_server.MODE_AUTO],
        )
    )

    assert calls == []


def test_hook_command_disconnected_writes_110():
    modbus_server, robot_controller = _real_modules()
    controller = robot_controller.DobotController("192.168.1.50")
    fake_server = _FakeStatusServer()
    controller.modbus_server = fake_server
    controller.is_connected = False
    controller.record_alarm = lambda *args, **kwargs: None
    controller.set_modbus_program_runner(
        lambda: True,
        readiness_checker=lambda: False,
    )

    controller._on_modbus_command(modbus_server.CMD_HOOK, mode=modbus_server.MODE_AUTO)

    assert controller._modbus_status_override == modbus_server.STATUS_HOOK_ERR
    assert fake_server.calls == [
        {"status": modbus_server.STATUS_HOOK_ERR, "mode": modbus_server.MODE_AUTO}
    ]


def test_stop_command_connected_stops_robot_and_holds_idle_status():
    modbus_server, robot_controller = _real_modules()
    controller = robot_controller.DobotController("192.168.1.50")
    fake_server = _FakeStatusServer()
    fake_dashboard = _FakeStopDashboard()
    controller.modbus_server = fake_server
    controller.dashboard = fake_dashboard
    controller.is_connected = True

    controller._on_modbus_command(modbus_server.CMD_STOP, mode=modbus_server.MODE_AUTO)

    assert fake_dashboard.calls == ["Stop", "ClearError", "EnableRobot"]
    assert fake_server.calls == [
        {"status": modbus_server.STATUS_IDLE, "mode": modbus_server.MODE_AUTO}
    ]
    assert controller._modbus_status_override == modbus_server.STATUS_IDLE


def test_stop_command_is_not_ignored_in_manual_mode():
    modbus_server, robot_controller = _real_modules()
    controller = robot_controller.DobotController("192.168.1.50")
    fake_server = _FakeStatusServer()
    fake_dashboard = _FakeStopDashboard()
    controller.modbus_server = fake_server
    controller.dashboard = fake_dashboard
    controller.is_connected = True

    controller._on_modbus_command(modbus_server.CMD_STOP, mode=modbus_server.MODE_MANUAL)

    assert fake_dashboard.calls == ["Stop", "ClearError", "EnableRobot"]
    assert fake_server.calls == [
        {"status": modbus_server.STATUS_IDLE, "mode": modbus_server.MODE_MANUAL}
    ]
    assert controller._modbus_status_override == modbus_server.STATUS_IDLE


def test_stop_command_clears_fault_latches_and_software_estop():
    modbus_server, robot_controller = _real_modules()
    controller = robot_controller.DobotController("192.168.1.50")
    fake_server = _FakeStatusServer()
    fake_dashboard = _FakeStopDashboard()
    controller.modbus_server = fake_server
    controller.dashboard = fake_dashboard
    controller.is_connected = True
    controller.software_emergency_active = True
    controller.last_error = "old fault"
    controller.clear_error_retry_count = 2
    controller._last_fault_code = 123
    controller._robot_alarm_recorded = True
    controller._modbus_status_override = modbus_server.STATUS_ROBOT_ERR

    controller._on_modbus_command(modbus_server.CMD_STOP, mode=modbus_server.MODE_AUTO)

    assert fake_dashboard.calls == ["Stop", ("EmergencyStop", 0), "ClearError", "EnableRobot"]
    assert controller.software_emergency_active is False
    assert controller.last_error == ""
    assert controller.clear_error_retry_count == 0
    assert controller._last_fault_code == 0
    assert controller._robot_alarm_recorded is False
    assert controller._modbus_status_override == modbus_server.STATUS_IDLE
    assert fake_server.calls == [
        {"status": modbus_server.STATUS_IDLE, "mode": modbus_server.MODE_AUTO}
    ]


def test_update_modbus_status_preserves_zero_override():
    modbus_server, robot_controller = _real_modules()
    controller = robot_controller.DobotController("192.168.1.50")
    fake_server = _FakeStatusServer()
    controller.modbus_server = fake_server
    controller.is_connected = True
    controller.is_enabled = True
    controller._modbus_status_override = modbus_server.STATUS_IDLE

    controller._update_modbus_status()

    assert fake_server.calls == [
        {"status": modbus_server.STATUS_IDLE, "mode": modbus_server.MODE_AUTO}
    ]


def test_reset_command_connected_dispatches_move_initial():
    modbus_server, robot_controller = _real_modules()
    controller = robot_controller.DobotController("192.168.1.50")
    controller.is_connected = True
    dispatched = []
    controller._modbus_dispatch_motion = lambda func, name: dispatched.append((func, name)) or True

    controller._on_modbus_command(modbus_server.CMD_RESET, mode=modbus_server.MODE_AUTO)

    assert dispatched == [(controller._modbus_move_initial, "回原点")]


def test_runtime_recovery_lock_only_accepts_zero():
    modbus_server, robot_controller = _real_modules()
    controller = robot_controller.DobotController("192.168.1.50")
    fake_server = _FakeStatusServer()
    controller.modbus_server = fake_server
    controller.record_alarm = lambda *args, **kwargs: None
    cleared = []
    controller.set_runtime_recovery_required(True, on_cleared=lambda: cleared.append(True))

    controller._on_modbus_command(modbus_server.CMD_RESET, mode=modbus_server.MODE_AUTO)
    assert controller._runtime_recovery_required is True
    assert cleared == []
    assert fake_server.calls[-1]["status"] == modbus_server.STATUS_HOOK_ERR

    controller._on_modbus_command(modbus_server.CMD_STOP, mode=modbus_server.MODE_AUTO)
    assert controller._runtime_recovery_required is False
    assert cleared == [True]
    assert fake_server.calls[-1]["status"] == modbus_server.STATUS_IDLE


def test_reset_value_releases_delay_instead_of_dispatching_reset():
    modbus_server, robot_controller = _real_modules()
    controller = robot_controller.DobotController("192.168.1.50")
    fake_server = _FakeStatusServer()
    controller.modbus_server = fake_server
    controller._active_flow_thread = object()
    dispatched = []
    controller._modbus_dispatch_motion = lambda func, name: dispatched.append((func, name)) or True

    controller.begin_modbus_delay_wait()
    controller._on_modbus_command(modbus_server.CMD_HOOK, mode=modbus_server.MODE_AUTO)
    assert not controller.is_modbus_delay_released()
    controller._on_modbus_command(modbus_server.CMD_RESET, mode=modbus_server.MODE_AUTO)

    assert fake_server.calls == [
        {"status": modbus_server.STATUS_DELAY_WAIT, "mode": modbus_server.MODE_AUTO},
        {"status": modbus_server.STATUS_DELAY_WAIT, "mode": modbus_server.MODE_AUTO},
        {"status": modbus_server.STATUS_DELAY_WAIT, "mode": modbus_server.MODE_AUTO},
    ]
    assert controller.is_modbus_delay_released()
    assert dispatched == []

    controller.end_modbus_delay_wait()
    assert fake_server.calls[-1] == {
        "status": modbus_server.STATUS_RUNNING,
        "mode": modbus_server.MODE_AUTO,
    }


def test_reset_and_hook_are_ignored_during_non_delay_flow_execution():
    modbus_server, robot_controller = _real_modules()
    controller = robot_controller.DobotController("192.168.1.50")
    fake_server = _FakeStatusServer()
    controller.modbus_server = fake_server
    controller._active_flow_thread = object()
    dispatched = []
    runner_calls = []
    controller._modbus_dispatch_motion = lambda func, name: dispatched.append((func, name)) or True
    controller.set_modbus_program_runner(lambda: runner_calls.append("run") or True)

    controller._on_modbus_command(modbus_server.CMD_RESET, mode=modbus_server.MODE_AUTO)
    controller._on_modbus_command(modbus_server.CMD_HOOK, mode=modbus_server.MODE_AUTO)

    assert dispatched == []
    assert runner_calls == []
    assert not controller.is_modbus_delay_released()
    assert fake_server.calls == [
        {"status": modbus_server.STATUS_RUNNING, "mode": modbus_server.MODE_AUTO},
        {"status": modbus_server.STATUS_RUNNING, "mode": modbus_server.MODE_AUTO},
    ]


def test_reset_command_success_writes_running_then_reset_complete(monkeypatch):
    modbus_server, robot_controller = _real_modules()
    controller = robot_controller.DobotController("192.168.1.50")
    fake_server = _FakeStatusServer()
    controller.modbus_server = fake_server
    controller.is_connected = True
    controller.acquire_motion = lambda owner: True
    controller.release_motion = lambda owner: None
    controller.move_to_point = lambda *args, **kwargs: True
    controller.ensure_robot_ready_for_motion = lambda auto_enable=True: True
    monkeypatch.setattr(robot_controller, "get_initial_point", lambda: [300, 0, 200, 0, 0, -90])

    controller._modbus_move_initial()

    statuses = [call["status"] for call in fake_server.calls]
    assert statuses == [modbus_server.STATUS_RUNNING, modbus_server.STATUS_STANDBY]
    assert controller._modbus_status_override == modbus_server.STATUS_STANDBY


def test_hook_command_connected_requests_program_runner():
    modbus_server, robot_controller = _real_modules()
    controller = robot_controller.DobotController("192.168.1.50")
    fake_server = _FakeStatusServer()
    controller.modbus_server = fake_server
    controller.is_connected = True
    calls = []
    controller.ensure_robot_ready_for_motion = lambda auto_enable=True: True
    controller.set_modbus_program_runner(lambda: calls.append("runner") or True)

    controller._on_modbus_command(modbus_server.CMD_HOOK, mode=modbus_server.MODE_AUTO)
    controller._modbus_exec_thread.join(timeout=1.0)

    assert calls == ["runner"]
    assert fake_server.calls == [
        {"status": modbus_server.STATUS_RUNNING, "mode": modbus_server.MODE_AUTO}
    ]


def test_hook_command_not_ready_writes_robot_error():
    modbus_server, robot_controller = _real_modules()
    controller = robot_controller.DobotController("192.168.1.50")
    fake_server = _FakeStatusServer()
    controller.modbus_server = fake_server
    controller.is_connected = True
    controller.ensure_robot_ready_for_motion = lambda auto_enable=True: False
    controller.last_error = "not ready"
    controller.set_modbus_program_runner(lambda: True)

    controller._on_modbus_command(modbus_server.CMD_HOOK, mode=modbus_server.MODE_AUTO)
    controller._modbus_exec_thread.join(timeout=1.0)

    assert controller._modbus_status_override == modbus_server.STATUS_HOOK_ERR
    assert fake_server.calls == [
        {"status": modbus_server.STATUS_RUNNING, "mode": modbus_server.MODE_AUTO},
        {"status": modbus_server.STATUS_HOOK_ERR, "mode": modbus_server.MODE_AUTO},
    ]


def test_hook_can_retry_directly_after_readiness_recovers():
    modbus_server, robot_controller = _real_modules()
    controller = robot_controller.DobotController("192.168.1.50")
    fake_server = _FakeStatusServer()
    controller.modbus_server = fake_server
    controller.is_connected = True
    controller.ensure_robot_ready_for_motion = lambda auto_enable=True: True
    state = {"ready": False}
    calls = []

    class Result:
        @property
        def ok(self):
            return state["ready"]

        @property
        def message(self):
            return "设备已就绪" if self.ok else "D405 未连接"

    controller.set_modbus_program_runner(
        lambda: calls.append("runner") or True,
        readiness_checker=Result,
    )

    controller._on_modbus_command(modbus_server.CMD_HOOK, mode=modbus_server.MODE_AUTO)
    assert controller._modbus_status_override == modbus_server.STATUS_HOOK_ERR
    assert calls == []

    state["ready"] = True
    controller._on_modbus_command(modbus_server.CMD_HOOK, mode=modbus_server.MODE_AUTO)
    controller._modbus_exec_thread.join(timeout=1.0)

    assert calls == ["runner"]
    assert controller._modbus_status_override == modbus_server.STATUS_RUNNING


def test_hook_background_prepare_does_not_block_command_callback():
    modbus_server, robot_controller = _real_modules()
    controller = robot_controller.DobotController("192.168.1.50")
    controller.modbus_server = _FakeStatusServer()
    controller.is_connected = True
    release = threading.Event()

    def slow_prepare(auto_enable=True):
        release.wait(1.0)
        return True

    controller.ensure_robot_ready_for_motion = slow_prepare
    controller.set_modbus_program_runner(
        lambda: True,
        readiness_checker=lambda: True,
    )

    started_at = time.monotonic()
    controller._on_modbus_command(modbus_server.CMD_HOOK, mode=modbus_server.MODE_AUTO)
    elapsed = time.monotonic() - started_at
    release.set()
    controller._modbus_exec_thread.join(timeout=1.0)

    assert elapsed < 0.2


def test_ensure_robot_ready_auto_enables_with_fresh_feedback():
    _, robot_controller = _real_modules()
    controller = robot_controller.DobotController("192.168.1.50")
    controller.is_connected = True
    controller.dashboard = object()
    controller.latest_feed_time = time.time()
    controller.feed_data = [[{"ErrorStatus": 0, "RobotMode": 4}]]
    calls = []

    def fake_enable():
        calls.append("enable")
        controller.is_enabled = True
        return True

    controller.enable_robot = fake_enable

    assert controller.ensure_robot_ready_for_motion(auto_enable=True)
    assert calls == ["enable"]
    assert controller.is_enabled is True


def test_ensure_robot_ready_rejects_alarm_state():
    _, robot_controller = _real_modules()
    controller = robot_controller.DobotController("192.168.1.50")
    controller.is_connected = True
    controller.dashboard = object()
    controller.latest_feed_time = time.time()
    controller.feed_data = [[{"ErrorStatus": 1, "RobotMode": 9}]]
    controller.record_alarm = lambda *args, **kwargs: None

    assert not controller.ensure_robot_ready_for_motion(auto_enable=True)
    assert "机器人报警" in controller.last_error


def test_hook_command_without_runner_writes_110():
    modbus_server, robot_controller = _real_modules()
    controller = robot_controller.DobotController("192.168.1.50")
    fake_server = _FakeStatusServer()
    controller.modbus_server = fake_server
    controller.is_connected = True
    controller.record_alarm = lambda *args, **kwargs: None

    controller._on_modbus_command(modbus_server.CMD_HOOK, mode=modbus_server.MODE_AUTO)

    assert controller._modbus_status_override == modbus_server.STATUS_HOOK_ERR
    assert fake_server.calls == [
        {"status": modbus_server.STATUS_HOOK_ERR, "mode": modbus_server.MODE_AUTO}
    ]


def test_program_finish_success_holds_hook_ok_status():
    modbus_server, robot_controller = _real_modules()
    controller = robot_controller.DobotController("192.168.1.50")
    fake_server = _FakeStatusServer()
    controller.modbus_server = fake_server

    controller.mark_modbus_program_finished(True)

    statuses = [call["status"] for call in fake_server.calls]
    assert statuses == [modbus_server.STATUS_HOOK_OK]
    assert controller._modbus_status_override == modbus_server.STATUS_HOOK_OK


def test_manual_mode_ignores_reset_and_hook_commands():
    modbus_server, robot_controller = _real_modules()
    controller = robot_controller.DobotController("192.168.1.50")
    fake_server = _FakeStatusServer()
    controller.modbus_server = fake_server
    controller.is_connected = True
    dispatched = []
    calls = []
    controller._modbus_dispatch_motion = lambda func, name: dispatched.append((func, name)) or True
    controller.set_modbus_program_runner(lambda: calls.append("runner") or True)

    controller._on_modbus_command(modbus_server.CMD_RESET, mode=modbus_server.MODE_MANUAL)
    controller._on_modbus_command(modbus_server.CMD_HOOK, mode=modbus_server.MODE_MANUAL)

    assert dispatched == []
    assert calls == []
    assert fake_server.calls == []


def test_send_relative_command_build_failure_returns_nonzero(monkeypatch):
    _, robot_controller = _real_modules()
    controller = robot_controller.DobotController("192.168.1.50")
    controller.is_connected = True
    controller.is_enabled = True
    controller.latest_feed_time = time.time()
    controller.latest_pose = [300, 0, 200, 0, 0, -90]
    controller._user_index = 0
    controller._tool_index = 0
    monkeypatch.setattr(
        controller,
        "_build_relative_command",
        lambda *args, **kwargs: (None, "RelMovLUser"),
    )

    resp_code, command_id = controller.send_relative_command(
        [0, 0, -10, 0, 0, 0],
        wait=False,
    )

    assert resp_code != 0
    assert resp_code is not False
    assert command_id is None


def test_build_relative_command_dispatches_to_user_and_tool_api_methods():
    cases = [
        ("user", "movl", "RelMovLUser"),
        ("tool", "movl", "RelMovLTool"),
        ("user", "movj", "RelMovJUser"),
        ("tool", "movj", "RelMovJTool"),
    ]

    for coord_system, motion_type, expected_name in cases:
        controller = _controller_with_fake_relative_dashboard()

        response, command_name = controller._build_relative_command(
            [1, 2, 3, 4, 5, 6],
            coord_system,
            motion_type,
            speed=40,
            acceleration=15,
            cp=7,
            r=-1,
        )

        assert response == "0,{0},42;"
        assert command_name == expected_name
        assert controller.dashboard.calls == [
            (
                expected_name,
                (1, 2, 3, 4, 5, 6),
                {"v": 40, "a": 15, "user": 1, "tool": 2, "cp": 7},
            )
        ]


def test_build_relative_command_uses_r_only_for_linear_relative_motion():
    controller = _controller_with_fake_relative_dashboard()

    response, command_name = controller._build_relative_command(
        [1, 2, 3, 4, 5, 6],
        "tool",
        "movl",
        speed=40,
        acceleration=15,
        cp=0,
        r=12,
    )

    assert response == "0,{0},42;"
    assert command_name == "RelMovLTool"
    assert controller.dashboard.calls == [
        (
            "RelMovLTool",
            (1, 2, 3, 4, 5, 6),
            {"v": 40, "a": 15, "user": 1, "tool": 2, "r": 12},
        )
    ]


def test_build_relative_command_does_not_pass_r_to_joint_relative_motion():
    controller = _controller_with_fake_relative_dashboard()

    response, command_name = controller._build_relative_command(
        [1, 2, 3, 4, 5, 6],
        "tool",
        "movj",
        speed=40,
        acceleration=15,
        cp=7,
        r=12,
    )

    assert response == "0,{0},42;"
    assert command_name == "RelMovJTool"
    assert controller.dashboard.calls == [
        (
            "RelMovJTool",
            (1, 2, 3, 4, 5, 6),
            {"v": 40, "a": 15, "user": 1, "tool": 2, "cp": 7},
        )
    ]


def test_queued_relative_path_does_not_treat_false_as_success():
    with open("dobot_move/flow/flow_executor.py", encoding="utf-8") as f:
        source = f.read()

    assert "if resp_code is not False and resp_code == 0:" in source


def test_force_guard_relative_path_forces_stop_each_mode():
    with open("dobot_move/flow/flow_executor.py", encoding="utf-8") as f:
        source = f.read()

    assert 'if force_guard is not None and execution_mode == "queued":' in source
    assert 'execution_mode = "stop_each"' in source
    assert "force_guard=force_guard" in source


def test_relative_path_segment_log_does_not_use_percent_formatting():
    with open("dobot_move/flow/flow_executor.py", encoding="utf-8") as f:
        source = f.read()

    assert "%.3fs\" % seg_elapsed" not in source
    assert "speed={seg_speed}% cp={seg_cp} r={seg_r} elapsed={seg_elapsed:.3f}s" in source


def test_runtime_exclusively_registers_modbus_program_runner():
    with open("dobot_move/ui/gui_app.py", encoding="utf-8") as f:
        gui_source = f.read()
    with open("dobot_move/runtime/runtime_agent.py", encoding="utf-8") as f:
        runtime_source = f.read()

    assert "set_modbus_program_runner" not in gui_source
    assert "DobotController(" not in gui_source
    assert "self.controller.set_modbus_program_runner(" in runtime_source
