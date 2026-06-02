from PyQt6.QtWidgets import QMessageBox, QTableWidgetItem


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
            self.modbus_status_label.setText("状态: 运行中")
            self.modbus_start_btn.setEnabled(False)
            self.modbus_stop_btn.setEnabled(True)
            self.modbus_port_input.setEnabled(False)
            self._modbus_refresh_timer.start(200)
            self._init_modbus_table()
        else:
            QMessageBox.critical(self, "错误", "Modbus服务启动失败")

    def stop_modbus_server(self):
        self.controller.stop_modbus()
        self.modbus_status_label.setText("状态: 已停止")
        self.modbus_start_btn.setEnabled(True)
        self.modbus_stop_btn.setEnabled(False)
        self.modbus_port_input.setEnabled(True)
        self._modbus_refresh_timer.stop()
        self.modbus_cycle_label.setText(" 周期: 0")
        self.modbus_duration_label.setText(" 耗时: 0ms")
        self.modbus_status_panel_label.setText(" 状态: 停止")

    def connect_cart_modbus(self):
        host = self.cart_ip_input.text().strip()
        try:
            port = int(self.cart_port_input.text().strip())
        except ValueError:
            QMessageBox.warning(self, "警告", "请输入有效的小车端口号")
            return

        result = self.controller.start_modbus_client(host, port)
        if result:
            self.cart_connect_btn.setEnabled(False)
            self.cart_disconnect_btn.setEnabled(True)
            self.cart_ip_input.setEnabled(False)
            self.cart_port_input.setEnabled(False)
            self.cart_status_label.setText(f"小车状态: 已连接 {host}:{port}")
        else:
            QMessageBox.critical(self, "错误", f"连接小车 Modbus 失败: {host}:{port}")

    def disconnect_cart_modbus(self):
        self.controller.stop_modbus_client()
        self.cart_connect_btn.setEnabled(True)
        self.cart_disconnect_btn.setEnabled(False)
        self.cart_ip_input.setEnabled(True)
        self.cart_port_input.setEnabled(True)
        self.cart_status_label.setText("小车状态: 未连接")
        self.cart_info_label.setText(" 小车状态: --- | 故障码: --- | 位置 X: --- Y: --- Z: ---")

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

        cart = stats.get('cart_status', {})
        if cart.get('connected'):
            cart_status_text = "空闲" if cart.get('cart_status') == 1 else ("运行" if cart.get('cart_status') == 2 else "故障")
            self.cart_info_label.setText(
                f" 小车状态: {cart_status_text} | 故障码: {cart.get('fault_code', 0)}"
                f" | 位置 X: {cart.get('x', 0)} Y: {cart.get('y', 0)} Z: {cart.get('z', 0)}"
            )

        if stats.get('client_connected'):
            self.cart_status_label.setText(f"小车状态: 已连接 {stats.get('client_host', '')}")
        else:
            if not self.cart_connect_btn.isEnabled():
                self.cart_status_label.setText("小车状态: 连接断开")
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
