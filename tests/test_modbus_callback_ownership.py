# -*- coding: utf-8 -*-
"""解耦 Modbus 回调与强制寄存器写所有权 — Task 1/2/3/6/7 单元测试。

覆盖：
- Task 1: ``write_status_register`` 仅写 40001；``update_status_registers`` 废弃后不再写 40002
- Task 2: ``_write_status_hook_err`` 为 ``async def``，非法 40004 + cmd==3 不阻塞事件循环
- Task 3: ``get_register_values`` 返回 dict 包含 40004 键
- Task 6: ``write_status_register`` 不触碰 40004
- Task 7: 旧 Delay 语义已删除（方法/常量/字段不存在，delay 模块仅支持纯超时）
"""
import asyncio
import contextlib
import importlib
import inspect
import queue
import shutil
import sys
import threading
import time
import types
import uuid
from pathlib import Path
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# pymodbus 桩（与 test_hook_type_register.py 相同的模式）
# ---------------------------------------------------------------------------

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
    return modbus_server


def _real_robot_controller():
    """导入 robot_controller 模块（与 test_00_modbus_hook_relative 相同的桩模式）。"""
    _real_modules()  # 确保 pymodbus 桩已安装
    sys.modules.pop("dobot_move.robot.robot_controller", None)
    robot_controller = importlib.import_module("dobot_move.robot.robot_controller")
    robot_controller = importlib.reload(robot_controller)
    return robot_controller


# ---------------------------------------------------------------------------
# Mock context / server / event-loop runner
# ---------------------------------------------------------------------------

class _MockContext:
    """记录 ``async_setValues`` 调用，可预设 ``async_getValues`` 返回值。"""

    def __init__(self):
        self.set_values_calls = []
        self.get_values_result = [0, 0, 0, 0]

    async def async_setValues(self, slave_id, fx, address, values):
        self.set_values_calls.append((slave_id, fx, address, list(values)))

    async def async_getValues(self, slave_id, fx, address, count):
        return list(self.get_values_result[:count])


class _MockServer:
    def __init__(self, context):
        self.context = context


class _LoopRunner:
    """在后台线程运行 asyncio 事件循环，供 ``run_coroutine_threadsafe`` 测试使用。"""

    def __init__(self):
        self._loop = None
        self._thread = None
        self._ready = threading.Event()

    def start(self):
        self._loop = asyncio.new_event_loop()

        def _run():
            asyncio.set_event_loop(self._loop)
            self._ready.set()
            self._loop.run_forever()

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=2.0)
        return self._loop

    def stop(self):
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if self._loop is not None:
            self._loop.close()
        self._loop = None
        self._thread = None


# ---------------------------------------------------------------------------
# Task 1: write_status_register 仅写 40001
# ---------------------------------------------------------------------------

def test_write_status_register_only_writes_40001():
    """write_status_register(4) 仅写 40001，不写 40002。"""
    modbus_server = _real_modules()
    server = modbus_server.DobotModbusServer()
    context = _MockContext()
    server._server = _MockServer(context)

    runner = _LoopRunner()
    loop = runner.start()
    try:
        server._loop = loop
        server.write_status_register(4)

        assert len(context.set_values_calls) == 1
        slave_id, fx, address, values = context.set_values_calls[0]
        assert address == modbus_server._WIRE_ADDR
        assert values == [4]
        # 确认只写了 1 个寄存器（40001），不是 2 个（40001+40002）
        assert len(values) == 1
    finally:
        runner.stop()


def test_update_status_registers_deprecated_no_longer_writes_40002():
    """废弃的 update_status_registers 不再写 40002，仅写 40001。"""
    modbus_server = _real_modules()
    server = modbus_server.DobotModbusServer()
    context = _MockContext()
    server._server = _MockServer(context)

    runner = _LoopRunner()
    loop = runner.start()
    try:
        server._loop = loop
        # 传入 mode=1（MODE_MANUAL），但应被忽略
        server.update_status_registers(status=4, mode=1)

        assert len(context.set_values_calls) == 1
        slave_id, fx, address, values = context.set_values_calls[0]
        assert address == modbus_server._WIRE_ADDR
        # 只写 1 个值（40001=4），不写 40002
        assert values == [4]
        assert len(values) == 1
    finally:
        runner.stop()


