import logging
import os

from ..config_manager import get_camera_model_path, set_camera_model_path
from ..qt_compat import QFileDialog, QMessageBox, QPixmap

from ..ui_theme import apply_status_visual

_logger = logging.getLogger(__name__)

try:
    import pyrealsense2 as rs
except ImportError:
    rs = None

try:
    from ..vision_system import VisionSystem as _VisionSystem
    VISION_AVAILABLE = True
    VisionSystem = _VisionSystem
except ImportError:
    _logger.warning("VisionSystem 不可用，视觉依赖未安装")
    VISION_AVAILABLE = False

    class VisionSystem:
        """VisionSystem stub when vision dependencies are not available."""
        def __init__(self, *args, **kwargs):
            raise Exception("视觉系统不可用，缺少依赖")
        def close(self):
            pass


class VisionMixin:

    def _refresh_camera_model_controls(self):
        for camera_type in ("D435i", "D405"):
            try:
                model_path = get_camera_model_path(camera_type)
                self.main_control.set_camera_model_path(camera_type, model_path)
            except Exception as exc:
                _logger.error("读取 %s 模型配置失败: %s", camera_type, exc)

    def _select_camera_model(self, camera_type):
        vision = self.vision_d435i if camera_type == "D435i" else self.vision_d405
        if vision is not None:
            QMessageBox.warning(self, "相机已连接", "请先断开相机，再更换模型")
            return

        current_path = get_camera_model_path(camera_type)
        selected_path, _ = QFileDialog.getOpenFileName(
            self,
            f"选择 {camera_type} ONNX 模型",
            os.path.dirname(current_path),
            "ONNX 模型 (*.onnx)",
        )
        if not selected_path:
            return
        try:
            normalized = set_camera_model_path(camera_type, selected_path)
            self.main_control.set_camera_model_path(camera_type, normalized)
            QMessageBox.information(
                self,
                "模型已保存",
                f"{camera_type} 将在下次连接时使用模型:\n{normalized}",
            )
        except Exception as exc:
            _logger.exception("保存 %s 模型失败", camera_type)
            QMessageBox.critical(self, "模型配置失败", str(exc))

    def _set_camera_status(self, camera_type, status):
        label = self.d435i_status_label if camera_type == "D435i" else self.d405_status_label
        label.setText(f"{camera_type}: {status}")
        apply_status_visual(label, status)

    def _stop_camera_workers_for(self, camera_type):
        if (
            hasattr(self, 'cam_test_worker')
            and self.cam_test_worker is not None
            and getattr(self.cam_test_worker, "cam_type", None) == camera_type
        ):
            self._stop_camera_test()

    def _detect_camera_serials(self):
        try:
            ctx = rs.context()
            devices = ctx.query_devices()
            serials = {}
            for dev in devices:
                name = dev.get_info(rs.camera_info.name)
                serial = dev.get_info(rs.camera_info.serial_number)
                _logger.info("发现设备: %s, 序列号: %s", name, serial)
                if "D405" in name:
                    serials["D405"] = serial
                elif "D435" in name:
                    serials["D435i"] = serial
                else:
                    serials.setdefault("D435i", serial)
            return serials
        except Exception as e:
            _logger.warning("探测设备失败: %s", e)
            return {}

    def _create_camera_system(self, camera_type):
        if not VISION_AVAILABLE:
            raise RuntimeError("视觉系统不可用")
        serial = self._detect_camera_serials().get(camera_type)
        vision = None
        try:
            vision = VisionSystem(camera_type=camera_type, serial_number=serial)
            depth_frame, color_frame = vision.capture_frames()
            if depth_frame is None or color_frame is None:
                raise RuntimeError(f"{camera_type} 相机抓帧预检失败")
            return vision
        except Exception:
            if vision is not None:
                try:
                    vision.close()
                except Exception:
                    _logger.exception("释放连接失败的 %s 相机资源时出错", camera_type)
            raise

    def _adopt_camera_system(self, camera_type, vision):
        if camera_type == "D435i":
            self.vision_d435i = vision
            connect_btn = self.d435i_connect_btn
            disconnect_btn = self.d435i_disconnect_btn
        else:
            self.vision_d405 = vision
            connect_btn = self.d405_connect_btn
            disconnect_btn = self.d405_disconnect_btn
        self._set_camera_status(camera_type, "已连接")
        connect_btn.setEnabled(False)
        disconnect_btn.setEnabled(True)
        self.main_control.set_camera_model_selection_enabled(camera_type, False)
        self.update_gpu_status(vision.inference_provider)
        if hasattr(self, "_refresh_action_states"):
            self._refresh_action_states()

    def connect_d435i(self):
        self._request_device_connection("D435i", manual=True)

    def disconnect_d435i(self):
        try:
            if self.vision_d435i is not None:
                self._stop_camera_workers_for("D435i")
                self.vision_d435i.close()
                self.vision_d435i = None
                self._set_camera_status("D435i", "未连接")
                self.update_gpu_status(None)
                self.d435i_connect_btn.setEnabled(True)
                self.d435i_disconnect_btn.setEnabled(False)
                self.main_control.set_camera_model_selection_enabled("D435i", True)
                if hasattr(self, "_refresh_action_states"):
                    self._refresh_action_states()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"D435i 相机关闭失败: {e}")

    def connect_d405(self):
        self._request_device_connection("D405", manual=True)

    def disconnect_d405(self):
        try:
            if self.vision_d405 is not None:
                self._stop_camera_workers_for("D405")
                self.vision_d405.close()
                self.vision_d405 = None
                self._set_camera_status("D405", "未连接")
                self.update_gpu_status(None)
                self.d405_connect_btn.setEnabled(True)
                self.d405_disconnect_btn.setEnabled(False)
                self.main_control.set_camera_model_selection_enabled("D405", True)
                if hasattr(self, "_refresh_action_states"):
                    self._refresh_action_states()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"D405 相机关闭失败: {e}")

    def open_realtime_feedback(self):
        try:
            from ..realtime_feedback_dialog import RealTimeFeedbackDialog
            dialog = RealTimeFeedbackDialog(ip=self.robot_ip)
            dialog.exec()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"打开实时反馈失败: {e}")

    def _start_camera_test(self):
        if hasattr(self, 'cam_test_worker') and self.cam_test_worker is not None:
            QMessageBox.warning(self, "警告", "相机测试已在运行")
            return
        cam_type = self.cam_test_combo.currentText()
        if cam_type == "D435i" and self.vision_d435i is None:
            QMessageBox.warning(self, "警告", "D435i 相机未连接")
            return
        if cam_type == "D405" and self.vision_d405 is None:
            QMessageBox.warning(self, "警告", "D405 相机未连接")
            return
        self.cam_test_d405_group.setVisible(cam_type == "D405")
        self.cam_test_start_btn.setEnabled(False)
        self.cam_test_stop_btn.setEnabled(True)
        vision = self.vision_d405 if cam_type == "D405" else self.vision_d435i
        from ..workers import CameraTestWorker
        self.cam_test_worker = CameraTestWorker(vision, cam_type, self.controller)
        self.cam_test_worker.result_ready.connect(self._on_camera_test_result)
        self.cam_test_worker.finished.connect(self.cam_test_worker.deleteLater)
        self.cam_test_worker.start()

    def _stop_camera_test(self):
        if hasattr(self, 'cam_test_worker') and self.cam_test_worker is not None:
            self.cam_test_worker.stop()
            self.cam_test_worker.wait(3000)
            self.cam_test_worker = None
        self.cam_test_start_btn.setEnabled(True)
        self.cam_test_stop_btn.setEnabled(False)
        self.cam_test_status_label.setText("状态: 已停止")

    def _on_camera_test_result(self, result):
        status = result.get('status', 'unknown')

        if status == 'no_frame':
            self.cam_test_status_label.setText("状态: 无法捕获帧")
            return

        if status == 'error':
            self.cam_test_status_label.setText(f"状态: 错误 - {result.get('error_msg', '')}")
            self.cam_test_status_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #fca5a5;")
            return

        q_img = result.get('q_image')
        if q_img:
            self.cam_test_image_label.setPixmap(QPixmap.fromImage(q_img))

        object_position = result.get('object_position')
        cam_type = result.get('cam_type', 'D435i')

        if object_position:
            cam_coords = result.get('cam_coords', [])
            conf = result.get('confidence', 0.0)
            source = result.get('source', 'unknown')
            self.cam_test_status_label.setText(f"状态: 检测到物体 ({source})")
            self.cam_test_status_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #86efac;")
            if len(cam_coords) >= 3:
                self.cam_test_cam_coords.setText(f"X: {cam_coords[0]:.1f}  Y: {cam_coords[1]:.1f}  Z: {cam_coords[2]:.1f}")
            self.cam_test_confidence.setText(f"{conf:.3f}")

            end_coords = result.get('end_coords')
            if end_coords is not None:
                self.cam_test_end_coords.setText(f"X: {end_coords[0]:.1f}  Y: {end_coords[1]:.1f}  Z: {end_coords[2]:.1f}")
            else:
                self.cam_test_end_coords.setText("X: ---  Y: ---  Z: --- (机器人未连接)")

            base_coords = result.get('base_coords')
            if base_coords is not None:
                self.cam_test_base_coords.setText(f"X: {base_coords[0]:.1f}  Y: {base_coords[1]:.1f}  Z: {base_coords[2]:.1f}")
            else:
                self.cam_test_base_coords.setText("X: ---  Y: ---  Z: --- (机器人未连接)")

        else:
            self.cam_test_status_label.setText("状态: 未检测到物体")
            self.cam_test_status_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #fca5a5;")
            self.cam_test_cam_coords.setText("X: ---  Y: ---  Z: ---")
            self.cam_test_end_coords.setText("X: ---  Y: ---  Z: ---")
            self.cam_test_base_coords.setText("X: ---  Y: ---  Z: ---")
            self.cam_test_confidence.setText("---")
