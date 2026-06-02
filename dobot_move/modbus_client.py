import logging
import time
from modbus_utils import regs_to_float
from pymodbus.client import ModbusTcpClient

logger = logging.getLogger(__name__)


class DobotModbusClient:
    def __init__(self):
        self._client = None
        self._connected = False
        self._host = ""
        self._port = 502
        self._cart_status = {
            "connected": False,
            "cart_status": 0,
            "fault_code": 0,
            "x": 0.0,
            "y": 0.0,
            "z": 0.0,
        }

    def connect(self, host, port=502):
        if self._connected:
            return True
        try:
            self._client = ModbusTcpClient(host, port, timeout=3)
            result = self._client.connect()
            if result:
                self._connected = True
                self._host = host
                self._port = port
                logger.info(f"✅ Modbus客户端已连接小车: {host}:{port}")
            return result
        except Exception as e:
            logger.error(f"❌ Modbus客户端连接失败: {e}")
            return False

    def disconnect(self):
        if self._client:
            self._client.close()
        self._client = None
        self._connected = False
        self._cart_status["connected"] = False
        logger.info("✅ Modbus客户端已断开")

    def is_connected(self):
        return self._connected and self._client is not None

    def read_holding_registers(self, address, count=1):
        if not self.is_connected():
            return None
        try:
            result = self._client.read_holding_registers(address, count)
            if hasattr(result, 'isError') and result.isError():
                return None
            return result.registers
        except Exception:
            return None

    def read_float32(self, address):
        regs = self.read_holding_registers(address, 2)
        if regs and len(regs) >= 2:
            return regs_to_float(regs[0], regs[1])
        return None

    def write_single_register(self, address, value):
        if not self.is_connected():
            return False
        try:
            result = self._client.write_register(address, value)
            return not (hasattr(result, 'isError') and result.isError())
        except Exception:
            return False

    def read_cart_status(self):
        if not self.is_connected():
            self._cart_status["connected"] = False
            return self._cart_status

        try:
            regs = self.read_holding_registers(40001, 16)
            if regs and len(regs) >= 6:
                self._cart_status["connected"] = True
                self._cart_status["cart_status"] = regs[0] if len(regs) > 0 else 0
                self._cart_status["fault_code"] = regs[1] if len(regs) > 1 else 0

                x = regs_to_float(
                    regs[10] if len(regs) > 10 else 0,
                    regs[11] if len(regs) > 11 else 0
                )
                y = regs_to_float(
                    regs[12] if len(regs) > 12 else 0,
                    regs[13] if len(regs) > 13 else 0
                )
                z = regs_to_float(
                    regs[14] if len(regs) > 14 else 0,
                    regs[15] if len(regs) > 15 else 0
                )
                self._cart_status["x"] = round(x, 2)
                self._cart_status["y"] = round(y, 2)
                self._cart_status["z"] = round(z, 2)
            else:
                self._cart_status["connected"] = False
        except Exception as e:
            self._cart_status["connected"] = False

        return self._cart_status

    def get_cart_status_dict(self):
        return dict(self._cart_status)

    def get_client_info(self):
        return {
            "host": self._host,
            "port": self._port,
            "connected": self._connected,
        }