def test_write_status_register_signature_has_no_mode_param():
    """write_status_register 签名只接受 status，不接受 mode。"""
    modbus_server = _real_modules()
    server = modbus_server.DobotModbusServer()
    sig = inspect.signature(server.write_status_register)
    params = list(sig.parameters.keys())
    assert params == ["status"]


# ---------------------------------------------------------------------------
# Task 2: _write_status_hook_err 为 async def，不阻塞事件循环
# ---------------------------------------------------------------------------

def test_write_status_hook_err_is_coroutine_function():
    """_write_status_hook_err 必须是 async def（协程函数）。"""
    modbus_server = _real_modules()
    server = modbus_server.DobotModbusServer()
    assert asyncio.iscoroutinefunction(server._write_status_hook_err)


def test_illegal_hook_type_cmd_hook_writes_110_without_blocking():
    """非法 40004 + cmd==3 时 _action_callback 通过 await 写 40001=110，不阻塞。"""
    modbus_server = _real_modules()
    server = modbus_server.DobotModbusServer(
        on_command_callback=lambda cmd, mode=0, hook_type=0: None
    )
    context = _MockContext()
    server._server = _MockServer(context)

    async def _run():
        # 在协程内绑定当前事件循环
        server._loop = asyncio.get_running_loop()
        await server._action_callback(
            function_code=16,
            start_address=0,
            address=0,
            count=1,
            current_registers=[0, modbus_server.MODE_AUTO, 0, 2],
            set_values=[modbus_server.CMD_HOOK],
        )

    # asyncio.run 在当前线程运行事件循环；如果 _write_status_hook_err 仍用
    # run_coroutine_threadsafe().result() 会死锁导致超时。
    # 改为 async/await 后应立即完成。
    asyncio.run(_run())

    # 40001 被写入 110 (STATUS_HOOK_ERR)
    assert len(context.set_values_calls) == 1
    _, _, address, values = context.set_values_calls[0]
    assert address == modbus_server._WIRE_ADDR
    assert values == [modbus_server.STATUS_HOOK_ERR]


def test_legal_hook_type_cmd_hook_does_not_call_write_status_hook_err():
    """合法 40004 + cmd==3 不触发 _write_status_hook_err，正常回调。"""
    modbus_server = _real_modules()
    calls = []
    server = modbus_server.DobotModbusServer(
        on_command_callback=lambda cmd, mode=0, hook_type=0: calls.append((cmd, mode, hook_type))
    )
    context = _MockContext()
    server._server = _MockServer(context)

    async def _run():
        server._loop = asyncio.get_running_loop()
        await server._action_callback(
            function_code=16,
            start_address=0,
            address=0,
            count=1,
            current_registers=[0, modbus_server.MODE_AUTO, 0, modbus_server.HOOK_TYPE_LOW],
            set_values=[modbus_server.CMD_HOOK],
        )

    asyncio.run(_run())

    # 回调被正常调用
    assert calls == [(modbus_server.CMD_HOOK, modbus_server.MODE_AUTO, modbus_server.HOOK_TYPE_LOW)]
    # 没有写 40001=110
    assert len(context.set_values_calls) == 0


# ---------------------------------------------------------------------------
# Task 3: get_register_values 包含 40004
# ---------------------------------------------------------------------------

