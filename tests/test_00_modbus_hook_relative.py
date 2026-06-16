"""Regression tests for Modbus hook command handling and relative queued motion."""
import asyncio
import importlib
import sys
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
    sys.modules.pop("dobot_move.modbus_server", None)
    try:
        modbus_server = importlib.import_module("dobot_move.modbus_server")
    except ImportError as exc:
        if "pymodbus" not in str(exc):
            raise
        _install_pymodbus_stub()
        sys.modules.pop("dobot_move.modbus_server", None)
        modbus_server = importlib.import_module("dobot_move.modbus_server")
    robot_controller = importlib.import_module("dobot_move.robot_controller")
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
        on_command_callback=lambda cmd, mode=0: calls.append((cmd, mode))
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
        on_command_callback=lambda cmd, mode=0: calls.append((cmd, mode))
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
        on_command_callback=lambda cmd, mode=0: calls.append((cmd, mode))
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
        on_command_callback=lambda cmd, mode=0: calls.append((cmd, mode))
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
        on_command_callback=lambda cmd, mode=0: calls.append((cmd, mode))
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
        on_command_callback=lambda cmd, mode=0: calls.append((cmd, mode))
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

    controller._on_modbus_command(modbus_server.CMD_HOOK, mode=modbus_server.MODE_AUTO)

    assert controller._modbus_status_override == modbus_server.STATUS_ROBOT_ERR
    assert fake_server.calls == [
        {"status": modbus_server.STATUS_ROBOT_ERR, "mode": modbus_server.MODE_AUTO}
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

    assert fake_dashboard.calls == ["Stop"]
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

    assert fake_dashboard.calls == ["Stop"]
    assert fake_server.calls == [
        {"status": modbus_server.STATUS_IDLE, "mode": modbus_server.MODE_MANUAL}
    ]
    assert controller._modbus_status_override == modbus_server.STATUS_IDLE


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

    assert controller._modbus_status_override == modbus_server.STATUS_ROBOT_ERR
    assert fake_server.calls == [
        {"status": modbus_server.STATUS_ROBOT_ERR, "mode": modbus_server.MODE_AUTO}
    ]


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
    with open("dobot_move/workers.py", encoding="utf-8") as f:
        source = f.read()

    assert "if resp_code is not False and resp_code == 0:" in source


def test_gui_modbus_program_uses_signal_and_resets_after_success():
    with open("dobot_move/gui_app.py", encoding="utf-8") as f:
        gui_source = f.read()
    with open("dobot_move/gui_mixins/grasp_flow_mixin.py", encoding="utf-8") as f:
        flow_source = f.read()

    assert "_modbus_program_requested = pyqtSignal()" in gui_source
    assert "set_modbus_program_runner" in gui_source
    assert "run_grasp_flow(modbus_triggered=True)" in gui_source
    assert "mark_modbus_program_finished(True)" in flow_source
    assert "reset_modbus_status_to_idle" not in flow_source
