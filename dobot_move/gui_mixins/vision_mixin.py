from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QMessageBox

try:
    import pyrealsense2 as rs
except ImportError:
    rs = None

_missing_deps = []
try:
    import cv2
except ImportError:
    cv2 = None
    _missing_deps.append(("opencv-python", "pip install opencv-python"))

try:
    import onnxruntime as ort
except ImportError:
    ort = None
    _missing_deps.append(("onnxruntime", "pip install onnxruntime"))

if _missing_deps:
    VISION_AVAILABLE = False
    rs = None
    cv2 = None
    class VisionSystem:
        def __init__(self):
            raise Exception("视觉系统不可用，缺少依赖: " + ", ".join(d[0] for d in _missing_deps))
        def close(self):
            pass
else:
    try:
        from vision_system import VisionSystem
        VISION_AVAILABLE = True
    except Exception:
        VISION_AVAILABLE = False
        class VisionSystem:
            def __init__(self):
                raise Exception("视觉系统不可用")
            def close(self):
                pass


class VisionMixin:

    def _detect_camera_serials(self):
        try:
            ctx = rs.context()
            devices = ctx.query_devices()
            serials = {}
            for dev in devices:
                name = dev.get_info(rs.camera_info.name)
                serial = dev.get_info(rs.camera_info.serial_number)
                print(f"📷 发现设备: {name}, 序列号: {serial}")
                if "D405" in name:
                    serials["D405"] = serial
                elif "D435" in name:
                    serials["D435i"] = serial
                else:
                    serials.setdefault("D435i", serial)
            return serials
        except Exception as e:
            print(f"⚠️ 探测设备失败: {e}")
            return {}

    def connect_d435i(self):
        if not VISION_AVAILABLE:
            QMessageBox.critical(self, "错误", "视觉系统不可用")
            return
        try:
            serials = self._detect_camera_serials()
            serial = serials.get("D435i")
            self.vision_d435i = VisionSystem(camera_type="D435i", serial_number=serial)
            self.d435i_status_label.setText("D435i: 已连接")
            self.d435i_status_label.setStyleSheet("color: green; font-weight: bold;")
            self.d435i_connect_btn.setEnabled(False)
            self.d435i_disconnect_btn.setEnabled(True)
            QMessageBox.information(self, "成功", f"D435i 相机连接成功" + (f" (SN: {serial})" if serial else ""))
        except Exception as e:
            self.d435i_status_label.setText("D435i: 连接失败")
            self.d435i_status_label.setStyleSheet("color: red; font-weight: bold;")
            QMessageBox.critical(self, "错误", f"D435i 相机连接失败: {e}")

    def disconnect_d435i(self):
        try:
            if self.vision_d435i is not None:
                self.vision_d435i.close()
                self.vision_d435i = None
                self.d435i_status_label.setText("D435i: 未连接")
                self.d435i_status_label.setStyleSheet("color: gray;")
                self.d435i_connect_btn.setEnabled(True)
                self.d435i_disconnect_btn.setEnabled(False)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"D435i 相机关闭失败: {e}")

    def connect_d405(self):
        if not VISION_AVAILABLE:
            QMessageBox.critical(self, "错误", "视觉系统不可用")
            return
        try:
            serials = self._detect_camera_serials()
            serial = serials.get("D405")
            self.vision_d405 = VisionSystem(camera_type="D405", serial_number=serial)
            self.d405_status_label.setText("D405: 已连接")
            self.d405_status_label.setStyleSheet("color: green; font-weight: bold;")
            self.d405_connect_btn.setEnabled(False)
            self.d405_disconnect_btn.setEnabled(True)
            QMessageBox.information(self, "成功", f"D405 相机连接成功" + (f" (SN: {serial})" if serial else ""))
        except Exception as e:
            self.d405_status_label.setText("D405: 连接失败")
            self.d405_status_label.setStyleSheet("color: red; font-weight: bold;")
            QMessageBox.critical(self, "错误", f"D405 相机连接失败: {e}")

    def disconnect_d405(self):
        try:
            if self.vision_d405 is not None:
                self.vision_d405.close()
                self.vision_d405 = None
                self.d405_status_label.setText("D405: 未连接")
                self.d405_status_label.setStyleSheet("color: gray;")
                self.d405_connect_btn.setEnabled(True)
                self.d405_disconnect_btn.setEnabled(False)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"D405 相机关闭失败: {e}")

    def open_realtime_feedback(self):
        try:
            from realtime_feedback_dialog import RealTimeFeedbackDialog
            dialog = RealTimeFeedbackDialog(ip=self.robot_ip)
            dialog.exec()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"打开实时反馈失败: {e}")

    def _start_camera_test(self):
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
        from gui_app import CameraTestWorker
        self.cam_test_worker = CameraTestWorker(vision, cam_type, self.controller)
        self.cam_test_worker.result_ready.connect(self._on_camera_test_result)
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
            self.cam_test_status_label.setStyleSheet("font-weight: bold; font-size: 14px; color: red;")
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
            self.cam_test_status_label.setStyleSheet("font-weight: bold; font-size: 14px; color: green;")
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
            self.cam_test_status_label.setStyleSheet("font-weight: bold; font-size: 14px; color: red;")
            self.cam_test_cam_coords.setText("X: ---  Y: ---  Z: ---")
            self.cam_test_end_coords.setText("X: ---  Y: ---  Z: ---")
            self.cam_test_base_coords.setText("X: ---  Y: ---  Z: ---")
            self.cam_test_confidence.setText("---")

    def start_d435i_low_fps(self):
        if self.vision_d435i is None:
            QMessageBox.warning(self, "警告", "D435i 相机未连接")
            return
        if hasattr(self, '_low_fps_worker') and self._low_fps_worker is not None:
            QMessageBox.warning(self, "警告", "低帧率识别已在运行")
            return
        from gui_app import D435iLowFpsWorker
        self._low_fps_worker = D435iLowFpsWorker(self.vision_d435i, self.controller)
        self._low_fps_worker.low_fps_result.connect(self._on_low_fps_result)
        self._low_fps_worker.start()
        self.d435i_low_fps_start_btn.setEnabled(False)
        self.d435i_low_fps_stop_btn.setEnabled(True)
        self.d435i_low_fps_status.setText("状态: 运行中")
        self.d435i_low_fps_status.setStyleSheet("color: green; font-weight: bold;")

    def stop_d435i_low_fps(self):
        if hasattr(self, '_low_fps_worker') and self._low_fps_worker is not None:
            self._low_fps_worker.stop()
            self._low_fps_worker.wait(3000)
            self._low_fps_worker = None
        self.d435i_low_fps_start_btn.setEnabled(True)
        self.d435i_low_fps_stop_btn.setEnabled(False)
        self.d435i_low_fps_status.setText("状态: 已停止")
        self.d435i_low_fps_status.setStyleSheet("color: gray;")

    def _on_low_fps_result(self, result):
        status = result.get('status', 'unknown')
        if status == 'no_frame':
            return
        if status == 'error':
            self.d435i_low_fps_status.setText(f"状态: 错误 - {result.get('error_msg', '')}")
            self.d435i_low_fps_status.setStyleSheet("color: red; font-weight: bold;")
            return

        object_position = result.get('object_position')
        if object_position:
            cam_coords = result.get('cam_coords', [])
            conf = result.get('confidence', 0.0)
            self.d435i_low_fps_status.setText(f"状态: 检测到物体 (置信度={conf:.2f})")
            self.d435i_low_fps_status.setStyleSheet("color: green; font-weight: bold;")
            if len(cam_coords) >= 3:
                self.d435i_low_fps_cam_coords.setText(f"X: {cam_coords[0]:.1f}  Y: {cam_coords[1]:.1f}  Z: {cam_coords[2]:.1f}")
            end_coords = result.get('end_coords')
            if end_coords is not None:
                self.d435i_low_fps_end_coords.setText(f"X: {end_coords[0]:.1f}  Y: {end_coords[1]:.1f}  Z: {end_coords[2]:.1f}")
            else:
                self.d435i_low_fps_end_coords.setText("X: ---  Y: ---  Z: ---")
            base_coords = result.get('base_coords')
            if base_coords is not None:
                self.d435i_low_fps_base_coords.setText(f"X: {base_coords[0]:.1f}  Y: {base_coords[1]:.1f}  Z: {base_coords[2]:.1f}")
            else:
                self.d435i_low_fps_base_coords.setText("X: ---  Y: ---  Z: ---")
        else:
            self.d435i_low_fps_status.setText("状态: 未检测到物体")
            self.d435i_low_fps_status.setStyleSheet("color: red; font-weight: bold;")
            self.d435i_low_fps_cam_coords.setText("X: ---  Y: ---  Z: ---")
            self.d435i_low_fps_end_coords.setText("X: ---  Y: ---  Z: ---")
            self.d435i_low_fps_base_coords.setText("X: ---  Y: ---  Z: ---")
