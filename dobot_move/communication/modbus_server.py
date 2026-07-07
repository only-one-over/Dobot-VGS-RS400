import asyncio
import logging
import socket
import threading
import time
from contextlib import suppress
from pymodbus.server import ModbusTcpServer
from pymodbus.simulator import SimData, SimDevice, DataType
from pymodbus import ModbusDeviceIdentification

try:
    import winsound
    _HAS_WINSOUND = True
except ImportError:
    _HAS_WINSOUND = False

logger = logging.getLogger(__name__)

# 底盘工控机协议寄存器定义（5 位约定地址，用于显示）
REG_CMD_STATUS = 40001  # 命令/状态
REG_MODE = 40002        # 模式
REG_HEARTBEAT = 40003   # 心跳

# Modbus 线路地址（0-based，用于 SimCore API）
_WIRE_ADDR = 0  # holding register 起始地址

CMD_STOP = 0
CMD_RESET = 1
CMD_HOOK = 3

STATUS_IDLE = 0
STATUS_STANDBY = 2
STATUS_RUNNING = 4
STATUS_HOOK_OK = 5
STATUS_DELAY_WAIT = 5
STATUS_HOOK_ERR = 110
STATUS_ROBOT_ERR = 111
STATUS_CAMERA_ERR = 112

MODE_AUTO = 0
MODE_MANUAL = 1

_CMD_DISPLAY = {0: "空闲/中停", 1: "复位/延时放行", 2: "复位完成", 3: "执行流程", 4: "运行中", 5: "延时等待/流程完成", 110: "流程ERR", 111: "机器人报错", 112: "相机报错"}
_MODE_DISPLAY = {0: "自动模式", 1: "手动模式"}

# 寄存器名称映射
REGISTER_NAME = {
    40001: "命令/状态",
    40002: "运行模式",
    40003: "心跳",
}

# 寄存器值描述映射
REGISTER_VALUE_DESC = {
    (40001, 0): "空闲/中停",
    (40001, 1): "非运行时复位/延时等待时放行",
    (40001, 2): "复位完成",
    (40001, 3): "执行运动编辑流程",
    (40001, 4): "运行中",
    (40001, 5): "延时等待/流程完成",
    (40001, 110): "流程ERR",
    (40001, 111): "机器人报错",
    (40001, 112): "相机报错",
    (40002, 0): "自动模式",
    (40002, 1): "手动模式",
}

# Holding register function codes
HR_FC = {3, 6, 16, 22, 23}


