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
from config_manager import get_photo_position

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

        self.initial_pose = get_photo_position()
        logger.info(f"初始位置: {self.initial_pose}")

        self.feed_four = None
        self.feed_lock = threading.Lock()
        self.feed_data = None
        self.feed_thread = None

        self.position_tolerance = 10.0
        self.safe_speed = 30
        self.current_speed = 30
        self.last_feed_time = 0
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

        self.force_monitor_enabled = False
        self.force_threshold = 30.0
        self.force_monitor_thread = None
        self._force_monitor_running = False
        self.force_trigger_callback = None
        self.last_force_value = 0.0
        self.force_triggered = False

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
        logger.info(" 已断开连接")

    def enable_robot(self):
        """使能机器人"""
        if not self.is_connected:
            logger.error(" 未连接机器人")
            return False

        logger.info(" 正在使能机器人...")

        try:
            with self._temp_timeout(2):
                response = self.dashboard.EnableRobot()
            logger.debug(f"使能响应: {response}")

            response_code = self.parse_response_code(response)
            if response_code == 0:
                self.is_enabled = True
                logger.info(" 机器人使能成功")
                time.sleep(1)
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
        if not 1 <= percentage <= 100:
            logger.warning(f" 速度比例必须在1-100之间")
            return False

        logger.info(f" 设置速度为 {percentage}%...")
        response = self.dashboard.SpeedFactor(percentage)
        logger.debug(f"设置速度响应: {response}")

        response_code = self.parse_response_code(response)
        if response_code == 0:
            logger.info(f" 速度已设置为 {percentage}%")
            return True
        else:
            logger.error(f"  设置速度失败，响应码: {response_code}")
            return False

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

    def wait_for_motion_completion(self, timeout=30):
        """等待运动完成"""
        logger.info(" 等待运动完成...")
        start_time = time.time()

        while time.time() - start_time < timeout:
            response = self.dashboard.RobotMode()
            if response:
                robot_mode = self.parse_robot_mode(response)

                if robot_mode == 5:
                    logger.info(" 运动完成")
                    self.clear_error_retry_count = 0
                    return True
                elif robot_mode == 7:
                    elapsed = time.time() - start_time
                    if int(elapsed) % 2 == 0:
                        logger.debug(f"  运行中... 已耗时: {elapsed:.1f}秒")
                elif robot_mode == 9:
                    logger.warning("  机器人出现错误，尝试自动清除报警...")
                    if self.clear_error_retry_count < 3:
                        self.clear_error_retry_count += 1
                        self.clear_error()
                        logger.warning(f"  第{self.clear_error_retry_count}次清除报警，等待0.5秒后继续检查...")
                        time.sleep(0.5)
                    else:
                        logger.error("  已重试3次清除报警失败，返回False")
                        self.clear_error_retry_count = 0
                        return False

            time.sleep(0.5)

        logger.error(f"  等待超时 ({timeout}秒)")
        return False

    def move_to_point(self, target_pose, move_type="MovJ", speed_percentage=None, middle_pose=None):
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

        start_pose = self.get_current_pose()
        if not start_pose:
            logger.error(" 无法获取起始位置")
            return False

        logger.info(f"\n 当前位置: X={start_pose[0]:.1f}, Y={start_pose[1]:.1f}, Z={start_pose[2]:.1f}")

        distance = math.sqrt(
            (x - start_pose[0]) ** 2 +
            (y - start_pose[1]) ** 2 +
            (z - start_pose[2]) ** 2
        )
        logger.info(f" 运动距离: {distance:.1f}mm")

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

        success = self.wait_for_motion_completion(timeout=estimated_time + 10)

        if not success:
            logger.error("  运动可能未完成，强制停止...")
            self.dashboard.Stop()
            return False

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

    def move_joint_relative(self, offsets, a=20, v=50, cp=100):
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
        success = self.wait_for_motion_completion(timeout=estimated_time + 10)

        if not success:
            logger.error("  运动可能未完成，强制停止...")
            self.dashboard.Stop()
            return False

        end_pose = self.get_current_pose()
        if not end_pose:
            logger.warning("  无法获取结束位置")
            return True

        logger.info(f" 结束点: X={end_pose[0]:.1f}, Y={end_pose[1]:.1f}, Z={end_pose[2]:.1f}")
        logger.info(" 运动完成")
        return True

    def move_to_initial_position(self):
        """移动到初始位置"""
        logger.info("\n" + "=" * 60)
        logger.info(" 初始位置: X={:.1f}, Y={:.1f}, Z={:.1f}".format(
            self.initial_pose[0], self.initial_pose[1], self.initial_pose[2]
        ))
        logger.info("=" * 60)

        logger.info(" 开始移动到初始位置...")
        success = self.move_to_point(self.initial_pose, move_type="MovJ", speed_percentage=20)

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
                        with self.feed_lock:
                            self.feed_data = result
                            self.last_feed_time = time.time()
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

        status = 1
        if not self.is_enabled:
            status = 1
        else:
            feed_data = self.get_feed_data()
            if feed_data is not None:
                try:
                    robot_mode = int(feed_data["RobotMode"][0])
                    if robot_mode in [2, 3, 4, 5, 6]:
                        status = 2
                    elif robot_mode in [1, 7]:
                        status = 3
                    elif robot_mode == 11:
                        status = 4
                    elif robot_mode == 9:
                        status = 5
                except Exception:
                    status = 1

        if self.is_connected:
            try:
                with self.feed_lock:
                    if self.feed_data is not None and len(self.feed_data) > 168:
                        x_mm = int(self.feed_data[144] * 1000)
                        y_mm = int(self.feed_data[145] * 1000)
                        z_mm = int(self.feed_data[146] * 1000)
                        pose_valid = True
                    else:
                        pose_valid = False
                if pose_valid:
                    self.modbus_server.update_status_registers(
                        status=status,
                        fault_code=0,
                        in_position=1 if status == 3 else 0,
                        x=x_mm, y=y_mm, z=z_mm
                    )
                    return
            except Exception:
                pass

        self.modbus_server.update_status_registers(
            status=status,
            fault_code=0,
            in_position=1 if status == 3 else 0,
            x=0, y=0, z=0
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
        else:
            logger.warning(f" 未知Modbus命令: {cmd}")

    def _modbus_reset(self):
        """复位"""
        if not self.is_connected:
            return
        try:
            self.dashboard.ClearError()
            time.sleep(0.5)
            self.enable_robot()
        except Exception as e:
            logger.error(f" Modbus复位失败: {e}")

    def clear_error(self):
        if not self.is_connected:
            logger.error("❌ 机器人未连接，无法清除故障")
            return False
        try:
            result = self.dashboard.ClearError()
            logger.debug(f"清除故障结果: {result}")
            time.sleep(0.5)
            self.enable_robot()
            return True
        except Exception as e:
            logger.error(f"❌ 清除故障失败: {e}")
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
        try:
            pose = self.initial_pose
            self.dashboard.MovJ(pose[0], pose[1], pose[2], pose[3], pose[4], pose[5], 0)
        except Exception as e:
            logger.error(f" Modbus回安全位失败: {e}")

    def _modbus_auto_hook(self):
        """自动提钩模式"""
        self.auto_hook_mode = True
        logger.info(" 已进入自动提钩模式")
        target = self.modbus_server.get_target_position() if self.modbus_server else None
        if target and self.is_connected:
            try:
                speed = int(target.get("speed", 30))
                self.dashboard.SpeedFactor(speed)
                self.dashboard.MovJ(
                    target["x"], target["y"], target["z"],
                    target["rx"], 0, 0, 0
                )
            except Exception as e:
                logger.error(f" Modbus提钩移动失败: {e}")

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
