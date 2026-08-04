import logging

from ...ui.qt_compat import QTableWidgetItem

logger = logging.getLogger(__name__)


# 寄存器名称以 modbus_server.REGISTER_NAME 为唯一真源，避免 UI 标签与从站
# 定义漂移。pymodbus 缺失等极端情况下回退到一致硬编码值。
try:
    from ...communication.modbus_server import REGISTER_NAME
except Exception:  # pragma: no cover - pymodbus 缺失时回退
    REGISTER_NAME = {
        40001: "命令/状态",
        40002: "运行模式",
        40003: "心跳",
        40004: "提钩杆类型",
    }

# Read-only register metadata rendered in the engineering UI.
# Address -> (含义, 类型). Values are populated from Runtime health snapshots
# (`_runtime_status.raw["modbus"]["registers"]`); when the runtime does not
# expose register values the table stays empty without raising.
_MODBUS_REGISTERS = (
    (40001, REGISTER_NAME.get(40001, "命令/状态"), "uint16"),
    (40002, REGISTER_NAME.get(40002, "运行模式"), "uint16"),
    (40003, REGISTER_NAME.get(40003, "心跳"), "uint16 (ms)"),
    (40004, REGISTER_NAME.get(40004, "提钩杆类型"), "uint16"),
)


class ModbusMixin:
    """Read-only Modbus status rendered from Runtime health."""

    def _init_modbus_table(self):
        self.modbus_table.setRowCount(0)
        self._modbus_registers_fetching = False
        self._cached_modbus_registers = None

    def _refresh_modbus_table(self):
        snapshot = getattr(self, "_runtime_status", None)
        online = bool(snapshot and snapshot.online)
        running = online and bool(snapshot.modbus_running)
        # 读取 modbus_port（由 Runtime 管理，不再回退到本地输入框）
        if online and snapshot and snapshot.modbus_port:
            port = snapshot.modbus_port
        else:
            port = 502

        # 简单状态文本：根据在线 / 运行状态切换
        if not online:
            state_text = "Runtime 离线"
        elif not running:
            state_text = "Modbus 未运行"
        else:
            state_text = "Modbus 运行中"
        self.modbus_status_label.setText(state_text)

        # 手动写按钮：仅当 runtime 在线且 modbus 从站运行时启用。
        # 写入经 IPC → runtime → 从站，故两个条件都需满足。
        # reason 显示在 group-box 标题中，让操作员看到写入被阻止的原因。
        if not online:
            write_reason = "Runtime 离线"
        elif not running:
            write_reason = "Modbus 未运行"
        else:
            write_reason = ""
        modbus_page = getattr(self, "modbus_comm_page", None)
        if modbus_page is not None and hasattr(
            modbus_page, "set_write_enabled"
        ):
            modbus_page.set_write_enabled(running, reason=write_reason)

        # 寄存器表：仅在 runtime 在线 + modbus 运行时填充。
        # 缺失 registers 块时保持 0 行。
        self.modbus_table.setRowCount(0)
        if not (online and running):
            return

        # 优先走 IPC 实时读取：online + running 时每次刷新都触发拉取（除非
        # 上一次 IPC 仍在拉取中）。on_success 回调立即填表并缓存；IPC 未返回
        # 或失败时下方用 health file 快照/缓存兜底填表，避免表格长期空白。
        # 注意：_refresh_modbus_table 可能在 _init_modbus_table 之前被调用
        # （_start_status_timer 在 __init__ 早期触发），使用 getattr 守卫。
        if not getattr(self, "_modbus_registers_fetching", False):
            self._modbus_registers_fetching = True

            def on_success(payload):
                self._modbus_registers_fetching = False
                if isinstance(payload, dict):
                    regs = payload.get("registers") or {}
                    if isinstance(regs, dict) and regs:
                        self._cached_modbus_registers = regs
                        # 立即填表（IPC 实时数据覆盖兜底数据）
                        self._fill_modbus_table_rows(regs)

            def on_failure(err):
                self._modbus_registers_fetching = False
                logger.warning("Modbus 寄存器 IPC 拉取失败: %s", err)

            self._send_runtime_ipc(
                "get_modbus_registers",
                on_success=on_success,
                on_failure=on_failure,
            )

        # 离线兜底：IPC 未返回/失败时用 health file 快照或缓存填表。
        # IPC 返回后 on_success 会用更新鲜的数据覆盖。
        modbus_raw = {}
        if online and snapshot is not None:
            modbus_raw = snapshot.raw.get("modbus") or {}
        registers = modbus_raw.get("registers") if modbus_raw else None
        cached = getattr(self, "_cached_modbus_registers", None)
        if (not isinstance(registers, dict) or not registers) and cached:
            registers = cached

        if isinstance(registers, dict) and registers:
            self._fill_modbus_table_rows(registers)

    def _fill_modbus_table_rows(self, registers: dict):
        """根据 registers dict 填表。registers 是 {40001: {...}, ...} 格式。"""
        self.modbus_table.setRowCount(0)
        if not isinstance(registers, dict):
            return
        rows = []
        for address, meaning, reg_type in _MODBUS_REGISTERS:
            value = _extract_register_value(registers, address)
            if value is None:
                continue
            rows.append((str(address), meaning, reg_type, str(value)))
        self.modbus_table.setRowCount(len(rows))
        for row_idx, cells in enumerate(rows):
            for col_idx, text in enumerate(cells):
                self.modbus_table.setItem(row_idx, col_idx, QTableWidgetItem(text))


def _extract_register_value(registers, address):
    """Return the scalar value for ``address`` from a registers dict.

    Supports both scalar values (``40001: 1``) and the nested layout produced
    by ``ModbusServer.get_register_values`` (``40001: {"value": 1, ...}``),
    and accepts either int or str address keys.
    """
    raw = registers.get(address)
    if raw is None:
        raw = registers.get(str(address))
    if raw is None:
        return None
    if isinstance(raw, dict):
        value = raw.get("value")
        return value if value is not None else raw.get("value_display")
    return raw