def test_get_register_values_returns_40004_key():
    """get_register_values() 返回的 dict 包含 40004 键。"""
    modbus_server = _real_modules()
    server = modbus_server.DobotModbusServer()
    context = _MockContext()
    context.get_values_result = [4, 0, 1, 0]  # 40001=4, 40002=0, 40003=1, 40004=0
    server._server = _MockServer(context)

    runner = _LoopRunner()
    loop = runner.start()
    try:
        server._loop = loop
        result = server.get_register_values()

        assert modbus_server.REG_HOOK_TYPE in result
        entry = result[modbus_server.REG_HOOK_TYPE]
        assert entry["value"] == 0
        assert "提钩杆类型" in entry["info"]
    finally:
        runner.stop()


def test_get_register_values_reads_count_four():
    """get_register_values 读取 4 个寄存器（40001-40004）。"""
    modbus_server = _real_modules()
    server = modbus_server.DobotModbusServer()
    context = _MockContext()
    context.get_values_result = [0, 0, 0, 0]
    server._server = _MockServer(context)

    runner = _LoopRunner()
    loop = runner.start()
    try:
        server._loop = loop
        result = server.get_register_values()

        # 应返回 4 个寄存器
        assert len(result) == 4
        assert modbus_server.REG_CMD_STATUS in result
        assert modbus_server.REG_MODE in result
        assert modbus_server.REG_HEARTBEAT in result
        assert modbus_server.REG_HOOK_TYPE in result
    finally:
        runner.stop()


def test_get_register_values_40004_value_display():
    """40004 的 value_display 为 '低钩子' 或 '高钩子'。"""
    modbus_server = _real_modules()
    server = modbus_server.DobotModbusServer()
    context = _MockContext()
    context.get_values_result = [0, 0, 0, modbus_server.HOOK_TYPE_HIGH]
    server._server = _MockServer(context)

    runner = _LoopRunner()
    loop = runner.start()
    try:
        server._loop = loop
        result = server.get_register_values()

        entry = result[modbus_server.REG_HOOK_TYPE]
        assert entry["value_display"] == "高钩子"
    finally:
        runner.stop()


def test_register_info_contains_40004():
    """_register_info 字典包含 40004 条目。"""
    modbus_server = _real_modules()
    server = modbus_server.DobotModbusServer()
    assert modbus_server.REG_HOOK_TYPE in server._register_info
    info = server._register_info[modbus_server.REG_HOOK_TYPE]
    assert "提钩杆类型" in info[0]


# ---------------------------------------------------------------------------
# Task 6: write_status_register 不触碰 40004
# ---------------------------------------------------------------------------

def test_write_status_register_does_not_touch_40004():
    """write_status_register 不写 40004 (_WIRE_ADDR+3)。"""
    modbus_server = _real_modules()
    server = modbus_server.DobotModbusServer()
    context = _MockContext()
    server._server = _MockServer(context)

    runner = _LoopRunner()
    loop = runner.start()
    try:
        server._loop = loop
        server.write_status_register(4)

        for slave_id, fx, address, values in context.set_values_calls:
            # 40004 = _WIRE_ADDR + 3
            assert address != modbus_server._WIRE_ADDR + 3, (
                "write_status_register 不应写 40004 (PLC 独占)"
            )
    finally:
        runner.stop()


def test_no_async_setvalues_writes_to_40004_in_modbus_server():
    """全项目确认 modbus_server.py 中无 async_setValues 调用写入 _WIRE_ADDR+3 (40004)。"""
    modbus_server = _real_modules()
    source_path = inspect.getsourcefile(modbus_server)
    with open(source_path, encoding="utf-8") as f:
        source = f.read()

    # _WIRE_ADDR + 3 对应 40004
    # 确认源码中没有 _WIRE_ADDR + 3 出现在 async_setValues 调用中
    assert "_WIRE_ADDR + 3" not in source, (
        "modbus_server.py 不应包含 _WIRE_ADDR + 3 的写入（40004 为 PLC 独占）"
    )


