import logging
import threading
import time

import numpy as np
from qt_compat import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QScrollArea, QWidget, QGroupBox, QGridLayout,
    QTimer, Qt, QFont,
)
from dobot_api import DobotApiFeedBack

logger = logging.getLogger(__name__)


class RealTimeFeedbackDialog(QDialog):
    ROBOT_MODE_MAP = {
        1: "初始化", 2: "抱闸松开", 3: "下电", 4: "未使能",
        5: "使能空闲", 6: "拖拽", 7: "运行", 8: "单次运动",
        9: "错误", 10: "暂停", 11: "碰撞"
    }

    def __init__(self, ip: str, port: int = 30004, parent=None):
        super().__init__(parent)
        self.ip = ip
        self.port = port
        self.feedback = None
        self._running = False
        self._latest_data = None
        self._data_lock = threading.Lock()
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_data)

        self.setWindowTitle("实时反馈数据")
        self.setMinimumSize(600, 700)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # 顶部控制区
        control_layout = QHBoxLayout()
        self.status_label = QLabel("未连接")
        self.status_label.setStyleSheet("color: red; font-weight: bold;")
        self.connect_btn = QPushButton("连接")
        self.connect_btn.clicked.connect(self.toggle_connection)
        control_layout.addWidget(self.status_label)
        control_layout.addStretch()
        control_layout.addWidget(self.connect_btn)
        layout.addLayout(control_layout)

        # 滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)

        self.labels = {}

        scroll_layout.addWidget(self.create_group("基本信息", [
            ("robot_mode", "机器人模式: --"),
            ("run_time", "运行时间: --"),
            ("velocity_ratio", "速度比例: --"),
            ("speed_scaling", "速度缩放: --"),
            ("vrobot", "合成速度: --"),
            ("irobot", "合成电流: --"),
        ]))

        scroll_layout.addWidget(self.create_group("关节位置 (QActual)", [
            (f"q_actual_{i}", f"关节{i+1}: --") for i in range(6)
        ]))

        scroll_layout.addWidget(self.create_group("关节速度 (QDActual)", [
            (f"qd_actual_{i}", f"关节{i+1}: --") for i in range(6)
        ]))

        scroll_layout.addWidget(self.create_group("TCP坐标", [
            ("tcp_x", "X: --"),
            ("tcp_y", "Y: --"),
            ("tcp_z", "Z: --"),
            ("tcp_rx", "Rx: --"),
            ("tcp_ry", "Ry: --"),
            ("tcp_rz", "Rz: --"),
        ]))

        scroll_layout.addWidget(self.create_group("TCP速度", [
            ("tcp_speed_x", "X: --"),
            ("tcp_speed_y", "Y: --"),
            ("tcp_speed_z", "Z: --"),
            ("tcp_speed_rx", "Rx: --"),
            ("tcp_speed_ry", "Ry: --"),
            ("tcp_speed_rz", "Rz: --"),
        ]))

        scroll_layout.addWidget(self.create_group("TCP受力", [
            ("tcp_force_x", "Fx: --"),
            ("tcp_force_y", "Fy: --"),
            ("tcp_force_z", "Fz: --"),
            ("tcp_force_mx", "Mx: --"),
            ("tcp_force_my", "My: --"),
            ("tcp_force_mz", "Mz: --"),
        ]))

        scroll_layout.addWidget(self.create_group("关节温度", [
            (f"joint_temp_{i}", f"关节{i+1}: --") for i in range(6)
        ]))

        scroll_layout.addWidget(self.create_group("其他", [
            ("user_coord", "用户坐标系: --"),
            ("tool_coord", "工具坐标系: --"),
            ("speed_scale", "速度比例: --"),
            ("acceleration_scale", "加速度比例: --"),
        ]))

        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)

    def create_group(self, title: str, items: list) -> QGroupBox:
        group = QGroupBox(title)
        layout = QGridLayout(group)
        for i, (key, text) in enumerate(items):
            label = QLabel(text)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.labels[key] = label
            layout.addWidget(label, i // 2, i % 2)
        return group

    def toggle_connection(self):
        if self.feedback is None:
            self.connect()
        else:
            self.disconnect()

    def connect(self):
        try:
            self.feedback = DobotApiFeedBack(self.ip, self.port)
            self._running = True
            threading.Thread(target=self._feed_loop, daemon=True).start()
            self.status_label.setText("已连接")
            self.status_label.setStyleSheet("color: green; font-weight: bold;")
            self.connect_btn.setText("断开")
            self.timer.start(100)
        except Exception as e:
            self.status_label.setText(f"连接失败: {e}")
            self.status_label.setStyleSheet("color: red; font-weight: bold;")

    def disconnect(self):
        self.timer.stop()
        self._running = False
        if self.feedback:
            self.feedback.close()
            self.feedback = None
        self.status_label.setText("未连接")
        self.status_label.setStyleSheet("color: red; font-weight: bold;")
        self.connect_btn.setText("连接")
        self.reset_labels()

    def _feed_loop(self):
        while self._running:
            result = self.feedback.feedBackData()
            if result is not None:
                with self._data_lock:
                    self._latest_data = result
            time.sleep(0.005)

    def reset_labels(self):
        for label in self.labels.values():
            text = label.text().split(":")[0]
            label.setText(f"{text}: --")

    def update_data(self):
        with self._data_lock:
            data = self._latest_data
        if data is None:
            return

        try:
            # 基本信息
            mode = int(data["RobotMode"][0])
            mode_text = self.ROBOT_MODE_MAP.get(mode, f"未知({mode})")
            self.labels["robot_mode"].setText(f"机器人模式: {mode_text}")
            run_time_ms = int(data["RunTime"][0])
            self.labels["run_time"].setText(f"运行时间: {run_time_ms / 1000:.2f}s")
            self.labels["velocity_ratio"].setText(f"速度比例: {int(data['VelocityRatio'][0])}%")
            self.labels["speed_scaling"].setText(f"速度缩放: {float(data['SpeedScaling'][0])*100:.2f}%")
            self.labels["vrobot"].setText(f"合成速度: {float(data['VRobot'][0]):.4f}")
            self.labels["irobot"].setText(f"合成电流: {float(data['IRobot'][0]):.4f}")

            # 关节位置
            q_actual = data["QActual"][0]
            for i in range(6):
                self.labels[f"q_actual_{i}"].setText(f"关节{i+1}: {float(q_actual[i]):.4f}")

            # 关节速度
            qd_actual = data["QDActual"][0]
            for i in range(6):
                self.labels[f"qd_actual_{i}"].setText(f"关节{i+1}: {float(qd_actual[i]):.4f}")

            # TCP坐标
            tcp = data["ToolVectorActual"][0]
            self.labels["tcp_x"].setText(f"X: {float(tcp[0]):.4f}")
            self.labels["tcp_y"].setText(f"Y: {float(tcp[1]):.4f}")
            self.labels["tcp_z"].setText(f"Z: {float(tcp[2]):.4f}")
            self.labels["tcp_rx"].setText(f"Rx: {float(tcp[3]):.4f}")
            self.labels["tcp_ry"].setText(f"Ry: {float(tcp[4]):.4f}")
            self.labels["tcp_rz"].setText(f"Rz: {float(tcp[5]):.4f}")

            # TCP速度
            tcp_speed = data["TCPSpeedActual"][0]
            for i, key in enumerate(["tcp_speed_x", "tcp_speed_y", "tcp_speed_z",
                                     "tcp_speed_rx", "tcp_speed_ry", "tcp_speed_rz"]):
                self.labels[key].setText(f"{['X', 'Y', 'Z', 'Rx', 'Ry', 'Rz'][i]}: {float(tcp_speed[i]):.4f}")

            # TCP受力
            tcp_force = data["ActualTCPForce"][0]
            for i, key in enumerate(["tcp_force_x", "tcp_force_y", "tcp_force_z",
                                     "tcp_force_mx", "tcp_force_my", "tcp_force_mz"]):
                self.labels[key].setText(f"{['Fx', 'Fy', 'Fz', 'Mx', 'My', 'Mz'][i]}: {float(tcp_force[i]):.4f}")

            # 关节温度
            temps = data["MotorTemperatures"][0]
            for i in range(6):
                self.labels[f"joint_temp_{i}"].setText(f"关节{i+1}: {float(temps[i]):.1f}°C")

            # 其他
            self.labels["user_coord"].setText(f"用户坐标系: {float(data['User'][0]):.0f}")
            self.labels["tool_coord"].setText(f"工具坐标系: {float(data['Tool'][0]):.0f}")
            self.labels["speed_scale"].setText(f"速度比例: {int(data['VelocityRatio'][0])}%")
            self.labels["acceleration_scale"].setText(f"加速度比例: {int(data['AccelerationRatio'][0])}%")

        except Exception as e:
            self.status_label.setText(f"更新失败: {e}")

    def closeEvent(self, event):
        self._running = False
        self.disconnect()
        super().closeEvent(event)
