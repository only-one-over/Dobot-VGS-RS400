from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QMessageBox, QInputDialog, QDoubleSpinBox, QCheckBox,
    QComboBox, QTableWidgetItem, QHBoxLayout, QWidget,
)

from config_manager import (
    get_points, get_point, set_point, add_point, delete_point, resolve_point,
    ConfigService,
)


class PointManagementMixin:

    def _get_point_combo_names(self):
        names = list(get_points().keys())
        for default_name in ("d435i", "d405", "current_pos"):
            if default_name not in names:
                names.append(default_name)
        return names

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
        old_row_count = table.rowCount()
        new_row_count = len(points)

        if old_row_count != new_row_count:
            table.setRowCount(new_row_count)

        for row, (name, data) in enumerate(points.items()):
            table.setRowHeight(row, 56)
            coords = data.get("coords", [0]*6)
            is_relative = data.get("is_relative", False)
            relative_to = data.get("relative_to", None)
            is_default = data.get("is_default", False)

            if row < old_row_count:
                existing_name_item = table.item(row, 0)
                existing_name = existing_name_item.text() if existing_name_item else None

                if existing_name == name and not is_default and table.cellWidget(row, 1) is not None:
                    x_spin = table.cellWidget(row, 1)
                    y_spin = table.cellWidget(row, 2)
                    z_spin = table.cellWidget(row, 3)
                    rx_spin = table.cellWidget(row, 4)
                    ry_spin = table.cellWidget(row, 5)
                    rz_spin = table.cellWidget(row, 6)
                    if all([x_spin, y_spin, z_spin, rx_spin, ry_spin, rz_spin]):
                        x_spin.blockSignals(True)
                        y_spin.blockSignals(True)
                        z_spin.blockSignals(True)
                        rx_spin.blockSignals(True)
                        ry_spin.blockSignals(True)
                        rz_spin.blockSignals(True)
                        x_spin.setValue(coords[0])
                        y_spin.setValue(coords[1])
                        z_spin.setValue(coords[2])
                        rx_spin.setValue(coords[3])
                        ry_spin.setValue(coords[4])
                        rz_spin.setValue(coords[5])
                        x_spin.blockSignals(False)
                        y_spin.blockSignals(False)
                        z_spin.blockSignals(False)
                        rx_spin.blockSignals(False)
                        ry_spin.blockSignals(False)
                        rz_spin.blockSignals(False)

                        cb_widget = table.cellWidget(row, 7)
                        if cb_widget:
                            cb = cb_widget.findChild(QCheckBox)
                            if cb:
                                cb.blockSignals(True)
                                cb.setChecked(is_relative)
                                cb.blockSignals(False)

                        combo = table.cellWidget(row, 8)
                        if isinstance(combo, QComboBox):
                            combo.blockSignals(True)
                            combo.clear()
                            combo.addItem("")
                            for other_name in self._get_point_combo_names():
                                if other_name != name:
                                    combo.addItem(other_name)
                            if relative_to:
                                idx = combo.findText(relative_to)
                                if idx >= 0:
                                    combo.setCurrentIndex(idx)
                            else:
                                combo.setCurrentIndex(0)
                            combo.setEnabled(is_relative)
                            combo.blockSignals(False)
                        continue

                if existing_name == name and is_default:
                    for col_idx in range(6):
                        value = coords[col_idx] if col_idx < len(coords) else 0
                        existing_item = table.item(row, col_idx + 1)
                        if existing_item:
                            existing_item.setText(f"{value:.2f}")
                        else:
                            item = QTableWidgetItem(f"{value:.2f}")
                            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                            table.setItem(row, col_idx + 1, item)
                    continue

            name_item = QTableWidgetItem(name)
            if is_default:
                name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row, 0, name_item)

            for col_idx in range(6):
                value = coords[col_idx] if col_idx < len(coords) else 0
                if is_default:
                    item = QTableWidgetItem(f"{value:.2f}")
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    table.setItem(row, col_idx + 1, item)
                else:
                    spin = QDoubleSpinBox()
                    spin.setRange(-9999, 9999)
                    spin.setDecimals(2)
                    spin.setValue(value)
                    spin.setStyleSheet("QDoubleSpinBox { padding: 0px 2px; font-size: 12px; } QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { width: 14px; }")
                    table.setCellWidget(row, col_idx + 1, spin)

            if not is_default:
                cb = QCheckBox()
                cb.setChecked(is_relative)
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
                if not is_relative:
                    combo.setEnabled(False)
                table.setCellWidget(row, 8, combo)

                cb.toggled.connect(lambda checked, r=row, c=combo: c.setEnabled(checked))
                combo.currentTextChanged.connect(lambda text, r=row: self._on_point_relative_to_changed(r, text))
                cb.toggled.connect(lambda checked, r=row: self._on_point_relative_changed(r, checked))

                for col_idx in range(6):
                    spin_widget = table.cellWidget(row, col_idx + 1)
                    if spin_widget:
                        spin_widget.valueChanged.connect(lambda val, r=row: self._on_point_coord_changed(r))

        self.points_table.blockSignals(False)
        self._refresh_point_combos()

    def _on_point_coord_changed(self, row):
        name_item = self.points_table.item(row, 0)
        if name_item is None:
            return
        name = name_item.text()
        coords = []
        for col_idx in range(6):
            spin = self.points_table.cellWidget(row, col_idx + 1)
            if spin:
                coords.append(spin.value())
            else:
                coords.append(0)
        point_data = get_point(name)
        if point_data is None:
            return
        point_data["coords"] = coords
        ConfigService.instance().set_point(name, point_data)

    def _on_point_relative_changed(self, row, checked):
        name_item = self.points_table.item(row, 0)
        if name_item is None:
            return
        name = name_item.text()
        point_data = get_point(name)
        if point_data is None:
            return
        point_data["is_relative"] = checked
        if not checked:
            point_data["relative_to"] = None
        ConfigService.instance().set_point(name, point_data)

    def _on_point_relative_to_changed(self, row, text):
        name_item = self.points_table.item(row, 0)
        if name_item is None:
            return
        name = name_item.text()
        point_data = get_point(name)
        if point_data is None:
            return
        point_data["relative_to"] = text if text else None
        ConfigService.instance().set_point(name, point_data)

    def _refresh_point_combos(self):
        points = get_points()
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
        if hasattr(self, 'fa_center_point_combo'):
            current = self.fa_center_point_combo.currentText()
            self.fa_center_point_combo.blockSignals(True)
            self.fa_center_point_combo.clear()
            self.fa_center_point_combo.addItems(point_names)
            idx = self.fa_center_point_combo.findText(current)
            if idx >= 0:
                self.fa_center_point_combo.setCurrentIndex(idx)
            self.fa_center_point_combo.blockSignals(False)

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
        if not self.controller.is_connected:
            QMessageBox.warning(self, "警告", "机器人未连接，请先连接")
            return
        current_pose = self.controller.get_current_pose()
        if current_pose and len(current_pose) >= 6:
            point_data = get_point("current_pos")
            if point_data is None:
                add_point("current_pos")
                point_data = get_point("current_pos")
            point_data["coords"] = list(current_pose[:6])
            ConfigService.instance().set_point("current_pos", point_data)
            self.refresh_points_table()
            idx = self.linear_point_combo.findText("current_pos")
            if idx >= 0:
                self.linear_point_combo.setCurrentIndex(idx)
        else:
            QMessageBox.critical(self, "错误", "获取当前位置失败")
