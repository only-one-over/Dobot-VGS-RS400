import json
import os

from qt_compat import QMessageBox

from config_manager import get_grasp_flow_file
from flow_step_list import STATUS_COMPLETED, STATUS_FAILED, STATUS_RUNNING


class GraspFlowMixin:
    def _normalize_flow_modules(self):
        for module in self.grasp_flow_modules:
            if module.get("type") == "force_arc":
                module["type"] = "arc_motion"
            if module.get("type") == "arc_motion":
                params = module.setdefault("params", {})
                for legacy_key in (
                    "fc_axes",
                    "correction_gain",
                    "deviation_pos",
                    "deviation_rot",
                    "damping_pos",
                    "damping_rot",
                    "num_waypoints",
                ):
                    params.pop(legacy_key, None)

    def run_grasping_task(self):
        if self.vision_d435i is None and self.vision_d405 is None:
            QMessageBox.warning(self, "警告", "相机未连接，请先连接至少一台相机")
            return
        if not self.controller.is_connected:
            QMessageBox.warning(self, "警告", "机器人未连接，请先连接")
            return
        if not self.controller.is_enabled and not self.controller.enable_robot():
            QMessageBox.critical(self, "错误", "机器人未使能，任务退出")
            return
        self.run_grasp_flow()

    def add_module(self):
        module_type = self.module_combo.currentText()
        new_module = None

        if module_type == "相机识别":
            new_module = {
                "type": "camera",
                "name": "识别物体并计算坐标",
                "params": {"camera_type": "D435i"},
            }
        elif module_type == "直线运动":
            new_module = {
                "type": "move",
                "name": "直线运动到目标",
                "params": {
                    "target": "camera_detected",
                    "motion_type": "MovL",
                    "speed": 30,
                    "point_name": "d435i",
                },
            }
        elif module_type == "圆弧运动":
            new_module = {
                "type": "arc_motion",
                "name": "圆弧运动",
                "params": {
                    "center_offset_z": 50,
                    "sweep_angle": 90,
                    "arc_direction": "ccw",
                    "speed": 20,
                },
            }
        elif module_type == "相对移动":
            new_module = {
                "type": "relative_move",
                "name": "相对移动",
                "params": {
                    "coord_system": "user",
                    "motion_type": "linear",
                    "offsets": [0, 0, 0, 0, 0, 0],
                    "speed": 30,
                    "acceleration": 20,
                    "cp": 100,
                },
            }
        elif module_type == "关节旋转":
            new_module = {
                "type": "joint_move",
                "name": "关节旋转运动",
                "params": {
                    "motion_type": "RelJointMovJ",
                    "offsets": [0, 0, 0, 0, 0, 0],
                    "acceleration": 20,
                    "speed": 50,
                },
            }
        elif module_type == "视觉伺服":
            new_module = {
                "type": "visual_servo",
                "name": "D405视觉伺服抓取",
                "params": {
                    "target_type": "grasp_point",
                    "converge_threshold": 2.0,
                    "max_iterations": 60,
                },
            }

        if new_module is None:
            QMessageBox.warning(self, "警告", "不支持的模块类型")
            return

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
        elif module_type == "圆弧运动":
            self.param_layout.addWidget(self.arc_motion_params, 0, 0)
        elif module_type == "相对移动":
            self.param_layout.addWidget(self.relative_move_params, 0, 0)
        elif module_type == "关节旋转":
            self.param_layout.addWidget(self.joint_rotation_params, 0, 0)
        elif module_type in ("相机识别", "视觉伺服"):
            self.param_layout.addWidget(self.camera_params, 0, 0)

    def update_module_params(self):
        if not self.grasp_flow_modules:
            QMessageBox.warning(self, "警告", "抓取流程为空，无法更新参数")
            return
        if self.selected_step_index == -1:
            QMessageBox.warning(self, "警告", "请先选择要修改的步骤")
            return

        self._normalize_flow_modules()
        current_module = self.grasp_flow_modules[self.selected_step_index]
        if (
            self.selected_step_index == 0
            and current_module["type"] == "move"
            and current_module["params"].get("target") == "initial_position"
        ):
            QMessageBox.warning(self, "警告", "第一个模块（移动到初始位置）不能被修改")
            return

        module_type = self.module_combo.currentText()
        if module_type == "直线运动" and current_module["type"] == "move":
            current_module["params"]["point_name"] = self.linear_point_combo.currentText()
            current_module["params"]["speed"] = int(self.linear_speed.value())
            QMessageBox.information(self, "成功", "直线运动参数已更新")
        elif module_type == "圆弧运动" and current_module["type"] == "arc_motion":
            current_module["params"]["center_offset_z"] = self.fa_center_offset_z.value()
            current_module["params"]["sweep_angle"] = self.fa_sweep_angle.value()
            current_module["params"]["arc_direction"] = "cw" if self.fa_arc_direction.currentText() == "顺时针" else "ccw"
            current_module["params"]["speed"] = int(self.fa_speed.value())
            QMessageBox.information(self, "成功", "圆弧运动参数已更新")
        elif module_type == "相对移动" and current_module["type"] == "relative_move":
            coord_map = {"用户": "user", "工具": "tool", "关节": "joint"}
            motion_map = {"直线": "linear", "关节": "joint"}
            current_module["params"]["coord_system"] = coord_map.get(self.rel_coord_combo.currentText(), "user")
            current_module["params"]["motion_type"] = motion_map.get(self.rel_motion_combo.currentText(), "linear")
            current_module["params"]["offsets"] = [self.rel_offsets[i].value() for i in range(6)]
            current_module["params"]["speed"] = int(self.rel_speed.value())
            current_module["params"]["acceleration"] = int(self.rel_accel.value())
            current_module["params"]["cp"] = int(self.rel_cp.value())
            QMessageBox.information(self, "成功", "相对移动参数已更新")
        elif module_type == "关节旋转" and current_module["type"] == "joint_move":
            current_module["params"]["offsets"] = [self.joint_offsets[i].value() for i in range(6)]
            current_module["params"]["acceleration"] = int(self.joint_accel.value())
            current_module["params"]["speed"] = int(self.joint_speed.value())
            QMessageBox.information(self, "成功", "关节旋转参数已更新")
        elif module_type == "相机识别" and current_module["type"] == "camera":
            current_module["params"]["camera_type"] = self.camera_module_combo.currentText()
            QMessageBox.information(self, "成功", "相机识别参数已更新")
        else:
            QMessageBox.warning(self, "警告", "请选择正确的模块类型")

        self.view_current_grasp_flow()

    def view_current_grasp_flow(self):
        self._normalize_flow_modules()
        self.flow_step_list.set_steps(self.grasp_flow_modules)

    def _update_step_highlight(self, old_index, new_index):
        self.flow_step_list.set_selected(new_index)

    def on_step_clicked(self, index):
        self._normalize_flow_modules()
        old_index = self.selected_step_index
        self.selected_step_index = index
        self.flow_step_list.set_selected(index)
        if not (0 <= index < len(self.grasp_flow_modules)):
            return

        module = self.grasp_flow_modules[index]
        module_type_text = {
            "camera": "相机识别",
            "move": "直线运动",
            "arc_motion": "圆弧运动",
            "relative_move": "相对移动",
            "joint_move": "关节旋转",
            "visual_servo": "视觉伺服",
        }.get(module.get("type"))
        if module_type_text:
            idx = self.module_combo.findText(module_type_text)
            if idx >= 0:
                self.module_combo.setCurrentIndex(idx)

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
        elif module["type"] == "arc_motion":
            p = module.get("params", {})
            self.fa_center_offset_z.setValue(float(p.get("center_offset_z", p.get("radius", 50))))
            self.fa_sweep_angle.setValue(float(p.get("sweep_angle", abs(float(p.get("end_angle", 90)) - float(p.get("start_angle", 0))))))
            direction = p.get("arc_direction")
            if direction is None:
                direction = "cw" if float(p.get("end_angle", 90)) < float(p.get("start_angle", 0)) else "ccw"
            idx = self.fa_arc_direction.findText("顺时针" if direction == "cw" else "逆时针")
            if idx >= 0:
                self.fa_arc_direction.setCurrentIndex(idx)
            self.fa_speed.setValue(float(p.get("speed", 20)))
        elif module["type"] == "relative_move":
            p = module.get("params", {})
            coord_text = {"user": "用户", "tool": "工具", "joint": "关节"}.get(p.get("coord_system", "user"), "用户")
            motion_text = {"linear": "直线", "joint": "关节"}.get(p.get("motion_type", "linear"), "直线")
            idx = self.rel_coord_combo.findText(coord_text)
            if idx >= 0:
                self.rel_coord_combo.setCurrentIndex(idx)
            idx = self.rel_motion_combo.findText(motion_text)
            if idx >= 0:
                self.rel_motion_combo.setCurrentIndex(idx)
            offsets = p.get("offsets", [0, 0, 0, 0, 0, 0])
            for i, spin in enumerate(self.rel_offsets):
                spin.setValue(float(offsets[i] if i < len(offsets) else 0))
            self.rel_speed.setValue(float(p.get("speed", 30)))
            self.rel_accel.setValue(float(p.get("acceleration", 20)))
            self.rel_cp.setValue(float(p.get("cp", 100)))

    def save_grasp_flow(self):
        if not self.grasp_flow_modules:
            QMessageBox.warning(self, "警告", "抓取流程为空，无法保存")
            return

        self._normalize_flow_modules()
        file_path = get_grasp_flow_file()
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(self.grasp_flow_modules, f, indent=2, ensure_ascii=False)
            self.view_current_grasp_flow()
            QMessageBox.information(self, "成功", f"抓取流程已保存到: {file_path}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存抓取流程时出错: {e}")

    def load_grasp_flow(self):
        file_path = get_grasp_flow_file()
        if not os.path.exists(file_path):
            QMessageBox.warning(self, "警告", f"文件不存在: {file_path}")
            return

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                self.grasp_flow_modules = json.load(f)
            self._normalize_flow_modules()
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
        if hasattr(self, "_refresh_action_states"):
            self._refresh_action_states()
        self._is_paused_ref = [False]
        self._normalize_flow_modules()

        from workers import validate_grasp_flow_modules

        errors = validate_grasp_flow_modules(self.grasp_flow_modules)
        if errors:
            self._flow_running = False
            error_text = "\n".join(errors)
            QMessageBox.warning(self, "流程校验失败", f"以下问题需要修正：\n\n{error_text}")
            if hasattr(self, "_refresh_action_states"):
                self._refresh_action_states()
            return

        from workers import FlowThread

        self._flow_thread = FlowThread(
            self.controller,
            self.vision_d435i,
            self.vision_d405,
            self.grasp_flow_modules,
            self._is_paused_ref,
            self,
        )
        self._flow_thread.flow_log.connect(self._on_flow_log)
        self._flow_thread.flow_finished.connect(self._on_flow_finished)
        self._flow_thread.flow_module_progress.connect(self._on_flow_module_progress)
        self._flow_thread.finished.connect(self._flow_thread.deleteLater)
        self._flow_thread.start()

    def _on_flow_log(self, msg):
        self.statusBar().showMessage(msg)
        if "❌" in msg or "失败" in msg or "报警" in msg:
            self.controller.record_alarm("流程执行", "", "报警", msg)
            if hasattr(self, "_refresh_alarm_table"):
                self._refresh_alarm_table()

    def _on_flow_module_progress(self, current, total, name):
        self.statusBar().showMessage(f"执行模块 {current}/{total}: {name}")
        idx = current - 1
        if 0 <= idx < len(self.grasp_flow_modules):
            for i in range(idx):
                self.flow_step_list.set_step_status(i, STATUS_COMPLETED)
            self.flow_step_list.set_step_status(idx, STATUS_RUNNING)

    def _on_flow_finished(self, success):
        self._flow_running = False
        self._flow_thread = None
        self.is_paused = False
        if hasattr(self, "_refresh_action_states"):
            self._refresh_action_states()
        for i in range(len(self.grasp_flow_modules)):
            self.flow_step_list.set_step_status(i, STATUS_COMPLETED if success else STATUS_FAILED)
        if success:
            QMessageBox.information(self, "成功", "抓取流程执行完成")
        else:
            self.controller.record_alarm("流程执行", "", "故障", "抓取流程执行失败", "查看状态栏和流程步骤，确认失败模块")
            if hasattr(self, "_refresh_alarm_table"):
                self._refresh_alarm_table()
            QMessageBox.warning(self, "失败", "抓取流程执行失败，请检查状态栏信息")

    def _on_steps_reordered(self, modules):
        self.grasp_flow_modules = modules
        self._normalize_flow_modules()
