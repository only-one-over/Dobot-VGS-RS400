from ..qt_compat import QMessageBox

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
        self._request_device_connection("robot", manual=True)

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