class DobotModbusServer:
    def __init__(self, on_command_callback=None, slave_id=5):
        self._on_command = on_command_callback
        self._slave_id = slave_id
        self._running = False
        self._server_thread = None
        self._client_connected = False
        self._lock = threading.Lock()
        self._server = None
        self._loop = None
        self._port = 0
        self._host = "0.0.0.0"
        self._internal_write_lock = threading.Lock()
        self._internal_write_signatures = []

        self.last_error = None
        self._started_event = threading.Event()

        # 心跳控制
        self._heartbeat_value = 0
        self._heartbeat_last_change = 0.0
        self._heartbeat_task = None
        self._heartbeat_monitor_task = None

        # 周期统计
        self._cycle_count = 0
        self._last_duration_ms = 0
        self._last_cycle_time = 0.0

        self._register_info = {
            REG_CMD_STATUS: ("命令/状态(0=停止/1=非运行时复位或延时中放行/2=复位完成/3=非运行时执行流程/4=运行中/5=延时等待或流程完成/110=流程ERR/111=机器人报错/112=相机报错)", "U16", "双向"),
            REG_MODE: ("模式(0=自动模式/1=手动模式)", "U16", "双向"),
            REG_HEARTBEAT: ("心跳(1/0交替)", "U16", "从站写"),
        }

    def _build_devices(self):
        """构建 SimDevice 列表，包含指定 slave_id 和通配 device_id=0"""
        simdata = SimData(address=0, count=65536, values=0, datatype=DataType.REGISTERS)
        devices = [
            SimDevice(id=self._slave_id, simdata=[simdata], action=self._action_callback),
            SimDevice(id=0, simdata=[simdata], action=self._action_callback),
        ]
        return devices

    @staticmethod
    def _display_address(raw_address):
        if raw_address >= REG_CMD_STATUS:
            return raw_address
        return REG_CMD_STATUS + (raw_address - _WIRE_ADDR)

    @staticmethod
    def _read_current_register(current_registers, start_address, display_address, default=0, prefer_display=False):
        wire_address = _WIRE_ADDR + (display_address - REG_CMD_STATUS)
        candidates = [display_address, wire_address] if prefer_display else [wire_address, display_address]
        for candidate in candidates:
            offset = candidate - start_address
            if 0 <= offset < len(current_registers):
                return current_registers[offset]
        return default

    @staticmethod
    def _write_signature(address, values):
        return int(address), tuple(int(v) for v in values)

    def _mark_internal_status_write(self, address, values):
        signature = self._write_signature(address, values)
        with self._internal_write_lock:
            self._internal_write_signatures.append(signature)
        return signature

    def _discard_internal_status_write(self, signature):
        with self._internal_write_lock:
            try:
                self._internal_write_signatures.remove(signature)
            except ValueError:
                pass

    def _consume_internal_status_write(self, address, values):
        signature = self._write_signature(address, values)
        with self._internal_write_lock:
            try:
                self._internal_write_signatures.remove(signature)
                return True
            except ValueError:
                return False

    async def _action_callback(self, function_code, start_address, address, count, current_registers, set_values):
        """SimDevice action 回调：实时监测主站写操作"""
        if set_values is None:
            return None
        if function_code not in HR_FC:
            return None

        internal_status_write = self._consume_internal_status_write(address, set_values)
        offset = address - start_address
        old_values = list(current_registers[offset:offset + len(set_values)])

        cmd_triggered = False
        cmd_value = 0
        cmd_prefers_display_address = False

        for i, value in enumerate(set_values):
            raw_addr = address + i
            reg_addr = self._display_address(raw_addr)
            prefers_display_address = raw_addr >= REG_CMD_STATUS
            old_val = old_values[i] if i < len(old_values) else None
            reg_name = REGISTER_NAME.get(reg_addr, "")
            value_desc = REGISTER_VALUE_DESC.get((reg_addr, value), "")

            logger.info(
                "[Modbus监测] 地址=%d %s: %s→%s %s",
                reg_addr,
                reg_name,
                old_val,
                value,
                value_desc,
            )

            # 心跳变化追踪
            if reg_addr == REG_HEARTBEAT and old_val != value:
                now = time.time()
                if self._last_cycle_time > 0:
                    self._cycle_count += 1
                    self._last_duration_ms = int((now - self._last_cycle_time) * 1000)
                self._last_cycle_time = now
                self._heartbeat_last_change = now

            # 命令/状态变化
            if reg_addr == REG_CMD_STATUS and old_val != value:
                old_desc = REGISTER_VALUE_DESC.get((REG_CMD_STATUS, old_val), str(old_val))
                new_desc = REGISTER_VALUE_DESC.get((REG_CMD_STATUS, value), str(value))
                logger.info("[Modbus监测] 命令/状态变化: %s → %s", old_desc, new_desc)
                if value in (110, 111, 112):
                    if _HAS_WINSOUND:
                        try:
                            winsound.Beep(1000, 500)
                        except Exception:
                            pass

            # 模式变化
            if reg_addr == REG_MODE and old_val != value:
                old_desc = REGISTER_VALUE_DESC.get((REG_MODE, old_val), str(old_val))
                new_desc = REGISTER_VALUE_DESC.get((REG_MODE, value), str(value))
                logger.info("[Modbus监测] 模式变化: %s → %s", old_desc, new_desc)

            # 命令检测
            if (
                not internal_status_write
                and reg_addr == REG_CMD_STATUS
                and value in (CMD_STOP, CMD_RESET, CMD_HOOK)
            ):
                cmd_triggered = True
                cmd_value = value
                cmd_prefers_display_address = prefers_display_address

        if cmd_triggered and self._on_command:
            # 读取当前模式
            current_mode = self._read_current_register(
                current_registers,
                start_address,
                REG_MODE,
                default=MODE_AUTO,
                prefer_display=cmd_prefers_display_address,
            )
            self._on_command(cmd_value, mode=current_mode)

        return None

    async def _heartbeat_coroutine(self):
        """心跳协程：40003 每秒交替 1/0"""
        await asyncio.sleep(2)  # 等待 2 秒后启动
        while self._running:
            self._heartbeat_value = 1 - self._heartbeat_value
            await self._server.context.async_setValues(self._slave_id, 3, _WIRE_ADDR + 2, [self._heartbeat_value])
            await asyncio.sleep(1.0)

    async def _heartbeat_monitor_coroutine(self):
        """心跳超时监控协程：40003 超过 3 秒未变化则告警"""
        await asyncio.sleep(2)
        while self._running:
            await asyncio.sleep(1.0)
            if self._heartbeat_last_change > 0:
                elapsed = time.time() - self._heartbeat_last_change
                if elapsed > 3.0:
                    logger.warning("心跳超时！机械臂可能离线 (已 %.1f 秒无心跳)", elapsed)

    async def _serve(self):
        """服务器主协程"""
        devices = self._build_devices()
        identity = ModbusDeviceIdentification()
        identity.VendorName = "Dobot"
        identity.ProductCode = "CR5"
        identity.VendorUrl = "https://www.dobot.cc"
        identity.ProductName = "Dobot Modbus Server"
        identity.ModelName = "CR5"
        identity.MajorMinorRevision = "2.0"

        self._server = ModbusTcpServer(
            context=devices,
            identity=identity,
            address=(self._host, self._port),
        )
        await self._server.serve_forever(background=True)

        # 启动心跳和监控协程
        self._heartbeat_task = asyncio.create_task(self._heartbeat_coroutine())
        self._heartbeat_monitor_task = asyncio.create_task(self._heartbeat_monitor_coroutine())

        self._started_event.set()

        with suppress(asyncio.exceptions.CancelledError):
            await self._server.serving

    def start(self, host="0.0.0.0", port=502):
        if self._running:
            return True
        self._running = True
        self._port = port
        self._host = host
        self.last_error = None
        self._started_event.clear()

        def _run():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            try:
                self._loop.run_until_complete(self._serve())
            except Exception as e:
                self.last_error = str(e)
                logger.error("Modbus server error: %s", e)
                self._started_event.set()
            finally:
                self._running = False
                self._loop.close()
                self._loop = None
                self._server = None

        self._server_thread = threading.Thread(target=_run, daemon=True)
        self._server_thread.start()

        if not self._started_event.wait(timeout=3.0):
            self.last_error = "Modbus server start timed out"
            logger.error(self.last_error)
            self._running = False
            return False

        if self.last_error is not None:
            logger.error("Modbus server failed to start: %s", self.last_error)
            return False

        logger.info("Modbus TCP server started on %s:%s slave_id=%d", host, port, self._slave_id)
        return True

    def stop(self):
        self._running = False
        # 取消心跳任务
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        if self._heartbeat_monitor_task:
            self._heartbeat_monitor_task.cancel()
        # 停止服务器
        if self._server and self._loop and self._loop.is_running():
            try:
                asyncio.run_coroutine_threadsafe(self._server.shutdown(), self._loop)
            except Exception:
                pass
        if self._port:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.5)
                s.connect(("127.0.0.1", self._port))
                s.close()
            except Exception:
                pass
        if self._server_thread and self._server_thread.is_alive():
            self._server_thread.join(timeout=2.0)
        self._server_thread = None
        self._server = None
        self._loop = None
        logger.info("Modbus TCP server stopped")

    def is_running(self):
        return self._running

    def get_cycle_stats(self):
        """返回周期计数和最近耗时"""
        return {
            "cycle_count": self._cycle_count,
            "last_duration_ms": self._last_duration_ms,
        }

    def update_status_registers(self, status=0, mode=0):
        """更新状态寄存器（40001 和 40002）"""
        if not self._loop or not self._loop.is_running() or not self._server:
            return
        values = [int(status), int(mode)]
        signature = self._mark_internal_status_write(_WIRE_ADDR, values)
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._server.context.async_setValues(self._slave_id, 3, _WIRE_ADDR, values),
                self._loop,
            )
            future.result(timeout=2.0)
        except Exception as e:
            logger.error("update_status_registers failed: %s", e)
        finally:
            self._discard_internal_status_write(signature)

    def get_register_values(self):
        """获取寄存器当前值"""
        if not self._loop or not self._loop.is_running() or not self._server:
            return {}
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._server.context.async_getValues(self._slave_id, 3, _WIRE_ADDR, 3),
                self._loop,
            )
            vals = future.result(timeout=2.0)
        except Exception as e:
            logger.error("get_register_values failed: %s", e)
            return {}

        if vals is None:
            return {}
        result = {}
        for i, addr in enumerate([REG_CMD_STATUS, REG_MODE, REG_HEARTBEAT]):
            info = self._register_info.get(addr, None)
            val = vals[i]
            entry = {
                "value": val,
                "info": info[0] if info else "",
                "type": info[1] if info else "U16",
                "direction": info[2] if info else "",
            }
            if addr == REG_CMD_STATUS:
                entry["value_display"] = _CMD_DISPLAY.get(val, str(val))
            elif addr == REG_MODE:
                entry["value_display"] = _MODE_DISPLAY.get(val, str(val))
            elif addr == REG_HEARTBEAT:
                entry["value_display"] = str(val)
            result[addr] = entry
        return result
