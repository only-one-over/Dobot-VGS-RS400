"""Modbus TCP client for reading registers from localhost:502."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from ..communication.modbus_server import (
    REGISTER_NAME,
    REGISTER_VALUE_DESC,
    REG_CMD_STATUS,
    REG_MODE,
    REG_HEARTBEAT,
    REG_HOOK_TYPE,
)

logger = logging.getLogger(__name__)


def read_registers(
    host: str,
    port: int,
    slave_id: int,
    timeout: float = 3.0,
) -> dict[str, Any]:
    """Read 4 holding registers (40001-40004) from the Modbus server.

    Returns a dict with:
        available: bool
        host: str
        port: int
        slave_id: int (only when available)
        timestamp: str (only when available)
        registers: list[dict] (only when available)
        raw_values: list[int] (only when available)
        error: str (only when not available)
    """
    try:
        from pymodbus.client import ModbusTcpClient

        client = ModbusTcpClient(host, port=port, timeout=timeout)
        if not client.connect():
            return {
                "available": False,
                "error": f"无法连接 Modbus 服务器 ({host}:{port})",
                "host": host,
                "port": port,
            }

        try:
            # pymodbus 3.x: slave= 参数（3.3+），兼容旧版 unit=
            try:
                rr = client.read_holding_registers(
                    address=0, count=4, slave=slave_id
                )
            except TypeError:
                rr = client.read_holding_registers(0, 4, unit=slave_id)

            if rr.isError():
                return {
                    "available": False,
                    "error": f"Modbus 读取错误: {rr}",
                    "host": host,
                    "port": port,
                }

            raw_values = [int(v) for v in rr.registers]
            addrs = [REG_CMD_STATUS, REG_MODE, REG_HEARTBEAT, REG_HOOK_TYPE]
            registers = []
            for i, addr in enumerate(addrs):
                val = raw_values[i]
                registers.append({
                    "addr": addr,
                    "name": REGISTER_NAME.get(addr, ""),
                    "value": val,
                    "desc": REGISTER_VALUE_DESC.get((addr, val), str(val)),
                })

            return {
                "available": True,
                "host": host,
                "port": port,
                "slave_id": slave_id,
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "registers": registers,
                "raw_values": raw_values,
            }
        finally:
            client.close()
    except Exception as e:
        logger.warning("Modbus 客户端读取失败: %s", e)
        return {
            "available": False,
            "error": str(e),
            "host": host,
            "port": port,
        }
