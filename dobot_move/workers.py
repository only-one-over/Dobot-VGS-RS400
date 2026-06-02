#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import time
from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger(__name__)


class DeviceInitThread(QThread):
    init_finished = pyqtSignal(object)
    init_progress = pyqtSignal(str)
    init_error = pyqtSignal(str)

    def run(self):
        battery = None

        self.init_progress.emit("正在连接电池监控...")
        try:
            from battery_monitor import BatteryMonitor
            battery = BatteryMonitor()
            battery.connect()
        except Exception as e:
            self.init_error.emit(f"电池监控连接失败: {e}")
            battery = None

        self.init_finished.emit(battery)


class StatusUpdateThread(QThread):
    """状态更新线程 - 基于反馈数据心跳检测连接状态"""
    status_updated = pyqtSignal(str, str)

    def __init__(self, controller, vision_d435i, vision_d405):
        super().__init__()
        self.controller = controller
        self.vision_d435i = vision_d435i
        self.vision_d405 = vision_d405
        self.running = True

    def run(self):
        while self.running:
            if self.controller:
                last_time = self.controller.get_last_feed_time()
                if last_time > 0 and time.time() - last_time < 2:
                    robot_status = "已连接"
                else:
                    robot_status = "未连接"
                    self.controller.is_connected = False
                self.status_updated.emit("robot", robot_status)

            cameras = []
            if self.vision_d435i and hasattr(self.vision_d435i, "camera") and self.vision_d435i.camera:
                cameras.append("D435i")
            if self.vision_d405 and hasattr(self.vision_d405, "camera") and self.vision_d405.camera:
                cameras.append("D405")
            camera_status = "已连接(" + "+".join(cameras) + ")" if cameras else "未连接"
            self.status_updated.emit("camera", camera_status)

            time.sleep(1)

    def stop(self):
        self.running = False
        self.wait()


class MonitorThread(QThread):
    data_updated = pyqtSignal(object)
    error_occurred = pyqtSignal(str)

    def __init__(self, device, read_fn, interval=200):
        super().__init__()
        self._device = device
        self._read_fn = read_fn
        self._interval = interval
        self._running = True

    def run(self):
        while self._running:
            if self._device.is_connected:
                try:
                    result = self._read_fn()
                    if result is not None:
                        self.data_updated.emit(result)
                except Exception as e:
                    self.error_occurred.emit(str(e))
            self.msleep(self._interval)

    def stop(self):
        self._running = False
        self.wait()


class RobotCmdThread(QThread):
    """机器人指令后台执行线程"""
    cmd_finished = pyqtSignal(str, bool)

    def __init__(self, cmd_name, cmd_func, parent=None):
        super().__init__(parent)
        self._cmd_name = cmd_name
        self._cmd_func = cmd_func

    def run(self):
        try:
            result = self._cmd_func()
            self.cmd_finished.emit(self._cmd_name, bool(result))
        except Exception as e:
            logger.error(f"❌ 指令执行异常: {e}")
            self.cmd_finished.emit(self._cmd_name, False)