# ---------------------------------------------------------------------------
# Task 4: Modbus 回调只解析和入队 (delegate enqueue + worker thread)
# ---------------------------------------------------------------------------
#
# Minimal fakes for instantiating DobotRuntimeAgent without real hardware.
# Lazy imports ensure the pymodbus stub (installed by _real_modules) is
# in place before importing runtime_agent (which imports modbus_server).

class _T4FakeDashboard:
    def Stop(self):
        return "0,0,0;"


class _T4FakeController:
    """Controller stub supporting delegate + mode-changed callback registration."""

    def __init__(self):
        self.is_connected = True
        self.dashboard = _T4FakeDashboard()
        self.robot_ip = "192.168.1.50"
        self.last_error = ""
        self.modbus_running = False
        self._active_flow_thread = None
        self.runtime_maintenance = False
        self.runtime_recovery_required = None
        self.written_statuses = []
        self.pause_calls = 0
        self.continue_calls = 0
        self.clear_error_calls = 0
        self.enable_calls = 0
        self.move_to_initial_calls = 0
        self.move_to_initial_return = True
        self.enable_return = True
        self.close_transport_calls = 0

    def get_feedback_health(self, max_age=0.3):
        return {"health": "ok"}

    def get_modbus_stats(self):
        return {"is_running": self.modbus_running}

    def set_modbus_program_runner(self, runner, readiness_checker=None, command_delegate=None):
        pass

    def set_modbus_mode_changed_callback(self, callback):
        pass

    def close_robot_transport(self):
        self.close_transport_calls += 1

    def abort_active_flow_for_disconnect(self, reason, source="flow"):
        pass

    def _write_modbus_status(self, status, mode=0):
        self.written_statuses.append((int(status), int(mode)))

    def record_alarm(self, *args, **kwargs):
        pass

    def mark_modbus_program_finished(self, success, mode=0, failure_status=None):
        pass

    def set_runtime_recovery_required(self, required=True, on_cleared=None):
        pass

    def set_runtime_maintenance(self, active=True):
        self.runtime_maintenance = bool(active)

    def pause(self):
        self.pause_calls += 1

    def continue_motion(self):
        self.continue_calls += 1

    def clear_error(self):
        self.clear_error_calls += 1

    def enable_robot(self):
        self.enable_calls += 1
        return self.enable_return

    def move_to_initial_position(self, verify_start_pose=True, verify_end_pose=True, **kwargs):
        self.move_to_initial_calls += 1
        return self.move_to_initial_return

    def stop_modbus(self):
        pass

    def release_control_lease(self):
        pass


class _T4FakeIpcServer:
    def __init__(self):
        self.last_error = ""

    def start(self):
        return True

    def stop(self):
        pass

    def snapshot(self):
        return {
            "running": True, "host": "127.0.0.1", "port": 8765,
            "clients": 0, "queue_depth": 0, "last_error": self.last_error,
        }


def _t4_imports():
    """Ensure pymodbus stub is installed and return runtime_agent module."""
    _real_modules()
    from dobot_move.runtime import runtime_agent as _ra
    return _ra


def _t4_make_request(flow_id="test-flow", mode="production"):
    _ra = _t4_imports()
    return _ra.RuntimeExecutionRequest(
        mode=mode, flow_id=flow_id, flow_name="Test Flow",
        modules=[], config={"robot_ip": "127.0.0.1"}, revision="test-rev",
    )


def _t4_runtime_agent_fixture():
    """Context manager yielding (agent, controller) with PR 3 wiring intact.

    Modeled after test_production_state_machine._runtime_agent_fixture but
    self-contained so this file can run independently.
    """
    return _t4_runtime_agent_fixture_inner()


