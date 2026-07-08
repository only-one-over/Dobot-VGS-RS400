"""PR 1 协议层测试：40004 钩子类型寄存器、40002 模式切换回调、命令回调 hook_type 传递。

覆盖 tasks.md Task 1-4：
- Task 1: 40004 寄存器常量 / REGISTER_NAME / REGISTER_VALUE_DESC
- Task 2: 40002 模式切换触发 on_mode_changed 回调
- Task 3: 40001 命令变化时读取 40004 并传递 hook_type；非法 40004 + cmd=3 写 40001=110
- Task 4: RobotController._on_modbus_command 签名扩展并转发 hook_type 给 runner
"""
import asyncio
import importlib
import sys
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


# ---------------------------------------------------------------------------
# Task 1: 40004 寄存器常量与映射
# ---------------------------------------------------------------------------

def test_reg_hook_type_constant_value():
    modbus_server, _ = _real_modules()
    assert modbus_server.REG_HOOK_TYPE == 40004


def test_hook_type_low_high_constants():
    modbus_server, _ = _real_modules()
    assert modbus_server.HOOK_TYPE_LOW == 0
    assert modbus_server.HOOK_TYPE_HIGH == 1


def test_register_name_contains_hook_type():
    modbus_server, _ = _real_modules()
    assert modbus_server.REGISTER_NAME[40004] == "提钩杆类型"


def test_register_value_desc_contains_hook_type_values():
    modbus_server, _ = _real_modules()
    assert modbus_server.REGISTER_VALUE_DESC[(40004, 0)] == "低钩子"
    assert modbus_server.REGISTER_VALUE_DESC[(40004, 1)] == "高钩子"


# ---------------------------------------------------------------------------
# Task 2: 40002 模式切换触发 on_mode_changed 回调
# ---------------------------------------------------------------------------

def test_mode_change_auto_to_manual_triggers_callback():
    modbus_server, _ = _real_modules()
    mode_events = []
    server = modbus_server.DobotModbusServer(
        on_mode_changed_callback=lambda old_mode, new_mode: mode_events.append((old_mode, new_mode))
    )

    asyncio.run(
        server._action_callback(
            function_code=16,
            start_address=0,
            address=modbus_server.REG_MODE - modbus_server.REG_CMD_STATUS,
            count=1,
            current_registers=[0, modbus_server.MODE_AUTO, 0],
            set_values=[modbus_server.MODE_MANUAL],
        )
    )

    assert mode_events == [(modbus_server.MODE_AUTO, modbus_server.MODE_MANUAL)]


def test_mode_change_manual_to_auto_triggers_callback():
    modbus_server, _ = _real_modules()
    mode_events = []
    server = modbus_server.DobotModbusServer(
        on_mode_changed_callback=lambda old_mode, new_mode: mode_events.append((old_mode, new_mode))
    )

    asyncio.run(
        server._action_callback(
            function_code=16,
            start_address=0,
            address=modbus_server.REG_MODE - modbus_server.REG_CMD_STATUS,
            count=1,
            current_registers=[0, modbus_server.MODE_MANUAL, 0],
            set_values=[modbus_server.MODE_AUTO],
        )
    )

    assert mode_events == [(modbus_server.MODE_MANUAL, modbus_server.MODE_AUTO)]


def test_mode_unchanged_does_not_trigger_callback():
    modbus_server, _ = _real_modules()
    mode_events = []
    server = modbus_server.DobotModbusServer(
        on_mode_changed_callback=lambda old_mode, new_mode: mode_events.append((old_mode, new_mode))
    )

    asyncio.run(
        server._action_callback(
            function_code=16,
            start_address=0,
            address=modbus_server.REG_MODE - modbus_server.REG_CMD_STATUS,
            count=1,
            current_registers=[0, modbus_server.MODE_AUTO, 0],
            set_values=[modbus_server.MODE_AUTO],
        )
    )

    assert mode_events == []


