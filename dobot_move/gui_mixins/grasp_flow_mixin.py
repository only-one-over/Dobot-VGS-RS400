import os
import json

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMessageBox, QLabel

from config_manager import resolve_point


class GraspFlowMixin:

    def run_grasping_task(self):
        if self.vision_d435i is None and self.vision_d405 is None:
            QMessageBox.warning(self, "警告", "相机未连接，请先连接至少一台相机")
            return

        if not self.controller.is_connected:
            QMessageBox.warning(self, "警告", "机器人未连接，请先连接")
            return

        if not self.controller.is_enabled:
            if not self.controller.enable_robot():
                QMessageBox.critical(self, "错误", "机器人未使能，任务退出")
                return

        self.run_grasp_flow()

    def add_module(self):
        module_type = self.module_combo.currentText()

        if module_type == "相机识别":
            new_module = {
                "type": "camera",
                "name": "识别物体并计算坐标",
                "params": {
                    "camera_type": "D435i"
                }
            }
        elif module_type == "直线运动":
            new_module = {
                "type": "move",
                "name": "直线运动到目标",
                "params": {
                    "target": "camera_detected",
                    "motion_type": "MovL",
                    "speed": 30,
                    "point_name": ""
                }
            }
        elif module_type == "力控圆弧":
            new_module = {
                "type": "force_arc",
                "name": "力控圆弧运动",
                "params": {
                    "center": [400, 0, 300],
                    "radius": 50,
                    "start_angle": 0,
                    "end_angle": 90,
                    "rotation_axis": "Z",
                    "num_waypoints": 30,
                    "speed": 20,
                    "fc_axes": {"x": 0, "y": 0, "z": 0, "rx": 1, "ry": 1, "rz": 1},
                    "correction_gain": 0.3,
                    "deviation_pos": 100,
                    "deviation_rot": 36,
                    "damping_pos": 50,
                    "damping_rot": 5,
                    "mode": "coords",
                    "point_name": "",
                    "center_mode": "coords",
                    "center_point_name": ""
                }
            }
        elif module_type == "关节旋转":
            new_module = {
                "type": "joint_move",
                "name": "关节旋转运动",
                "params": {
                    "motion_type": "RelJointMovJ",
                    "offsets": [0, 0, 0, 0, 0, 0],
                    "acceleration": 20,
                    "speed": 50
                }
            }
        elif module_type == "夹爪开合":
            new_module = {
                "type": "gripper",
                "name": "夹爪开合",
                "params": {
                    "action": "打开",
                    "force": 50,
                    "speed": 50
                }
            }
        elif module_type == "视觉伺服":
            new_module = {
                "type": "visual_servo",
                "name": "D405视觉伺服抓取",
                "params": {
                    "target_type": "grasp_point",
                    "converge_threshold": 2.0,
                    "max_iterations": 60
                }
            }

        if self.selected_step_index >= 0:
            insert_index = self.selected_step_index + 1
            self.grasp_flow_modules.insert(insert_index, new_module)
            self.selected_step_index = insert_index
        else:
            self.grasp_flow_modules.append(new_module)
        self.view_current_grasp_flow()
        QMessageBox.information(self, "成功", f"模块 '{module_type}' 已添加")

    def remove_module(self):
        if not self.grasp_flow_modules:
            QMessageBox.warning(self, "警告", "抓取流程为空，无法移除模块")
            return

        if self.selected_step_index < 0:
            QMessageBox.warning(self, "警告", "请先选择要删除的模块")
            return

        removed_module = self.grasp_flow_modules.pop(self.selected_step_index)
        if self.selected_step_index >= len(self.grasp_flow_modules):
            self.selected_step_index = len(self.grasp_flow_modules) - 1
        self.view_current_grasp_flow()
        QMessageBox.information(self, "成功", f"模块 '{removed_module['name']}' 已移除")

    def on_module_combo_changed(self, index):
        module_type = self.module_combo.currentText()

        for i in reversed(range(self.param_layout.count())):
            widget = self.param_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)

        if module_type == "直线运动":
            self.param_layout.addWidget(self.linear_params, 0, 0)
        elif module_type == "力控圆弧":
            self.param_layout.addWidget(self.force_arc_params, 0, 0)
        elif module_type == "关节旋转":
            self.param_layout.addWidget(self.joint_rotation_params, 0, 0)
        elif module_type == "夹爪开合":
            self.param_layout.addWidget(self.gripper_params, 0, 0)
        elif module_type == "相机识别":
            self.param_layout.addWidget(self.camera_params, 0, 0)
        elif module_type == "视觉伺服":
            self.param_layout.addWidget(self.camera_params, 0, 0)

    def update_module_params(self):
        if not self.grasp_flow_modules:
            QMessageBox.warning(self, "警告", "抓取流程为空，无法更新参数")
            return

        if self.selected_step_index == -1:
            QMessageBox.warning(self, "警告", "请先选择要修改的步骤")
            return

        current_module = self.grasp_flow_modules[self.selected_step_index]

        if self.selected_step_index == 0 and current_module['type'] == 'move' and current_module['params']['target'] == 'initial_position':
            QMessageBox.warning(self, "警告", "第一个模块（移动到初始位置）不能被修改")
            return

        module_type = self.module_combo.currentText()

        if module_type == "直线运动" and current_module["type"] == "move" and current_module["params"]["motion_type"] == "MovL":
            current_module["params"]["point_name"] = self.linear_point_combo.currentText()
            current_module["params"]["speed"] = int(self.linear_speed.value())
            QMessageBox.information(self, "成功", "直线运动参数已更新")
        elif module_type == "力控圆弧" and current_module["type"] == "force_arc":
            if self.fa_mode == "point":
                current_module["params"]["mode"] = "point"
                current_module["params"]["point_name"] = self.fa_point_combo.currentText()
            else:
                current_module["params"]["mode"] = "coords"
                current_module["params"]["point_name"] = ""
                current_module["params"]["center"] = [
                    self.fa_center_x.value(),
                    self.fa_center_y.value(),
                    self.fa_center_z.value()
                ]
            if self.fa_center_mode == "point":
                current_module["params"]["center_mode"] = "point"
                current_module["params"]["center_point_name"] = self.fa_center_point_combo.currentText()
            else:
                current_module["params"]["center_mode"] = "coords"
                current_module["params"]["center_point_name"] = ""
            current_module["params"]["radius"] = self.fa_radius.value()
            current_module["params"]["start_angle"] = self.fa_start_angle.value()
            current_module["params"]["end_angle"] = self.fa_end_angle.value()
            current_module["params"]["rotation_axis"] = self.fa_rotation_axis.currentText()
            current_module["params"]["num_waypoints"] = int(self.fa_num_waypoints.value())
            current_module["params"]["speed"] = int(self.fa_speed.value())
            current_module["params"]["fc_axes"] = {
                "x": 0, "y": 0, "z": 0,
                "rx": 1 if self.fa_fc_rx.currentText() == "开启" else 0,
                "ry": 1 if self.fa_fc_ry.currentText() == "开启" else 0,
                "rz": 1 if self.fa_fc_rz.currentText() == "开启" else 0
            }
            current_module["params"]["correction_gain"] = self.fa_correction_gain.value()
            current_module["params"]["deviation_pos"] = self.fa_deviation_pos.value()
            current_module["params"]["deviation_rot"] = self.fa_deviation_rot.value()
            current_module["params"]["damping_pos"] = self.fa_damping_pos.value()
            current_module["params"]["damping_rot"] = self.fa_damping_rot.value()
            QMessageBox.information(self, "成功", "力控圆弧参数已更新")
        elif module_type == "关节旋转" and current_module["type"] == "joint_move":
            current_module["params"]["offsets"] = [self.joint_offsets[i].value() for i in range(6)]
            current_module["params"]["acceleration"] = int(self.joint_accel.value())
            current_module["params"]["speed"] = int(self.joint_speed.value())
            QMessageBox.information(self, "成功", "关节旋转参数已更新")
        elif module_type == "夹爪开合" and current_module["type"] == "gripper":
            current_module["params"]["action"] = self.gripper_action.currentText()
            current_module["params"]["force"] = int(self.gripper_force.value())
            current_module["params"]["speed"] = int(self.gripper_speed.value())
            QMessageBox.information(self, "成功", "夹爪开合参数已更新")
        elif module_type == "相机识别" and current_module["type"] == "camera":
            current_module["params"]["camera_type"] = self.camera_module_combo.currentText()
            QMessageBox.information(self, "成功", "相机识别参数已更新")
        else:
            QMessageBox.warning(self, "警告", "请选择正确的模块类型")

        self.view_current_grasp_flow()

    def view_current_grasp_flow(self):
        while self.flow_display_layout.count():
            child = self.flow_display_layout.takeAt(0)
            if child.widget():
                child.widget().setParent(None)
        self.step_labels.clear()

        self.flow_display_widget.updateGeometry()

        if not self.grasp_flow_modules:
            empty_label = QLabel("抓取流程为空")
            empty_label.setStyleSheet("color: #1a237e; background-color: white; padding: 5px; border-radius: 4px;")
            self.flow_display_layout.addWidget(empty_label)
            self.step_labels.append(empty_label)
            return

        for i, module in enumerate(self.grasp_flow_modules):
            step_text = f"{i+1}. {module['name']}"
            if module['type'] == "move":
                if module['params']['motion_type'] == "MovL":
                    point_name = module['params'].get('point_name', '')
                    step_text += f" (直线运动, 点位: {point_name}, 速度: {module['params']['speed']}%)"
            elif module['type'] == "force_arc":
                p = module['params']
                step_text += f" (力控圆弧, 圆心: {p['center']}, 半径: {p['radius']}mm, {p['start_angle']}°→{p['end_angle']}°, 轴: {p['rotation_axis']}, 增益: {p['correction_gain']})"
            elif module['type'] == "joint_move":
                offsets = module['params'].get('offsets', [0]*6)
                step_text += f" (关节旋转, 偏移: {offsets}, 速度: {module['params']['speed']}%)"
            elif module['type'] == "visual_servo":
                p = module['params']
                step_text += f" (视觉伺服, 目标: {p.get('target_type', 'grasp_point')}, 阈值: {p.get('converge_threshold', 2.0)}mm)"

            step_label = QLabel(step_text)
            step_label.setMinimumHeight(25)

            step_label.setStyleSheet("color: #1a237e; background-color: white; padding: 5px; border-radius: 4px;")

            step_label.setCursor(Qt.CursorShape.PointingHandCursor)
            step_label.mousePressEvent = lambda event, idx=i: self.on_step_clicked(idx)

            self.flow_display_layout.addWidget(step_label)
            self.step_labels.append(step_label)

        self._update_step_highlight(-1, self.selected_step_index)

        self.flow_display_widget.update()
        self.flow_display_widget.repaint()

    def _update_step_highlight(self, old_index, new_index):
        if 0 <= old_index < len(self.step_labels):
            self.step_labels[old_index].setStyleSheet("color: #1a237e; background-color: white; padding: 5px; border-radius: 4px;")
        if 0 <= new_index < len(self.step_labels):
            self.step_labels[new_index].setStyleSheet("color: white; background-color: #2196f3; padding: 5px; border-radius: 4px;")

    def on_step_clicked(self, index):
        old_index = self.selected_step_index
        self.selected_step_index = index
        self._update_step_highlight(old_index, index)
        if 0 <= index < len(self.grasp_flow_modules):
            module = self.grasp_flow_modules[index]
            if module["type"] == "camera":
                cam_type = module.get("params", {}).get("camera_type", "D435i")
                idx = self.camera_module_combo.findText(cam_type)
                if idx >= 0:
                    self.camera_module_combo.setCurrentIndex(idx)
            elif module["type"] == "move" and module["params"].get("motion_type") == "MovL":
                point_name = module["params"].get("point_name", "")
                idx = self.linear_point_combo.findText(point_name)
                if idx >= 0:
                    self.linear_point_combo.setCurrentIndex(idx)
                self.linear_speed.setValue(module["params"].get("speed", 30))
            elif module["type"] == "force_arc":
                mode = module["params"].get("mode", "coords")
                if mode == "point":
                    self.fa_coords_radio.setChecked(False)
                    self.fa_point_radio.setChecked(True)
                    point_name = module["params"].get("point_name", "")
                    idx = self.fa_point_combo.findText(point_name)
                    if idx >= 0:
                        self.fa_point_combo.setCurrentIndex(idx)
                else:
                    self.fa_coords_radio.setChecked(True)
                    self.fa_point_radio.setChecked(False)
                center_mode = module["params"].get("center_mode", "coords")
                if center_mode == "point":
                    self.fa_center_coords_radio.setChecked(False)
                    self.fa_center_point_radio.setChecked(True)
                    center_point_name = module["params"].get("center_point_name", "")
                    idx = self.fa_center_point_combo.findText(center_point_name)
                    if idx >= 0:
                        self.fa_center_point_combo.setCurrentIndex(idx)
                else:
                    self.fa_center_coords_radio.setChecked(True)
                    self.fa_center_point_radio.setChecked(False)

    def save_grasp_flow(self):
        if not self.grasp_flow_modules:
            QMessageBox.warning(self, "警告", "抓取流程为空，无法保存")
            return

        _module_dir = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(_module_dir, "grasp_flow_modules.json")

        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(self.grasp_flow_modules, f, indent=2)
            QMessageBox.information(self, "成功", f"抓取流程已保存到: {file_path}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存抓取流程时出错: {e}")

    def load_grasp_flow(self):
        _module_dir = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(_module_dir, "grasp_flow_modules.json")

        if not os.path.exists(file_path):
            QMessageBox.warning(self, "警告", f"文件不存在: {file_path}")
            return

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                self.grasp_flow_modules = json.load(f)

            self.view_current_grasp_flow()
            QMessageBox.information(self, "成功", f"抓取流程已从: {file_path} 加载")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"加载抓取流程时出错: {e}")

    def run_grasp_flow(self):
        if self._flow_running:
            self.statusBar().showMessage("流程已在运行中")
            return
        self._flow_running = True
        self.is_paused = False
        self.pause_btn.setEnabled(True)
        self.continue_btn.setEnabled(True)
        self.run_task_btn.setEnabled(False)
        self._is_paused_ref = [False]
        from gui_app import FlowThread
        self._flow_thread = FlowThread(
            self.controller, self.vision_d435i, self.vision_d405, self.gripper, self.grasp_flow_modules, self._is_paused_ref, self
        )
        self._flow_thread.flow_log.connect(self._on_flow_log)
        self._flow_thread.flow_finished.connect(self._on_flow_finished)
        self._flow_thread.flow_module_progress.connect(self._on_flow_module_progress)
        self._flow_thread.start()

    def _on_flow_log(self, msg):
        self.statusBar().showMessage(msg)

    def _on_flow_module_progress(self, current, total, name):
        self.statusBar().showMessage(f"执行模块 {current}/{total}: {name}")

    def _on_flow_finished(self, success):
        self._flow_running = False
        self.is_paused = False
        self.pause_btn.setEnabled(False)
        self.continue_btn.setEnabled(False)
        self.run_task_btn.setEnabled(True)
        if success:
            QMessageBox.information(self, "成功", "抓取流程执行完成")
        else:
            QMessageBox.warning(self, "失败", "抓取流程执行失败，请检查状态栏信息")
