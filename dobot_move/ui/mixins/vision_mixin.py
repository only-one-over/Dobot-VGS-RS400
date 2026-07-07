import logging
import os

from ...config.config_manager import get_camera_model_path, set_camera_model_path
from ...ui.qt_compat import QFileDialog, QMessageBox
from ...ui.ui_theme import apply_status_visual

logger = logging.getLogger(__name__)


class VisionMixin:
    """Camera configuration UI backed only by Runtime health snapshots."""

    def _refresh_camera_model_controls(self):
        for camera_type in ("D435i", "D405"):
            try:
                model_path = get_camera_model_path(camera_type)
                self.main_control.set_camera_model_path(camera_type, model_path)
            except Exception as exc:
                logger.error("读取 %s 模型配置失败: %s", camera_type, exc)

    def _runtime_camera_connected(self, camera_type):
        snapshot = getattr(self, "_runtime_status", None)
        if snapshot is None:
            return False
        if camera_type == "D405":
            return bool(snapshot.d405_connected)
        return bool(snapshot.d435i_connected)

    def _select_camera_model(self, camera_type):
        if self._runtime_camera_connected(camera_type):
            QMessageBox.warning(
                self,
                "相机正在使用",
                f"{camera_type} 正由 Runtime 使用，请先在生产侧安全停用后再更换模型",
            )
            return False

        current_path = get_camera_model_path(camera_type)
        selected_path, _ = QFileDialog.getOpenFileName(
            self,
            f"选择 {camera_type} ONNX 模型",
            os.path.dirname(current_path),
            "ONNX 模型 (*.onnx)",
        )
        if not selected_path:
            return False
        try:
            normalized = set_camera_model_path(camera_type, selected_path)
            self.main_control.set_camera_model_path(camera_type, normalized)
            QMessageBox.information(
                self,
                "模型已保存",
                f"{camera_type} 模型配置已保存，Runtime 热重载将在后续 IPC 阶段提供\n{normalized}",
            )
            return True
        except Exception as exc:
            logger.exception("保存 %s 模型失败", camera_type)
            QMessageBox.critical(self, "模型配置失败", str(exc))
            return False

    def _set_camera_status(self, camera_type, status):
        label = (
            self.d435i_status_label
            if camera_type == "D435i"
            else self.d405_status_label
        )
        label.setText(f"{camera_type}: {status}")
        apply_status_visual(label, status)

    def connect_d435i(self):
        return self._show_runtime_ipc_required("连接 D435i")

    def disconnect_d435i(self):
        return self._show_runtime_ipc_required("断开 D435i")

    def connect_d405(self):
        return self._show_runtime_ipc_required("连接 D405")

    def disconnect_d405(self):
        return self._show_runtime_ipc_required("断开 D405")

    def open_realtime_feedback(self):
        return self._show_runtime_ipc_required("实时反馈")

    def _start_camera_test(self):
        return self._show_runtime_ipc_required("相机测试")

    def _stop_camera_test(self):
        self.cam_test_start_btn.setEnabled(False)
        self.cam_test_stop_btn.setEnabled(False)
        self.cam_test_status_label.setText("状态: Runtime 只读模式")
        return False

    def _run_camera_self_test(self):
        """Quick camera self-check via Runtime IPC.

        Sends ``test_d435i`` or ``test_d405`` based on the current
        selection in ``cam_test_combo`` and shows the result in the
        status bar.
        """
        camera_type = self.cam_test_combo.currentText() or "D435i"
        command = "test_d405" if camera_type == "D405" else "test_d435i"
        self.statusBar().showMessage(f"相机自检: {camera_type} 检测中...", 3000)
        self._send_runtime_ipc(
            command,
            on_success=lambda data: self._on_camera_self_test_finished(
                camera_type, data
            ),
        )

    def _on_camera_self_test_finished(self, camera_type, data):
        camera_ok = bool(data.get("camera_ok"))
        inference_ok = bool(data.get("inference_ok"))
        if camera_ok and inference_ok:
            self.statusBar().showMessage(
                f"相机自检: {camera_type} 通过", 5000
            )
        else:
            reasons = []
            if not camera_ok:
                reasons.append("相机不可用")
            if not inference_ok:
                reasons.append("推理失败")
            self.statusBar().showMessage(
                f"相机自检: {camera_type} 失败 ({', '.join(reasons)})", 5000
            )
