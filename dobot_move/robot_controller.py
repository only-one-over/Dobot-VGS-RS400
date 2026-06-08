#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
越疆机器人控制模块
"""

import time
import re
import socket
import logging
from contextlib import contextmanager
from modbus_server import DobotModbusServer
from modbus_client import DobotModbusClient
import math
import threading
import numpy as np
from dobot_api import DobotApiDashboard, DobotApiFeedBack
from config_manager import get_initial_point, get_performance_config
from alarm_history import AlarmHistory

logger = logging.getLogger(__name__)


class DobotController:
    """机器人控制器"""

    def __init__(self, robot_ip="192.168.5.1"):
        self.robot_ip = robot_ip
        self.dashboard = None
        self.is_connected = False
        self.is_enabled = False
        self.last_error = ""

        self.pose_pattern = re.compile(r'{([^}]+)}')

        self.initial_pose = get_initial_point()
        logger.info(f"初始位置: {self.initial_pose}")

        self.feed_four = None
        self.feed_lock = threading.Lock()
        self.feed_data = None
        self.feed_thread = None
        self.latest_pose = None
        self.latest_pose_time = 0.0
        self.latest_robot_mode = None
        self.latest_robot_mode_time = 0.0
        self.latest_feed_time = 0.0

        self.position_tolerance = 10.0
        self.safe_speed = 30
        self.current_speed = 30
        self._last_speed_factor = None
        self.last_feed_time = 0
        self._last_robot_mode_dashboard_query_time = 0.0
        self._last_robot_mode_dashboard_query_value = None
        self._feed_error_count = 0
        self.clear_error_retry_count = 0
        self.modbus_server = None
        self.modbus_client = None
        self._modbus_thread = None
        self._modbus_event = threading.Event()
        self._modbus_cycle_count = 0
        self._modbus_last_duration = 0.0
        self.auto_hook_mode = False
        self._cart_status_data = {}
        self._modbus_status_override = None
        self._last_fault_code = 0
        self._robot_alarm_recorded = False
        self.software_emergency_active = False
        self.alarm_history = AlarmHistory()

        self.force_monitor_enabled = False
        self.force_threshold = 30.0
        self.force_monitor_thread = None
        self._force_monitor_running = False
        self.force_trigger_callback = None
        self.last_force_value = 0.0
        self.force_triggered = False

        self._motion_owner = None
        self._motion_lock = threading.Lock()

    def record_alarm(self, source, code="", level="报警", description="", solution="", raw=""):
        try:
            return self.alarm_history.add(source, code, level, description, solution, raw)
        except Exception as e:
            logger.error(f"记录报警失败: {e}")
            return None

    def _read_robot_error_raw(self):
        if not self.dashboard:
            return "", 0
        try:
            raw = self.dashboard.GetErrorID()
            body = re.search(r'\{([^}]*)\}', str(raw))
            nums = re.findall(r'-?\d+', body.group(1) if body else str(raw))
            code = next((int(n) for n in nums if int(n) != 0), 0)
            return raw, code
        except Exception as e:
            return f"GetErrorID failed: {e}", 0

    @contextmanager
    def _temp_timeout(self, seconds):
        old_timeout = self.dashboard.socket_dobot.gettimeout()
        self.dashboard.socket_dobot.settimeout(seconds)
        try:
            yield
        finally:
            self.dashboard.socket_dobot.settimeout(old_timeout)

    def _describe_error_code(self, code):
        error_map = {
            -1: "参数错误",
            -2: "机器人处于错误状态",
            -3: "机器人处于运行状态",
            -4: "机器人处于暂停状态",
            -5: "机器人处于急停状态",
            -6: "机器人处于碰撞保护状态",
            -7: "机器人处于脚本暂停状态",
        }
        return error_map.get(code, "未知错误")

    def parse_response_code(self, response):
        """解析响应码"""
        if not response:
            return None
        response = response.strip()
        try:
            parts = response.split(',', 1)
            if len(parts) >= 1:
                code_str = parts[0].strip()
                match = re.search(r'(-?\d+)', code_str)
                if match:
                    return int(match.group(1))
        except Exception as e:
            logger.error(f" 解析响应码失败: {e}")
        return None

    def parse_robot_mode(self, response):
        """专门解析RobotMode响应，提取花括号中的状态码"""
        if not response:
            return None

        try:
            match = re.search(r'{(\d+)}', response)
            if match:
                mode = int(match.group(1))
                return mode
        except Exception as e:
            logger.error(f" 解析机器人模式失败: {e}")

        return self.parse_response_code(response)

    def parse_pose_response(self, response):
        """解析GetPose响应"""
        try:
            match = self.pose_pattern.search(response)
            if match:
                pose_str = match.group(1)
                pose_values = [float(x.strip()) for x in pose_str.split(',')]

                if len(pose_values) == 6:
                    return pose_values
            parts = response.split(',')
            if len(parts) >= 6:
                nums = []
                for part in parts:
                    match = re.search(r'(-?\d+\.?\d*)', part)
                    if match:
                        nums.append(float(match.group(1)))
                if len(nums) >= 6:
                    return nums[:6]
            return None
        except Exception as e:
            logger.error(f" 解析坐标失败: {e}")
            return None

    def validate_ip(self, ip):
        """验证IP地址格式是否正确"""
        ip_pattern = r'^((25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$'
        if re.match(ip_pattern, ip):
            return True
        return False

    def test_connection(self, port=29999, timeout=2):
        """测试与机器人的网络连接"""
        if not self.validate_ip(self.robot_ip):
            self.last_error = f"无效的IP地址格式: {self.robot_ip}"
            logger.error(f" [测试] {self.last_error}")
            return False, self.last_error

        try:
            test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            test_socket.settimeout(timeout)
            result = test_socket.connect_ex((self.robot_ip, port))
            test_socket.close()

            if result == 0:
                self.last_error = ""
                logger.info(f" [测试] 网络连接测试成功: {self.robot_ip}:{port}")
                return True, "网络连接正常"
            elif result == 10061:
                self.last_error = f"端口 {port} 拒绝连接，请检查机器人TCP/IP控制模式是否启用"
                logger.error(f" [测试] {self.last_error}")
                return False, self.last_error
            elif result == 10060:
                self.last_error = f"连接超时({timeout}秒)，请检查网络连接和IP地址"
                logger.error(f" [测试] {self.last_error}")
                return False, self.last_error
            elif result == 10051:
                self.last_error = f"网络不可达，请检查电脑和机器人是否在同一网段"
                logger.error(f" [测试] {self.last_error}")
                return False, self.last_error
            else:
                self.last_error = f"连接失败，错误码: {result}"
                logger.error(f" [测试] {self.last_error}")
                return False, self.last_error
        except Exception as e:
            self.last_error = f"网络测试异常: {str(e)}"
            logger.error(f" [测试] {self.last_error}")
            return False, self.last_error

    def _validate_robot_mode(self, response):
        """验证RobotMode响应是否有效"""
        try:
            match = re.search(r'\{(\d+)\}', response)
            if match:
                mode = int(match.group(1))
                if 1 <= mode <= 11:
                    return True, mode, f"有效模式: {mode}"
                else:
                    return False, None, f"无效模式值: {mode} (应在1-11范围内)"
            else:
                parts = response.strip().split(',')
                if len(parts) >= 2:
                    mode_str = parts[1].strip('{}')
                    if mode_str.isdigit():
                        mode = int(mode_str)
                        if 1 <= mode <= 11:
                            return True, mode, f"有效模式: {mode}"
                        else:
                            return False, None, f"无效模式值: {mode} (应在1-11范围内)"
                return False, None, f"无法解析RobotMode响应: {response}"
        except Exception as e:
            return False, None, f"解析RobotMode响应失败: {str(e)}"

    def _validate_get_angle(self, response):
        """验证GetAngle响应是否有效"""
        try:
            match = re.search(r'\{([^}]+)\}', response)
            if match:
                angles_str = match.group(1)
                angles = [float(x.strip()) for x in angles_str.split(',')]
                if len(angles) == 6:
                    valid = True
                    for angle in angles:
                        if not (-360 <= angle <= 360):
                            valid = False
                            break
                    if valid:
                        return True, angles, "关节角度有效"
                    else:
                        return False, None, f"关节角度超出合理范围: {angles}"
                else:
                    return False, None, f"关节角度数量不正确: {len(angles)} (应为6个)"
            return False, None, f"无法解析GetAngle响应: {response}"
        except Exception as e:
            return False, None, f"解析GetAngle响应失败: {str(e)}"

    def connect(self):
        """连接机器人"""
        logger.info(f"\n===== [{time.strftime('%Y-%m-%d %H:%M:%S')}] 开始连接机器人 =====")
        logger.info(f" [连接] 目标IP: {self.robot_ip}")
        logger.info(f" [连接] 目标端口: 29999")

        test_ok, test_msg = self.test_connection()
        if not test_ok:
            logger.error(f" [连接] 网络测试失败: {test_msg}")
            logger.error(f"===== [{time.strftime('%Y-%m-%d %H:%M:%S')}] 连接失败 =====")
            return False

        try:
            logger.info(" [连接] 创建Dashboard连接...")
            self.dashboard = DobotApiDashboard(self.robot_ip, 29999)

            if self.dashboard.socket_dobot == 0:
                self.last_error = "Socket连接失败，可能是网络问题或端口未开放"
                logger.error(f" [连接] {self.last_error}")
                self.dashboard = None
                logger.error(f"===== [{time.strftime('%Y-%m-%d %H:%M:%S')}] 连接失败 =====")
                return False

            with self._temp_timeout(3):
                logger.info(" [连接] 发送RobotMode指令验证连接...")
                response = self.dashboard.RobotMode()
                logger.debug(f" [连接] RobotMode响应: {response}")

                valid, mode, msg = self._validate_robot_mode(response)
                if not valid:
                    self.last_error = f"RobotMode验证失败: {msg}"
                    logger.error(f" [连接] {self.last_error}")
                    self.dashboard.close()
                    self.dashboard = None
                    logger.error(f"===== [{time.strftime('%Y-%m-%d %H:%M:%S')}] 连接失败 =====")
                    return False
                logger.info(f" [连接] RobotMode验证通过，当前模式: {mode}")

                logger.info(" [连接] 发送GetAngle指令验证关节数据...")
                response = self.dashboard.GetAngle()
                logger.debug(f" [连接] GetAngle响应: {response}")

                valid, angles, msg = self._validate_get_angle(response)
                if not valid:
                    self.last_error = f"GetAngle验证失败: {msg}"
                    logger.error(f" [连接] {self.last_error}")
                    self.dashboard.close()
                    self.dashboard = None
                    logger.error(f"===== [{time.strftime('%Y-%m-%d %H:%M:%S')}] 连接失败 =====")
                    return False
                logger.info(f" [连接] GetAngle验证通过，关节角度: {angles[:3]}...")

            logger.info(" [连接] 测试实时反馈端口30004...")
            feedback_port_ok, feedback_msg = self.test_connection(30004, timeout=2)
            if not feedback_port_ok:
                logger.warning(f" [连接] 警告: 反馈端口30004测试失败: {feedback_msg}")
                logger.warning(" [连接] 将尝试继续连接，但实时反馈功能可能受限")

            logger.info(" [连接] 启动实时反馈线程...")
            self.start_feedback()

            logger.info(" [连接] 等待实时反馈数据...")
            feedback_timeout = 10
            feedback_retries = 3
            feed_ok = False

            for retry in range(feedback_retries):
                start_time = time.time()
                while time.time() - start_time < feedback_timeout:
                    with self.feed_lock:
                        if self.feed_data is not None:
                            logger.info(" [连接] 实时反馈数据接收成功")
                            feed_ok = True
                            break
                    time.sleep(0.1)
                if feed_ok:
                    break
                logger.warning(f" [连接] 反馈数据等待超时，重试 {retry+1}/{feedback_retries}...")
                self.stop_feedback()
                time.sleep(0.5)
                self.start_feedback()

            if not feed_ok:
                self.last_error = f"实时反馈超时({feedback_timeout*feedback_retries}秒)，未收到反馈数据"
                logger.error(f" [连接] {self.last_error}")
                self.stop_feedback()
                self.dashboard.close()
                self.dashboard = None
                logger.error(f"===== [{time.strftime('%Y-%m-%d %H:%M:%S')}] 连接失败 =====")
                return False

            self.is_connected = True
            self.last_error = ""

            logger.info(f"===== [{time.strftime('%Y-%m-%d %H:%M:%S')}] 机器人连接成功！ =====")
            return True

        except socket.timeout:
            self.last_error = "连接超时(3秒)，请检查网络稳定性和机器人状态"
            logger.error(f" [连接] {self.last_error}")
            if self.dashboard:
                self.dashboard.close()
            self.dashboard = None
            logger.error(f"===== [{time.strftime('%Y-%m-%d %H:%M:%S')}] 连接失败 =====")
            return False
        except ConnectionRefusedError:
            self.last_error = "连接被拒绝，请确保机器人已启用TCP/IP控制模式"
            logger.error(f" [连接] {self.last_error}")
            if self.dashboard:
                self.dashboard.close()
            self.dashboard = None
            logger.error(f"===== [{time.strftime('%Y-%m-%d %H:%M:%S')}] 连接失败 =====")
            return False
        except OSError as e:
            error_codes = {
                10061: "端口拒绝连接，请检查机器人TCP/IP控制模式是否启用",
                10060: "连接超时，请检查网络连接和IP地址",
                10051: "网络不可达，请检查电脑和机器人是否在同一网段",
                10054: "连接被重置，机器人可能已断开或重启"
            }
            self.last_error = error_codes.get(e.errno, f"网络错误: {str(e)}")
            logger.error(f" [连接] {self.last_error}")
            if self.dashboard:
                self.dashboard.close()
            self.dashboard = None
            logger.error(f"===== [{time.strftime('%Y-%m-%d %H:%M:%S')}] 连接失败 =====")
            return False
        except Exception as e:
            self.last_error = f"连接异常: {str(e)}"
            logger.error(f" [连接] {self.last_error}")
            if self.dashboard:
                self.dashboard.close()
            self.dashboard = None
            logger.error(f"===== [{time.strftime('%Y-%m-%d %H:%M:%S')}] 连接失败 =====")
            return False

    def disconnect(self):
        """断开连接"""
        logger.info(" 正在断开连接...")
        self.stop_feedback()
        if self.dashboard:
            self.dashboard.close()
        self.stop_modbus()
        self.stop_modbus_client()
        self.is_connected = False
        self._last_speed_factor = None
        logger.info(" 已断开连接")

    def enable_robot(self):
        """使能机器人"""
        if not self.is_connected:
            logger.error(" 未连接机器人")
            return False

        if self.is_enabled:
            logger.info(" 机器人已经处于使能状态")
            return True

        robot_mode = self._get_robot_mode()
        if robot_mode in (5, 7):
            self.is_enabled = True
            logger.info(f" 机器人当前模式 {robot_mode}，视为已使能")
            return True

        logger.info(" 正在使能机器人...")

        try:
            with self._temp_timeout(2):
                response = self.dashboard.EnableRobot()
            logger.debug(f"使能响应: {response}")

            response_code = self.parse_response_code(response)
            if response_code == 0:
                self.is_enabled = True
                logger.info(" 机器人使能成功")
                return True
            else:
                logger.error(f" 使能失败，响应码: {response_code}")
                return False
        except socket.timeout:
            logger.error(" 使能超时(2秒)")
            return False
        except Exception as e:
            logger.error(f" 使能异常: {e}")
            return False

    def disable_robot(self):
        """下使能机器人"""
        if not self.is_connected:
            logger.error(" 未连接机器人")
            return False

        if not self.is_enabled:
            logger.info("  机器人已经处于下使能状态")
            return True

        logger.info(" 正在下使能机器人...")

        try:
            with self._temp_timeout(2):
                response = self.dashboard.DisableRobot()
            logger.debug(f"下使能响应: {response}")

            response_code = self.parse_response_code(response)
            if response_code == 0:
                self.is_enabled = False
                self._last_speed_factor = None
                logger.info(" 机器人已下使能")
                return True
            else:
                logger.error(f" 下使能失败，响应码: {response_code}")
                return False
        except socket.timeout:
            logger.error(" 下使能超时(2秒)")
            return False
        except Exception as e:
            logger.error(f" 下使能异常: {e}")
            return False

    def set_robot_ip(self, ip):
        """设置机器人IP地址"""
        self.robot_ip = ip
        logger.info(f" 机器人IP已设置为: {ip}")

    def set_collision_level(self, level):
        """设置碰撞检测等级"""
        if not self.is_connected:
            logger.error(" 未连接机器人")
            return False

        try:
            with self._temp_timeout(2):
                response = self.dashboard.SetCollisionLevel(level)
            logger.debug(f" 碰撞等级设置响应: {response}")
            response_code = self.parse_response_code(response)
            if response_code == 0:
                logger.info(f" 碰撞检测等级已设置为: {level}")
                return True
            else:
                logger.error(f" 碰撞等级设置失败，响应码: {response_code}")
                return False
        except socket.timeout:
            logger.error(" 碰撞等级设置超时(2秒)")
            return False
        except Exception as e:
            logger.error(f" 碰撞等级设置异常: {e}")
            return False

    def set_speed(self, percentage):
        """设置速度比例"""
        percentage = int(round(float(percentage)))
        if not 1 <= percentage <= 100:
            logger.warning(f" 速度比例必须在1-100之间")
            return False

        if self._last_speed_factor == percentage:
            logger.debug(f" 速度已为 {percentage}%，跳过SpeedFactor")
            self.current_speed = percentage
            return True

        logger.info(f" 设置速度为 {percentage}%...")
        response = self.dashboard.SpeedFactor(percentage)
        logger.debug(f"设置速度响应: {response}")

        response_code = self.parse_response_code(response)
        if response_code == 0:
            self._last_speed_factor = percentage
            self.current_speed = percentage
            logger.info(f" 速度已设置为 {percentage}%")
            return True
        else:
            logger.error(f"  设置速度失败，响应码: {response_code}")
            return False

    def acquire_motion(self, owner: str, allow_if_idle: bool = True) -> bool:
        """Try to acquire exclusive motion control. Returns True if acquired."""
        with self._motion_lock:
            if self._motion_owner is None:
                if allow_if_idle:
                    self._motion_owner = owner
                    logger.info("运动控制权获取: %s", owner)
                    return True
                return False
            if self._motion_owner == owner:
                return True
            logger.warning("运动控制权被 %s 占用，%s 无法获取", self._motion_owner, owner)
            return False

    def release_motion(self, owner: str):
        """Release motion control if currently held by owner."""
        with self._motion_lock:
            if self._motion_owner == owner:
                self._motion_owner = None
                logger.info("运动控制权释放: %s", owner)
            else:
                logger.warning("运动控制权不属于 %s（当前: %s），无法释放", owner, self._motion_owner)

    def get_force(self, tool=2):
        """获取力传感器当前数值（工具坐标系2）

        Args:
            tool: 工具坐标系，取值范围[0, 50]，默认为2

        Returns:
            dict: {'fx': Fx, 'fy': Fy, 'fz': Fz, 'mx': Mx, 'my': My, 'mz': Mz}
                  失败返回None
        """
        if not self.is_connected:
            logger.error(" 未连接机器人")
            return None

        try:
            response = self.dashboard.GetForce(tool)
            if response:
                logger.debug(f" 力传感器响应 (工具坐标系{tool}): {response}")
                match = re.search(r'\{([^}]+)\}', response)
                if match:
                    values = match.group(1).split(',')
                    if len(values) == 6:
                        return {
                            'fx': float(values[0].strip()),
                            'fy': float(values[1].strip()),
                            'fz': float(values[2].strip()),
                            'mx': float(values[3].strip()),
                            'my': float(values[4].strip()),
                            'mz': float(values[5].strip()),
                        }
            return None
        except Exception as e:
            logger.error(f" 获取力传感器数据失败: {e}")
            return None

    def get_current_pose(self, max_retries=3):
        """获取当前位置

        Args:
            max_retries: 最大重试次数

        Returns:
            list: 机器人当前位姿 [x, y, z, rx, ry, rz]，失败返回 None
        """
        if not self.is_connected:
            logger.error(" 未连接机器人")
            return None

        if not self.is_enabled:
            logger.warning("  机器人未使能，尝试获取位置可能失败")

        for attempt in range(max_retries):
            try:
                with self._temp_timeout(3):
                    response = self.dashboard.GetPose()

                if response:
                    logger.debug(f" 获取位置响应 (尝试 {attempt+1}/{max_retries}): {response}")

                    if 'error' in str(response).lower() or 'failed' in str(response).lower():
                        logger.warning(f"  响应包含错误: {response}")
                        continue

                    pose = self.parse_pose_response(response)
                    if pose:
                        logger.info(f" 当前位置: X={pose[0]:.1f}, Y={pose[1]:.1f}, Z={pose[2]:.1f}, Rx={pose[3]:.1f}, Ry={pose[4]:.1f}, Rz={pose[5]:.1f}")
                        return pose
                    else:
                        logger.warning(f"  解析位置失败，响应格式: {response}")
                else:
                    logger.warning(f"  获取位置响应为空 (尝试 {attempt+1}/{max_retries})")

            except Exception as e:
                logger.error(f"  获取位置异常 (尝试 {attempt+1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(0.5)

        logger.error(" 获取位置失败，已达到最大重试次数")
        return None

    def _extract_pose_from_feed_data(self, data):
        try:
            if data is None:
                return None
            names = getattr(getattr(data, "dtype", None), "names", None)
            if names and "ToolVectorActual" in names:
                pose = data["ToolVectorActual"][0]
            elif hasattr(data, "get"):
                pose = data.get("ToolVectorActual")
                if pose is not None and len(pose) and hasattr(pose[0], "__iter__"):
                    pose = pose[0]
            else:
                return None
            pose = [float(v) for v in pose[:6]]
            return pose if len(pose) == 6 and all(np.isfinite(pose)) else None
        except Exception:
            return None

    def _extract_robot_mode_from_feed_data(self, data):
        try:
            if data is None:
                return None
            if hasattr(data, "get"):
                robot_mode = data.get("RobotMode")
                if robot_mode is not None:
                    try:
                        return int(robot_mode[0])
                    except Exception:
                        return int(robot_mode)
            names = getattr(getattr(data, "dtype", None), "names", None)
            if names and "RobotMode" in names:
                return int(data["RobotMode"][0])
        except Exception:
            return None
        return None

    def get_cached_pose(self, max_age=0.3):
        """Read parsed TCP pose from the 30004 feedback cache."""
        if not self.is_connected:
            return None
        now = time.time()
        with self.feed_lock:
            pose = list(self.latest_pose) if self.latest_pose is not None else None
            pose_time = self.latest_pose_time
        if pose is None or pose_time <= 0 or now - pose_time > max_age:
            return None
        return pose

    def get_current_pose_from_feedback(self, max_age=0.3):
        return self.get_cached_pose(max_age=max_age)

    def get_current_pose_fast(self, max_age=0.3, fallback=True, max_retries=1):
        """Prefer parsed 30004 feedback pose; fallback to dashboard GetPose when needed."""
        pose = self.get_cached_pose(max_age=max_age)
        if pose is not None:
            return pose
        logger.debug("30004 pose cache expired; fallback=%s", fallback)
        if not fallback:
            return None
        return self.get_current_pose(max_retries=max_retries)

    def get_robot_mode_fast(self, max_age=0.3, fallback=True, dashboard_fallback_interval=None):
        now = time.time()
        with self.feed_lock:
            mode = self.latest_robot_mode
            mode_time = self.latest_robot_mode_time
        if mode is not None and mode_time > 0 and now - mode_time <= max_age:
            return mode
        if not fallback or not self.dashboard:
            return None

        perf = get_performance_config()
        fallback_interval = float(
            dashboard_fallback_interval
            if dashboard_fallback_interval is not None
            else perf.get("robot_mode_dashboard_fallback_interval", 0.5)
        )
        if now - self._last_robot_mode_dashboard_query_time < fallback_interval:
            return self._last_robot_mode_dashboard_query_value

        try:
            logger.debug("30004 RobotMode cache expired; fallback to dashboard RobotMode()")
            response = self.dashboard.RobotMode()
            mode = self.parse_robot_mode(response) if response else None
            self._last_robot_mode_dashboard_query_time = now
            self._last_robot_mode_dashboard_query_value = mode
            return mode
        except Exception as e:
            logger.debug(f" 获取RobotMode失败: {e}")
            self._last_robot_mode_dashboard_query_time = now
            self._last_robot_mode_dashboard_query_value = None
            return None

    def _get_robot_mode_from_feedback(self):
        return self.get_robot_mode_fast(fallback=False)

    def _get_robot_mode(self):
        return self.get_robot_mode_fast()

    def get_feedback_health(self, max_age: float = 0.3) -> dict:
        """Return feedback cache snapshot with health status.

        Health levels:
        - "ok": feedback within max_age
        - "stale": feedback older than max_age but within stale_fail_age
        - "disconnected": feedback older than stale_fail_age or never received
        """
        perf = get_performance_config()
        stale_warn_age = float(perf.get("feedback_stale_warn_age", 0.5))
        stale_fail_age = float(perf.get("feedback_stale_fail_age", 2.0))

        now = time.time()
        with self.feed_lock:
            pose = list(self.latest_pose) if self.latest_pose is not None else None
            mode = self.latest_robot_mode
            timestamp = self.latest_pose_time

        if timestamp <= 0:
            return {
                "pose": None, "robot_mode": None, "timestamp": 0.0,
                "health": "disconnected",
            }

        age = now - timestamp
        if age <= max_age:
            health = "ok"
        elif age <= stale_fail_age:
            health = "stale"
            if age > stale_warn_age:
                logger.warning("反馈缓存过期: %.2fs (warn_age=%.1fs)", age, stale_warn_age)
        else:
            health = "disconnected"
            logger.error("反馈缓存断流: %.2fs (fail_age=%.1fs)", age, stale_fail_age)

        return {
            "pose": pose, "robot_mode": mode, "timestamp": timestamp,
            "health": health,
        }

    def wait_for_motion_completion(
        self,
        timeout=30,
        poll_interval=0.05,
        auto_clear_error=True,
        dashboard_fallback_interval=None,
        settle_time=None,
        stop_checker=None,
    ):
        """Wait until RobotMode reports idle, preferring 30004 feedback cache."""
        perf = get_performance_config()
        poll_interval = float(poll_interval if poll_interval is not None else perf.get("flow_wait_poll_interval", 0.05))
        dashboard_fallback_interval = float(
            dashboard_fallback_interval
            if dashboard_fallback_interval is not None
            else perf.get("robot_mode_dashboard_fallback_interval", 0.5)
        )
        settle_time = float(settle_time if settle_time is not None else perf.get("motion_settle_time", 0.15))

        logger.info(" 等待运动完成: timeout=%.1fs poll=%.2fs settle=%.2fs", timeout, poll_interval, settle_time)
        start_time = time.time()
        if settle_time > 0:
            time.sleep(settle_time)

        last_running_log_second = -1
        while time.time() - start_time < timeout:
            if stop_checker is not None and stop_checker():
                logger.info("运动等待被外部打断")
                return False
            robot_mode = self.get_robot_mode_fast(
                max_age=float(perf.get("pose_cache_max_age", 0.3)),
                fallback=True,
                dashboard_fallback_interval=dashboard_fallback_interval,
            )
            if robot_mode is not None:

                if robot_mode == 5:
                    logger.info(" 运动完成")
                    self.clear_error_retry_count = 0
                    return True
                elif robot_mode in (7, 8):
                    elapsed = time.time() - start_time
                    elapsed_second = int(elapsed)
                    if elapsed_second != last_running_log_second and elapsed_second % 2 == 0:
                        logger.debug(f"  运行中... 已耗时: {elapsed:.1f}秒")
                        last_running_log_second = elapsed_second
                elif robot_mode == 9:
                    logger.warning("  机器人出现错误，尝试自动清除报警...")
                    if auto_clear_error and self.clear_error_retry_count < 3:
                        self.clear_error_retry_count += 1
                        self.clear_error(auto_enable=False)
                        logger.warning(f"  第{self.clear_error_retry_count}次清除报警，等待0.5秒后继续检查...")
                        time.sleep(max(poll_interval, 0.1))
                    else:
                        logger.error("  已重试3次清除报警失败，返回False")
                        self.clear_error_retry_count = 0
                        return False

            time.sleep(poll_interval)

        logger.error(f"  等待超时 ({timeout}秒)")
        return False

    def move_to_point(
        self,
        target_pose,
        move_type="MovJ",
        speed_percentage=None,
        middle_pose=None,
        verify_start_pose=True,
        verify_end_pose=True,
        wait_poll_interval=0.05,
    ):
        """移动到目标点"""
        if not self.is_enabled:
            logger.error(" 机器人未使能")
            return False

        if speed_percentage is not None:
            self.set_speed(speed_percentage)
        else:
            self.set_speed(self.current_speed)

        x, y, z, rx, ry, rz = target_pose

        logger.info("\n" + "=" * 60)
        logger.info(" 移动详情")
        logger.info("=" * 60)
        logger.info(f" 目标位置: X={x:.1f}, Y={y:.1f}, Z={z:.1f}")
        logger.info(f" 目标姿态: Rx={rx:.1f}, Ry={ry:.1f}, Rz={rz:.1f}")
        logger.info(f" 运动类型: {move_type}")
        if middle_pose:
            mx, my, mz, mrx, mry, mrz = middle_pose
            logger.info(f" 中间点: X={mx:.1f}, Y={my:.1f}, Z={mz:.1f}")
        logger.info(f" 速度设置: {speed_percentage if speed_percentage else self.safe_speed}%")

        start_pose = self.get_current_pose() if verify_start_pose else None
        if verify_start_pose and not start_pose:
            logger.error(" 无法获取起始位置")
            return False

        if start_pose:
            logger.info(f"\n 当前位置: X={start_pose[0]:.1f}, Y={start_pose[1]:.1f}, Z={start_pose[2]:.1f}")
            distance = math.sqrt(
                (x - start_pose[0]) ** 2 +
                (y - start_pose[1]) ** 2 +
                (z - start_pose[2]) ** 2
            )
            logger.info(f" 运动距离: {distance:.1f}mm")
        else:
            distance = 300.0
            logger.info(" 跳过起始位置校验，使用默认运动超时估计")

        estimated_time = max(5, distance / 30)
        estimated_time = min(estimated_time, 60)
        logger.info(f"  预计运动时间: {estimated_time:.1f}秒")
        logger.info("=" * 60)

        logger.info(f" 发送{move_type}指令...")
        if move_type == "MovJ":
            response = self.dashboard.MovJ(x, y, z, rx, ry, rz, 0)
        elif move_type == "MovL":
            response = self.dashboard.MovL(x, y, z, rx, ry, rz, 0)
        elif move_type == "MovC":
            if not middle_pose:
                logger.error(" MovC需要提供中间点参数 middle_pose")
                return False
            mx, my, mz, mrx, mry, mrz = middle_pose
            response = self.dashboard.MovC(x, y, z, rx, ry, rz, mx, my, mz, mrx, mry, mrz, 0)
        else:
            logger.error(f" 不支持的运动类型: {move_type}")
            return False

        logger.debug(f" 运动响应: {response}")

        response_code = self.parse_response_code(response)
        if response_code != 0:
            logger.error(f" 运动指令被拒绝，响应码: {response_code}")

            if response_code == -7:
                logger.warning("  机器人处于脚本暂停状态，尝试停止脚本后重试...")
                self.dashboard.Stop()
                time.sleep(1)

                logger.info(" 重试发送运动指令...")
                if move_type == "MovJ":
                    response = self.dashboard.MovJ(x, y, z, rx, ry, rz, 0)
                elif move_type == "MovL":
                    response = self.dashboard.MovL(x, y, z, rx, ry, rz, 0)
                elif move_type == "MovC":
                    mx, my, mz, mrx, mry, mrz = middle_pose
                    response = self.dashboard.MovC(x, y, z, rx, ry, rz, mx, my, mz, mrx, mry, mrz, 0)

                logger.debug(f" 重试运动响应: {response}")
                response_code = self.parse_response_code(response)

                if response_code != 0:
                    logger.error(f" 重试运动指令仍然失败，响应码: {response_code}")
                    return False
            else:
                return False

        logger.info(" 运动指令已接受")

        success = self.wait_for_motion_completion(timeout=estimated_time + 10, poll_interval=wait_poll_interval)

        if not success:
            logger.error("  运动可能未完成，强制停止...")
            self.dashboard.Stop()
            return False

        if not verify_end_pose:
            logger.info(" 跳过结束位置校验")
            return True

        end_pose = self.get_current_pose()
        if not end_pose:
            logger.warning("  无法获取结束位置")
            return True

        target_error = math.sqrt(
            (end_pose[0] - x) ** 2 +
            (end_pose[1] - y) ** 2 +
            (end_pose[2] - z) ** 2
        )

        logger.info(f" 结束点: X={end_pose[0]:.1f}, Y={end_pose[1]:.1f}, Z={end_pose[2]:.1f}")
        logger.info(f" 目标点误差: {target_error:.1f}mm")

        if target_error < self.position_tolerance:
            logger.info(" 运动完成，精度良好")
            return True
        else:
            logger.warning("  运动完成，但位置有偏差")
            return True

    def servo_p(self, pose, t=0.05, aheadtime=50, gain=500):
        """ServoP 伺服运动 — 按固定周期下发目标位姿，不等待运动完成

        Args:
            pose: 目标位姿 [X, Y, Z, Rx, Ry, Rz]
            t: 该点位的运行时间(秒)，默认0.05，范围[0.004, 3600.0]
            aheadtime: 类似PID的D项，默认50，范围[20.0, 100.0]
            gain: 类似PID的P项，默认500，范围[200.0, 1000.0]

        Returns:
            bool: 指令是否发送成功
        """
        if not self.is_connected or not self.is_enabled:
            logger.error(" 机器人未连接或未使能，无法执行ServoP")
            return False

        try:
            x, y, z, rx, ry, rz = pose[:6]
            response = self.dashboard.ServoP(x, y, z, rx, ry, rz, t=t, aheadtime=aheadtime, gain=gain)
            response_code = self.parse_response_code(response)
            if response_code != 0:
                logger.warning(f" ServoP响应码: {response_code}")
                return False
            return True
        except Exception as e:
            logger.error(f" ServoP异常: {e}")
            return False

    def move_joint_relative(self, offsets, a=20, v=50, cp=100, verify_end_pose=True, wait_poll_interval=0.05):
        """关节相对运动"""
        if not self.is_enabled:
            logger.error(" 机器人未使能")
            return False

        logger.info("\n" + "=" * 60)
        logger.info(" 关节相对运动详情")
        logger.info("=" * 60)
        logger.info(f" 关节偏移: {offsets}")
        logger.info(f" 加速度: {a}, 速度: {v}, CP: {cp}")
        logger.info("=" * 60)

        logger.info(f" 发送RelJointMovJ指令...")
        response = self.dashboard.RelJointMovJ(offsets[0], offsets[1], offsets[2], offsets[3], offsets[4], offsets[5], a, v, cp)

        logger.debug(f" 运动响应: {response}")

        response_code = self.parse_response_code(response)
        if response_code != 0:
            logger.error(f" 运动指令被拒绝，响应码: {response_code}")

            if response_code == -7:
                logger.warning("  机器人处于脚本暂停状态，尝试停止脚本后重试...")
                self.dashboard.Stop()
                time.sleep(1)

                logger.info(" 重试发送运动指令...")
                response = self.dashboard.RelJointMovJ(offsets[0], offsets[1], offsets[2], offsets[3], offsets[4], offsets[5], a, v, cp)

                logger.debug(f" 重试运动响应: {response}")
                response_code = self.parse_response_code(response)

                if response_code != 0:
                    logger.error(f" 重试运动指令仍然失败，响应码: {response_code}")
                    return False
            else:
                return False

        logger.info(" 运动指令已接受")

        estimated_time = 10
        success = self.wait_for_motion_completion(timeout=estimated_time + 10, poll_interval=wait_poll_interval)

        if not success:
            logger.error("  运动可能未完成，强制停止...")
            self.dashboard.Stop()
            return False

        if not verify_end_pose:
            logger.info(" 跳过结束位置校验")
            return True

        end_pose = self.get_current_pose()
        if not end_pose:
            logger.warning("  无法获取结束位置")
            return True

        logger.info(f" 结束点: X={end_pose[0]:.1f}, Y={end_pose[1]:.1f}, Z={end_pose[2]:.1f}")
        logger.info(" 运动完成")
        return True

    def move_relative(
        self,
        offsets,
        coord_system="user",
        motion_type="linear",
        speed=30,
        acceleration=20,
        cp=100,
        wait_poll_interval=0.05,
    ):
        """Relative motion without force control."""
        if not self.is_connected:
            logger.error("机器人未连接，无法执行相对移动")
            return False
        if not self.is_enabled:
            logger.error("机器人未使能，无法执行相对移动")
            return False

        offsets = [float(v) for v in list(offsets)[:6]]
        if len(offsets) < 6:
            offsets.extend([0.0] * (6 - len(offsets)))
        coord_system = str(coord_system or "user").lower()
        motion_type = str(motion_type or "linear").lower()
        speed = int(speed)
        acceleration = int(acceleration)
        cp = int(cp)

        if coord_system == "joint":
            return self.move_joint_relative(
                offsets,
                a=acceleration,
                v=speed,
                cp=cp,
                verify_end_pose=False,
                wait_poll_interval=wait_poll_interval,
            )

        self.set_speed(speed)
        logger.info(
            "相对移动: coord=%s motion=%s offsets=%s speed=%s acceleration=%s cp=%s",
            coord_system, motion_type, offsets, speed, acceleration, cp
        )

        if coord_system == "tool":
            if motion_type == "joint":
                response = self.dashboard.RelMovJTool(
                    offsets[0], offsets[1], offsets[2], offsets[3], offsets[4], offsets[5],
                    a=acceleration, v=speed, cp=cp
                )
                command_name = "RelMovJTool"
            else:
                response = self.dashboard.RelMovLTool(
                    offsets[0], offsets[1], offsets[2], offsets[3], offsets[4], offsets[5],
                    a=acceleration, v=speed, speed=speed, cp=cp
                )
                command_name = "RelMovLTool"
        else:
            if motion_type == "joint":
                response = self.dashboard.RelMovJUser(
                    offsets[0], offsets[1], offsets[2], offsets[3], offsets[4], offsets[5],
                    a=acceleration, v=speed, cp=cp
                )
                command_name = "RelMovJUser"
            else:
                response = self.dashboard.RelMovLUser(
                    offsets[0], offsets[1], offsets[2], offsets[3], offsets[4], offsets[5],
                    a=acceleration, v=speed, speed=speed, cp=cp
                )
                command_name = "RelMovLUser"

        logger.debug(f"{command_name}响应: {response}")
        response_code = self.parse_response_code(response)
        if response_code != 0:
            logger.error(f"{command_name}指令被拒绝，响应码: {response_code}")
            return False

        linear_distance = math.sqrt(offsets[0] ** 2 + offsets[1] ** 2 + offsets[2] ** 2)
        angular_distance = max(abs(offsets[3]), abs(offsets[4]), abs(offsets[5]))
        timeout = min(max(max(linear_distance / 20.0, angular_distance / 20.0) + 5.0, 5.0), 60.0)
        if not self.wait_for_motion_completion(timeout=timeout, poll_interval=wait_poll_interval):
            logger.error("相对移动等待完成失败")
            self.dashboard.Stop()
            return False
        return True

    def move_until_force_limit(self, axis, distance, force_limit, speed_percentage=20):
        """Move along a user-coordinate axis until distance completes or TCP force exceeds limit."""
        if not self.is_connected:
            logger.error("机器人未连接，无法执行力阈值移动")
            return False
        if not self.is_enabled:
            logger.error("机器人未使能，无法执行力阈值移动")
            return False
        if self.get_feed_data() is None:
            logger.error("反馈数据不可用，无法监控力阈值")
            return False

        axis = str(axis).upper()
        offsets = {
            "X": [distance, 0, 0, 0, 0, 0],
            "Y": [0, distance, 0, 0, 0, 0],
            "Z": [0, 0, distance, 0, 0, 0],
        }.get(axis)
        if offsets is None:
            logger.error(f"不支持的力阈值移动方向: {axis}")
            return False
        if force_limit <= 0:
            logger.error(f"力上限必须大于0: {force_limit}")
            return False

        self.set_speed(int(speed_percentage))
        response = self.dashboard.RelMovLUser(
            offsets[0], offsets[1], offsets[2], offsets[3], offsets[4], offsets[5],
            speed=int(speed_percentage)
        )
        logger.debug(f"力阈值移动响应: {response}")
        response_code = self.parse_response_code(response)
        if response_code != 0:
            logger.error(f"力阈值移动指令被拒绝，响应码: {response_code}")
            return False

        timeout = min(max(abs(float(distance)) / 20.0 + 5.0, 5.0), 60.0)
        start_time = time.time()
        while time.time() - start_time < timeout:
            current_force = self.get_current_force()
            if current_force > force_limit:
                logger.warning(f"力阈值触发: {current_force:.2f}N > {force_limit:.2f}N，停止当前运动")
                self.dashboard.Stop()
                return True

            robot_mode = self.get_robot_mode_fast(
                max_age=float(get_performance_config().get("pose_cache_max_age", 0.3)),
                fallback=True,
            )
            if robot_mode == 5:
                logger.info("力阈值移动自然完成，未触发停止")
                return True
            if robot_mode == 9:
                logger.error("力阈值移动过程中机器人报警")
                return False
            time.sleep(0.05)

        logger.warning("力阈值移动等待超时，停止当前运动")
        self.dashboard.Stop()
        return True

    def move_to_initial_position(self, verify_start_pose=True, verify_end_pose=True, wait_poll_interval=0.05):
        """移动到初始位置"""
        self.initial_pose = get_initial_point()
        logger.info("\n" + "=" * 60)
        logger.info(" 初始位置: X={:.1f}, Y={:.1f}, Z={:.1f}".format(
            self.initial_pose[0], self.initial_pose[1], self.initial_pose[2]
        ))
        logger.info("=" * 60)

        logger.info(" 开始移动到初始位置...")
        success = self.move_to_point(
            self.initial_pose,
            move_type="MovJ",
            speed_percentage=20,
            verify_start_pose=verify_start_pose,
            verify_end_pose=verify_end_pose,
            wait_poll_interval=wait_poll_interval,
        )

        if success:
            logger.info("\n 已成功移动到初始位置!")
            return True
        else:
            logger.error("\n 移动到初始位置失败!")
            return False

    def start_feedback(self):
        self.feed_four = DobotApiFeedBack(self.robot_ip, 30004)
        self._feed_running = True
        self.feed_thread = threading.Thread(target=self._feed_loop, daemon=True)
        self.feed_thread.start()
        return True

    def stop_feedback(self):
        self._feed_running = False
        if self.feed_thread:
            self.feed_thread.join()
        if self.feed_four:
            self.feed_four.close()
        with self.feed_lock:
            self.latest_pose = None
            self.latest_pose_time = 0.0
            self.latest_robot_mode = None
            self.latest_robot_mode_time = 0.0
            self.latest_feed_time = 0.0

    def _feed_loop(self):
        while self._feed_running:
            try:
                result = self.feed_four.feedBackData()
                if result is not None and len(result) > 0:
                    try:
                        magic_ok = result[0][0] == 0x123456789abcdef
                    except:
                        magic_ok = True

                    if magic_ok or len(result[0]) > 0:
                        now = time.time()
                        pose = self._extract_pose_from_feed_data(result)
                        robot_mode = self._extract_robot_mode_from_feed_data(result)
                        with self.feed_lock:
                            self.feed_data = result
                            self.last_feed_time = now
                            self.latest_feed_time = now
                            if pose is not None:
                                self.latest_pose = pose
                                self.latest_pose_time = now
                            if robot_mode is not None:
                                self.latest_robot_mode = robot_mode
                                self.latest_robot_mode_time = now
                        self._feed_error_count = 0
            except Exception as e:
                self._feed_error_count += 1
                if self._feed_error_count <= 5 or self._feed_error_count % 50 == 0:
                    logger.warning(f" FeedBack异常(第{self._feed_error_count}次): {e}")
                if self._feed_error_count >= 100:
                    logger.error(f"  连续100次FeedBack异常，停止反馈线程")
                    self._feed_running = False
                    break
                time.sleep(0.1)

    def get_feed_data(self):
        with self.feed_lock:
            return np.copy(self.feed_data) if self.feed_data is not None else None

    def get_last_feed_time(self):
        """获取最后收到反馈数据的时间戳"""
        return self.last_feed_time

    def start_modbus(self, port=502):
        """启动Modbus TCP服务器"""
        if self.modbus_server and self.modbus_server.is_running():
            logger.info(" Modbus服务已在运行")
            return True

        self.modbus_server = DobotModbusServer(on_command_callback=self._on_modbus_command)
        result = self.modbus_server.start(host="0.0.0.0", port=port)
        if not result:
            return False

        self._modbus_cycle_count = 0
        self._modbus_last_duration = 0.0
        self._modbus_event.clear()
        self._modbus_thread = threading.Thread(target=self._modbus_cycle_loop, daemon=True)
        self._modbus_thread.start()
        return True

    def stop_modbus(self):
        """停止Modbus TCP服务器"""
        self._modbus_event.set()
        if self._modbus_thread and self._modbus_thread.is_alive():
            self._modbus_thread.join(timeout=1.0)
        self._modbus_thread = None
        if self.modbus_server:
            self.modbus_server.stop()
            self.modbus_server = None

    def _modbus_cycle_loop(self):
        """Modbus 200ms 严格周期循环"""
        while not self._modbus_event.is_set():
            t_start = time.time()
            try:
                if self.modbus_server and self.modbus_server.is_running():
                    self.modbus_server.check_commands()
                    self._update_modbus_status()
                if self.modbus_client and self.modbus_client.is_connected():
                    self._cart_status_data = self.modbus_client.read_cart_status()
            except Exception as e:
                logger.error(f" Modbus周期异常: {e}")

            self._modbus_last_duration = (time.time() - t_start) * 1000
            self._modbus_cycle_count += 1

            elapsed = time.time() - t_start
            wait_time = max(0, 0.2 - elapsed)
            self._modbus_event.wait(wait_time)

    def start_modbus_client(self, host, port=502):
        """连接小车 Modbus 服务器（PC作为Master）"""
        if self.modbus_client and self.modbus_client.is_connected():
            logger.info(" Modbus客户端已连接小车")
            return True
        self.modbus_client = DobotModbusClient()
        return self.modbus_client.connect(host, port)

    def stop_modbus_client(self):
        """断开小车 Modbus 连接"""
        if self.modbus_client:
            self.modbus_client.disconnect()
            self.modbus_client = None

    def get_cart_status(self):
        """获取小车Modbus状态"""
        if not self.modbus_client or not self.modbus_client.is_connected():
            return {"connected": False, "cart_status": 0, "fault_code": 0, "x": 0.0, "y": 0.0, "z": 0.0}
        return self.modbus_client.read_cart_status()

    def get_modbus_stats(self):
        return {
            "cycle_count": self._modbus_cycle_count,
            "last_duration_ms": round(self._modbus_last_duration, 1),
            "is_running": self.modbus_server is not None and self.modbus_server.is_running(),
            "port": self.modbus_server._port if hasattr(self.modbus_server, '_port') else 502,
            "client_connected": self.modbus_client is not None and self.modbus_client.is_connected(),
            "client_host": self.modbus_client._host if self.modbus_client else "",
            "cart_status": dict(self._cart_status_data) if self._cart_status_data else {},
        }

    def _update_modbus_status(self):
        """更新Modbus状态寄存器"""
        if not self.modbus_server or not self.is_connected:
            return

        status = self._modbus_status_override or 1
        if not self.is_enabled:
            status = self._modbus_status_override or 1
        else:
            feed_data = self.get_feed_data()
            if feed_data is not None:
                try:
                    robot_mode = int(feed_data["RobotMode"][0])
                    if self._modbus_status_override:
                        status = self._modbus_status_override
                    elif robot_mode == 7:
                        status = 2
                    elif robot_mode == 5:
                        status = 3
                    elif robot_mode in [9, 11]:
                        status = 4
                        if not self._robot_alarm_recorded:
                            raw_error, error_code = self._read_robot_error_raw()
                            self._last_fault_code = error_code
                            self.record_alarm(
                                "机器人报警",
                                error_code or robot_mode,
                                "报警",
                                "机器人进入报警模式",
                                "请查看机器人报警信息，处理后清除报警并重新使能",
                                raw=f"RobotMode={robot_mode}; {raw_error}",
                            )
                            self._robot_alarm_recorded = True
                    elif robot_mode in [2, 3, 4, 6]:
                        status = 2
                    if robot_mode not in [9, 11]:
                        self._robot_alarm_recorded = False
                except Exception:
                    status = self._modbus_status_override or 1

        if self.is_connected:
            try:
                with self.feed_lock:
                    if self.feed_data is not None:
                        tcp_pose = self.feed_data["ToolVectorActual"][0]
                        x_mm = float(tcp_pose[0])
                        y_mm = float(tcp_pose[1])
                        z_mm = float(tcp_pose[2])
                        pose_valid = True
                    else:
                        pose_valid = False
                if pose_valid:
                    self.modbus_server.update_status_registers(
                        status=status,
                        fault_code=self._last_fault_code,
                        in_position=1 if status == 3 else 0,
                        x=x_mm, y=y_mm, z=z_mm,
                        emergency=1 if status == 5 else 0,
                    )
                    return
            except Exception:
                pass

        self.modbus_server.update_status_registers(
            status=status,
            fault_code=self._last_fault_code,
            in_position=1 if status == 3 else 0,
            x=0, y=0, z=0,
            emergency=1 if status == 5 else 0,
        )

    def _on_modbus_command(self, cmd):
        """Modbus命令回调"""
        logger.info(f" 收到Modbus命令: {cmd}")
        if cmd == 1:
            self._modbus_reset()
        elif cmd == 2:
            self._modbus_go_safe_position()
        elif cmd == 3:
            self._modbus_auto_hook()
        elif cmd == 9:
            self.emergency_stop()
        else:
            logger.warning(f" 未知Modbus命令: {cmd}")
            self._last_fault_code = int(cmd)
            self.record_alarm("Modbus命令", cmd, "故障", "收到未知Modbus命令")

    def _modbus_reset(self):
        """复位"""
        if not self.is_connected:
            return
        try:
            self.clear_error(auto_enable=True)
            self._modbus_status_override = None
            self._last_fault_code = 0
        except Exception as e:
            logger.error(f" Modbus复位失败: {e}")
            self._last_fault_code = 1
            self.record_alarm("Modbus复位", "EXCEPTION", "故障", "Modbus复位失败", raw=e)

    def clear_error(self, auto_enable=True):
        if not self.is_connected:
            logger.error("❌ 机器人未连接，无法清除故障")
            return False
        try:
            result = self.dashboard.ClearError()
            logger.debug(f"清除故障结果: {result}")
            response_code = self.parse_response_code(result)
            if response_code not in (0, None):
                logger.error(f"❌ 清除故障失败，响应码: {response_code}")
                return False
            time.sleep(0.1)
            robot_mode = self._get_robot_mode()
            if robot_mode == 9:
                logger.warning(" 清除故障后机器人仍处于报警状态")
                return False
            self._last_fault_code = 0
            if self._modbus_status_override == 5:
                self._modbus_status_override = None
            if auto_enable and not self.is_enabled:
                self.enable_robot()
            return True
        except Exception as e:
            logger.error(f"❌ 清除故障失败: {e}")
            return False

    def emergency_stop(self):
        if not self.is_connected:
            logger.error("❌ 机器人未连接，无法软件急停")
            self.record_alarm("软件急停", "DISCONNECTED", "故障", "机器人未连接，无法执行软件急停")
            return False
        try:
            response = self.dashboard.EmergencyStop(1)
            response_code = self.parse_response_code(response)
            if response_code != 0:
                logger.error(f"❌ 软件急停失败，响应码: {response_code}")
                self.record_alarm("软件急停", response_code, "故障", "软件急停指令被拒绝", raw=response)
                return False
            self._modbus_status_override = 5
            self.is_enabled = False
            self._last_speed_factor = None
            self.software_emergency_active = True
            self.record_alarm("软件急停", response_code, "急停", "软件急停信号已触发", "复位软件急停信号后清除报警并重新使能", response)
            if self.modbus_server:
                self.modbus_server.update_status_registers(status=5, fault_code=0, in_position=0, emergency=1)
            logger.warning("软件急停已触发")
            return True
        except Exception as e:
            logger.error(f"❌ 软件急停异常: {e}")
            self.record_alarm("软件急停", "EXCEPTION", "故障", "软件急停执行异常", raw=e)
            return False

    def release_emergency_stop(self):
        if not self.is_connected:
            logger.error("❌ 机器人未连接，无法解除软件急停")
            self.record_alarm("解除软件急停", "DISCONNECTED", "故障", "机器人未连接，无法解除软件急停")
            return False
        try:
            response = self.dashboard.EmergencyStop(0)
            response_code = self.parse_response_code(response)
            if response_code != 0:
                logger.error(f"❌ 解除软件急停失败，响应码: {response_code}")
                self.record_alarm("解除软件急停", response_code, "故障", "解除软件急停指令被拒绝", raw=response)
                return False
            self.software_emergency_active = False
            if self._modbus_status_override == 5:
                self._modbus_status_override = None
            if self.modbus_server:
                self.modbus_server.update_status_registers(status=1, fault_code=self._last_fault_code, in_position=0, emergency=0)
            logger.info("软件急停信号已解除")
            return True
        except Exception as e:
            logger.error(f"❌ 解除软件急停异常: {e}")
            self.record_alarm("解除软件急停", "EXCEPTION", "故障", "解除软件急停执行异常", raw=e)
            return False

    def pause(self):
        if not self.is_connected:
            logger.error("❌ 机器人未连接，无法暂停")
            return False
        try:
            self.dashboard.Pause()
            logger.info("暂停指令已发送")
            return True
        except Exception as e:
            logger.error(f"❌ 暂停失败: {e}")
            return False

    def continue_motion(self):
        if not self.is_connected:
            logger.error("❌ 机器人未连接，无法继续")
            return False
        try:
            self.dashboard.Continue()
            logger.info("继续指令已发送")
            return True
        except Exception as e:
            logger.error(f"❌ 继续失败: {e}")
            return False

    def move_jog(self, axis_id, coordtype=1):
        if not self.is_connected:
            logger.error("❌ 机器人未连接，无法点动")
            return False
        try:
            self.dashboard.MoveJog(axis_id, coordtype)
            return True
        except Exception as e:
            logger.error(f"❌ 点动控制失败: {e}")
            return False

    def stop_jog(self):
        if not self.is_connected:
            return False
        try:
            self.dashboard.MoveJog("")
            return True
        except Exception as e:
            logger.error(f"❌ 停止点动失败: {e}")
            return False

    def _modbus_go_safe_position(self):
        """回安全位"""
        if not self.is_connected:
            return
        if not self.acquire_motion("modbus"):
            logger.warning("流程运行中，Modbus回安全位被拒绝")
            self._modbus_status_override = 4
            self._last_fault_code = 2
            self.record_alarm("Modbus回安全位", "BUSY", "故障", "流程运行中，回安全位被拒绝")
            if self.modbus_server:
                self.modbus_server.update_status_registers(status=4, fault_code=2, in_position=0, emergency=0)
            return
        try:
            self._modbus_status_override = 2
            pose = self.initial_pose
            success = self.move_to_point(
                pose,
                move_type="MovJ",
                speed_percentage=self.current_speed or 20,
                verify_start_pose=False,
                verify_end_pose=False,
            )
            if not success:
                self._modbus_status_override = 4
                self._last_fault_code = 2
                self.record_alarm("Modbus回安全位", "REJECTED", "故障", "回安全位指令被拒绝或超时")
            else:
                self._modbus_status_override = None
        except Exception as e:
            logger.error(f" Modbus回安全位失败: {e}")
            self._modbus_status_override = 4
            self._last_fault_code = 2
            self.record_alarm("Modbus回安全位", "EXCEPTION", "故障", "Modbus回安全位执行异常", raw=e)
        finally:
            self.release_motion("modbus")
    def _modbus_auto_hook(self):
        """执行外部主站写入的目标位姿"""
        if not self.is_connected:
            return
        if not self.acquire_motion("modbus"):
            logger.warning("流程运行中，Modbus目标运动被拒绝")
            self._modbus_status_override = 4
            self._last_fault_code = 3
            self.record_alarm("Modbus目标运动", "BUSY", "故障", "流程运行中，目标运动被拒绝")
            if self.modbus_server:
                self.modbus_server.update_status_registers(status=4, fault_code=3, in_position=0, emergency=0)
            return
        target = self.modbus_server.get_target_position() if self.modbus_server else None
        if not target:
            self.release_motion("modbus")
            return
        try:
            speed = int(target.get("speed", 30))
            speed = min(max(speed, 1), 100)
            self._modbus_status_override = 2
            target_pose = [target["x"], target["y"], target["z"], target["rx"], target.get("ry", 0.0), target.get("rz", 0.0)]
            success = self.move_to_point(
                target_pose,
                move_type="MovJ",
                speed_percentage=speed,
                verify_start_pose=False,
                verify_end_pose=False,
            )
            if not success:
                self._modbus_status_override = 4
                self._last_fault_code = 3
                self.record_alarm("Modbus目标运动", "REJECTED", "故障", "目标运动指令被拒绝或超时")
            else:
                self._modbus_status_override = None
        except Exception as e:
            logger.error(f" Modbus目标运动失败: {e}")
            self._modbus_status_override = 4
            self._last_fault_code = 3
            self.record_alarm("Modbus目标运动", "EXCEPTION", "故障", "目标运动执行异常", raw=e)
        finally:
            self.release_motion("modbus")

    def set_force_threshold(self, threshold):
        """设置力控阈值"""
        if threshold >= 0:
            self.force_threshold = threshold
            logger.info(f" 力控阈值已设置为: {threshold}N")
            return True
        return False

    def get_current_force(self):
        """获取当前TCP受力合力"""
        data = self.get_feed_data()
        if data is None:
            return 0.0
        try:
            tcp_force = data["ActualTCPForce"][0]
            fx, fy, fz = float(tcp_force[0]), float(tcp_force[1]), float(tcp_force[2])
            resultant = math.sqrt(fx*fx + fy*fy + fz*fz)
            self.last_force_value = resultant
            return resultant
        except Exception as e:
            logger.error(f" 获取受力失败: {e}")
            return 0.0

    def set_force_trigger_callback(self, callback):
        """设置力控触发回调函数"""
        self.force_trigger_callback = callback

    def start_force_monitor(self):
        """启动力控监控线程"""
        if self._force_monitor_running:
            logger.info(" 力控监控已在运行")
            return True

        self._force_monitor_running = True
        self.force_monitor_thread = threading.Thread(target=self._force_monitor_loop, daemon=True)
        self.force_monitor_thread.start()
        logger.info(" 力控监控已启动")
        return True

    def stop_force_monitor(self):
        """停止力控监控线程"""
        self._force_monitor_running = False
        if self.force_monitor_thread and self.force_monitor_thread.is_alive():
            self.force_monitor_thread.join(timeout=1.0)
        self.force_monitor_thread = None
        logger.info(" 力控监控已停止")

    def _force_monitor_loop(self):
        """力控监控循环"""
        while self._force_monitor_running:
            if self.force_monitor_enabled and self.is_connected:
                current_force = self.get_current_force()
                if current_force > self.force_threshold and not self.force_triggered:
                    logger.warning(f" ⚠️ 力控触发! 当前受力: {current_force:.2f}N > 阈值: {self.force_threshold}N")
                    self.force_triggered = True
                    if self.force_trigger_callback:
                        try:
                            self.force_trigger_callback(current_force)
                        except Exception as e:
                            logger.error(f" 力控回调执行失败: {e}")
                elif current_force <= self.force_threshold * 0.9:
                    self.force_triggered = False
            time.sleep(0.05)

    def close(self):
        self.stop_feedback()
        self.stop_force_monitor()
        if self.dashboard:
            self.dashboard.close()
