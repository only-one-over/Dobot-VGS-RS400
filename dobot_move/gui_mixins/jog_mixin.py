from qt_compat import QPushButton, QEvent


class JogMixin:

    _jog_active = False

    def _create_jog_button(self, text, axis_id):
        btn = QPushButton(text)
        btn.setMinimumHeight(40)
        btn.pressed.connect(lambda: self._on_jog_start(axis_id))
        btn.released.connect(self._on_jog_stop)
        btn.installEventFilter(self)
        return btn

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Leave and obj.isDown():
            self._on_jog_stop()
        return False

    def _on_jog_start(self, axis_id):
        if not self.controller.is_connected:
            self.statusBar().showMessage("请先连接并使能机器人")
            return
        if not self.controller.is_enabled:
            self.statusBar().showMessage("请先使能机器人")
            return
        coordtype = self.jog_coord_combo.currentData()
        if coordtype is None:
            coordtype = 1
        result = self.controller.move_jog(axis_id, coordtype)
        if not result:
            self.statusBar().showMessage("点动控制失败，请检查机器人状态")
            return
        self._jog_active = True

    def _on_jog_stop(self):
        self.controller.stop_jog()
        self._jog_active = False

    def cleanup_jog(self):
        if self._jog_active:
            self.controller.stop_jog()
            self._jog_active = False

    def _on_jog_mode_changed(self, index):
        self.jog_stacked.setCurrentIndex(index)

    def _on_coord_move_to_target(self):
        if not self.controller.is_connected:
            self.statusBar().showMessage("请先连接机器人")
            return
        if not self.controller.is_enabled:
            self.statusBar().showMessage("请先使能机器人")
            return
        if not self.controller.acquire_motion("jog_target"):
            self.statusBar().showMessage("机器人正在执行其他运动，请稍后再试")
            return
        x = self.coord_target_x.value()
        y = self.coord_target_y.value()
        z = self.coord_target_z.value()
        rx = self.coord_target_rx.value()
        ry = self.coord_target_ry.value()
        rz = self.coord_target_rz.value()
        try:
            self.statusBar().showMessage(f"正在运动到目标坐标 ({x:.2f}, {y:.2f}, {z:.2f})...")
            success = self.controller.move_to_point(
                [x, y, z, rx, ry, rz],
                move_type="MovJ",
                verify_start_pose=False,
                verify_end_pose=False,
            )
            if success:
                self.statusBar().showMessage("运动完成")
            else:
                self.statusBar().showMessage("运动失败，请查看日志")
        except Exception as e:
            self.statusBar().showMessage(f"运动失败: {e}")
        finally:
            self.controller.release_motion("jog_target")

    def _on_axis_move_to_target(self):
        # UI 仅有 J1-J4 输入，缺少 J5/J6，关节目标运动需要完整 6 轴数据
        self.statusBar().showMessage("关节目标运动需补齐 J1-J6 后启用")
