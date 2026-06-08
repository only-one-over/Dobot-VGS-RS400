from qt_compat import QMessageBox, QTableWidgetItem


class ModbusMixin:

    def start_modbus_server(self):
        try:
            port = int(self.modbus_port_input.text().strip())
        except ValueError:
            QMessageBox.warning(self, "警告", "请输入有效的端口号")
            return

        if not self.controller.is_connected:
            QMessageBox.warning(self, "警告", "请先连接机器人")
            return

        result = self.controller.start_modbus(port=port)
        if result:
            self.modbus_status_label.setText("状态: 从站运行中，等待外部主站连接")
            self.modbus_start_btn.setEnabled(False)
            self.modbus_stop_btn.setEnabled(True)
            self.modbus_port_input.setEnabled(False)
            self._modbus_refresh_timer.start(200)
            self._init_modbus_table()
        else:
            QMessageBox.critical(self, "错误", "Modbus从站服务启动失败")

    def stop_modbus_server(self):
        self.controller.stop_modbus()
        self.modbus_status_label.setText("状态: 从站已停止")
        self.modbus_start_btn.setEnabled(True)
        self.modbus_stop_btn.setEnabled(False)
        self.modbus_port_input.setEnabled(True)
        self._modbus_refresh_timer.stop()
        self.modbus_cycle_label.setText(" 周期: 0")
        self.modbus_duration_label.setText(" 耗时: 0ms")
        self.modbus_status_panel_label.setText(" 状态: 停止")

    def _init_modbus_table(self):
        if not self.controller.modbus_server:
            return
        reg_values = self.controller.modbus_server.get_register_values()
        self.modbus_table.setRowCount(len(reg_values))
        for row, (addr, info) in enumerate(sorted(reg_values.items())):
            self.modbus_table.setItem(row, 0, QTableWidgetItem(str(addr)))
            self.modbus_table.setItem(row, 1, QTableWidgetItem(info.get("info", "")))
            self.modbus_table.setItem(row, 2, QTableWidgetItem(info.get("type", "U16")))

    def _refresh_modbus_table(self):
        stats = self.controller.get_modbus_stats()
        self.modbus_cycle_label.setText(f" 周期: {stats['cycle_count']}")
        self.modbus_duration_label.setText(f" 耗时: {stats['last_duration_ms']}ms")
        self.modbus_status_panel_label.setText(f" 状态: {'运行中' if stats['is_running'] else '停止'}")

        if not self.controller.modbus_server:
            return
        reg_values = self.controller.modbus_server.get_register_values()
        for row, (addr, info) in enumerate(sorted(reg_values.items())):
            float_val = info.get("float_value")
            if float_val is not None:
                val_str = f"{float_val}"
            else:
                val_str = str(info.get("value", 0))
            item = self.modbus_table.item(row, 3)
            if item:
                item.setText(val_str)
            else:
                self.modbus_table.setItem(row, 3, QTableWidgetItem(val_str))
