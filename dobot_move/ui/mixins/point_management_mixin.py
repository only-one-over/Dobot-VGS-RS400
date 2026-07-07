from ...ui.qt_compat import (
    Qt,
    QMessageBox, QInputDialog, QDoubleSpinBox, QCheckBox,
    QComboBox, QTableWidgetItem, QHBoxLayout, QWidget,
)

from ...config.config_manager import (
    get_points, get_point, add_point, delete_point, resolve_point,
    ConfigService,
)


class PointManagementMixin:

    def _get_point_combo_names(self):
        names = list(get_points().keys())
        for default_name in ("initial_point", "d435i", "d405", "current_pos"):
            if default_name not in names:
                names.append(default_name)
        return names

    def _set_point_edit_buttons(self, editing):
        if hasattr(self, "edit_point_btn"):
            self.edit_point_btn.setEnabled(not editing)
        if hasattr(self, "save_point_btn"):
            self.save_point_btn.setEnabled(editing)
        if hasattr(self, "cancel_point_btn"):
            self.cancel_point_btn.setEnabled(editing)
        if hasattr(self, "read_point_btn"):
            self.read_point_btn.setEnabled(editing)
        if hasattr(self, "add_point_btn"):
            self.add_point_btn.setEnabled(not editing)
        if hasattr(self, "delete_point_btn"):
            self.delete_point_btn.setEnabled(not editing)

    def _on_add_point(self):
        name, ok = QInputDialog.getText(self, "添加点位", "点位名称:")
        if ok and name.strip():
            name = name.strip()
            if get_point(name):
                QMessageBox.warning(self, "警告", f"点位 '{name}' 已存在")
                return
            ConfigService.instance().add_point(name)
            self.refresh_points_table()

    def _on_delete_point(self):
        row = self.points_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "警告", "请先选择要删除的点位")
            return
        name_item = self.points_table.item(row, 0)
        if name_item is None:
            return
        name = name_item.text()
        point_data = get_point(name)
        if point_data and point_data.get("is_default", False):
            QMessageBox.warning(self, "警告", f"默认点位 '{name}' 不能删除")
            return
        ConfigService.instance().delete_point(name)
        self.refresh_points_table()

    def refresh_points_table(self):
        self.points_table.blockSignals(True)
        points = get_points()
        table = self.points_table
        table.setRowCount(len(points))

        for row, (name, data) in enumerate(points.items()):
            table.setRowHeight(row, 56)
            coords = list(data.get("coords", [0] * 6))
            is_relative = bool(data.get("is_relative", False))
            relative_to = data.get("relative_to", None)
            editing = row == getattr(self, "_editing_point_row", -1)

            name_item = QTableWidgetItem(name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row, 0, name_item)

            for col_idx in range(6):
                spin = QDoubleSpinBox()
                spin.setRange(-9999, 9999)
                spin.setDecimals(2)
                spin.setValue(coords[col_idx] if col_idx < len(coords) else 0)
                spin.setEnabled(editing)
                spin.setStyleSheet(
                    "QDoubleSpinBox { padding: 0px 2px; font-size: 12px; background: #111827; color: #e2e8f0; border: 1px solid #2a3550; border-radius: 4px; } "
                    "QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { width: 14px; }"
                )
                table.setCellWidget(row, col_idx + 1, spin)

            cb = QCheckBox()
            cb.setChecked(is_relative)
            cb.setEnabled(editing)
            cb_widget = QWidget()
            cb_layout = QHBoxLayout(cb_widget)
            cb_layout.addWidget(cb)
            cb_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cb_layout.setContentsMargins(0, 0, 0, 0)
            table.setCellWidget(row, 7, cb_widget)

            combo = QComboBox()
            combo.addItem("")
            for other_name in self._get_point_combo_names():
                if other_name != name:
                    combo.addItem(other_name)
            if relative_to:
                idx = combo.findText(relative_to)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
            combo.setEnabled(editing and is_relative)
            cb.toggled.connect(lambda checked, c=combo: c.setEnabled(checked))
            table.setCellWidget(row, 8, combo)

        self.points_table.blockSignals(False)
        self._set_point_edit_buttons(getattr(self, "_editing_point_row", -1) >= 0)
        self._refresh_point_combos()

    def _on_edit_point(self):
        row = self.points_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "警告", "请先选择要修改的点位")
            return
        name_item = self.points_table.item(row, 0)
        if name_item is None:
            return
        self._editing_point_row = row
        self._editing_point_name = name_item.text()
        self.refresh_points_table()
        self.points_table.selectRow(row)

    def _on_save_point_edit(self):
        row = getattr(self, "_editing_point_row", -1)
        name = getattr(self, "_editing_point_name", None)
        if row < 0 or not name:
            return

        coords = []
        for col_idx in range(6):
            spin = self.points_table.cellWidget(row, col_idx + 1)
            coords.append(float(spin.value()) if spin else 0.0)

        cb_widget = self.points_table.cellWidget(row, 7)
        cb = cb_widget.findChild(QCheckBox) if cb_widget else None
        combo = self.points_table.cellWidget(row, 8)
        point_data = get_point(name) or {}
        point_data["coords"] = coords
        point_data["is_relative"] = bool(cb.isChecked()) if cb else False
        relative_to = combo.currentText() if point_data["is_relative"] and combo else ""
        point_data["relative_to"] = relative_to or None
        point_data.setdefault("offset", [0, 0, 0, 0, 0, 0])
        point_data.setdefault("is_default", False)
        ConfigService.instance().set_point(name, point_data)

        if name == "initial_point":
            resolved = resolve_point("initial_point")
            if resolved and len(resolved) >= 6:
                self.update_status("photo_position", resolved[:6])

        self._editing_point_row = -1
        self._editing_point_name = None
        self.refresh_points_table()
        QMessageBox.information(self, "成功", f"点位 '{name}' 已保存")

    def _on_cancel_point_edit(self):
        self._editing_point_row = -1
        self._editing_point_name = None
        self.refresh_points_table()

    def _on_read_current_for_selected_point(self):
        name = getattr(self, "_editing_point_name", None)
        if name:
            success, msg = self._runtime_facade.get_point(name)
        else:
            success, msg = self._runtime_facade.get_current_pose()
        self.statusBar().showMessage(msg, 3000)
        return success

    def _on_point_selection_changed(self):
        """Toggle the 'move_to_point' button based on table selection."""
        if not hasattr(self, "move_to_point_btn"):
            return
        has_selection = self.points_table.currentRow() >= 0
        self.move_to_point_btn.setEnabled(has_selection)

    def _on_move_to_point(self):
        """Send ``move_to_point`` IPC command for the selected point.

        Uses default ``motion_type="MovJ"`` and ``speed=10`` per the spec.
        The Runtime enters maintenance mode (if not already) before
        executing the motion.
        """
        row = self.points_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "警告", "请先选择一个点位")
            return
        name_item = self.points_table.item(row, 0)
        if name_item is None:
            return
        point_name = name_item.text()
        self.statusBar().showMessage(f"运动到此点: {point_name} ...", 3000)
        self._send_runtime_ipc(
            "move_to_point",
            {
                "point_name": point_name,
                "motion_type": "MovJ",
                "speed": 10,
            },
            on_success=lambda data: self.statusBar().showMessage(
                f"已运动到点位 {point_name}", 5000
            ),
        )

    def _refresh_point_combos(self):
        point_names = self._get_point_combo_names()
        if hasattr(self, 'linear_point_combo'):
            current = self.linear_point_combo.currentText()
            self.linear_point_combo.blockSignals(True)
            self.linear_point_combo.clear()
            self.linear_point_combo.addItems(point_names)
            idx = self.linear_point_combo.findText(current)
            if idx >= 0:
                self.linear_point_combo.setCurrentIndex(idx)
            self.linear_point_combo.blockSignals(False)

    def _on_linear_point_selected(self, name):
        if not name:
            self.linear_point_preview.setText("")
            return
        self.linear_point_preview.setText(self._format_point_preview(name))

    def _format_point_preview(self, name):
        point = get_point(name)
        if not point:
            return ""
        coords = point.get("coords", [0, 0, 0, 0, 0, 0])
        resolved = resolve_point(name)
        if point.get("is_relative", False):
            base = point.get("relative_to") or "未选择"
            text = (
                f"偏移 X:{coords[0]:.2f} Y:{coords[1]:.2f} Z:{coords[2]:.2f} "
                f"Rx:{coords[3]:.2f} Ry:{coords[4]:.2f} Rz:{coords[5]:.2f}; 基准: {base}"
            )
            if resolved and len(resolved) >= 6:
                text += (
                    f" | 解析 X:{resolved[0]:.2f} Y:{resolved[1]:.2f} Z:{resolved[2]:.2f} "
                    f"Rx:{resolved[3]:.2f} Ry:{resolved[4]:.2f} Rz:{resolved[5]:.2f}"
                )
            return text
        if resolved and len(resolved) >= 6:
            return (
                f"X:{resolved[0]:.2f} Y:{resolved[1]:.2f} Z:{resolved[2]:.2f} "
                f"Rx:{resolved[3]:.2f} Ry:{resolved[4]:.2f} Rz:{resolved[5]:.2f}"
            )
        return ""

    def _on_read_current_for_linear(self):
        success, msg = self._runtime_facade.get_current_pose()
        self.statusBar().showMessage(msg, 3000)
        return success
