from ...ui.qt_compat import QMessageBox


class RobotControlMixin:
    """GUI hardware commands remain disabled until Runtime IPC is available."""

    def _show_runtime_ipc_required(self, action):
        message = f"{action}暂不可用：硬件由 Runtime 独占，等待调试 IPC 接入"
        self.statusBar().showMessage(message)
        QMessageBox.information(self, "Runtime 只读模式", message)
        return False

    def enable_robot(self):
        return self._show_runtime_ipc_required("使能机器人")

    def disable_robot(self):
        return self._show_runtime_ipc_required("下使能机器人")

    def on_clear_error(self):
        return self._show_runtime_ipc_required("清除故障")

    def move_to_initial_position(self):
        return self._show_runtime_ipc_required("回到初始位置")

    def on_pause(self):
        return self._show_runtime_ipc_required("暂停流程")

    def on_continue(self):
        return self._show_runtime_ipc_required("继续流程")

    def connect_robot(self):
        return self._show_runtime_ipc_required("连接机器人")

    def set_collision_level(self):
        return self._show_runtime_ipc_required("设置碰撞等级")

    def _run_cmd_thread(
        self,
        cmd_name,
        cmd_func=None,
        *,
        on_success=None,
        show_result=True,
    ):
        del cmd_func, on_success, show_result
        return self._show_runtime_ipc_required(cmd_name)

    def _on_cmd_finished(self, cmd_name, success):
        del cmd_name, success

    def get_current_position(self):
        return self._show_runtime_ipc_required("获取当前位置")
