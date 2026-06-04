from config_manager import resolve_point


class ForceArcMixin:

    def _on_fa_mode_changed(self, checked):
        self.fa_mode = "point"
        self.fa_center_mode = "point"
        self._refresh_point_combos()

    def _on_fa_center_mode_changed(self, checked):
        self.fa_mode = "point"
        self.fa_center_mode = "point"
        self._refresh_point_combos()

    def _on_fa_point_selected(self, name):
        if not hasattr(self, "fa_point_preview"):
            return
        if not name:
            self.fa_point_preview.setText("")
            return
        if hasattr(self, "_format_point_preview"):
            self.fa_point_preview.setText(self._format_point_preview(name))
            return
        coords = resolve_point(name)
        self.fa_point_preview.setText(
            f"X:{coords[0]:.2f} Y:{coords[1]:.2f} Z:{coords[2]:.2f}"
            if coords and len(coords) >= 3 else ""
        )

    def _on_fa_center_point_selected(self, name):
        if not name:
            self.fa_center_point_preview.setText("")
            return
        if hasattr(self, "_format_point_preview"):
            self.fa_center_point_preview.setText(self._format_point_preview(name))
            return
        coords = resolve_point(name)
        self.fa_center_point_preview.setText(
            f"X:{coords[0]:.2f} Y:{coords[1]:.2f} Z:{coords[2]:.2f}"
            if coords and len(coords) >= 3 else ""
        )