@contextlib.contextmanager
def _t4_runtime_agent_fixture_inner():
    _ra = _t4_imports()
    DobotRuntimeAgent = _ra.DobotRuntimeAgent
    ProductionFlowRouter = _ra.ProductionFlowRouter

    temp_dir = Path.cwd() / f"_t4_modbus_cb_{uuid.uuid4().hex}"
    temp_dir.mkdir()
    try:
        controller = _T4FakeController()
        agent = DobotRuntimeAgent(
            controller=controller,
            health_path=temp_dir / "health.json",
            state_path=temp_dir / "state.json",
            startup_delay=0,
            poll_interval=0.1,
            ipc_server=_T4FakeIpcServer(),
        )
        agent.state_store.begin_boot()
        agent._state_initialized = True
        agent.flow_router = ProductionFlowRouter(
            {
                "low_hook": "flow-low",
                "high_hook": "flow-high",
                "error_recovery": "flow-recovery",
            }
        )
        agent.program_runner.build_production_request = MagicMock(
            side_effect=lambda flow_id, task_id="": _t4_make_request(flow_id)
        )
        agent.program_runner.start_request = MagicMock(return_value=True)
        agent.program_runner.pause = MagicMock(return_value=True)
        agent.program_runner.resume = MagicMock(return_value=True)
        agent.program_runner.stop = MagicMock(return_value=True)
        agent.program_runner.current_module_index = 2
        agent.program_runner.task_mode = None
        yield agent, controller
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_delegate_enqueues_command_and_returns_true():
    """Task 4: _on_modbus_command_delegate(cmd=3, mode=0, hook_type=0) returns
    True immediately and the queue contains (3, 0, 0)."""
    with _t4_runtime_agent_fixture() as (agent, _controller):
        result = agent._on_modbus_command_delegate(cmd=3, mode=0, hook_type=0)
        assert result is True
        # Queue should contain exactly one item: (3, 0, 0)
        item = agent._modbus_command_queue.get_nowait()
        assert item == (3, 0, 0)
        # Queue should now be empty
        assert agent._modbus_command_queue.empty()


def test_delegate_returns_false_for_manual_mode():
    """Task 4: mode != MODE_AUTO → delegate returns False (controller handles)."""
    with _t4_runtime_agent_fixture() as (agent, _controller):
        # mode=1 (MANUAL) → delegate returns False, nothing enqueued
        result = agent._on_modbus_command_delegate(cmd=3, mode=1, hook_type=0)
        assert result is False
        assert agent._modbus_command_queue.empty()


def test_delegate_does_not_call_handle_methods_synchronously():
    """Task 4: delegate must NOT synchronously call _handle_hook_command etc."""
    with _t4_runtime_agent_fixture() as (agent, _controller):
        agent._handle_hook_command = MagicMock()
        agent._handle_pause_command = MagicMock(return_value=True)
        agent._handle_reset_command = MagicMock(return_value=True)
        agent._on_modbus_command_delegate(cmd=3, mode=0, hook_type=0)
        agent._on_modbus_command_delegate(cmd=0, mode=0, hook_type=0)
        agent._on_modbus_command_delegate(cmd=1, mode=0, hook_type=0)
        # None of the handlers should have been called (only enqueued)
        agent._handle_hook_command.assert_not_called()
        agent._handle_pause_command.assert_not_called()
        agent._handle_reset_command.assert_not_called()
        # Queue should have 3 items
        assert agent._modbus_command_queue.qsize() == 3


def test_worker_thread_processes_queue_and_calls_handle_hook_command():
    """Task 4: worker thread drains the queue and calls _handle_hook_command."""
    with _t4_runtime_agent_fixture() as (agent, _controller):
        agent._set_production_state(agent.production_state.__class__.STANDBY)
        agent._handle_hook_command = MagicMock()
        # Start the worker thread
        worker = threading.Thread(
            target=agent._command_worker_loop, daemon=True,
            name="t4-worker-test",
        )
        worker.start()
        try:
            # Enqueue a cmd=3 (HOOK) command
            agent._modbus_command_queue.put((3, 0, 0))
            # Wait for the worker to process it (poll up to 2s)
            deadline = time.time() + 2.0
            while time.time() < deadline:
                if agent._handle_hook_command.called:
                    break
                time.sleep(0.02)
            assert agent._handle_hook_command.called, (
                "worker thread should have called _handle_hook_command"
            )
            agent._handle_hook_command.assert_called_once_with(0)
        finally:
            # Sentinel to stop the worker
            agent._modbus_command_queue.put(None)
            worker.join(timeout=3.0)
        assert not worker.is_alive(), "worker thread should have exited"