# ---------------------------------------------------------------------------
# Task 3: 40001 命令变化时读取 40004 并传递 hook_type；非法 40004 拒绝 cmd=3
# ---------------------------------------------------------------------------

def test_cmd_hook_with_low_hook_type_passed_through():
    modbus_server, _ = _real_modules()
    calls = []
    server = modbus_server.DobotModbusServer(
        on_command_callback=lambda cmd, mode=0, hook_type=0: calls.append((cmd, mode, hook_type))
    )

    # current_registers: [40001=0, 40002=0(自动), 40003=0, 40004=0(低钩子)]
    asyncio.run(
        server._action_callback(
            function_code=16,
            start_address=0,
            address=0,
            count=1,
            current_registers=[0, modbus_server.MODE_AUTO, 0, modbus_server.HOOK_TYPE_LOW],
            set_values=[modbus_server.CMD_HOOK],
        )
    )

    assert calls == [(modbus_server.CMD_HOOK, modbus_server.MODE_AUTO, modbus_server.HOOK_TYPE_LOW)]


def test_cmd_hook_with_high_hook_type_passed_through():
    modbus_server, _ = _real_modules()
    calls = []
    server = modbus_server.DobotModbusServer(
        on_command_callback=lambda cmd, mode=0, hook_type=0: calls.append((cmd, mode, hook_type))
    )

    asyncio.run(
        server._action_callback(
            function_code=16,
            start_address=0,
            address=0,
            count=1,
            current_registers=[0, modbus_server.MODE_AUTO, 0, modbus_server.HOOK_TYPE_HIGH],
            set_values=[modbus_server.CMD_HOOK],
        )
    )

    assert calls == [(modbus_server.CMD_HOOK, modbus_server.MODE_AUTO, modbus_server.HOOK_TYPE_HIGH)]


def test_illegal_hook_type_rejects_cmd_hook_and_writes_110():
    modbus_server, _ = _real_modules()
    calls = []
    write_calls = []
    server = modbus_server.DobotModbusServer(
        on_command_callback=lambda cmd, mode=0, hook_type=0: calls.append((cmd, mode, hook_type))
    )
    # 桩 _write_status_hook_err 以记录调用而不真正写寄存器
    server._write_status_hook_err = lambda: write_calls.append(modbus_server.STATUS_HOOK_ERR)

    asyncio.run(
        server._action_callback(
            function_code=16,
            start_address=0,
            address=0,
            count=1,
            current_registers=[0, modbus_server.MODE_AUTO, 0, 2],
            set_values=[modbus_server.CMD_HOOK],
        )
    )

    assert calls == []
    assert write_calls == [modbus_server.STATUS_HOOK_ERR]


def test_illegal_hook_type_with_non_hook_cmd_still_passes_with_warning():
    modbus_server, _ = _real_modules()
    calls = []
    server = modbus_server.DobotModbusServer(
        on_command_callback=lambda cmd, mode=0, hook_type=0: calls.append((cmd, mode, hook_type))
    )

    # cmd=0 (CMD_STOP) + 非法 hook_type=2 → 仍传递（带 warning 日志）
    asyncio.run(
        server._action_callback(
            function_code=16,
            start_address=0,
            address=0,
            count=1,
            current_registers=[0, modbus_server.MODE_AUTO, 0, 2],
            set_values=[modbus_server.CMD_STOP],
        )
    )

    assert len(calls) == 1
    assert calls[0][0] == modbus_server.CMD_STOP
    assert calls[0][2] == 2


# ---------------------------------------------------------------------------
# Task 4: RobotController._on_modbus_command 转发 hook_type 给 runner
# ---------------------------------------------------------------------------

class _FakeStatusServer:
    def __init__(self):
        self.calls = []

    def update_status_registers(self, **kwargs):
        self.calls.append(kwargs)


