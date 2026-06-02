import math

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QMessageBox

from config_manager import (
    set_photo_position as config_set_photo_position,
    set_robot_ip as config_set_robot_ip,
)
from workers import MonitorThread, RobotCmdThread


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
        self.statusBar().showMessage("正在清除故障...")
        try:
            result = self.controller.clear_error()
            if result:
                self.statusBar().showMessage("✅ 故障已清除，机器人已重新使能")
            else:
                self.statusBar().showMessage("❌ 清除故障失败，请检查机器人状态")
        except Exception as e:
            self.statusBar().showMessage(f"❌ 清除故障出错: {e}")

    def on_pause(self):
        if not self._flow_running:
            self.statusBar().showMessage("当前没有运行中的任务")
            return
        self.is_paused = True
        self._is_paused_ref[0] = True
        self.controller.pause()
        self.statusBar().showMessage("流程已暂停")
        self.pause_btn.setEnabled(False)
        self.continue_btn.setEnabled(True)

    def on_continue(self):
        if not self._flow_running:
            self.statusBar().showMessage("当前没有运行中的任务")
            return
        self.is_paused = False
        self._is_paused_ref[0] = False
        self.controller.continue_motion()
        self.statusBar().showMessage("流程已继续")
        self.pause_btn.setEnabled(True)
        self.continue_btn.setEnabled(False)

    def connect_robot(self):
        if self.controller.is_connected:
            QMessageBox.information(self, "提示", "机器人已连接")
            return

        ip = self.ip_input.text().strip()
        if not ip:
            QMessageBox.warning(self, "警告", "请输入机器人IP地址")
            return

        self.controller.set_robot_ip(ip)
        config_set_robot_ip(ip)
        self._run_cmd_thread("连接", self.controller.connect)

    def set_collision_level(self):
        if not self.controller.is_connected:
            QMessageBox.warning(self, "警告", "机器人未连接，请先连接")
            return

        level = self.collision_combo.currentIndex()
        self._run_cmd_thread("设置碰撞等级", lambda: self.controller.set_collision_level(level))

    def _run_cmd_thread(self, cmd_name, cmd_func):
        self.statusBar().showMessage(f"正在{cmd_name}...")
        self._cmd_thread = RobotCmdThread(cmd_name, cmd_func, self)
        self._cmd_thread.cmd_finished.connect(self._on_cmd_finished)
        self._cmd_thread.start()

    def _on_cmd_finished(self, cmd_name, success):
        if success:
            QMessageBox.information(self, "成功", f"{cmd_name}成功")
        else:
            error_msg = self.controller.last_error if hasattr(self.controller, 'last_error') else ""
            if error_msg:
                QMessageBox.critical(self, "错误", f"{cmd_name}失败\n\n原因: {error_msg}\n\n建议检查:\n1. 机器人IP地址是否正确\n2. 电脑和机器人是否在同一网段\n3. 机器人是否已启用TCP/IP控制模式\n4. 防火墙是否阻止了端口29999")
            else:
                QMessageBox.critical(self, "错误", f"{cmd_name}失败")
        self.statusBar().showMessage(f"{cmd_name}{'成功' if success else '失败'}")

    def get_current_position(self):
        if not self.controller.is_connected:
            QMessageBox.warning(self, "警告", "机器人未连接，请先连接")
            return

        current_pose = self.controller.get_current_pose()
        if current_pose:
            reply = QMessageBox.question(
                self, "当前位置",
                f"当前位置:\n{current_pose}\n\n是否将此位置设为拍照位置？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._fill_photo_position_inputs(current_pose)
        else:
            QMessageBox.critical(self, "错误", "获取位置失败")

    def _fill_photo_position_inputs(self, pose):
        for i, input_box in enumerate(self.photo_position_inputs):
            if i < len(pose):
                input_box.setValue(pose[i])

    def _get_photo_from_current(self):
        if not self.controller.is_connected:
            QMessageBox.warning(self, "警告", "机器人未连接，请先连接")
            return
        current_pose = self.controller.get_current_pose()
        if current_pose:
            self._fill_photo_position_inputs(current_pose)
            QMessageBox.information(self, "成功", f"已将当前位置填入拍照位置:\n{current_pose}")
        else:
            QMessageBox.critical(self, "错误", "获取位置失败")

    def set_photo_position(self):
        try:
            new_position = [float(input_box.value()) for input_box in self.photo_position_inputs]

            reply = QMessageBox.question(
                self, "确认", f"新的拍照位置: {new_position}\n确认修改？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes
            )

            if reply == QMessageBox.StandardButton.Yes:
                self.controller.initial_pose = new_position
                if config_set_photo_position(new_position):
                    self.photo_position_label.setText(f"拍照位置: {new_position}")
                    QMessageBox.information(self, "成功", "拍照位置已成功修改并保存")
                else:
                    QMessageBox.warning(self, "警告", "拍照位置已修改但保存失败")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"修改拍照位置时出错: {e}")

    def update_battery_data(self, data):
        self.battery_label.setText(f"电池: {data['soc']}% | {data['voltage']:.1f}V | {data['current']:.1f}A | {data['status']}")

    def update_torque_data(self, data):
        if data is None:
            return
        try:
            tcp_force = data["ActualTCPForce"][0]
            fx = float(tcp_force[0])
            fy = float(tcp_force[1])
            fz = float(tcp_force[2])
            resultant = math.sqrt(fx*fx + fy*fy + fz*fz)
            self.torque_label.setText(f"力矩: Fx:{fx:.2f}N Fy:{fy:.2f}N Fz:{fz:.2f}N 合力:{resultant:.2f}N")

            if hasattr(data, 'get'):
                i_actual = data.get("IActual")
                if i_actual is not None and len(i_actual) > 0:
                    current_values = i_actual[0]
                    if len(current_values) >= 6:
                        self.torque_joint1_label.setText(f"关节1: {float(current_values[0]):.2f} A")
                        self.torque_joint2_label.setText(f"关节2: {float(current_values[1]):.2f} A")
                        self.torque_joint3_label.setText(f"关节3: {float(current_values[2]):.2f} A")
                        self.torque_joint4_label.setText(f"关节4: {float(current_values[3]):.2f} A")
                        self.torque_joint5_label.setText(f"关节5: {float(current_values[4]):.2f} A")
                        self.torque_joint6_label.setText(f"关节6: {float(current_values[5]):.2f} A")

        except Exception as e:
            print(f"更新力矩数据失败: {e}")
            pass

    def start_monitor_threads(self):
        if self.battery and self.battery.is_connected:
            def read_battery():
                self.battery.read_data()
                return self.battery.get_data()
            self.battery_thread = MonitorThread(self.battery, read_battery)
            self.battery_thread.data_updated.connect(self.update_battery_data)
            self.battery_thread.start()

        self._torque_timer = QTimer()
        self._torque_timer.timeout.connect(self._read_torque_from_controller)
        self._torque_timer.start(200)

    def _read_torque_from_controller(self):
        data = self.controller.get_feed_data()
        if data is not None:
            self.update_torque_data(data)
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
        if self.battery_thread:
            self.battery_thread.stop()
        if hasattr(self, '_torque_timer') and self._torque_timer:
            self._torque_timer.stop()
