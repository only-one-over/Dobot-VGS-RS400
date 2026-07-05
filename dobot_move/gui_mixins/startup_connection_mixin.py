import logging
import time

from ..config_manager import ConfigService, get_runtime_config
from ..flow_library import required_camera_types
from ..gui_connection import DaemonConnectionTask
from ..qt_compat import QMessageBox, QTimer
from ..startup_connection import StartupConnectionState

logger = logging.getLogger(__name__)


class StartupConnectionMixin:
    """Coordinate non-blocking GUI startup connections and fault latching."""

    def _initialize_startup_connections(self):
        runtime = get_runtime_config()
        self._startup_connection_closing = False
        self._startup_connection_generation = 0
        self._device_connect_tasks = {}
        self._device_connect_manual = {}
        self._device_next_attempt = {}
        self._reconnect_requested_devices = set()
        self._startup_connection = StartupConnectionState(
            timeout_s=float(runtime.get("startup_connect_timeout_s", 5.0))
        )
        self._startup_camera_retry_interval_s = float(
            runtime.get("camera_retry_interval_s", 10.0)
        )
        self._startup_retry_timer = QTimer(self)
        self._startup_retry_timer.timeout.connect(self._retry_startup_connections)
        self._startup_retry_timer.start(1000)
        self._startup_deadline_timer = QTimer(self)
        self._startup_deadline_timer.setSingleShot(True)
        self._startup_deadline_timer.timeout.connect(self._on_startup_connection_deadline)

        self.start_modbus_server()
        self._restart_startup_connection_check()

    def _main_flow_required_cameras(self):
        main_flow = self.flow_library.get_main_flow()
        return required_camera_types(main_flow.get("modules", []))

    def _restart_startup_connection_check(self):
        if not hasattr(self, "_startup_connection"):
            return
        self._startup_connection_generation += 1
        required = self._main_flow_required_cameras()
        self._startup_connection.begin(required)
        timeout_ms = max(100, int(self._startup_connection.timeout_s * 1000))
        self._startup_deadline_timer.start(timeout_ms)
        self._request_device_connection("robot")
        for camera_type in required:
            self._request_device_connection(camera_type)
        self._update_startup_connection_state()

    def _device_is_connected(self, device_name):
        if device_name == "robot":
            if (
                not self.controller.is_connected
                or self.controller.dashboard is None
            ):
                return False
            try:
                return self.controller.get_feedback_health().get("health") == "ok"
            except Exception:
                return False
        vision = self.vision_d405 if device_name == "D405" else self.vision_d435i
        return bool(vision is not None and getattr(vision, "is_available", True))

    def _request_device_connection(self, device_name, manual=False):
        if getattr(self, "_startup_connection_closing", False):
            return False
        if self._device_is_connected(device_name):
            return True
        task = self._device_connect_tasks.get(device_name)
        if task is not None and task.is_alive:
            if manual:
                self.statusBar().showMessage(f"{device_name} 正在连接，请稍候")
            return False

        if device_name == "robot":
            ip = self.ip_input.text().strip()
            if not ip:
                if manual:
                    QMessageBox.warning(self, "警告", "请输入机器人IP地址")
                return False
            self.controller.set_robot_ip(ip)
            ConfigService.instance().set_ip("robot_ip", ip)

            def connector():
                if (
                    self.controller.is_connected
                    or self.controller.dashboard is not None
                    or self.controller.feed_thread is not None
                ):
                    self.controller.close_robot_transport()
                connected = self.controller.connect()
                if connected and self._startup_connection_closing:
                    self.controller.disconnect()
                    return None
                return self.controller if connected else None
        else:
            stale_vision = (
                self.vision_d405
                if device_name == "D405"
                else self.vision_d435i
            )
            if stale_vision is not None:
                if device_name == "D405":
                    self.vision_d405 = None
                else:
                    self.vision_d435i = None

            def connector():
                if stale_vision is not None:
                    stale_vision.close()
                vision = self._create_camera_system(device_name)
                if self._startup_connection_closing:
                    vision.close()
                    return None
                return vision

        generation = self._startup_connection_generation
        task = DaemonConnectionTask(device_name, generation, connector)
        task.signals.finished.connect(self._on_device_connection_finished)
        self._device_connect_tasks[device_name] = task
        self._device_connect_manual[device_name] = bool(manual)
        self._device_next_attempt[device_name] = float("inf")
        self.statusBar().showMessage(f"正在连接 {device_name}...")
        if device_name in ("D405", "D435i"):
            self._set_camera_status(device_name, "连接中")
        self._refresh_action_states()
        task.start()
        return True

    def _on_device_connection_finished(
        self,
        device_name,
        generation,
        success,
        payload,
        error,
    ):
        manual = self._device_connect_manual.pop(device_name, False)
        task = self._device_connect_tasks.get(device_name)
        if task is not None and task.generation == generation:
            self._device_connect_tasks.pop(device_name, None)
        self._device_next_attempt[device_name] = (
            time.monotonic() + self._startup_camera_retry_interval_s
        )

        if self._startup_connection_closing:
            if device_name == "robot" and success:
                try:
                    self.controller.disconnect()
                except Exception:
                    logger.exception("断开迟到的机器人连接失败")
            elif payload is not None:
                try:
                    payload.close()
                except Exception:
                    logger.exception("关闭迟到的 %s 相机结果失败", device_name)
            return

        if success and device_name in ("D405", "D435i"):
            if self._device_is_connected(device_name):
                try:
                    payload.close()
                except Exception:
                    logger.exception("关闭重复的 %s 相机实例失败", device_name)
            elif device_name not in self._startup_connection.required_cameras and not manual:
                try:
                    payload.close()
                except Exception:
                    logger.exception("关闭已不再需要的 %s 相机实例失败", device_name)
            else:
                self._adopt_camera_system(device_name, payload)

        if success:
            self.statusBar().showMessage(f"{device_name} 连接成功")
            if manual:
                QMessageBox.information(self, "成功", f"{device_name} 连接成功")
        else:
            if device_name in ("D405", "D435i"):
                self._set_camera_status(device_name, "连接失败")
            message = error or getattr(self.controller, "last_error", "") or "连接失败"
            self.statusBar().showMessage(f"{device_name} 连接失败: {message}")
            if manual:
                QMessageBox.critical(self, "连接失败", f"{device_name}: {message}")

        self._update_startup_connection_state()
        self._refresh_action_states()

    def _update_startup_connection_state(self):
        self._startup_connection.update(
            robot_connected=self._device_is_connected("robot"),
            camera_connected={
                "D435i": self._device_is_connected("D435i"),
                "D405": self._device_is_connected("D405"),
            },
        )

    def _on_startup_connection_deadline(self):
        self._update_startup_connection_state()
        snapshot = self._startup_connection.snapshot()
        if not snapshot["missing_devices"]:
            return
        logger.warning(
            "启动观察窗口结束，缺失设备=%s；后台将继续重连",
            snapshot["missing_devices"],
        )
        self.statusBar().showMessage(
            "启动连接观察结束，后台继续尝试缺失设备，不影响界面和Modbus"
        )

    def _retry_startup_connections(self):
        if self._startup_connection_closing:
            return
        self._update_startup_connection_state()
        now = time.monotonic()
        active_cameras = required_camera_types(
            getattr(self, "_active_flow_modules", [])
        )
        devices = {
            "robot",
            *self._startup_connection.required_cameras,
            *active_cameras,
            *self._reconnect_requested_devices,
        }
        missing = [
            device_name
            for device_name in devices
            if not self._device_is_connected(device_name)
        ]
        if missing and getattr(self, "_flow_running", False):
            self._reconnect_requested_devices.update(missing)
            reason = f"流程运行中设备断线: {', '.join(sorted(missing))}"
            self.controller.record_alarm(
                "流程设备断线",
                "DEVICE_DISCONNECTED",
                "故障",
                reason,
            )
            self.controller.abort_active_flow_for_disconnect(reason)
            return
        for device_name in devices:
            if self._device_is_connected(device_name):
                self._reconnect_requested_devices.discard(device_name)
                continue
            if now >= self._device_next_attempt.get(device_name, 0.0):
                self._request_device_connection(device_name)

    def _request_missing_devices_background(self, missing_devices):
        for device_name in missing_devices:
            if device_name in ("robot", "D435i", "D405"):
                self._reconnect_requested_devices.add(device_name)
                self._device_next_attempt[device_name] = 0.0
                self._request_device_connection(device_name)

    def _shutdown_startup_connections(self):
        self._startup_connection_closing = True
        if hasattr(self, "_startup_retry_timer"):
            self._startup_retry_timer.stop()
        if hasattr(self, "_startup_deadline_timer"):
            self._startup_deadline_timer.stop()