def test_on_modbus_command_forwards_hook_type_to_runner():
    modbus_server, robot_controller = _real_modules()
    controller = robot_controller.DobotController("192.168.1.50")
    fake_server = _FakeStatusServer()
    controller.modbus_server = fake_server
    controller.is_connected = True
    controller.ensure_robot_ready_for_motion = lambda auto_enable=True: True
    runner_calls = []
    controller.set_modbus_program_runner(
        lambda hook_type=0: runner_calls.append(hook_type) or True
    )

    controller._on_modbus_command(
        modbus_server.CMD_HOOK,
        mode=modbus_server.MODE_AUTO,
        hook_type=modbus_server.HOOK_TYPE_HIGH,
    )
    controller._modbus_exec_thread.join(timeout=1.0)

    assert runner_calls == [modbus_server.HOOK_TYPE_HIGH]
    assert fake_server.calls == [
        {"status": modbus_server.STATUS_RUNNING, "mode": modbus_server.MODE_AUTO}
    ]


def test_on_modbus_command_default_hook_type_is_low():
    modbus_server, robot_controller = _real_modules()
    controller = robot_controller.DobotController("192.168.1.50")
    fake_server = _FakeStatusServer()
    controller.modbus_server = fake_server
    controller.is_connected = True
    controller.ensure_robot_ready_for_motion = lambda auto_enable=True: True
    runner_calls = []
    controller.set_modbus_program_runner(
        lambda hook_type=99: runner_calls.append(hook_type) or True
    )

    # 不传 hook_type → 默认 HOOK_TYPE_LOW
    controller._on_modbus_command(modbus_server.CMD_HOOK, mode=modbus_server.MODE_AUTO)
    controller._modbus_exec_thread.join(timeout=1.0)

    assert runner_calls == [modbus_server.HOOK_TYPE_LOW]


def test_on_modbus_command_low_hook_type_forwarded():
    modbus_server, robot_controller = _real_modules()
    controller = robot_controller.DobotController("192.168.1.50")
    fake_server = _FakeStatusServer()
    controller.modbus_server = fake_server
    controller.is_connected = True
    controller.ensure_robot_ready_for_motion = lambda auto_enable=True: True
    runner_calls = []
    controller.set_modbus_program_runner(
        lambda hook_type=99: runner_calls.append(hook_type) or True
    )

    controller._on_modbus_command(
        modbus_server.CMD_HOOK,
        mode=modbus_server.MODE_AUTO,
        hook_type=modbus_server.HOOK_TYPE_LOW,
    )
    controller._modbus_exec_thread.join(timeout=1.0)

    assert runner_calls == [modbus_server.HOOK_TYPE_LOW]


def test_robot_controller_hook_type_constants():
    _, robot_controller = _real_modules()
    assert robot_controller.HOOK_TYPE_LOW == 0
    assert robot_controller.HOOK_TYPE_HIGH == 1
    # MODE_AUTO / MODE_MANUAL 已从 modbus_server 导入
    assert robot_controller.MODE_AUTO == 0
    assert robot_controller.MODE_MANUAL == 1


def test_legacy_runner_without_hook_type_still_works():
    """旧版 runner（无 hook_type 参数）应保持向后兼容。"""
    modbus_server, robot_controller = _real_modules()
    controller = robot_controller.DobotController("192.168.1.50")
    fake_server = _FakeStatusServer()
    controller.modbus_server = fake_server
    controller.is_connected = True
    controller.ensure_robot_ready_for_motion = lambda auto_enable=True: True
    runner_calls = []
    controller.set_modbus_program_runner(lambda: runner_calls.append("run") or True)

    controller._on_modbus_command(
        modbus_server.CMD_HOOK,
        mode=modbus_server.MODE_AUTO,
        hook_type=modbus_server.HOOK_TYPE_HIGH,
    )
    controller._modbus_exec_thread.join(timeout=1.0)

    assert runner_calls == ["run"]
