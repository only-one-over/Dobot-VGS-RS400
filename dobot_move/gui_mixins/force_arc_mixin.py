from config_manager import resolve_point


class ForceArcMixin:

    def _on_fa_mode_changed(self, checked):
        if self.fa_coords_radio.isChecked():
            self.fa_mode = "coords"
            self.fa_center_widget.show()
            self.fa_point_combo.hide()
            self.fa_point_preview.hide()
            self.fa_point_preview.setText("")
        else:
            self.fa_mode = "point"
            self.fa_center_widget.hide()
            self._refresh_point_combos()
            self.fa_point_combo.show()
            self.fa_point_preview.show()

    def _on_fa_center_mode_changed(self, checked):
        if self.fa_center_coords_radio.isChecked():
            self.fa_center_mode = "coords"
            self.fa_center_widget.show()
            self.fa_center_point_combo.hide()
            self.fa_center_point_preview.hide()
            self.fa_center_point_preview.setText("")
        else:
            self.fa_center_mode = "point"
            self.fa_center_widget.hide()
            self._refresh_point_combos()
            self.fa_center_point_combo.show()
            self.fa_center_point_preview.show()

    def _on_fa_point_selected(self, name):
        if not name:
            self.fa_point_preview.setText("")
            return
        coords = resolve_point(name)
        if coords and len(coords) >= 6:
            self.fa_point_preview.setText(
                f"X:{coords[0]:.2f} Y:{coords[1]:.2f} Z:{coords[2]:.2f} "
                f"Rx:{coords[3]:.2f} Ry:{coords[4]:.2f} Rz:{coords[5]:.2f}"
            )
        else:
            self.fa_point_preview.setText("")

    def _on_fa_center_point_selected(self, name):
        if not name:
            self.fa_center_point_preview.setText("")
            return
        coords = resolve_point(name)
        if coords and len(coords) >= 6:
            self.fa_center_point_preview.setText(
                f"X:{coords[0]:.2f} Y:{coords[1]:.2f} Z:{coords[2]:.2f} "
                f"Rx:{coords[3]:.2f} Ry:{coords[4]:.2f} Rz:{coords[5]:.2f}"
            )
        else:
            self.fa_center_point_preview.setText("")
