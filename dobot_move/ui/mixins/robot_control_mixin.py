class RobotControlMixin:
    """GUI hardware commands delegated to Runtime via ``RuntimeFacade`` IPC."""

    def enable_robot(self):
        success, msg = self._runtime_facade.enable_robot()
        self.statusBar().showMessage(msg, 3000)
        return success

    def disable_robot(self):
        success, msg = self._runtime_facade.disable_robot()
        self.statusBar().showMessage(msg, 3000)
        return success

    def on_clear_error(self):
        success, msg = self._runtime_facade.clear_alarms()
        self.statusBar().showMessage(msg, 3000)
        return success

    def move_to_initial_position(self):
        success, msg = self._runtime_facade.move_to_initial_position()
        self.statusBar().showMessage(msg, 3000)
        return success

    def on_pause(self):
        success, msg = self._runtime_facade.pause_flow()
        self.statusBar().showMessage(msg, 3000)
        return success

    def on_continue(self):
        success, msg = self._runtime_facade.resume_flow()
        self.statusBar().showMessage(msg, 3000)
        return success

    def connect_robot(self):
        success, msg = self._runtime_facade.connect_robot()
        self.statusBar().showMessage(msg, 3000)
        return success

    def set_collision_level(self):
        success, msg = self._runtime_facade.set_collision_level()
        self.statusBar().showMessage(msg, 3000)
        return success

    def _run_cmd_thread(
        self,
        cmd_name,
        cmd_func=None,
        *,
        on_success=None,
        show_result=True,
    ):
        del cmd_func, on_success, show_result
        success, msg = self._runtime_facade._send(cmd_name, action_name=cmd_name)
        self.statusBar().showMessage(msg, 3000)
        return success

    def _on_cmd_finished(self, cmd_name, success):
        del cmd_name, success

    def get_current_position(self):
        success, msg = self._runtime_facade.get_current_pose()
        self.statusBar().showMessage(msg, 3000)
        return success
