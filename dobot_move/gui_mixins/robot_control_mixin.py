from ..qt_compat import QMessageBox, QTimer

from ..config_manager import ConfigService
from ..workers import RobotCmdThread


class RobotControlMixin:

    def enable_robot(self):
        if not self.controller.is_connected:
            QMessageBox.warning(self, "警告", "机器人未连接，请先连接")
            return

        if self.controller.is_enabled:
            QMessageBox.information(self, "提示", "机器人已使能")
            return

        self._run_cmd_thread("使能", self.controller.enable_robot)

    def disable_robot(self):
        if not self.controller.is_connected:
            QMessageBox.warning(self, "警告", "机器人未连接，请先连接")
            return

        if not self.controller.is_enabled:
            QMessageBox.information(self, "提示", "机器人已下使能")
            return

        self._run_cmd_thread("下使能", self.controller.disable_robot)

    def on_clear_error(self):
        if not self.controller.is_connected:
            QMessageBox.warning(self, "提示", "请先连接机器人")
            return
        self._run_cmd_thread("清除故障", self.controller.clear_error)

    def move_to_initial_position(self):
        if not self.controller.is_connected:
            QMessageBox.warning(self, "警告", "机器人未连接，请先连接")
            return

        def _move_home():
            if not getattr(self.controller, "is_enabled", False):
                if not self.controller.enable_robot():
                    return False
            return self.controller.move_to_initial_position(
                verify_start_pose=False,
                verify_end_pose=True,
            )

        self._run_cmd_thread("回到初始位置", _move_home)

    def on_pause(self):
        if not self._flow_running:
            self.statusBar().showMessage("当前没有运行中的任务")
            return
        self.is_paused = True
        self._is_paused_ref[0] = True
        self.controller.pause()
        self.statusBar().showMessage("流程已暂停")
        if hasattr(self, "_refresh_action_states"):
            self._refresh_action_states()

    def on_continue(self):
        if not self._flow_running:
            self.statusBar().showMessage("当前没有运行中的任务")
            return
        self.is_paused = False
        self._is_paused_ref[0] = False
        self.controller.continue_motion()
        self.statusBar().showMessage("流程已继续")
        if hasattr(self, "_refresh_action_states"):
            self._refresh_action_states()

    def connect_robot(self):
        if self.controller.is_connected:
            QMessageBox.information(self, "提示", "机器人已连接")
            return

        ip = self.ip_input.text().strip()
        if not ip:
            QMessageBox.warning(self, "警告", "请输入机器人IP地址")
            return

        self.controller.set_robot_ip(ip)
        ConfigService.instance().set_ip('robot_ip', ip)
        self._run_cmd_thread("连接", self.controller.connect)

    def set_collision_level(self):
        if not self.controller.is_connected:
            QMessageBox.warning(self, "警告", "机器人未连接，请先连接")
            return

        level = self.collision_combo.currentIndex()
        self._run_cmd_thread("设置碰撞等级", lambda: self.controller.set_collision_level(level))

    def _run_cmd_thread(self, cmd_name, cmd_func):
        if getattr(self, "_cmd_running", False):
            self.statusBar().showMessage("已有机器人命令正在执行，请稍候")
            return
        self._cmd_running = True
        if hasattr(self, "_refresh_action_states"):
            self._refresh_action_states()
        self.statusBar().showMessage(f"正在{cmd_name}...")
        self._cmd_thread = RobotCmdThread(cmd_name, cmd_func, self)
        self._cmd_thread.cmd_finished.connect(self._on_cmd_finished)
        self._cmd_thread.finished.connect(self._cmd_thread.deleteLater)
        self._cmd_thread.start()

    def _on_cmd_finished(self, cmd_name, success):
        self._cmd_running = False
        self._cmd_thread = None
        if success:
            QMessageBox.information(self, "成功", f"{cmd_name}成功")
        else:
            error_msg = self.controller.last_error if hasattr(self.controller, 'last_error') else ""
            if error_msg:
                QMessageBox.critical(self, "错误", f"{cmd_name}失败\n\n原因: {error_msg}\n\n建议检查:\n1. 机器人IP地址是否正确\n2. 电脑和机器人是否在同一网段\n3. 机器人是否已启用TCP/IP控制模式\n4. 防火墙是否阻止了端口29999")
            else:
                QMessageBox.critical(self, "错误", f"{cmd_name}失败")
        self.statusBar().showMessage(f"{cmd_name}{'成功' if success else '失败'}")
        if hasattr(self, "_refresh_action_states"):
            self._refresh_action_states()

    def get_current_position(self):
        if not self.controller.is_connected:
            QMessageBox.warning(self, "警告", "机器人未连接，请先连接")
            return

        current_pose = self.controller.get_current_pose_fast()
        if current_pose:
            QMessageBox.information(self, "当前位置", f"当前位置:\n{current_pose}")
        else:
            QMessageBox.critical(self, "错误", "获取位置失败")

    def start_monitor_threads(self):
        self._pose_monitor_timer = QTimer()
        self._pose_monitor_timer.timeout.connect(self._update_pose_display)
        self._pose_monitor_timer.start(200)

    def _update_pose_display(self):
        data = self.controller.get_feed_data()
        if data is not None:
            try:
                tool_vector = data.get("ToolVectorActual")
                if tool_vector is not None and len(tool_vector) > 0:
                    vals = tool_vector[0]
                    if len(vals) >= 6:
                        self.coord_x_label.setText(f"X: {float(vals[0]):.2f}")
                        self.coord_y_label.setText(f"Y: {float(vals[1]):.2f}")
                        self.coord_z_label.setText(f"Z: {float(vals[2]):.2f}")
                        self.coord_rx_label.setText(f"Rx: {float(vals[3]):.2f}")
                        self.coord_ry_label.setText(f"Ry: {float(vals[4]):.2f}")
                        self.coord_rz_label.setText(f"Rz: {float(vals[5]):.2f}")
            except Exception:
                pass
            try:
                q_actual = data.get("QActual")
                if q_actual is not None and len(q_actual) > 0:
                    vals = q_actual[0]
                    if len(vals) >= 4:
                        self.axis_j1_label.setText(f"J1: {float(vals[0]):.2f}")
                        self.axis_j2_label.setText(f"J2: {float(vals[1]):.2f}")
                        self.axis_j3_label.setText(f"J3: {float(vals[2]):.2f}")
                        self.axis_j4_label.setText(f"J4: {float(vals[3]):.2f}")
            except Exception:
                pass

    def stop_monitor_threads(self):
        if hasattr(self, '_pose_monitor_timer') and self._pose_monitor_timer:
            self._pose_monitor_timer.stop()
