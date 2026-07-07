class ModbusMixin:
    """Read-only Modbus status rendered from Runtime health."""

    def start_modbus_server(self):
        return self._show_runtime_ipc_required("启动 Modbus 服务")

    def stop_modbus_server(self):
        return self._show_runtime_ipc_required("停止 Modbus 服务")

    def _init_modbus_table(self):
        self.modbus_table.setRowCount(0)

    def _refresh_modbus_table(self):
        snapshot = getattr(self, "_runtime_status", None)
        running = bool(snapshot and snapshot.modbus_running)
        port = (
            snapshot.modbus_port
            if snapshot is not None and snapshot.online
            else self.modbus_port_input.text().strip() or "502"
        )
        state_text = "运行中" if running else "停止"
        if snapshot is not None and not snapshot.online:
            state_text = "Runtime 离线"

        self.modbus_status_panel_label.setText(f" 状态: {state_text}")
        self.modbus_status_label.setText(
            f"状态: {state_text}（由 Runtime 管理，端口 {port}）"
        )
        self.modbus_port_input.setText(str(port))
        self.modbus_port_input.setEnabled(False)
        self.modbus_slave_id_input.setEnabled(False)
        self.modbus_start_btn.setEnabled(False)
        self.modbus_stop_btn.setEnabled(False)
        self.modbus_cycle_label.setText(" 周期: --")
        self.modbus_duration_label.setText(" 耗时: --")
        self.modbus_table.setRowCount(0)