def test_sentinel_none_causes_worker_thread_exit():
    """Task 4: enqueueing None (sentinel) causes the worker thread to exit."""
    with _t4_runtime_agent_fixture() as (agent, _controller):
        worker = threading.Thread(
            target=agent._command_worker_loop, daemon=True,
            name="t4-sentinel-test",
        )
        worker.start()
        assert worker.is_alive()
        # Send sentinel
        agent._modbus_command_queue.put(None)
        worker.join(timeout=3.0)
        assert not worker.is_alive(), (
            "worker thread should exit after receiving None sentinel"
        )


def test_dispatch_command_contains_resetting_guard():
    """Task 4: _dispatch_command retains the RESETTING guard from the delegate."""
    with _t4_runtime_agent_fixture() as (agent, _controller):
        from dobot_move.runtime.production_state import ProductionState
        agent._set_production_state(ProductionState.RESETTING)
        agent._handle_hook_command = MagicMock()
        agent._handle_pause_command = MagicMock(return_value=True)
        # CMD_HOOK in RESETTING → ignored (no handler called)
        agent._dispatch_command(cmd=3, mode=0, hook_type=0)
        agent._handle_hook_command.assert_not_called()
        # CMD_STOP in RESETTING → no-op (no handler called)
        agent._dispatch_command(cmd=0, mode=0, hook_type=0)
        agent._handle_pause_command.assert_not_called()
        # State unchanged
        assert agent.production_state == ProductionState.RESETTING


# ---------------------------------------------------------------------------
# Task 5: 禁止 Modbus Event Loop 执行机器人动作 (验证层)
# ---------------------------------------------------------------------------

def test_action_callback_source_has_no_direct_motion_calls():
    """Task 5: _action_callback source must not directly call controller.*
    motion methods, program_runner.start_request, or reset_strategy.execute."""
    modbus_server = _real_modules()
    source = inspect.getsource(modbus_server.DobotModbusServer._action_callback)
    # These motion/action entry points must NOT appear in _action_callback
    forbidden = [
        "program_runner.start_request",
        "reset_strategy.execute",
        "controller.pause",
        "controller.continue_motion",
        "controller.move_to_initial",
        "controller.clear_error",
        "controller.enable_robot",
        "controller.dashboard",
        ".start_new_task",
        "._handle_hook_command",
        "._handle_pause_command",
        "._handle_reset_command",
    ]
    for token in forbidden:
        assert token not in source, (
            f"_action_callback must not directly call {token} "
            f"(Task 5: Modbus Event Loop 禁止执行机器人动作)"
        )


def test_action_callback_40001_3_calls_on_command_without_synchronous_motion():
    """Task 5: _action_callback processing 40001=3 calls _on_command (which
    enqueues) and returns without synchronous motion."""
    modbus_server = _real_modules()
    calls = []
    # _on_command is the delegate chain — it should only enqueue and return
    server = modbus_server.DobotModbusServer(
        on_command_callback=lambda cmd, mode=0, hook_type=0: calls.append(
            (cmd, mode, hook_type)
        )
    )
    context = _MockContext()
    server._server = _MockServer(context)

    motion_calls = []

    async def _run():
        server._loop = asyncio.get_running_loop()
        await server._action_callback(
            function_code=16,
            start_address=0,
            address=0,
            count=1,
            current_registers=[0, modbus_server.MODE_AUTO, 0, modbus_server.HOOK_TYPE_LOW],
            set_values=[modbus_server.CMD_HOOK],
        )

    # If _action_callback tried any synchronous motion it would raise
    # (no controller wired up). The call should complete without error.
    asyncio.run(_run())

    # _on_command was called with (CMD_HOOK, MODE_AUTO, HOOK_TYPE_LOW)
    assert len(calls) == 1
    assert calls[0] == (
        modbus_server.CMD_HOOK,
        modbus_server.MODE_AUTO,
        modbus_server.HOOK_TYPE_LOW,
    )
    # No motion side-effects (the callback only appended to `calls`)
    assert motion_calls == []


