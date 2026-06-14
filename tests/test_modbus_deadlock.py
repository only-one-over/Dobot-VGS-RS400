"""Tests for Modbus check_commands deadlock prevention."""
import threading
import time
import pytest

# Skip entire module if pymodbus is not available or incompatible
try:
    from pymodbus import ModbusDeviceIdentification
    from dobot_move.modbus_server import DobotModbusServer
    HAS_MODBUS = True
except ImportError:
    HAS_MODBUS = False

pytestmark = pytest.mark.skipif(not HAS_MODBUS, reason="pymodbus not available or incompatible")


class _MockDataBlock:
    """Minimal mock for pymodbus data block with setValues/getValues."""
    def __init__(self, registers):
        self._values = dict(registers)

    def setValues(self, fx, address, values):
        for i, v in enumerate(values):
            self._values[address + i] = v

    def getValues(self, fx, address, count=1):
        return [self._values.get(address + i, 0) for i in range(count)]


class _MockContext:
    """Minimal mock for ModbusServerContext that supports [0] indexing."""
    def __init__(self, block):
        self._block = block

    def __getitem__(self, slave_id):
        return self._block


class TestModbusNoDeadlock:
    def test_check_commands_callback_can_update_status(self):
        """Callback inside check_commands must be able to call update_status_registers without deadlock."""
        server = DobotModbusServer()
        block = _MockDataBlock(server._registers)
        server._context = _MockContext(block)

        callback_completed = threading.Event()

        def on_command(cmd, hook_enable=0):
            """Simulate a callback that updates status registers."""
            try:
                server.update_status_registers(
                    x=100.0, y=200.0, z=300.0,
                    rotation=45.0,
                    status=1, fault_code=0, in_position=0,
                    hook_status=0,
                )
                callback_completed.set()
            except Exception:
                pass

        server._on_command = on_command
        with server._lock:
            server._registers[50001] = 3
            server._registers[50003] = 1
            server._sync_registers_to_context()

        result_thread = threading.Thread(target=server.check_commands)
        result_thread.start()
        result_thread.join(timeout=5.0)

        assert not result_thread.is_alive(), "check_commands deadlocked!"
        assert callback_completed.is_set(), "Callback was not executed"
