"""Modbus TCP client for reading registers from localhost:502.

修复版：兼容 pymodbus 3.0 / 3.3+ / 3.6+ 等不同版本的 API 差异。
将此文件复制到 PC 项目覆盖 dobot_move/remote_api/modbus_client.py 即可。
"""

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


def _try_read_holding_registers(client, count: int, slave_id: int):
    """尝试多种 pymodbus API 风格读取 holding registers。

    pymodbus 版本差异：
      3.6+/3.12+: read_holding_registers(address, *, count=1, device_id=1) —— count 与 device_id 均为关键字参数（pymodbus 3.12.1 验证）
      3.3+ : read_holding_registers(address, count, slave=slave_id)
      3.0-3.2: read_holding_registers(address, count, **kwargs) 不接受 slave/unit
      2.x  : read_holding_registers(address, count, unit=slave_id)
    """
    # 依次尝试不同写法，任一成功即返回
    attempts = [
        lambda: client.read_holding_registers(0, count=count, device_id=slave_id),  # pymodbus 3.6+/3.12+
        lambda: client.read_holding_registers(0, count, slave=slave_id),      # 3.3+
        lambda: client.read_holding_registers(0, count, unit=slave_id),       # 2.x
        lambda: client.read_holding_registers(0, count),                      # 3.0-3.2 无 slave 参数
    ]
    last_error = None
    for attempt in attempts:
        try:
            rr = attempt()
            if rr is not None and not rr.isError():
                return rr
            # 调用成功但返回了错误响应（如非法地址），直接返回让上层处理
            return rr
        except TypeError as e:
            last_error = e
            continue
    # 所有尝试都因 TypeError 失败
    raise TypeError(f"所有 read_holding_registers 调用方式均失败，最后错误: {last_error}")


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
                "error": f"无法连接 PC 本地 Modbus 从站 ({host}:{port})，请确认 runtime 进程或 remote_api 轻量从站已启动",
                "host": host,
                "port": port,
            }

        try:
            rr = _try_read_holding_registers(client, 4, slave_id)

            if rr is None or rr.isError():
                error_msg = f"Modbus 读取错误: {rr}" if rr is not None else "Modbus 读取返回 None"
                return {
                    "available": False,
                    "error": error_msg,
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
