import logging
import threading
import time
from modbus_utils import float_to_regs, regs_to_float
from pymodbus.server import StartTcpServer
from pymodbus.datastore import ModbusSequentialDataBlock, ModbusServerContext
from pymodbus import ModbusDeviceIdentification

logger = logging.getLogger(__name__)


class DobotModbusServer:
    def __init__(self, on_command_callback=None):
        self._on_command = on_command_callback
        self._running = False
        self._server_thread = None
        self._context = None
        self._client_connected = False
        self._lock = threading.Lock()

        self._registers = {}
        for addr in range(50001, 50050):
            self._registers[addr] = 0

        self._register_info = {
            50001: ("命令(1=复位,2=回安全位,3=提钩)", "U16", "底盘写"),
            50003: ("提钩使能(1/0)", "U16", "底盘写"),
            50010: ("X目标位置(高16位)", "F32", "底盘写"),
            50012: ("Y目标位置(高16位)", "F32", "底盘写"),
            50014: ("Z目标位置(高16位)", "F32", "底盘写"),
            50016: ("末端旋转角度(高16位)", "F32", "底盘写"),
            50018: ("移动速度(高16位)", "F32", "底盘写"),
            50030: ("状态(1空闲/2运行/3完成/4故障/5急停)", "U16", "机械臂写"),
            50031: ("故障代码", "U16", "机械臂写"),
            50032: ("在位标志(0/1)", "U16", "机械臂写"),
            50040: ("当前X位置(高16位)", "F32", "机械臂写"),
            50042: ("当前Y位置(高16位)", "F32", "机械臂写"),
            50044: ("当前Z位置(高16位)", "F32", "机械臂写"),
        }

    def _build_context(self):
        min_addr = 50001
        max_addr = 50050
        count = max_addr - min_addr + 1
        values = [self._registers.get(min_addr + i, 0) for i in range(count)]
        block = ModbusSequentialDataBlock(min_addr, values)
        self._context = ModbusServerContext(slaves=block, single=True)

    def _sync_registers_to_context(self):
        if not self._context:
            return
        for addr, val in self._registers.items():
            try:
                self._context[0].setValues(3, addr, [val])
            except Exception:
                pass

    def _sync_context_to_registers(self):
        if not self._context:
            return
        for addr in self._registers:
            try:
                vals = self._context[0].getValues(3, addr, 1)
                self._registers[addr] = vals[0]
            except Exception:
                pass

    def start(self, host="0.0.0.0", port=502):
        if self._running:
            return True
        self._build_context()
        self._running = True
        self._port = port

        def _run():
            identity = ModbusDeviceIdentification()
            identity.VendorName = "Dobot"
            identity.ProductCode = "CR5"
            identity.VendorUrl = "https://www.dobot.cc"
            identity.ProductName = "Dobot Modbus Server"
            identity.ModelName = "CR5"
            identity.MajorMinorRevision = "1.0"

            try:
                StartTcpServer(
                    context=self._context,
                    identity=identity,
                    address=(host, port),
                )
            except Exception as e:
                logger.error(f"Modbus server error: {e}")
            finally:
                self._running = False

        self._server_thread = threading.Thread(target=_run, daemon=True)
        self._server_thread.start()
        time.sleep(0.5)
        logger.info(f"Modbus TCP server started on {host}:{port}")
        return True

    def stop(self):
        self._running = False
        self._context = None
        logger.info("Modbus TCP server stopped")

    def is_running(self):
        return self._running

    def update_status_registers(self, status=1, fault_code=0, in_position=0, x=0.0, y=0.0, z=0.0):
        with self._lock:
            self._registers[50030] = int(status)
            self._registers[50031] = int(fault_code)
            self._registers[50032] = int(in_position)

            x_h, x_l = float_to_regs(x)
            self._registers[50040] = x_h
            self._registers[50041] = x_l

            y_h, y_l = float_to_regs(y)
            self._registers[50042] = y_h
            self._registers[50043] = y_l

            z_h, z_l = float_to_regs(z)
            self._registers[50044] = z_h
            self._registers[50045] = z_l

            self._sync_registers_to_context()

    def check_commands(self):
        if not self._context:
            return
        self._sync_context_to_registers()

        cmd = self._registers.get(50001, 0)
        if cmd != 0 and self._on_command:
            self._on_command(cmd)
            self._registers[50001] = 0
            self._sync_registers_to_context()

        return cmd

    def get_target_position(self):
        with self._lock:
            try:
                x = regs_to_float(self._registers.get(50010, 0), self._registers.get(50011, 0))
                y = regs_to_float(self._registers.get(50012, 0), self._registers.get(50013, 0))
                z = regs_to_float(self._registers.get(50014, 0), self._registers.get(50015, 0))
                rx = regs_to_float(self._registers.get(50016, 0), self._registers.get(50017, 0))
                speed = regs_to_float(self._registers.get(50018, 0), self._registers.get(50019, 0))
                hook_enable = self._registers.get(50003, 0)
            except Exception:
                return None
        return {"x": x, "y": y, "z": z, "rx": rx, "speed": speed, "hook_enable": hook_enable}

    def get_register_values(self):
        with self._lock:
            result = {}
            for addr in sorted(self._registers.keys()):
                info = self._register_info.get(addr, None)
                result[addr] = {
                    "value": self._registers[addr],
                    "info": info[0] if info else "",
                    "type": info[1] if info else "U16",
                    "direction": info[2] if info else "",
                }

            for base_addr, name in [(50010, "X目标"), (50012, "Y目标"), (50014, "Z目标"),
                                     (50016, "旋转角度"), (50018, "速度"),
                                     (50040, "当前X"), (50042, "当前Y"), (50044, "当前Z")]:
                try:
                    val = regs_to_float(self._registers.get(base_addr, 0), self._registers.get(base_addr + 1, 0))
                    result[base_addr]["float_value"] = round(val, 2)
                except Exception:
                    pass

            return result