def test_action_callback_only_enqueues_via_on_command_callback():
    """Task 5: _action_callback's only command-dispatch side-effect is calling
    _on_command (the delegate which enqueues). No other dispatch path."""
    modbus_server = _real_modules()
    source = inspect.getsource(modbus_server.DobotModbusServer._action_callback)
    # The only command-dispatch call should be self._on_command(...)
    assert "self._on_command(" in source
    # _write_status_hook_err is allowed (async, only for illegal 40004)
    assert "await self._write_status_hook_err" in source



# ---------------------------------------------------------------------------
# Task 7: 删除 1/5 旧 Delay 语义
# ---------------------------------------------------------------------------

def test_status_delay_wait_constant_removed_from_robot_controller():
    """robot_controller.py 不再定义 STATUS_DELAY_WAIT 常量。"""
    robot_controller = _real_robot_controller()
    assert not hasattr(robot_controller, "STATUS_DELAY_WAIT"), (
        "STATUS_DELAY_WAIT 常量应已移除（状态 5 仅表示 HOLDING_HOOK）"
    )


def test_status_delay_wait_constant_removed_from_modbus_server():
    """modbus_server.py 不再定义 STATUS_DELAY_WAIT 常量。"""
    modbus_server = _real_modules()
    assert not hasattr(modbus_server, "STATUS_DELAY_WAIT"), (
        "STATUS_DELAY_WAIT 常量应已移除（状态 5 仅表示 STATUS_HOOK_OK）"
    )


def test_status_hook_ok_constant_still_exists():
    """STATUS_HOOK_OK = 5 仍然保留（HOLDING_HOOK 状态使用）。"""
    modbus_server = _real_modules()
    assert hasattr(modbus_server, "STATUS_HOOK_OK")
    assert modbus_server.STATUS_HOOK_OK == 5


def test_begin_modbus_delay_wait_removed():
    """DobotController 不再拥有 begin_modbus_delay_wait 方法。"""
    robot_controller = _real_robot_controller()
    controller = robot_controller.DobotController("192.168.1.50")
    assert not hasattr(controller, "begin_modbus_delay_wait"), (
        "begin_modbus_delay_wait 方法应已删除"
    )


def test_end_modbus_delay_wait_removed():
    """DobotController 不再拥有 end_modbus_delay_wait 方法。"""
    robot_controller = _real_robot_controller()
    controller = robot_controller.DobotController("192.168.1.50")
    assert not hasattr(controller, "end_modbus_delay_wait"), (
        "end_modbus_delay_wait 方法应已删除"
    )


def test_is_modbus_delay_released_removed():
    """DobotController 不再拥有 is_modbus_delay_released 方法。"""
    robot_controller = _real_robot_controller()
    controller = robot_controller.DobotController("192.168.1.50")
    assert not hasattr(controller, "is_modbus_delay_released"), (
        "is_modbus_delay_released 方法应已删除"
    )


def test_release_modbus_delay_if_waiting_removed():
    """DobotController 不再拥有 _release_modbus_delay_if_waiting 方法。"""
    robot_controller = _real_robot_controller()
    controller = robot_controller.DobotController("192.168.1.50")
    assert not hasattr(controller, "_release_modbus_delay_if_waiting"), (
        "_release_modbus_delay_if_waiting 方法应已删除"
    )


