import os

from ..qt_compat import QInputDialog, QMessageBox, QTableWidgetItem

from ..config_manager import get_grasp_flow_file
from ..flow_library import FlowLibrary
from ..flow_step_list import STATUS_COMPLETED, STATUS_RUNNING


class GraspFlowMixin:
    def _refresh_flow_selectors(self):
        flows = self.flow_library.flows
        self.main_control.set_main_flows(
            flows,
            self.flow_library.main_flow_id,
        )
        if hasattr(self, "edit_flow_combo"):
            self.edit_flow_combo.blockSignals(True)
            self.edit_flow_combo.clear()
            selected_index = 0
            for index, flow in enumerate(flows):
                self.edit_flow_combo.addItem(flow["name"], flow["id"])
                if flow["id"] == self.editing_flow_id:
                    selected_index = index
            self.edit_flow_combo.setCurrentIndex(selected_index)
            self.edit_flow_combo.blockSignals(False)

    def _on_main_flow_changed(self, flow_id):
        try:
            self.flow_library.set_main_flow(flow_id)
            self.flow_library.save()
            self._refresh_flow_selectors()
            if hasattr(self, "_restart_startup_connection_check"):
                self._restart_startup_connection_check()
        except Exception as exc:
            QMessageBox.critical(self, "主流程设置失败", str(exc))

    def _on_edit_flow_changed(self, index):
        flow_id = self.edit_flow_combo.itemData(index)
        if flow_id:
            self._select_editing_flow(str(flow_id), persist=True)

    def _select_editing_flow(self, flow_id, persist=False):
        flow = self.flow_library.get_flow(flow_id)
        self.editing_flow_id = flow_id
        self.grasp_flow_modules = flow["modules"]
        self.selected_step_index = -1
        self.flow_step_list.set_steps(self.grasp_flow_modules)
        if persist:
            self.flow_library.set_last_edited_flow(flow_id)
            self.flow_library.save()
        self._refresh_flow_selectors()

    def create_flow(self):
        default_name = f"流程 {len(self.flow_library.flows) + 1}"
        name, ok = QInputDialog.getText(self, "新建流程", "流程名称:", text=default_name)
        if not ok:
            return
        try:
            flow = self.flow_library.create_flow(name)
            self.flow_library.save()
            self._select_editing_flow(flow["id"])
        except Exception as exc:
            QMessageBox.warning(self, "新建流程失败", str(exc))

    def rename_flow(self):
        flow = self.flow_library.get_flow(self.editing_flow_id)
        name, ok = QInputDialog.getText(
            self,
            "重命名流程",
            "流程名称:",
            text=flow["name"],
        )
        if not ok:
            return
        try:
            self.flow_library.rename_flow(flow["id"], name)
            self.flow_library.save()
            self._refresh_flow_selectors()
        except Exception as exc:
            QMessageBox.warning(self, "重命名失败", str(exc))

    def duplicate_flow(self):
        try:
            flow = self.flow_library.duplicate_flow(self.editing_flow_id)
            self.flow_library.save()
            self._select_editing_flow(flow["id"])
        except Exception as exc:
            QMessageBox.warning(self, "复制流程失败", str(exc))

    def delete_flow(self):
        flow = self.flow_library.get_flow(self.editing_flow_id)
        answer = QMessageBox.question(
            self,
            "删除流程",
            f"确定删除“{flow['name']}”吗？",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.flow_library.delete_flow(flow["id"])
            self.flow_library.save()
            self._select_editing_flow(self.flow_library.last_edited_flow_id)
        except Exception as exc:
            QMessageBox.warning(self, "删除流程失败", str(exc))

    @staticmethod
    def _default_force_guard(enabled=False, threshold_n=5.0):
        return {
            "enabled": bool(enabled),
            "threshold_n": float(threshold_n),
            "mode": "resultant_delta",
        }

    def _force_guard_from_controls(self, enabled_widget, threshold_widget):
        return self._default_force_guard(
            enabled=enabled_widget.isChecked(),
            threshold_n=threshold_widget.value(),
        )

    def _apply_force_guard_to_controls(self, params, enabled_widget, threshold_widget):
        guard = params.get("force_guard") or {}
        enabled_widget.setChecked(bool(guard.get("enabled", False)))
        threshold_widget.setValue(float(guard.get("threshold_n", 5.0)))

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
        return self._show_runtime_ipc_required("运行主流程")

    def check_main_flow_readiness(self):
        return False

    def _check_modules_readiness(self, modules):
        del modules
        return False

    def _handle_flow_readiness_failure(self, result, modbus_triggered):
        del result, modbus_triggered
        return self._show_runtime_ipc_required("运行流程")

    def _stop_camera_test_before_flow(self, modbus_triggered=False):
        del modbus_triggered
        return False

    def _get_flow_camera_test_workers(self):
        return {}

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
                    "target": "saved_point",
                    "motion_type": "MovL",
                    "speed": 30,
                    "point_name": "d435i",
                    "force_guard": self._default_force_guard(),
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
                    "force_guard": self._default_force_guard(),
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
                    "force_guard": self._default_force_guard(),
                },
            }
        elif module_type == "连续相对路径":
            new_module = {
                "type": "relative_path",
                "name": "连续相对路径",
                "params": {
                    "coord_system": "user",
                    "motion_type": "linear",
                    "speed": 30,
                    "acceleration": 30,
                    "cp": 0,
                    "execution_mode": "stop_each",
                    "force_guard": self._default_force_guard(),
                    "segments": [],
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
        elif module_type == "延时":
            new_module = {
                "type": "delay",
                "name": "延时",
                "params": {
                    "wait_mode": "time",
                    "duration_s": 1.0,
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
        elif module_type == "连续相对路径":
            self.param_layout.addWidget(self.relative_path_params, 0, 0)
        elif module_type == "关节旋转":
            self.param_layout.addWidget(self.joint_rotation_params, 0, 0)
        elif module_type == "延时":
            self.param_layout.addWidget(self.delay_params, 0, 0)
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
            target_text_map = {
                "已保存点位": "saved_point",
                "相机识别坐标": "camera_detected",
                "初始位置": "initial_position",
            }
            current_module["params"]["target"] = target_text_map.get(self.linear_target_combo.currentText(), "saved_point")
            current_module["params"]["point_name"] = self.linear_point_combo.currentText()
            current_module["params"]["speed"] = int(self.linear_speed.value())
            current_module["params"]["force_guard"] = self._force_guard_from_controls(
                self.linear_force_guard_enabled,
                self.linear_force_threshold,
            )
            QMessageBox.information(self, "成功", "直线运动参数已更新")
        elif module_type == "圆弧运动" and current_module["type"] == "arc_motion":
            current_module["params"]["center_offset_z"] = self.fa_center_offset_z.value()
            current_module["params"]["sweep_angle"] = self.fa_sweep_angle.value()
            current_module["params"]["arc_direction"] = "cw" if self.fa_arc_direction.currentText() == "顺时针" else "ccw"
            current_module["params"]["speed"] = int(self.fa_speed.value())
            current_module["params"]["force_guard"] = self._force_guard_from_controls(
                self.fa_force_guard_enabled,
                self.fa_force_threshold,
            )
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
            current_module["params"]["force_guard"] = self._force_guard_from_controls(
                self.rel_force_guard_enabled,
                self.rel_force_threshold,
            )
            QMessageBox.information(self, "成功", "相对移动参数已更新")
        elif module_type == "连续相对路径" and current_module["type"] == "relative_path":
            coord_map = {"用户": "user", "工具": "tool", "关节": "joint"}
            motion_map = {"直线": "linear", "关节": "joint"}
            current_module["params"]["coord_system"] = coord_map.get(self.rpath_coord_combo.currentText(), "user")
            current_module["params"]["motion_type"] = motion_map.get(self.rpath_motion_combo.currentText(), "linear")
            current_module["params"]["speed"] = int(self.rpath_speed.value())
            current_module["params"]["acceleration"] = int(self.rpath_accel.value())
            current_module["params"]["cp"] = int(self.rpath_cp.value())
            current_module["params"]["execution_mode"] = self.rpath_exec_mode.currentText()
            current_module["params"]["force_guard"] = self._force_guard_from_controls(
                self.rpath_force_guard_enabled,
                self.rpath_force_threshold,
            )
            self._save_path_segments(self.rpath_seg_table, current_module["params"])
            QMessageBox.information(self, "成功", "连续相对路径参数已更新")
        elif module_type == "关节旋转" and current_module["type"] == "joint_move":
            current_module["params"]["offsets"] = [self.joint_offsets[i].value() for i in range(6)]
            current_module["params"]["acceleration"] = int(self.joint_accel.value())
            current_module["params"]["speed"] = int(self.joint_speed.value())
            QMessageBox.information(self, "成功", "关节旋转参数已更新")
        elif module_type == "相机识别" and current_module["type"] == "camera":
            current_module["params"]["camera_type"] = self.camera_module_combo.currentText()
            QMessageBox.information(self, "成功", "相机识别参数已更新")
        elif module_type == "延时" and current_module["type"] == "delay":
            current_module["params"]["wait_mode"] = (
                "modbus_or_timeout"
                if self.delay_wait_mode.currentIndex() == 1
                else "time"
            )
            current_module["params"]["duration_s"] = float(self.delay_seconds.value())
            current_module["params"].pop("modbus_address", None)
            current_module["params"].pop("modbus_target_value", None)
            QMessageBox.information(self, "成功", "延时参数已更新")
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
            "relative_path": "连续相对路径",
            "joint_move": "关节旋转",
            "visual_servo": "视觉伺服",
            "delay": "延时",
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
            target = module["params"].get("target", "saved_point")
            target_text_map = {
                "saved_point": "已保存点位",
                "camera_detected": "相机识别坐标",
                "initial_position": "初始位置",
            }
            target_text = target_text_map.get(target, "已保存点位")
            idx = self.linear_target_combo.findText(target_text)
            if idx >= 0:
                self.linear_target_combo.setCurrentIndex(idx)
            point_name = module["params"].get("point_name", "")
            idx = self.linear_point_combo.findText(point_name)
            if idx >= 0:
                self.linear_point_combo.setCurrentIndex(idx)
            self.linear_speed.setValue(module["params"].get("speed", 30))
            self._apply_force_guard_to_controls(
                module["params"],
                self.linear_force_guard_enabled,
                self.linear_force_threshold,
            )
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
            self._apply_force_guard_to_controls(
                p,
                self.fa_force_guard_enabled,
                self.fa_force_threshold,
            )
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
            self._apply_force_guard_to_controls(
                p,
                self.rel_force_guard_enabled,
                self.rel_force_threshold,
            )
        elif module["type"] == "relative_path":
            p = module.get("params", {})
            coord_text = {"user": "用户", "tool": "工具", "joint": "关节"}.get(p.get("coord_system", "user"), "用户")
            motion_text = {"linear": "直线", "joint": "关节"}.get(p.get("motion_type", "linear"), "直线")
            idx = self.rpath_coord_combo.findText(coord_text)
            if idx >= 0:
                self.rpath_coord_combo.setCurrentIndex(idx)
            idx = self.rpath_motion_combo.findText(motion_text)
            if idx >= 0:
                self.rpath_motion_combo.setCurrentIndex(idx)
            self.rpath_speed.setValue(float(p.get("speed", 30)))
            self.rpath_accel.setValue(float(p.get("acceleration", 30)))
            self.rpath_cp.setValue(float(p.get("cp", 0)))
            self._apply_force_guard_to_controls(
                p,
                self.rpath_force_guard_enabled,
                self.rpath_force_threshold,
            )
            # Load execution_mode
            exec_mode = p.get("execution_mode", "stop_each")
            idx = self.rpath_exec_mode.findText(exec_mode)
            if idx >= 0:
                self.rpath_exec_mode.setCurrentIndex(idx)
            # Load segments into table
            self.rpath_seg_table.setRowCount(0)
            for seg in p.get("segments", []):
                row = self.rpath_seg_table.rowCount()
                self.rpath_seg_table.insertRow(row)
                # enabled
                self.rpath_seg_table.setItem(row, 0, QTableWidgetItem("✓" if seg.get("enabled", True) else "✗"))
                # name
                self.rpath_seg_table.setItem(row, 1, QTableWidgetItem(seg.get("name", "")))
                # coord_system
                self.rpath_seg_table.setItem(row, 2, QTableWidgetItem(seg.get("coord_system", "继承")))
                # motion_type
                self.rpath_seg_table.setItem(row, 3, QTableWidgetItem(seg.get("motion_type", "继承")))
                # offsets
                for col, key in enumerate(["x", "y", "z", "rx", "ry", "rz"]):
                    self.rpath_seg_table.setItem(row, 4 + col, QTableWidgetItem(str(seg.get(key, 0))))
                # speed
                self.rpath_seg_table.setItem(row, 10, QTableWidgetItem(str(seg["speed"]) if "speed" in seg else "继承"))
                # acceleration
                self.rpath_seg_table.setItem(row, 11, QTableWidgetItem(str(seg["acceleration"]) if "acceleration" in seg else "继承"))
                # cp
                self.rpath_seg_table.setItem(row, 12, QTableWidgetItem(str(seg["cp"]) if "cp" in seg else "继承"))
                # wait_after
                self.rpath_seg_table.setItem(row, 13, QTableWidgetItem("是" if seg.get("wait_after", True) else "否"))
                # note
                self.rpath_seg_table.setItem(row, 14, QTableWidgetItem(seg.get("note", "")))
        elif module["type"] == "delay":
            params = module.get("params", {})
            wait_mode = params.get("wait_mode", "time")
            self.delay_wait_mode.setCurrentIndex(
                1 if wait_mode == "modbus_or_timeout" else 0
            )
            duration_s = float(params.get("duration_s", 1.0))
            self.delay_seconds.setValue(duration_s)

    def save_grasp_flow(self):
        if not self.grasp_flow_modules:
            QMessageBox.warning(self, "警告", "抓取流程为空，无法保存")
            return False

        self._normalize_flow_modules()
        try:
            self.flow_library.get_flow(self.editing_flow_id)[
                "modules"
            ] = self.grasp_flow_modules
            self.flow_library.save()
            self.view_current_grasp_flow()
            QMessageBox.information(
                self,
                "成功",
                f"流程“{self.flow_library.get_flow(self.editing_flow_id)['name']}”已保存",
            )
            return True
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存抓取流程时出错: {e}")
            return False

    def load_grasp_flow(self):
        file_path = get_grasp_flow_file()
        if not os.path.exists(file_path):
            QMessageBox.warning(self, "警告", f"文件不存在: {file_path}")
            return

        try:
            self.flow_library = FlowLibrary.load(file_path)
            self.editing_flow_id = self.flow_library.last_edited_flow_id
            self.grasp_flow_modules = self.flow_library.get_flow(
                self.editing_flow_id
            )["modules"]
            self._normalize_flow_modules()
            self.view_current_grasp_flow()
            self._refresh_flow_selectors()
            QMessageBox.information(self, "成功", f"抓取流程已从: {file_path} 加载")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"加载抓取流程时出错: {e}")

    def run_grasp_flow(self, modbus_triggered=False, flow_id=None):
        del modbus_triggered, flow_id
        return self._show_runtime_ipc_required("运行流程")

    def _start_grasp_flow_snapshot(
        self,
        selected_flow_id,
        selected_flow_name,
        modules,
        modbus_triggered,
    ):
        del selected_flow_id, selected_flow_name, modules, modbus_triggered
        return self._show_runtime_ipc_required("运行流程")

    def _on_flow_log(self, msg):
        self.statusBar().showMessage(msg)

    def _on_flow_module_progress(self, current, total, name):
        self.statusBar().showMessage(f"执行模块 {current}/{total}: {name}")
        idx = current - 1
        if (
            self._active_flow_id == self.editing_flow_id
            and 0 <= idx < len(self.grasp_flow_modules)
        ):
            for i in range(idx):
                self.flow_step_list.set_step_status(i, STATUS_COMPLETED)
            self.flow_step_list.set_step_status(idx, STATUS_RUNNING)

    def _on_flow_finished(self, success):
        del success
        self._flow_started_by_modbus = False
        self._flow_running = False
        self._flow_thread = None
        self.is_paused = False
        if hasattr(self, "_refresh_action_states"):
            self._refresh_action_states()

    def _on_steps_reordered(self, modules):
        self.grasp_flow_modules = modules
        self.flow_library.get_flow(self.editing_flow_id)["modules"] = modules
        self._normalize_flow_modules()

    # -- 连续相对路径 segment table helpers --

    def _add_path_template(self, table, template):
        row = table.rowCount()
        table.insertRow(row)
        # Column order: 启用, 名称, 坐标系, 方式, X, Y, Z, Rx, Ry, Rz, 速度, 加速度, CP, 段后等待, 备注
        table.setItem(row, 0, QTableWidgetItem("✓"))  # enabled
        if template == "x200":
            table.setItem(row, 1, QTableWidgetItem("X+200"))
            values = [200, 0, 0, 0, 0, 0]
        elif template == "y200":
            table.setItem(row, 1, QTableWidgetItem("Y+200"))
            values = [0, 200, 0, 0, 0, 0]
        elif template == "z200":
            table.setItem(row, 1, QTableWidgetItem("Z+200"))
            values = [0, 0, 200, 0, 0, 0]
        elif template == "zy200":
            table.setItem(row, 1, QTableWidgetItem("ZY平面200"))
            values = [0, 141.4, 141.4, 0, 0, 0]
        else:
            table.setItem(row, 1, QTableWidgetItem(f"段{row+1}"))
            values = [0, 0, 0, 0, 0, 0]
        table.setItem(row, 2, QTableWidgetItem("继承"))  # coord_system
        table.setItem(row, 3, QTableWidgetItem("继承"))  # motion_type
        for col, val in enumerate(values):
            table.setItem(row, 4 + col, QTableWidgetItem(str(val)))
        table.setItem(row, 10, QTableWidgetItem("继承"))  # speed
        table.setItem(row, 11, QTableWidgetItem("继承"))  # acceleration
        table.setItem(row, 12, QTableWidgetItem("继承"))  # cp
        table.setItem(row, 13, QTableWidgetItem("是"))  # wait_after
        table.setItem(row, 14, QTableWidgetItem(""))  # note

    def _remove_path_segment(self, table):
        rows = set(item.row() for item in table.selectedItems())
        for row in sorted(rows, reverse=True):
            table.removeRow(row)
        self._renumber_segments(table)

    def _move_path_segment(self, table, direction):
        rows = set(item.row() for item in table.selectedItems())
        if not rows:
            return
        row = min(rows)
        new_row = row + direction
        if new_row < 0 or new_row >= table.rowCount():
            return
        for col in range(table.columnCount()):
            item1 = table.takeItem(row, col)
            item2 = table.takeItem(new_row, col)
            table.setItem(row, col, item2)
            table.setItem(new_row, col, item1)
        self._renumber_segments(table)

    def _renumber_segments(self, table):
        # No longer renumbering column 0 (now "启用" instead of "段号")
        pass

    def _copy_path_segment(self, table):
        rows = set(item.row() for item in table.selectedItems())
        if not rows:
            return
        for row in sorted(rows):
            new_row = row + 1
            table.insertRow(new_row)
            for col in range(table.columnCount()):
                item = table.item(row, col)
                new_item = QTableWidgetItem(item.text() if item else "")
                table.setItem(new_row, col, new_item)
        self._renumber_segments(table)

    def _apply_global_to_segments(self, table):
        """Apply global defaults to selected segments."""
        rows = set(item.row() for item in table.selectedItems())
        for row in rows:
            table.setItem(row, 2, QTableWidgetItem("继承"))  # coord_system
            table.setItem(row, 3, QTableWidgetItem("继承"))  # motion_type
            table.setItem(row, 10, QTableWidgetItem("继承"))  # speed
            table.setItem(row, 11, QTableWidgetItem("继承"))  # acceleration
            table.setItem(row, 12, QTableWidgetItem("继承"))  # cp

    def _zero_selected_segments(self, table):
        """Zero out offsets for selected segments."""
        rows = set(item.row() for item in table.selectedItems())
        for row in rows:
            for col in range(4, 10):  # X, Y, Z, Rx, Ry, Rz columns
                table.setItem(row, col, QTableWidgetItem("0"))

    def _save_path_segments(self, table, module_params):
        segments = []
        for row in range(table.rowCount()):
            seg = {}
            # enabled
            enabled_item = table.item(row, 0)
            seg["enabled"] = enabled_item.text() != "✗" if enabled_item else True
            # name
            name_item = table.item(row, 1)
            if name_item and name_item.text():
                seg["name"] = name_item.text()
            # coord_system (only save if not "继承")
            coord_item = table.item(row, 2)
            if coord_item and coord_item.text() and coord_item.text() != "继承":
                seg["coord_system"] = coord_item.text()
            # motion_type (only save if not "继承")
            motion_item = table.item(row, 3)
            if motion_item and motion_item.text() and motion_item.text() != "继承":
                seg["motion_type"] = motion_item.text()
            # offsets
            for col, key in enumerate(["x", "y", "z", "rx", "ry", "rz"]):
                item = table.item(row, 4 + col)
                try:
                    seg[key] = float(item.text()) if item else 0.0
                except ValueError:
                    seg[key] = 0.0
            # speed (only save if not "继承")
            speed_item = table.item(row, 10)
            if speed_item and speed_item.text() and speed_item.text() != "继承":
                try:
                    seg["speed"] = int(float(speed_item.text()))
                except ValueError:
                    pass
            # acceleration (only save if not "继承")
            accel_item = table.item(row, 11)
            if accel_item and accel_item.text() and accel_item.text() != "继承":
                try:
                    seg["acceleration"] = int(float(accel_item.text()))
                except ValueError:
                    pass
            # cp (only save if not "继承")
            cp_item = table.item(row, 12)
            if cp_item and cp_item.text() and cp_item.text() != "继承":
                try:
                    seg["cp"] = int(float(cp_item.text()))
                except ValueError:
                    pass
            # wait_after
            wait_item = table.item(row, 13)
            seg["wait_after"] = wait_item.text() != "否" if wait_item else True
            # note
            note_item = table.item(row, 14)
            if note_item and note_item.text():
                seg["note"] = note_item.text()
            segments.append(seg)
        module_params["segments"] = segments
