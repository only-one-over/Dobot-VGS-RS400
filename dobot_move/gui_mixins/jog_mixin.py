from qt_compat import QPushButton


class JogMixin:

    def _create_jog_button(self, text, axis_id):
        btn = QPushButton(text)
        btn.setMinimumHeight(40)
        btn.pressed.connect(lambda: self._on_jog_start(axis_id))
        btn.released.connect(self._on_jog_stop)
        return btn

    def _on_jog_start(self, axis_id):
        if not self.controller.is_connected:
            self.statusBar().showMessage("请先连接并使能机器人")
            return
        coordtype = self.jog_coord_combo.currentData()
        if coordtype is None:
            coordtype = 1
        self.controller.move_jog(axis_id, coordtype)

    def _on_jog_stop(self):
        self.controller.stop_jog()

    def _on_jog_mode_changed(self, index):
        self.jog_stacked.setCurrentIndex(index)

    def _on_coord_move_to_target(self):
        if not self.controller.is_connected:
            self.statusBar().showMessage("请先连接并使能机器人")
            return
        x = self.coord_target_x.value()
        y = self.coord_target_y.value()
        z = self.coord_target_z.value()
        rx = self.coord_target_rx.value()
        ry = self.coord_target_ry.value()
        rz = self.coord_target_rz.value()
        try:
            self.statusBar().showMessage(f"正在运动到目标坐标 ({x:.2f}, {y:.2f}, {z:.2f})...")
            result = self.controller.dashboard.MovJ(x, y, z, rx, ry, rz, 0)
            self.statusBar().showMessage(f"运动指令已发送: {result}")
        except Exception as e:
            self.statusBar().showMessage(f"运动失败: {e}")

    def _on_axis_move_to_target(self):
        if not self.controller.is_connected:
            self.statusBar().showMessage("请先连接并使能机器人")
            return
        j1 = self.axis_target_j1.value()
        j2 = self.axis_target_j2.value()
        j3 = self.axis_target_j3.value()
        j4 = self.axis_target_j4.value()
        try:
            self.statusBar().showMessage(f"正在运动到目标角度 ({j1:.2f}, {j2:.2f}, {j3:.2f}, {j4:.2f})...")
            result = self.controller.dashboard.MovJ(j1, j2, j3, j4, 0, 0, 1)
            self.statusBar().showMessage(f"运动指令已发送: {result}")
        except Exception as e:
            self.statusBar().showMessage(f"运动失败: {e}")