def test_modbus_delay_instance_fields_removed():
    """DobotController 不再拥有 _modbus_delay_waiting / _modbus_delay_release_event 字段。"""
    robot_controller = _real_robot_controller()
    controller = robot_controller.DobotController("192.168.1.50")
    assert not hasattr(controller, "_modbus_delay_waiting"), (
        "_modbus_delay_waiting 字段应已删除"
    )
    assert not hasattr(controller, "_modbus_delay_release_event"), (
        "_modbus_delay_release_event 字段应已删除"
    )


def test_wait_for_flow_delay_or_signal_has_no_signal_checker_param():
    """wait_for_flow_delay_or_signal 不再接受 signal_checker 参数。"""
    if "pyrealsense2" not in sys.modules:
        sys.modules["pyrealsense2"] = types.ModuleType("pyrealsense2")
    from dobot_move.flow.flow_executor import wait_for_flow_delay_or_signal

    sig = inspect.signature(wait_for_flow_delay_or_signal)
    params = list(sig.parameters.keys())
    assert "signal_checker" not in params, (
        "signal_checker 参数应已移除（delay 模块仅支持纯超时）"
    )


def test_wait_for_flow_delay_or_signal_returns_timeout_or_stopped_only():
    """wait_for_flow_delay_or_signal 仅返回 'timeout' 或 'stopped'。"""
    if "pyrealsense2" not in sys.modules:
        sys.modules["pyrealsense2"] = types.ModuleType("pyrealsense2")
    from dobot_move.flow.flow_executor import wait_for_flow_delay_or_signal

    # 正常超时
    result = wait_for_flow_delay_or_signal(0.01, threading.Event(), poll_interval=0.005)
    assert result == "timeout"

    # 立即停止
    stop_event = threading.Event()
    stop_event.set()
    result = wait_for_flow_delay_or_signal(10.0, stop_event, poll_interval=0.005)
    assert result == "stopped"


def test_delay_module_validation_rejects_modbus_or_timeout():
    """delay 模块校验拒绝 modbus_or_timeout 模式（仅支持 time）。"""
    if "pyrealsense2" not in sys.modules:
        sys.modules["pyrealsense2"] = types.ModuleType("pyrealsense2")
    from dobot_move.flow.flow_executor import validate_grasp_flow_modules

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
    assert len(errors) == 1
    assert "延时等待方式无效" in errors[0]


def test_delay_module_validation_accepts_time_mode():
    """delay 模块校验接受 time 模式。"""
    if "pyrealsense2" not in sys.modules:
        sys.modules["pyrealsense2"] = types.ModuleType("pyrealsense2")
    from dobot_move.flow.flow_executor import validate_grasp_flow_modules

    modules = [
        {
            "type": "delay",
            "name": "延时",
            "params": {
                "wait_mode": "time",
                "duration_s": 1.5,
            },
        }
    ]
    assert validate_grasp_flow_modules(modules) == []


def test_on_modbus_command_flow_active_no_delay_logic():
    """流程运行中收到 40001=1 不再触发 delay 放行，仅写 STATUS_RUNNING。"""
    robot_controller = _real_robot_controller()
    modbus_server = _real_modules()

    class _FakeServer:
        def __init__(self):
            self.calls = []

        def write_status_register(self, status):
            self.calls.append({"status": status, "mode": 0})

    controller = robot_controller.DobotController("192.168.1.50")
    controller.modbus_server = _FakeServer()
    controller._active_flow_thread = object()  # 模拟流程运行中

    # 40001=1 (CMD_RESET) 在流程运行中应被忽略，写 STATUS_RUNNING
    controller._on_modbus_command(modbus_server.CMD_RESET, mode=modbus_server.MODE_AUTO)

    assert len(controller.modbus_server.calls) == 1
    assert controller.modbus_server.calls[0]["status"] == modbus_server.STATUS_RUNNING

