#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
越疆机器人控制模块
"""

import time
import re
import socket
import logging
import inspect
from pathlib import Path
from contextlib import contextmanager
from ..communication.modbus_server import DobotModbusServer, REG_CMD_STATUS, REG_MODE, STATUS_IDLE, STATUS_STANDBY, STATUS_RUNNING, STATUS_HOOK_OK, STATUS_HOOK_ERR, STATUS_ROBOT_ERR, MODE_AUTO, MODE_MANUAL, CMD_STOP, CMD_RESET, CMD_HOOK
import math
import threading
import numpy as np
from ..robot.dobot_api import DobotApiDashboard, DobotApiFeedBack
from ..config.config_manager import get_initial_point, get_performance_config, get_config, get_hook_target, get_modbus_slave_id
from ..robot.motion_safety import (
    validate_absolute_pose, validate_relative_delta,
    validate_motion_target, validate_servo_p_params,
    MotionValidationResult, MotionSafetyState,
)
from ..robot.robot_pose_buffer import RobotPoseBuffer
from ..config.alarm_history import AlarmHistory
from ..runtime.runtime_resilience import SingleInstanceLock

logger = logging.getLogger(__name__)
STATUS_DELAY_WAIT = STATUS_HOOK_OK
_FEEDBACK_MAGIC = 0x123456789ABCDEF

# 提钩杆类型常量（与 Modbus 40004 协议层一致）
HOOK_TYPE_LOW = 0
HOOK_TYPE_HIGH = 1


class _ConnectionSupersededError(RuntimeError):
    pass


class DobotController:
    """机器人控制器"""

    def __init__(self, robot_ip="192.168.5.1", enforce_single_instance=False):
        self.robot_ip = robot_ip
        self.dashboard = None
        self.is_connected = False
        self.is_enabled = False
        self.last_error = ""
        self._transport_lock = threading.RLock()
        self._connect_attempt_lock = threading.Lock()
        self._connection_generation = 0
        self._robot_connect_deadline_s = 5.0
        self._socket_connect_timeout_s = 2.0
        self._feedback_read_timeout_s = 1.0
        self._enforce_single_instance = bool(enforce_single_instance)
        self._control_lease_path = (
            Path(__file__).resolve().parent.parent / "robot_control.lock"
        )
        self._control_lease = None
        self._control_lease_acquired = not self._enforce_single_instance
        self._acquire_control_lease()

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
        self.latest_tcp_speed = None
        self.latest_tcp_speed_time = 0.0
        self.latest_actual_tcp_force = None
        self.latest_actual_tcp_force_time = 0.0
        self.latest_running_status = None
        self.latest_running_status_time = 0.0
        self.latest_run_queued_cmd = None
        self.latest_run_queued_cmd_time = 0.0
        self.latest_current_command_id = None
        self.latest_current_command_id_time = 0.0
        self.latest_tool_vector_target = None
        self.latest_tool_vector_target_time = 0.0
        self.latest_q_actual = None
        self.latest_q_actual_time = 0.0
        self.latest_q_target = None
        self.latest_q_target_time = 0.0

        self._motion_command_sent_time = 0.0
        self._has_seen_motion_state = False

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
        self._modbus_exec_thread = None
        self._modbus_exec_lock = threading.Lock()
        self._modbus_hook_status = 0
        self.auto_hook_mode = False
        self._modbus_status_override = None
        self._modbus_mode = 0  # MODE_AUTO
        self._modbus_program_runner = None
        self._modbus_program_readiness_checker = None
        # PR 3: optional delegate that intercepts 40001 commands BEFORE
        # the controller's default dispatch. Returns True to short-circuit
        # the default handling. Used by RuntimeAgent's production state
        # machine for cmd=0 (pause) / cmd=1 (reset) / cmd=3 (hook).
        self._modbus_command_delegate = None
        # PR 3: optional callback invoked when 40002 (mode) changes.
        # Signature: (old_mode: int, new_mode: int) -> None.
        self._modbus_on_mode_changed = None
        # PR 5 Task 4: optional callback invoked when 40004 (hook_type)
        # changes. Signature: (old_hook: int, new_hook: int) -> None.
        self._modbus_on_hook_type_changed = None
        self._last_modbus_command = None
        self._last_modbus_command_time = 0.0
        self._last_fault_code = 0
        self._robot_alarm_recorded = False
        self.software_emergency_active = False
        self._active_flow_thread = None
        self._modbus_flow_state_lock = threading.Lock()
        self._modbus_delay_waiting = False
        self._modbus_delay_release_event = threading.Event()
        self._runtime_recovery_required = False
        self._runtime_recovery_cleared_callback = None
        self._runtime_maintenance = False
        self._disconnect_stop_thread = None
        self._disconnect_stop_lock = threading.Lock()
        self.alarm_history = AlarmHistory()

        self._motion_owner = None
        self._motion_lock = threading.Lock()
        self._last_move_timing = {}  # {"speed_set": 0.0, "command_send": 0.0, "motion_wait": 0.0}
        self._last_command_id = None
        self._last_motion_completion_reason = None
        self._last_force_guard_event = None
        self._feed_packet_drops = 0
        # 视觉时间对齐：位姿环形缓冲区，在 _store_feedback_packet 中每个 30004 Pose push
        self.pose_buffer = RobotPoseBuffer()

        _cfg = get_config()
        self._user_index = _cfg.get("user_index", 0)
        self._tool_index = _cfg.get("tool_index", 0)

    def record_alarm(self, source, code="", level="报警", description="", solution="", raw=""):
        try:
            return self.alarm_history.add(source, code, level, description, solution, raw)
        except Exception as e:
            logger.error(f"记录报警失败: {e}")
            return None

    def _get_error_detail(self):
        """调用 GetError("zh_cn") 获取报警详情，返回第一个错误的 id/level/description/solution 字典。

        GetError 通过 HTTP 接口返回 JSON，格式:
        {"errMsg": [{"id": xxx, "level": xxx, "description": "xxx", "solution": "xxx", ...}]}
        若无报警或解析失败则返回 None。
        """
        if not self.dashboard:
            return None
        try:
            result = self.dashboard.GetError("zh_cn")
            if not result or not isinstance(result, dict):
                return None
            err_msg = result.get("errMsg")
            if not err_msg or not isinstance(err_msg, list) or len(err_msg) == 0:
                return None
            first = err_msg[0]
            return {
                "id": first.get("id", ""),
                "level": first.get("level", ""),
                "description": first.get("description", ""),
                "solution": first.get("solution", ""),
            }
        except Exception as e:
            logger.debug(f"GetError详情获取失败: {e}")
            return None

    def _fetch_error_detail_async(self, robot_mode, error_code, raw_error):
        """后台线程获取 GetError 详情，成功后追加到日志"""
        def _worker():
            try:
                detail = self._get_error_detail()
                if detail:
                    desc = detail.get("description", "")
                    solution = detail.get("solution", "")
                    level = detail.get("level", "")
                    logger.info(f"报警详情(异步): code={error_code}, desc={desc}, solution={solution}, level={level}")
                    self.record_alarm(
                        source="报警详情",
                        code=str(error_code),
                        level=level,
                        description=desc,
                        solution=solution,
                    )
            except Exception as e:
                logger.debug(f"异步获取报警详情失败: {e}")
        import threading
        t = threading.Thread(target=_worker, daemon=True)
        t.start()

    def _read_robot_error_raw(self):
        """仅调用 GetErrorID() 获取错误码，不调用 GetError() 以避免阻塞 Modbus 循环。"""
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
        with self._api_timeout(self.dashboard, seconds):
            yield

    @staticmethod
    @contextmanager
    def _api_timeout(api, seconds):
        if api is None:
            yield
            return
        socket_dobot = getattr(api, "socket_dobot", None)
        if socket_dobot is None or not hasattr(socket_dobot, "gettimeout") or not hasattr(socket_dobot, "settimeout"):
            yield
            return
        old_timeout = socket_dobot.gettimeout()
        socket_dobot.settimeout(seconds)
        try:
            yield
        finally:
            socket_dobot.settimeout(old_timeout)

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

    def parse_response_ids(self, response):
        """Parse Dashboard response to extract [code, command_id, ...].

        Follows official DobotDemo.parseResultId pattern.
        Returns list of ints, e.g. [0, 123] for "0,123,..."
        or [0] if only code present, or [1] if "Not Tcp" detected.
        """
        if not response:
            return [1]
        if "Not Tcp" in str(response):
            logger.warning("控制模式不是TCP模式")
            return [1]
        try:
            nums = [int(n) for n in re.findall(r'-?\d+', str(response))]
            return nums if nums else [2]
        except Exception as e:
            logger.error(f"解析响应ID失败: {e}")
            return [2]

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
        """Build and validate candidate transports before publishing them."""
        if not self._acquire_control_lease():
            logger.error(self.last_error)
            return False
        if not self._connect_attempt_lock.acquire(blocking=False):
            self.last_error = "机器人连接任务已在执行"
            logger.warning(self.last_error)
            return False

        candidate_dashboard = None
        candidate_feedback = None
        try:
            if self.is_connected and self.dashboard is not None:
                return True
            with self._transport_lock:
                self._connection_generation += 1
                generation = self._connection_generation
            deadline = time.monotonic() + max(
                0.5,
                float(self._robot_connect_deadline_s),
            )

            logger.info(
                "===== [%s] 开始连接机器人 generation=%d ip=%s =====",
                time.strftime("%Y-%m-%d %H:%M:%S"),
                generation,
                self.robot_ip,
            )
            connect_timeout = min(
                self._socket_connect_timeout_s,
                self._remaining_connect_time(deadline),
            )
            candidate_dashboard = DobotApiDashboard(
                self.robot_ip,
                29999,
                connect_timeout=connect_timeout,
                io_timeout=connect_timeout,
            )
            self._require_current_connection_attempt(generation)

            with self._api_timeout(
                candidate_dashboard,
                min(2.0, self._remaining_connect_time(deadline)),
            ):
                response = candidate_dashboard.RobotMode()
            valid, mode, msg = self._validate_robot_mode(response)
            if not valid:
                raise RuntimeError(f"RobotMode验证失败: {msg}")

            with self._api_timeout(
                candidate_dashboard,
                min(2.0, self._remaining_connect_time(deadline)),
            ):
                response = candidate_dashboard.GetAngle()
            valid, angles, msg = self._validate_get_angle(response)
            if not valid:
                raise RuntimeError(f"GetAngle验证失败: {msg}")
            logger.info(
                "Dashboard验证通过 generation=%d mode=%s angles=%s",
                generation,
                mode,
                angles[:3],
            )
            self._require_current_connection_attempt(generation)

            feedback_timeout = min(
                self._socket_connect_timeout_s,
                self._remaining_connect_time(deadline),
            )
            candidate_feedback = DobotApiFeedBack(
                self.robot_ip,
                30004,
                connect_timeout=feedback_timeout,
                io_timeout=min(
                    self._feedback_read_timeout_s,
                    self._remaining_connect_time(deadline),
                ),
            )
            initial_packet = self._wait_for_candidate_feedback(
                candidate_feedback,
                generation,
                deadline,
            )

            old_dashboard, old_feedback, old_feed_thread = (
                self._commit_candidate_transport(
                    candidate_dashboard,
                    candidate_feedback,
                    initial_packet,
                    generation,
                )
            )
            candidate_dashboard = None
            candidate_feedback = None
            self._close_replaced_transport(
                old_dashboard,
                old_feedback,
                old_feed_thread,
            )
            # 重连清空 pose_buffer，避免旧位姿污染视觉时间对齐
            self.pose_buffer.clear()
            logger.info(
                "===== [%s] 机器人连接成功 generation=%d =====",
                time.strftime("%Y-%m-%d %H:%M:%S"),
                generation,
            )
            return True

        except _ConnectionSupersededError as exc:
            self.last_error = str(exc)
            logger.info("机器人连接结果已丢弃: %s", exc)
            return False
        except (socket.timeout, TimeoutError):
            self.last_error = "机器人连接超过业务截止时间"
            logger.error(self.last_error)
            return False
        except ConnectionRefusedError:
            self.last_error = "连接被拒绝，请确保机器人已启用TCP/IP控制模式"
            logger.error(self.last_error)
            return False
        except OSError as exc:
            error_codes = {
                10061: "端口拒绝连接，请检查机器人TCP/IP控制模式是否启用",
                10060: "连接超时，请检查网络连接和IP地址",
                10051: "网络不可达，请检查电脑和机器人是否在同一网段",
                10054: "连接被重置，机器人可能已断开或重启",
            }
            self.last_error = error_codes.get(
                getattr(exc, "errno", None),
                f"网络错误: {exc}",
            )
            logger.error(self.last_error)
            return False
        except Exception as e:
            self.last_error = f"连接异常: {str(e)}"
            logger.exception(self.last_error)
            return False
        finally:
            self._close_api(candidate_feedback)
            self._close_api(candidate_dashboard)
            self._connect_attempt_lock.release()

    @staticmethod
    def _close_api(api):
        if api is None:
            return
        try:
            api.close()
        except Exception:
            logger.exception("关闭候选机器人连接失败")

    @staticmethod
    def _remaining_connect_time(deadline):
        remaining = float(deadline) - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("机器人连接业务截止时间已到")
        return remaining

    def _require_current_connection_attempt(self, generation):
        with self._transport_lock:
            if generation != self._connection_generation:
                raise _ConnectionSupersededError(
                    f"连接代次已过期: {generation} != {self._connection_generation}"
                )

    def _wait_for_candidate_feedback(self, feedback, generation, deadline):
        while True:
            self._require_current_connection_attempt(generation)
            remaining = self._remaining_connect_time(deadline)
            try:
                with self._api_timeout(
                    feedback,
                    min(self._feedback_read_timeout_s, remaining),
                ):
                    result = feedback.feedBackData()
            except socket.timeout:
                continue
            if result is None or len(result) == 0:
                continue
            try:
                magic_ok = int(result[0]["TestValue"]) == _FEEDBACK_MAGIC
            except Exception:
                magic_ok = False
            if magic_ok:
                return result

    def _commit_candidate_transport(
        self,
        dashboard,
        feedback,
        initial_packet,
        generation,
    ):
        with self._transport_lock:
            self._require_current_connection_attempt(generation)
            old_dashboard = self.dashboard
            old_feedback = self.feed_four
            old_feed_thread = self.feed_thread
            with self.feed_lock:
                self._reset_feedback_cache_locked()
            self._store_feedback_packet(initial_packet)
            self.dashboard = dashboard
            self.feed_four = feedback
            self._feed_running = True
            self.feed_thread = threading.Thread(
                target=self._feed_loop,
                args=(feedback, generation),
                name=f"DobotFeedback-{generation}",
                daemon=True,
            )
            self.feed_thread.start()
            self.is_connected = True
            self.is_enabled = False
            self.last_error = ""
            return old_dashboard, old_feedback, old_feed_thread

    def _close_replaced_transport(
        self,
        old_dashboard,
        old_feedback,
        old_feed_thread,
    ):
        self._close_api(old_feedback)
        self._close_api(old_dashboard)
        if (
            old_feed_thread is not None
            and old_feed_thread is not threading.current_thread()
            and old_feed_thread.is_alive()
        ):
            old_feed_thread.join(timeout=1.0)

    def disconnect(self):
        """断开连接"""
        logger.info(" 正在断开连接...")
        self.close_robot_transport()
        self.stop_modbus()
        self.release_control_lease()
        logger.info(" 已断开连接")

    def close_robot_transport(self):
        """Close robot sockets without stopping Modbus or releasing the control lease."""
        with self._transport_lock:
            self._connection_generation += 1
            self._feed_running = False
            dashboard = self.dashboard
            feedback = self.feed_four
            feed_thread = self.feed_thread
            self.dashboard = None
            self.feed_four = None
            self.feed_thread = None
            self.is_connected = False
            self.is_enabled = False
            self._last_speed_factor = None
        self._close_api(feedback)
        self._close_api(dashboard)
        if (
            feed_thread is not None
            and feed_thread is not threading.current_thread()
            and feed_thread.is_alive()
        ):
            feed_thread.join(timeout=1.0)
            if feed_thread.is_alive():
                logger.warning("反馈线程未能在1秒内退出")
        with self.feed_lock:
            self._reset_feedback_cache_locked()
        # 断开连接时清空 pose_buffer，避免旧位姿污染下次重连后的视觉时间对齐
        self.pose_buffer.clear()

    def release_control_lease(self):
        if self._control_lease is not None:
            self._control_lease.release()
            self._control_lease = None
        self._control_lease_acquired = not self._enforce_single_instance

    def _acquire_control_lease(self):
        if not self._enforce_single_instance:
            self._control_lease_acquired = True
            return True
        if self._control_lease is not None and self._control_lease_acquired:
            return True
        self._control_lease = SingleInstanceLock(self._control_lease_path)
        self._control_lease_acquired = self._control_lease.acquire()
        if not self._control_lease_acquired:
            self._control_lease = None
            self.last_error = "另一个GUI或后台进程已持有机器人控制权"
        return self._control_lease_acquired

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

    def get_motion_safety_state(self):
        """
        获取运动安全状态（只读缓存，不发任何 Dashboard 查询）。
        用于 motion_safety.py 的校验函数。
        """
        from ..robot.motion_safety import MotionSafetyState

        # 计算反馈年龄
        feedback_age = 999.0
        if self.latest_feed_time > 0:
            feedback_age = time.monotonic() - self.latest_feed_time

        # 从反馈数据读取 ErrorStatus 和 RobotMode
        error_status = 0
        robot_mode = 0
        if self.feed_data is not None:
            try:
                error_status = int(self.feed_data[0][0]['ErrorStatus'])
            except (IndexError, KeyError, ValueError, TypeError):
                pass
            try:
                robot_mode = int(self.feed_data[0][0]['RobotMode'])
            except (IndexError, KeyError, ValueError, TypeError):
                pass

        return MotionSafetyState(
            is_connected=self.is_connected,
            is_enabled=self.is_enabled,
            software_emergency_active=self.software_emergency_active,
            error_status=error_status,
            robot_mode=robot_mode,
            feedback_age=feedback_age,
        )

    def _read_feedback_field(self, data, field_name):
        """Read one field from supported 30004 feedback payload shapes."""
        if data is None:
            return None

        try:
            names = getattr(getattr(data, "dtype", None), "names", None)
            if names and field_name in names:
                values = data[field_name]
                if len(values) == 0:
                    return None
                return values[0]
        except (IndexError, KeyError, TypeError, ValueError) as e:
            logger.debug("read structured feedback field %s failed: %s", field_name, e)

        try:
            if hasattr(data, "get"):
                value = data.get(field_name)
                if value is None:
                    return None
                if isinstance(value, np.ndarray):
                    if value.size == 0:
                        return None
                    return value[0] if value.ndim > 0 else value.item()
                if isinstance(value, (list, tuple)):
                    if not value:
                        return None
                    first = value[0]
                    if isinstance(first, (list, tuple, np.ndarray)):
                        return first
                return value
        except (IndexError, KeyError, TypeError, ValueError) as e:
            logger.debug("read dict feedback field %s failed: %s", field_name, e)

        try:
            return data[0][0][field_name]
        except (IndexError, KeyError, TypeError, ValueError) as e:
            logger.debug("read legacy feedback field %s failed: %s", field_name, e)
            return None

    def _extract_vector6_from_feed_data(self, data, field_name):
        """从反馈数据中提取6元素向量字段"""
        try:
            values = self._read_feedback_field(data, field_name)
            if values is None:
                return None
            vector = np.asarray(values, dtype=float).reshape(-1)
            if vector.size < 6:
                logger.debug("extract %s failed: length=%s", field_name, vector.size)
                return None
            return vector[:6]
        except (IndexError, KeyError, ValueError, TypeError) as e:
            logger.debug("提取 %s 失败: %s", field_name, e)
            return None

    def _extract_int_from_feed_data(self, data, field_name):
        """Extract one integer scalar from a 30004 feedback payload."""
        try:
            value = self._read_feedback_field(data, field_name)
            if value is None:
                return None
            if isinstance(value, np.ndarray):
                if value.size == 0:
                    return None
                value = value.reshape(-1)[0]
            elif isinstance(value, (list, tuple)):
                if not value:
                    return None
                value = value[0]
            return int(value)
        except (ValueError, TypeError, IndexError) as e:
            logger.debug("extract %s failed: %s", field_name, e)
            return None

    def _extract_pose_from_feed_data(self, data):
        return self._extract_vector6_from_feed_data(data, "ToolVectorActual")

    def _extract_tcp_speed_from_feed_data(self, data):
        return self._extract_vector6_from_feed_data(data, "TCPSpeedActual")

    def _extract_actual_tcp_force_from_feed_data(self, data):
        return self._extract_vector6_from_feed_data(data, "ActualTCPForce")

    def _extract_robot_mode_from_feed_data(self, data):
        return self._extract_int_from_feed_data(data, "RobotMode")

    def _extract_running_status_from_feed_data(self, data):
        """Extract RunningStatus from 30004 feedback data. Returns int or None."""
        return self._extract_int_from_feed_data(data, "RunningStatus")

    def _extract_run_queued_cmd_from_feed_data(self, data):
        """Extract RunQueuedCmd from 30004 feedback data. Returns int or None."""
        return self._extract_int_from_feed_data(data, "RunQueuedCmd")

    def _extract_current_command_id_from_feed_data(self, data):
        """Extract CurrentCommandId from 30004 feedback data. Returns int or None."""
        return self._extract_int_from_feed_data(data, "CurrentCommandId")

    def _extract_tool_vector_target_from_feed_data(self, data):
        return self._extract_vector6_from_feed_data(data, "ToolVectorTarget")

    def _extract_q_actual_from_feed_data(self, data):
        return self._extract_vector6_from_feed_data(data, "QActual")

    def _extract_q_target_from_feed_data(self, data):
        return self._extract_vector6_from_feed_data(data, "QTarget")

    @staticmethod
    def _force_delta_norm(current_force, baseline_force):
        """Return resultant delta force for Fx/Fy/Fz in Newtons."""
        current = [float(v) for v in list(current_force)[:3]]
        baseline = [float(v) for v in list(baseline_force)[:3]]
        if len(current) < 3 or len(baseline) < 3:
            raise ValueError("TCP force vector must contain at least Fx/Fy/Fz")
        return math.sqrt(sum((current[i] - baseline[i]) ** 2 for i in range(3)))

    @staticmethod
    def _force_guard_enabled(force_guard):
        return bool(force_guard and force_guard.get("enabled"))

    def prepare_force_guard(self, force_guard, max_age=None):
        """Validate force guard config and sample a pre-motion software baseline."""
        if not self._force_guard_enabled(force_guard):
            return None

        guard = dict(force_guard)
        try:
            threshold = float(guard.get("threshold_n", 0))
        except (TypeError, ValueError):
            threshold = 0.0
        if threshold <= 0:
            raise RuntimeError("TCP力阈值必须大于0N")

        perf = get_performance_config()
        max_age = float(max_age if max_age is not None else perf.get("pose_cache_max_age", 0.3))
        try:
            sample_count = max(1, int(guard.get("baseline_samples", 3)))
            sample_interval = max(0.0, float(guard.get("baseline_interval", 0.02)))
            sample_timeout = max(0.01, float(guard.get("sample_timeout", 1.0)))
        except (TypeError, ValueError):
            sample_count = 3
            sample_interval = 0.02
            sample_timeout = 1.0
        deadline = time.monotonic() + sample_timeout
        samples = []

        while len(samples) < sample_count and time.monotonic() <= deadline:
            snapshot = self.get_motion_feedback_snapshot(max_age=max_age)
            force = snapshot.get("actual_tcp_force")
            if snapshot.get("health") == "ok" and force is not None and len(force) >= 3:
                sample = [float(v) for v in list(force)[:6]]
                if len(sample) < 6:
                    sample.extend([0.0] * (6 - len(sample)))
                samples.append(sample)
            if len(samples) < sample_count:
                time.sleep(sample_interval)

        if len(samples) < sample_count:
            raise RuntimeError("TCP力反馈不可用，无法启用力到位保护")

        baseline = [
            sum(sample[i] for sample in samples) / len(samples)
            for i in range(6)
        ]
        guard["enabled"] = True
        guard["mode"] = "resultant_delta"
        guard["threshold_n"] = threshold
        guard["baseline_force"] = baseline
        try:
            guard["debounce_samples"] = max(1, int(guard.get("debounce_samples", 1)))
        except (TypeError, ValueError):
            guard["debounce_samples"] = 1
        guard["max_age"] = max_age
        return guard

    def get_cached_pose(self, max_age=0.3):
        """Read parsed TCP pose from the 30004 feedback cache."""
        if not self.is_connected:
            return None
        now = time.monotonic()
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
        now = time.monotonic()
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

        now = time.monotonic()
        with self.feed_lock:
            pose = list(self.latest_pose) if self.latest_pose is not None else None
            mode = self.latest_robot_mode
            running_status = self.latest_running_status
            run_queued_cmd = self.latest_run_queued_cmd
            tcp_speed = list(self.latest_tcp_speed) if self.latest_tcp_speed is not None else None
            actual_tcp_force = list(self.latest_actual_tcp_force) if self.latest_actual_tcp_force is not None else None
            timestamp = self.latest_feed_time
            pose_timestamp = self.latest_pose_time

        if timestamp <= 0:
            return {
                "pose": None, "robot_mode": None, "timestamp": 0.0,
                "health": "disconnected",
                "running_status": None, "run_queued_cmd": None, "tcp_speed": None,
                "actual_tcp_force": None,
                "pose_timestamp": 0.0,
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
            "running_status": running_status,
            "run_queued_cmd": run_queued_cmd,
            "tcp_speed": tcp_speed,
            "actual_tcp_force": actual_tcp_force,
            "pose_timestamp": pose_timestamp,
        }

    def get_motion_feedback_snapshot(self, max_age: float = 0.3) -> dict:
        """Return a unified snapshot of all 30004 feedback fields for motion completion detection.

        Returns dict with: pose, tcp_speed, running_status, run_queued_cmd,
        current_command_id, tool_vector_target, robot_mode, q_actual, q_target,
        timestamp, health ("ok"/"stale"/"disconnected").
        """
        perf = get_performance_config()
        stale_fail_age = float(perf.get("feedback_stale_fail_age", 2.0))

        now = time.monotonic()
        with self.feed_lock:
            pose = list(self.latest_pose) if self.latest_pose is not None else None
            tcp_speed = list(self.latest_tcp_speed) if self.latest_tcp_speed is not None else None
            running_status = self.latest_running_status
            run_queued_cmd = self.latest_run_queued_cmd
            current_command_id = self.latest_current_command_id
            tool_vector_target = list(self.latest_tool_vector_target) if self.latest_tool_vector_target is not None else None
            actual_tcp_force = list(self.latest_actual_tcp_force) if self.latest_actual_tcp_force is not None else None
            robot_mode = self.latest_robot_mode
            q_actual = list(self.latest_q_actual) if self.latest_q_actual is not None else None
            q_target = list(self.latest_q_target) if self.latest_q_target is not None else None
            timestamp = self.latest_feed_time
            pose_timestamp = self.latest_pose_time

        if timestamp <= 0:
            return {
                "pose": None, "tcp_speed": None, "running_status": None,
                "run_queued_cmd": None, "current_command_id": None,
                "tool_vector_target": None, "robot_mode": None,
                "actual_tcp_force": None,
                "q_actual": None, "q_target": None,
                "timestamp": 0.0, "health": "disconnected",
                "feedback_age": 999.0,
                "pose_timestamp": 0.0,
            }

        age = now - timestamp
        if age <= max_age:
            health = "ok"
        elif age <= stale_fail_age:
            health = "stale"
        else:
            health = "disconnected"

        return {
            "pose": pose, "tcp_speed": tcp_speed, "running_status": running_status,
            "run_queued_cmd": run_queued_cmd, "current_command_id": current_command_id,
            "tool_vector_target": tool_vector_target, "robot_mode": robot_mode,
            "actual_tcp_force": actual_tcp_force,
            "q_actual": q_actual, "q_target": q_target,
            "timestamp": timestamp, "health": health,
            "feedback_age": age,
            "pose_timestamp": pose_timestamp,
        }

    def _wait_after_stop_settled(self, timeout=1.5, poll_interval=0.05):
        """Wait after Stop() until the robot is idle enough for the next command."""
        perf = get_performance_config()
        speed_threshold = float(perf.get("motion_done_speed_threshold", 1.0))
        rotation_speed_threshold = float(perf.get("motion_done_rotation_speed_threshold", 1.0))
        pose_cache_max_age = float(perf.get("pose_cache_max_age", 0.3))
        deadline = time.monotonic() + max(0.1, float(timeout))
        poll_interval = max(0.01, float(poll_interval))
        last_event = {
            "post_robot_mode": None,
            "post_error_status": None,
        }

        while time.monotonic() <= deadline:
            snapshot = self.get_motion_feedback_snapshot(max_age=pose_cache_max_age)
            state = self.get_motion_safety_state()
            robot_mode = snapshot.get("robot_mode")
            if robot_mode is None:
                robot_mode = state.robot_mode
            error_status = state.error_status
            last_event = {
                "post_robot_mode": robot_mode,
                "post_error_status": error_status,
            }

            if error_status != 0 or robot_mode in (9, 11):
                self.last_error = (
                    f"力触发Stop后机器人报警: RobotMode={robot_mode}, "
                    f"ErrorStatus={error_status}，可能阈值过高/速度过快/接触过硬"
                )
                self.record_alarm(
                    "TCP力停止",
                    "STOP_ALARM",
                    "故障",
                    self.last_error,
                    "降低速度、降低TCP力阈值或减小接触行程，确认工件接触不是硬碰撞",
                )
                return False, last_event

            tcp_speed = snapshot.get("tcp_speed")
            if tcp_speed is None:
                speed_ok = True
            else:
                linear_ok = all(abs(v) <= speed_threshold for v in list(tcp_speed)[:3])
                angular_ok = all(abs(v) <= rotation_speed_threshold for v in list(tcp_speed)[3:6])
                speed_ok = linear_ok and angular_ok

            running_status = snapshot.get("running_status")
            run_queued_cmd = snapshot.get("run_queued_cmd")
            queue_ok = running_status in (None, 0) and run_queued_cmd in (None, 0)
            mode_ok = robot_mode in (None, 5)

            if snapshot.get("health") == "ok" and speed_ok and queue_ok and mode_ok:
                self.last_error = ""
                return True, last_event

            time.sleep(poll_interval)

        self.last_error = (
            "Stop后机器人未在限定时间内稳定，可能仍处于暂停/运行/队列未清空状态"
        )
        self.record_alarm("TCP力停止", "STOP_SETTLE_TIMEOUT", "故障", self.last_error)
        return False, last_event

    def _recover_after_stop_rejected(self, reason=""):
        """Recover once after Dashboard returns -7/script paused."""
        logger.warning("运动指令被拒绝(-7)，执行Stop并等待稳定后重试: %s", reason)
        try:
            self.dashboard.Stop()
        except Exception as e:
            self.last_error = f"Stop恢复失败: {e}"
            logger.warning(self.last_error)
            return False
        settled, event = self._wait_after_stop_settled(timeout=1.5, poll_interval=0.05)
        if not settled:
            logger.error("Stop恢复后机器人未稳定: %s event=%s", self.last_error, event)
            return False
        return True

    def wait_for_motion_completion(
        self,
        timeout=30,
        poll_interval=0.05,
        auto_clear_error=True,
        dashboard_fallback_interval=None,
        settle_time=None,
        stop_checker=None,
        target_pose=None,
        command_id=None,
        force_guard=None,
    ):
        """Wait until motion is complete, preferring 30004 feedback state machine."""
        perf = get_performance_config()
        poll_interval = float(poll_interval if poll_interval is not None else perf.get("flow_wait_poll_interval", 0.05))
        dashboard_fallback_interval = float(
            dashboard_fallback_interval
            if dashboard_fallback_interval is not None
            else perf.get("robot_mode_dashboard_fallback_interval", 1.0)
        )
        settle_time = float(settle_time if settle_time is not None else perf.get("motion_settle_time", 0.15))
        speed_threshold = float(perf.get("motion_done_speed_threshold", 1.0))
        rotation_speed_threshold = float(perf.get("motion_done_rotation_speed_threshold", 1.0))
        pose_tolerance = float(perf.get("motion_done_pose_tolerance", 2.0))
        rot_tolerance = float(perf.get("motion_done_rotation_tolerance", 2.0))
        stable_samples = int(perf.get("motion_done_stable_samples", 3))
        use_feedback = perf.get("motion_done_use_feedback", True)
        pose_cache_max_age = float(perf.get("pose_cache_max_age", 0.3))
        feedback_stale_fail_age = float(perf.get("feedback_stale_fail_age", 2.0))
        force_guard = dict(force_guard) if self._force_guard_enabled(force_guard) else None
        force_guard_counter = 0
        self._last_motion_completion_reason = None
        self._last_force_guard_event = None

        if force_guard is not None and not force_guard.get("baseline_force"):
            logger.error("力到位保护缺少运动前TCP力基线")
            return False

        logger.info("等待运动完成: timeout=%.1fs poll=%.2fs settle=%.2fs target=%s",
                    timeout, poll_interval, settle_time,
                    "absolute" if target_pose is not None else "relative")

        start_time = time.monotonic()
        if settle_time > 0:
            time.sleep(settle_time)

        last_running_log_second = -1
        self._motion_done_stable_count = 0
        _feedback_stale_logged = False

        while time.monotonic() - start_time < timeout:
            if stop_checker is not None and stop_checker():
                logger.info("运动等待被外部打断")
                return False

            # --- Settle time guard ---
            if self._motion_command_sent_time > 0 and time.monotonic() - self._motion_command_sent_time < settle_time:
                time.sleep(poll_interval)
                continue

            # --- Get feedback snapshot ---
            snapshot = self.get_motion_feedback_snapshot(max_age=pose_cache_max_age)
            cur_pose = snapshot["pose"]
            cur_speed = snapshot["tcp_speed"]
            running_status = snapshot["running_status"]
            run_queued_cmd = snapshot["run_queued_cmd"]
            snapshot_health = snapshot["health"]
            snapshot_timestamp = snapshot["timestamp"]

            # --- Force guard check: must run before command_id completion ---
            if force_guard is not None:
                actual_force = snapshot.get("actual_tcp_force")
                if snapshot_health != "ok" or actual_force is None:
                    logger.error("力到位保护失效: 30004 TCP力反馈不可用，停止当前运动")
                    try:
                        self.dashboard.Stop()
                    except Exception as e:
                        logger.warning("力到位保护停止失败: %s", e)
                    return False

                try:
                    delta_n = self._force_delta_norm(actual_force, force_guard["baseline_force"])
                except (ValueError, TypeError) as e:
                    logger.error("力到位保护TCP力数据异常: %s", e)
                    try:
                        self.dashboard.Stop()
                    except Exception as stop_error:
                        logger.warning("力到位保护停止失败: %s", stop_error)
                    return False

                threshold_n = float(force_guard["threshold_n"])
                if delta_n >= threshold_n:
                    force_guard_counter += 1
                else:
                    force_guard_counter = 0

                if force_guard_counter >= int(force_guard.get("debounce_samples", 1)):
                    event = {
                        "threshold_n": threshold_n,
                        "delta_n": delta_n,
                        "current_force": list(actual_force)[:6],
                        "baseline_force": list(force_guard["baseline_force"])[:6],
                        "pose": cur_pose,
                        "timestamp": snapshot_timestamp,
                    }
                    logger.warning(
                        "TCP力到位触发: delta=%.3fN threshold=%.3fN force=%s baseline=%s",
                        delta_n, threshold_n, event["current_force"], event["baseline_force"]
                    )
                    try:
                        stop_response = self.dashboard.Stop()
                        event["stop_response"] = stop_response
                    except Exception as e:
                        logger.warning("TCP力到位Stop()失败: %s", e)
                    self._motion_done_stable_count = 0
                    settled, post_event = self._wait_after_stop_settled(timeout=1.5, poll_interval=max(poll_interval, 0.01))
                    event.update(post_event)
                    self._last_force_guard_event = event
                    if not settled:
                        logger.error("TCP力触发Stop后机器人未稳定: %s", self.last_error)
                        return False
                    self._last_motion_completion_reason = "force_triggered"
                    return True

            # --- Command ID completion check (official pattern) ---
            # Official DobotDemo: RobotMode == 5 && CurrentCommandId == command_id
            if command_id is not None and snapshot_health == "ok":
                feedback_cmd_id = snapshot.get("current_command_id")
                if feedback_cmd_id is not None and feedback_cmd_id == command_id:
                    robot_mode = snapshot.get("robot_mode")
                    if robot_mode == 5:
                        self._motion_done_stable_count = getattr(self, '_motion_done_stable_count', 0) + 1
                        if self._motion_done_stable_count >= stable_samples:
                            logger.info("官方模式判定完成: CurrentCommandId=%d匹配+RobotMode=5, 连续%d次", command_id, stable_samples)
                            self._motion_done_stable_count = 0
                            self._last_motion_completion_reason = "motion_done"
                            return True
                    else:
                        self._motion_done_stable_count = 0
                else:
                    self._motion_done_stable_count = 0

            # 有 command_id 且 30004 新鲜时，仅走命令 ID 判定，跳过通用速度/状态判定
            if command_id is not None and snapshot_health == "ok":
                time.sleep(poll_interval)
                continue

            # --- Motion state guard: must have seen motion before allowing completion ---
            if cur_speed is not None:
                has_speed = any(abs(v) > speed_threshold for v in cur_speed[:3]) or any(abs(v) > rotation_speed_threshold for v in cur_speed[3:6])
                if has_speed:
                    self._has_seen_motion_state = True
            if running_status is not None and running_status != 0:
                self._has_seen_motion_state = True

            if snapshot_health == "ok" and not self._has_seen_motion_state:
                # Haven't seen motion yet, can't judge completion via 30004 feedback state machine
                time.sleep(poll_interval)
                continue

            # --- 30004 feedback-assisted completion check ---
            if use_feedback and cur_speed is not None:
                # Check speed near zero
                linear_speed_ok = all(abs(v) < speed_threshold for v in cur_speed[:3])
                rotation_speed_ok = all(abs(v) < rotation_speed_threshold for v in cur_speed[3:6]) if len(cur_speed) >= 6 else True
                speed_ok = linear_speed_ok and rotation_speed_ok

                if speed_ok:
                    if target_pose is not None and cur_pose is not None:
                        # --- Absolute motion: speed + pose + stable ---
                        pos_ok = True
                        if len(target_pose) >= 3:
                            pos_diff = sum((a - b) ** 2 for a, b in zip(cur_pose[:3], target_pose[:3])) ** 0.5
                            pos_ok = pos_diff < pose_tolerance

                        rot_ok = True
                        if len(target_pose) >= 6 and len(cur_pose) >= 6:
                            rot_diff = sum((a - b) ** 2 for a, b in zip(cur_pose[3:6], target_pose[3:6])) ** 0.5
                            rot_ok = rot_diff < rot_tolerance

                        if pos_ok and rot_ok:
                            self._motion_done_stable_count = getattr(self, '_motion_done_stable_count', 0) + 1
                            if self._motion_done_stable_count >= stable_samples:
                                logger.info("30004反馈辅助判定完成: 速度归零+位姿到位, 连续%d次", stable_samples)
                                self._motion_done_stable_count = 0
                                self._last_motion_completion_reason = "motion_done"
                                return True
                        else:
                            self._motion_done_stable_count = 0

                    elif target_pose is None:
                        # --- Relative motion: speed + RunningStatus/RunQueuedCmd + stable ---
                        status_done = False
                        if running_status is not None and running_status == 0:
                            status_done = True
                        if run_queued_cmd is not None and run_queued_cmd == 0:
                            status_done = True

                        if status_done:
                            self._motion_done_stable_count = getattr(self, '_motion_done_stable_count', 0) + 1
                            if self._motion_done_stable_count >= stable_samples:
                                logger.info("30004反馈辅助判定完成: 速度归零+运行状态完成, 连续%d次", stable_samples)
                                self._motion_done_stable_count = 0
                                self._last_motion_completion_reason = "motion_done"
                                return True
                        else:
                            self._motion_done_stable_count = 0
                    else:
                        self._motion_done_stable_count = 0
                else:
                    self._motion_done_stable_count = 0
            else:
                self._motion_done_stable_count = 0

            # --- Dashboard fallback: only when 30004 feedback is NOT fresh ---
            if snapshot_health != "ok":
                now = time.monotonic()
                feedback_age = now - snapshot_timestamp if snapshot_timestamp > 0 else 999

                # Log feedback disconnect
                if feedback_age > feedback_stale_fail_age and not _feedback_stale_logged:
                    logger.warning("30004反馈断流: %.1fs (fail_age=%.1fs), 使用Dashboard兜底", feedback_age, feedback_stale_fail_age)
                    _feedback_stale_logged = True

                robot_mode = self.get_robot_mode_fast(
                    max_age=pose_cache_max_age,
                    fallback=True,
                    dashboard_fallback_interval=dashboard_fallback_interval,
                )
                if robot_mode is not None:
                    if robot_mode == 5:
                        logger.info("运动完成 (Dashboard RobotMode=5)")
                        self.clear_error_retry_count = 0
                        self._last_motion_completion_reason = "motion_done"
                        return True
                    elif robot_mode in (7, 8):
                        elapsed = time.monotonic() - start_time
                        elapsed_second = int(elapsed)
                        if elapsed_second != last_running_log_second and elapsed_second % 2 == 0:
                            logger.debug("运行中... 已耗时: %.1f秒", elapsed)
                            last_running_log_second = elapsed_second
                    elif robot_mode == 9:
                        logger.warning("机器人出现错误，尝试自动清除报警...")
                        if auto_clear_error and self.clear_error_retry_count < 3:
                            self.clear_error_retry_count += 1
                            self.clear_error(auto_enable=False)
                            logger.warning("第%d次清除报警，等待0.5秒后继续检查...", self.clear_error_retry_count)
                            time.sleep(max(poll_interval, 0.1))
                        else:
                            logger.error("已重试3次清除报警失败，返回False")
                            self.clear_error_retry_count = 0
                            return False

            time.sleep(poll_interval)

        logger.error("等待超时 (%.1f秒)", timeout)
        return False

    def _check_arc_non_collinear(self, current, middle, target, tolerance=0.5):
        """检查三点是否共线，仅检查XYZ分量。

        Args:
            current: 起始点 [x, y, z, rx, ry, rz]
            middle: 中间点 [x, y, z, rx, ry, rz]
            target: 目标点 [x, y, z, rx, ry, rz]
            tolerance: 共线判定容差（mm），默认0.5mm

        Returns:
            True: 三点不共线，可执行圆弧运动
            False: 三点共线或起止点重合，无法执行圆弧运动
        """
        import numpy as np

        p0 = np.array(current[:3], dtype=float)
        p1 = np.array(middle[:3], dtype=float)
        p2 = np.array(target[:3], dtype=float)

        vec_02 = p2 - p0
        vec_01 = p1 - p0

        length_02 = np.linalg.norm(vec_02)
        if length_02 < 1e-6:
            logger.error("三点共线校验: 起始点与目标点重合，无法执行圆弧运动")
            return False

        cross = np.cross(vec_02, vec_01)
        distance = np.linalg.norm(cross) / length_02

        if distance < tolerance:
            logger.error(
                "三点共线校验: 中间点到起止连线的距离 %.3fmm < 容差 %.1fmm，三点共线，无法执行圆弧运动",
                distance, tolerance,
            )
            return False

        logger.debug("三点共线校验通过: 中间点偏移距离 %.3fmm", distance)
        return True

    def move_to_point(
        self,
        target_pose,
        move_type="MovJ",
        speed_percentage=None,
        middle_pose=None,
        verify_start_pose=True,
        verify_end_pose=True,
        wait_poll_interval=0.05,
        force_guard=None,
    ):
        """移动到目标点"""
        _cmd_speed = speed_percentage if speed_percentage is not None else self.current_speed
        result = validate_absolute_pose(self, target_pose, speed=_cmd_speed)
        if not result:
            logger.error("move_to_point 校验失败: %s (code=%d)", result.message, result.code)
            return False
        if not self.is_enabled:
            logger.error(" 机器人未使能")
            return False

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

        _cmd_speed = speed_percentage if speed_percentage is not None else self.current_speed
        try:
            prepared_force_guard = self.prepare_force_guard(force_guard)
        except RuntimeError as e:
            logger.error("力到位保护准备失败: %s", e)
            return False

        logger.info(f" 发送{move_type}指令...")
        _cmd_start = time.perf_counter()
        if move_type == "MovJ":
            response = self.dashboard.MovJ(x, y, z, rx, ry, rz, 0, user=self._user_index, tool=self._tool_index, v=_cmd_speed)
        elif move_type == "MovL":
            response = self.dashboard.MovL(x, y, z, rx, ry, rz, 0, user=self._user_index, tool=self._tool_index, v=_cmd_speed)
        elif move_type == "MovC":
            if not middle_pose:
                logger.error(" MovC需要提供中间点参数 middle_pose")
                return False
            # 三点共线校验
            current_pose = self.get_current_pose_from_feedback()
            if current_pose is not None:
                if not self._check_arc_non_collinear(current_pose, middle_pose, target_pose):
                    logger.error("三点共线，无法执行圆弧运动")
                    return False
            else:
                logger.warning("无法获取当前位姿，跳过三点共线校验")
            mx, my, mz, mrx, mry, mrz = middle_pose
            response = self.dashboard.MovC(x, y, z, rx, ry, rz, mx, my, mz, mrx, mry, mrz, 0, user=self._user_index, tool=self._tool_index, v=_cmd_speed)
        else:
            logger.error(f" 不支持的运动类型: {move_type}")
            return False

        logger.debug(f" 运动响应: {response}")
        _cmd_elapsed = time.perf_counter() - _cmd_start

        response_code = self.parse_response_code(response)
        if response_code != 0:
            logger.error(f" 运动指令被拒绝，响应码: {response_code}")

            if response_code == -7:
                logger.warning("  机器人处于脚本暂停状态，尝试停止脚本后重试...")
                if not self._recover_after_stop_rejected(reason="absolute motion"):
                    return False

                logger.info(" 重试发送运动指令...")
                if move_type == "MovJ":
                    response = self.dashboard.MovJ(x, y, z, rx, ry, rz, 0, user=self._user_index, tool=self._tool_index, v=_cmd_speed)
                elif move_type == "MovL":
                    response = self.dashboard.MovL(x, y, z, rx, ry, rz, 0, user=self._user_index, tool=self._tool_index, v=_cmd_speed)
                elif move_type == "MovC":
                    mx, my, mz, mrx, mry, mrz = middle_pose
                    response = self.dashboard.MovC(x, y, z, rx, ry, rz, mx, my, mz, mrx, mry, mrz, 0, user=self._user_index, tool=self._tool_index, v=_cmd_speed)

                logger.debug(f" 重试运动响应: {response}")
                response_code = self.parse_response_code(response)

                if response_code != 0:
                    logger.error(f" 重试运动指令仍然失败，响应码: {response_code}")
                    return False
                else:
                    ids = self.parse_response_ids(response)
                    self._last_command_id = ids[1] if len(ids) > 1 else None
            else:
                return False

        logger.info(" 运动指令已接受")
        if response_code == 0:
            ids = self.parse_response_ids(response)
            self._last_command_id = ids[1] if len(ids) > 1 else None

        self._motion_command_sent_time = time.monotonic()
        self._has_seen_motion_state = False

        _wait_start = time.perf_counter()
        success = self.wait_for_motion_completion(
            timeout=estimated_time + 10,
            poll_interval=wait_poll_interval,
            target_pose=target_pose,
            command_id=self._last_command_id,
            force_guard=prepared_force_guard,
        )
        _wait_elapsed = time.perf_counter() - _wait_start

        self._last_move_timing = {
            "speed_set": 0.0,
            "command_send": _cmd_elapsed,
            "motion_wait": _wait_elapsed,
        }

        if not success:
            logger.error("  运动可能未完成，强制停止...")
            self.dashboard.Stop()
            return False

        if self._last_motion_completion_reason == "force_triggered":
            logger.info("TCP力触发停止，跳过结束点校验")
            return True

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
        result = validate_absolute_pose(self, pose, speed=None)
        if not result:
            logger.error("servo_p 校验失败: %s (code=%d)", result.message, result.code)
            return False
        if not self.is_connected or not self.is_enabled:
            logger.error(" 机器人未连接或未使能，无法执行ServoP")
            return False

        # ServoP 参数最终防线
        t = max(t, 0.02)  # t 不低于 20ms (官方下限)
        aheadtime = max(20, min(100, int(aheadtime)))
        gain = max(200, min(1000, int(gain)))

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

    def move_joint_relative(self, offsets, a=20, v=50, cp=100, verify_end_pose=True, wait_poll_interval=0.05, force_guard=None):
        """关节相对运动"""
        if not self.is_connected:
            logger.error("机器人未连接，无法执行关节相对运动")
            return False
        if not self.is_enabled:
            logger.error("  机器人未使能")
            return False

        logger.info("\n" + "=" * 60)
        logger.info(" 关节相对运动详情")
        logger.info("=" * 60)
        logger.info(f" 关节偏移: {offsets}")
        logger.info(f" 加速度: {a}, 速度: {v}, CP: {cp}")
        logger.info("=" * 60)

        try:
            prepared_force_guard = self.prepare_force_guard(force_guard)
        except RuntimeError as e:
            logger.error("力到位保护准备失败: %s", e)
            return False

        logger.info(f" 发送RelJointMovJ指令...")
        response = self.dashboard.RelJointMovJ(offsets[0], offsets[1], offsets[2], offsets[3], offsets[4], offsets[5], a, v, cp)

        logger.debug(f" 运动响应: {response}")

        response_code = self.parse_response_code(response)
        if response_code != 0:
            logger.error(f" 运动指令被拒绝，响应码: {response_code}")

            if response_code == -7:
                logger.warning("  机器人处于脚本暂停状态，尝试停止脚本后重试...")
                if not self._recover_after_stop_rejected(reason="joint relative motion"):
                    return False

                logger.info(" 重试发送运动指令...")
                response = self.dashboard.RelJointMovJ(offsets[0], offsets[1], offsets[2], offsets[3], offsets[4], offsets[5], a, v, cp)

                logger.debug(f" 重试运动响应: {response}")
                response_code = self.parse_response_code(response)

                if response_code != 0:
                    logger.error(f" 重试运动指令仍然失败，响应码: {response_code}")
                    return False
                else:
                    ids = self.parse_response_ids(response)
                    self._last_command_id = ids[1] if len(ids) > 1 else None
            else:
                return False

        logger.info(" 运动指令已接受")
        ids = self.parse_response_ids(response)
        self._last_command_id = ids[1] if len(ids) > 1 else None

        self._motion_command_sent_time = time.monotonic()
        self._has_seen_motion_state = False

        estimated_time = 10
        success = self.wait_for_motion_completion(
            timeout=estimated_time + 10,
            poll_interval=wait_poll_interval,
            command_id=self._last_command_id,
            force_guard=prepared_force_guard,
        )

        if not success:
            logger.error("  运动可能未完成，强制停止...")
            self.dashboard.Stop()
            return False

        if self._last_motion_completion_reason == "force_triggered":
            logger.info("TCP力触发停止，跳过关节相对运动结束点校验")
            return True

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

    def _build_relative_command(self, offsets, coord_system, motion_type, speed=None, acceleration=None, cp=None, r=None):
        """构建相对运动命令，返回 (response, command_name)"""
        if not self.is_connected:
            logger.error("机器人未连接，无法执行相对运动")
            return None, None

        if len(offsets) < 6:
            logger.error("偏移量长度不足6")
            return None, None

        x, y, z, rx, ry, rz = offsets[:6]
        coord_system = str(coord_system or "user").lower()
        user = self._user_index
        tool = self._tool_index

        if motion_type == 'movl':
            cmd_speed = speed if speed is not None else self._cmd_speed
            cmd_accel = acceleration if acceleration is not None else self._cmd_acceleration
            command_func = self.dashboard.RelMovLTool if coord_system == "tool" else self.dashboard.RelMovLUser
            command_name = "RelMovLTool" if coord_system == "tool" else "RelMovLUser"
            if cp is not None and cp > 0:
                response = command_func(x, y, z, rx, ry, rz, v=cmd_speed, a=cmd_accel, user=user, tool=tool, cp=cp)
            elif r is not None and r > 0:
                response = command_func(x, y, z, rx, ry, rz, v=cmd_speed, a=cmd_accel, user=user, tool=tool, r=r)
            else:
                response = command_func(x, y, z, rx, ry, rz, v=cmd_speed, a=cmd_accel, user=user, tool=tool)
            return response, command_name
        else:  # movj
            cmd_speed = speed if speed is not None else self._cmd_speed
            cmd_accel = acceleration if acceleration is not None else self._cmd_acceleration
            command_func = self.dashboard.RelMovJTool if coord_system == "tool" else self.dashboard.RelMovJUser
            command_name = "RelMovJTool" if coord_system == "tool" else "RelMovJUser"
            response = command_func(x, y, z, rx, ry, rz, v=cmd_speed, a=cmd_accel, user=user, tool=tool, cp=cp)
            return response, command_name

    def move_relative(
        self,
        offsets,
        coord_system="user",
        motion_type="linear",
        speed=30,
        acceleration=20,
        cp=100,
        r=-1,
        wait_poll_interval=0.05,
        force_guard=None,
    ):
        """Relative motion without force control."""
        result = validate_relative_delta(self, offsets, coord_system=coord_system, motion_type=motion_type, speed=speed)
        if not result:
            logger.error("move_relative 校验失败: %s (code=%d)", result.message, result.code)
            return False

        offsets = [float(v) for v in list(offsets)[:6]]
        if len(offsets) < 6:
            offsets.extend([0.0] * (6 - len(offsets)))
        coord_system = str(coord_system or "user").lower()
        motion_type = str(motion_type or "linear").lower()
        speed = int(speed)
        acceleration = int(acceleration)
        cp = int(cp)
        r = int(r)

        if coord_system == "joint":
            return self.move_joint_relative(
                offsets,
                a=acceleration,
                v=speed,
                cp=cp,
                verify_end_pose=False,
                wait_poll_interval=wait_poll_interval,
                force_guard=force_guard,
            )

        logger.info(
            "相对移动: coord=%s motion=%s offsets=%s speed=%s acceleration=%s cp=%s r=%s",
            coord_system, motion_type, offsets, speed, acceleration, cp, r
        )

        try:
            prepared_force_guard = self.prepare_force_guard(force_guard)
        except RuntimeError as e:
            logger.error("力到位保护准备失败: %s", e)
            return False

        build_motion_type = 'movl' if motion_type != 'joint' else 'movj'
        response, command_name = self._build_relative_command(offsets, coord_system, build_motion_type, speed, acceleration, cp, r)
        if response is None:
            return False

        logger.debug(f"{command_name}响应: {response}")
        response_code = self.parse_response_code(response)
        if response_code != 0:
            logger.error(f"{command_name}指令被拒绝，响应码: {response_code}")
            if response_code == -7 and self._recover_after_stop_rejected(reason="relative motion"):
                response, command_name = self._build_relative_command(
                    offsets, coord_system, build_motion_type, speed, acceleration, cp, r
                )
                logger.debug(f"{command_name}重试响应: {response}")
                response_code = self.parse_response_code(response)
                if response_code != 0:
                    logger.error(f"{command_name}重试后仍被拒绝，响应码: {response_code}")
                    return False
            else:
                return False

        ids = self.parse_response_ids(response)
        self._last_command_id = ids[1] if len(ids) > 1 else None

        self._motion_command_sent_time = time.monotonic()
        self._has_seen_motion_state = False

        linear_distance = math.sqrt(offsets[0] ** 2 + offsets[1] ** 2 + offsets[2] ** 2)
        angular_distance = max(abs(offsets[3]), abs(offsets[4]), abs(offsets[5]))
        timeout = min(max(max(linear_distance / 20.0, angular_distance / 20.0) + 5.0, 5.0), 60.0)
        if not self.wait_for_motion_completion(
            timeout=timeout,
            poll_interval=wait_poll_interval,
            command_id=self._last_command_id,
            force_guard=prepared_force_guard,
        ):
            logger.error("相对移动等待完成失败")
            self.dashboard.Stop()
            return False
        return True

    def send_relative_command(self, offsets, coord_system="user", motion_type="linear",
                              speed=30, acceleration=20, cp=100, r=-1, wait=True,
                              wait_poll_interval=0.05, force_guard=None):
        """Send a relative motion command with unified logging, response parsing, and command_id tracking.

        Args:
            wait: If True, wait for motion completion (same as move_relative).
                  If False, only send the command and return (response_code, command_id).

        Returns:
            If wait=True: bool (success/failure, same as move_relative)
            If wait=False: tuple (response_code, command_id)
        """
        result = validate_relative_delta(self, offsets, coord_system=coord_system, motion_type=motion_type, speed=speed)
        if not result:
            logger.error("send_relative_command 校验失败: %s (code=%d)", result.message, result.code)
            return (result.code, None) if not wait else False

        offsets = [float(v) for v in list(offsets)[:6]]
        if len(offsets) < 6:
            offsets.extend([0.0] * (6 - len(offsets)))
        coord_system = str(coord_system or "user").lower()
        motion_type = str(motion_type or "linear").lower()
        speed = int(speed)
        acceleration = int(acceleration)
        cp = int(cp)
        r = int(r)
        try:
            prepared_force_guard = self.prepare_force_guard(force_guard) if wait else None
        except RuntimeError as e:
            logger.error("力到位保护准备失败: %s", e)
            return False

        if coord_system == "joint":
            response = self.dashboard.RelJointMovJ(
                offsets[0], offsets[1], offsets[2], offsets[3], offsets[4], offsets[5],
                a=acceleration, v=speed, cp=cp
            )
            command_name = "RelJointMovJ"
        else:
            build_motion_type = 'movl' if motion_type != 'joint' else 'movj'
            response, command_name = self._build_relative_command(offsets, coord_system, build_motion_type, speed, acceleration, cp, r)
            if response is None:
                return (1, None) if not wait else False

        logger.debug(f"{command_name}响应: {response}")
        response_code = self.parse_response_code(response)
        ids = self.parse_response_ids(response)
        command_id = ids[1] if len(ids) > 1 else None

        if response_code != 0:
            logger.error(f"{command_name}指令被拒绝，响应码: {response_code}")
            if response_code == -7 and self._recover_after_stop_rejected(reason=f"{command_name} relative command"):
                if coord_system == "joint":
                    response = self.dashboard.RelJointMovJ(
                        offsets[0], offsets[1], offsets[2], offsets[3], offsets[4], offsets[5],
                        a=acceleration, v=speed, cp=cp
                    )
                else:
                    response, command_name = self._build_relative_command(
                        offsets, coord_system, build_motion_type, speed, acceleration, cp, r
                    )
                    if response is None:
                        return (1, None) if not wait else False
                logger.debug(f"{command_name}重试响应: {response}")
                response_code = self.parse_response_code(response)
                ids = self.parse_response_ids(response)
                command_id = ids[1] if len(ids) > 1 else None
                if response_code != 0:
                    logger.error(f"{command_name}重试后仍被拒绝，响应码: {response_code}")
                    if not wait:
                        return (response_code, command_id)
                    return False
            else:
                if not wait:
                    return (response_code, command_id)
                return False

        if not wait:
            self._last_command_id = command_id
            logger.info("send_relative_command(no-wait): %s cmd_id=%s offsets=%s", command_name, command_id, offsets)
            return (response_code, command_id)

        # wait=True: same as move_relative
        self._last_command_id = command_id
        self._motion_command_sent_time = time.monotonic()
        self._has_seen_motion_state = False
        linear_distance = math.sqrt(offsets[0] ** 2 + offsets[1] ** 2 + offsets[2] ** 2)
        angular_distance = max(abs(offsets[3]), abs(offsets[4]), abs(offsets[5]))
        timeout = min(max(max(linear_distance / 20.0, angular_distance / 20.0) + 5.0, 5.0), 60.0)
        if not self.wait_for_motion_completion(
            timeout=timeout,
            poll_interval=wait_poll_interval,
            command_id=command_id,
            force_guard=prepared_force_guard,
        ):
            logger.error("相对移动等待完成失败")
            self.dashboard.Stop()
            return False
        return True

    def move_to_initial_position(self, verify_start_pose=True, verify_end_pose=True, wait_poll_interval=0.05, force_guard=None):
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
            force_guard=force_guard,
        )

        if success:
            logger.info("\n 已成功移动到初始位置!")
            return True
        else:
            logger.error("\n 移动到初始位置失败!")
            return False

    def _reset_feedback_cache_locked(self):
        self.feed_data = None
        self.last_feed_time = 0
        self.latest_pose = None
        self.latest_pose_time = 0.0
        self.latest_robot_mode = None
        self.latest_robot_mode_time = 0.0
        self.latest_feed_time = 0.0
        self.latest_tcp_speed = None
        self.latest_tcp_speed_time = 0.0
        self.latest_actual_tcp_force = None
        self.latest_actual_tcp_force_time = 0.0
        self.latest_running_status = None
        self.latest_running_status_time = 0.0
        self.latest_run_queued_cmd = None
        self.latest_run_queued_cmd_time = 0.0
        self.latest_current_command_id = None
        self.latest_current_command_id_time = 0.0
        self.latest_tool_vector_target = None
        self.latest_tool_vector_target_time = 0.0
        self.latest_q_actual = None
        self.latest_q_actual_time = 0.0
        self.latest_q_target = None
        self.latest_q_target_time = 0.0

    def start_feedback(self):
        with self._transport_lock:
            self._connection_generation += 1
            generation = self._connection_generation
        feedback = None
        try:
            feedback = DobotApiFeedBack(
                self.robot_ip,
                30004,
                connect_timeout=self._socket_connect_timeout_s,
                io_timeout=self._feedback_read_timeout_s,
            )
            self._require_current_connection_attempt(generation)
            with self._transport_lock:
                old_feedback = self.feed_four
                old_feed_thread = self.feed_thread
                self.feed_four = feedback
                self._feed_running = True
                with self.feed_lock:
                    self._reset_feedback_cache_locked()
                self.feed_thread = threading.Thread(
                    target=self._feed_loop,
                    args=(feedback, generation),
                    name=f"DobotFeedback-{generation}",
                    daemon=True,
                )
                self.feed_thread.start()
                feedback = None
            self._close_api(old_feedback)
            if old_feed_thread and old_feed_thread.is_alive():
                old_feed_thread.join(timeout=1.0)
            return True
        finally:
            self._close_api(feedback)

    def stop_feedback(self):
        with self._transport_lock:
            self._connection_generation += 1
            self._feed_running = False
            feedback = self.feed_four
            feed_thread = self.feed_thread
            self.feed_four = None
            self.feed_thread = None
        self._close_api(feedback)
        if feed_thread and feed_thread is not threading.current_thread():
            feed_thread.join(timeout=1.0)
            if feed_thread.is_alive():
                logger.warning("反馈线程未能在1秒内退出")
        with self.feed_lock:
            self._reset_feedback_cache_locked()

    def _store_feedback_packet(self, result):
        now = time.monotonic()
        pose = self._extract_pose_from_feed_data(result)
        robot_mode = self._extract_robot_mode_from_feed_data(result)
        tcp_speed = self._extract_tcp_speed_from_feed_data(result)
        actual_tcp_force = self._extract_actual_tcp_force_from_feed_data(result)
        running_status = self._extract_running_status_from_feed_data(result)
        run_queued_cmd = self._extract_run_queued_cmd_from_feed_data(result)
        current_command_id = self._extract_current_command_id_from_feed_data(result)
        tool_vector_target = self._extract_tool_vector_target_from_feed_data(result)
        q_actual = self._extract_q_actual_from_feed_data(result)
        q_target = self._extract_q_target_from_feed_data(result)
        with self.feed_lock:
            self.feed_data = result
            self.last_feed_time = now
            self.latest_feed_time = now
            if pose is not None:
                self.latest_pose = pose
                self.latest_pose_time = now
                # 视觉时间对齐：每个有效 30004 Pose 都 push 到 pose_buffer
                # 使用 perf_counter 单调时钟，与 VisionThread capture_time 对齐
                self.pose_buffer.push(time.perf_counter(), pose)
            if robot_mode is not None:
                self.latest_robot_mode = robot_mode
                self.latest_robot_mode_time = now
            if tcp_speed is not None:
                self.latest_tcp_speed = tcp_speed
                self.latest_tcp_speed_time = now
            if actual_tcp_force is not None:
                self.latest_actual_tcp_force = actual_tcp_force
                self.latest_actual_tcp_force_time = now
            if running_status is not None:
                self.latest_running_status = running_status
                self.latest_running_status_time = now
            if run_queued_cmd is not None:
                self.latest_run_queued_cmd = run_queued_cmd
                self.latest_run_queued_cmd_time = now
            if current_command_id is not None:
                self.latest_current_command_id = current_command_id
                self.latest_current_command_id_time = now
            if tool_vector_target is not None:
                self.latest_tool_vector_target = tool_vector_target
                self.latest_tool_vector_target_time = now
            if q_actual is not None:
                self.latest_q_actual = q_actual
                self.latest_q_actual_time = now
            if q_target is not None:
                self.latest_q_target = q_target
                self.latest_q_target_time = now

    def _feed_loop(self, feedback=None, generation=None):
        feedback = feedback or self.feed_four
        while self._feed_running:
            if (
                generation is not None
                and generation != self._connection_generation
            ):
                break
            try:
                result = feedback.feedBackData()
                if result is not None and len(result) > 0:
                    try:
                        magic_ok = int(result[0]["TestValue"]) == _FEEDBACK_MAGIC
                    except Exception:
                        magic_ok = False

                    if not magic_ok:
                        self._feed_packet_drops += 1
                        if self._feed_packet_drops == 1 or self._feed_packet_drops % 100 == 0:
                            logger.warning("30004反馈包校验失败(TestValue不匹配), 累计%d次", self._feed_packet_drops)
                        self._feed_error_count = 0
                        continue

                    self._store_feedback_packet(result)
                    self._feed_error_count = 0
            except Exception as e:
                if (
                    generation is not None
                    and generation != self._connection_generation
                ):
                    break
                self._feed_error_count += 1
                if self._feed_error_count <= 5 or self._feed_error_count % 50 == 0:
                    logger.warning(f" FeedBack异常(第{self._feed_error_count}次): {e}")
                if self._feed_error_count >= 100:
                    logger.error(f"  连续100次FeedBack异常，停止反馈线程")
                    if (
                        generation is None
                        or generation == self._connection_generation
                    ):
                        self._feed_running = False
                    break
                time.sleep(0.1)

    def get_feed_data(self):
        with self.feed_lock:
            return np.copy(self.feed_data) if self.feed_data is not None else None

    def get_last_feed_time(self):
        """获取最后收到反馈数据的时间戳"""
        return self.last_feed_time

    def start_modbus(self, port=502, slave_id=5):
        """启动Modbus TCP服务器"""
        if not self._acquire_control_lease():
            logger.error(self.last_error)
            return False
        if self.modbus_server and self.modbus_server.is_running():
            logger.info(" Modbus服务已在运行")
            return True

        self.modbus_server = DobotModbusServer(
            on_command_callback=self._on_modbus_command,
            on_mode_changed_callback=self._modbus_on_mode_changed,
            on_hook_type_changed_callback=self._modbus_on_hook_type_changed,
            slave_id=slave_id,
        )
        result = self.modbus_server.start(host="0.0.0.0", port=port)
        return result

    def stop_modbus(self):
        """停止Modbus TCP服务器"""
        if self.modbus_server:
            self.modbus_server.stop()
            self.modbus_server = None

    def set_modbus_program_runner(self, runner, readiness_checker=None, command_delegate=None):
        """Register flow start and side-effect-free readiness callbacks.

        PR 3: ``command_delegate`` is an optional callable with signature
        ``(cmd: int, mode: int, hook_type: int) -> bool`` invoked at the
        top of :meth:`_on_modbus_command`. Returning ``True`` short-
        circuits the controller's default dispatch so the runtime
        production state machine can fully own 40001=0/1/3 handling.
        """
        self._modbus_program_runner = runner
        self._modbus_program_readiness_checker = readiness_checker
        if command_delegate is not None:
            self._modbus_command_delegate = command_delegate

    def set_modbus_mode_changed_callback(self, callback):
        """Register a callback invoked when 40002 (mode) changes.

        PR 3: used by RuntimeAgent to detect 40002 0→1 (manual offline)
        and 1→0 (re-online) transitions. Signature:
        ``(old_mode: int, new_mode: int) -> None``.
        """
        self._modbus_on_mode_changed = callback
        # If the server is already running, patch its callback too so
        # the registration takes effect immediately.
        if self.modbus_server is not None:
            self.modbus_server._on_mode_changed = callback

    def set_modbus_hook_type_changed_callback(self, callback):
        """Register a callback invoked when 40004 (hook_type) changes.

        PR 5 Task 4: used by RuntimeAgent to emit a PLC diagnostic log
        whenever the PLC changes 40004, even when no production task is
        running. Signature: ``(old_hook: int, new_hook: int) -> None``.
        """
        self._modbus_on_hook_type_changed = callback
        # If the server is already running, patch its callback too so
        # the registration takes effect immediately.
        if self.modbus_server is not None:
            self.modbus_server._on_hook_type_changed = callback

    def abort_active_flow_for_disconnect(self, reason):
        """Stop the current flow immediately and send robot Stop off-thread."""
        flow = self._active_flow_thread
        ctx = getattr(flow, "_ctx", None) if flow is not None else None
        if ctx is not None:
            ctx.stop_event.set()
        self._write_modbus_status(STATUS_HOOK_ERR)

        with self._disconnect_stop_lock:
            if (
                self._disconnect_stop_thread is not None
                and self._disconnect_stop_thread.is_alive()
            ):
                return

            def _stop_worker():
                try:
                    if self.dashboard:
                        self.dashboard.Stop()
                except Exception:
                    logger.exception("设备断线后的后台Stop()失败")

            self._disconnect_stop_thread = threading.Thread(
                target=_stop_worker,
                name="DisconnectFlowStop",
                daemon=True,
            )
            self._disconnect_stop_thread.start()
        logger.error("流程因设备断线停止: %s", reason)

    def get_modbus_stats(self):
        cycle_stats = self.modbus_server.get_cycle_stats() if self.modbus_server else {"cycle_count": 0, "last_duration_ms": 0}
        return {
            "is_running": self.modbus_server is not None and self.modbus_server.is_running(),
            "port": self.modbus_server._port if hasattr(self.modbus_server, '_port') else 502,
            "cycle_count": cycle_stats["cycle_count"],
            "last_duration_ms": cycle_stats["last_duration_ms"],
        }

    def _update_modbus_status(self):
        """更新Modbus状态寄存器（40001 和 40002）"""
        if not self.modbus_server:
            return
        if not self.is_connected:
            return

        # 确定当前模式
        mode = MODE_AUTO
        if hasattr(self, '_modbus_mode'):
            mode = self._modbus_mode

        # 确定当前状态
        if self._modbus_status_override is not None:
            status = self._modbus_status_override
        elif not self.is_enabled:
            status = STATUS_IDLE
        else:
            feed_data = self.get_feed_data()
            if feed_data is not None:
                try:
                    robot_mode = int(feed_data["RobotMode"][0])
                    if robot_mode == 7:
                        status = STATUS_RUNNING
                    elif robot_mode == 5:
                        status = STATUS_IDLE
                    elif robot_mode in [9, 11]:
                        status = STATUS_ROBOT_ERR
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
                            self._fetch_error_detail_async(robot_mode, error_code, raw_error)
                    elif robot_mode in [2, 3, 4, 6]:
                        status = STATUS_RUNNING
                    else:
                        status = STATUS_IDLE
                    if robot_mode not in [9, 11]:
                        self._robot_alarm_recorded = False
                except Exception:
                    status = STATUS_IDLE
            else:
                status = STATUS_IDLE

        self.modbus_server.update_status_registers(status=status, mode=mode)

    def _write_modbus_status(self, status, mode=None):
        if mode is None:
            mode = getattr(self, '_modbus_mode', MODE_AUTO)
        if self._runtime_recovery_required:
            status = STATUS_HOOK_ERR
        self._modbus_status_override = status
        if self.modbus_server:
            self.modbus_server.update_status_registers(status=status, mode=mode)

    def ensure_robot_ready_for_motion(self, auto_enable=True, feedback_max_age=0.5):
        """Ensure robot is connected, feedback is fresh, alarm-free, and enabled."""
        if not self.is_connected or self.dashboard is None:
            self.last_error = "机器人未连接"
            self.record_alarm("运动前检查", "DISCONNECTED", "故障", self.last_error)
            return False

        if self.software_emergency_active:
            self.last_error = "软件急停未解除"
            self.record_alarm("运动前检查", "SOFTWARE_ESTOP", "故障", self.last_error)
            return False

        feedback = self.get_feedback_health(max_age=feedback_max_age)
        if feedback.get("health") != "ok":
            self.last_error = f"机器人反馈不健康: {feedback.get('health')}"
            self.record_alarm("运动前检查", "FEEDBACK_STALE", "故障", self.last_error)
            return False

        state = self.get_motion_safety_state()
        if state.error_status != 0 or state.robot_mode in (9, 11):
            self.last_error = f"机器人报警: error_status={state.error_status}, robot_mode={state.robot_mode}"
            self.record_alarm("运动前检查", "ROBOT_ALARM", "故障", self.last_error)
            return False

        if state.robot_mode in (5, 7):
            self.is_enabled = True

        if self.is_enabled:
            self.last_error = ""
            return True

        if not auto_enable:
            self.last_error = "机器人未使能"
            self.record_alarm("运动前检查", "NOT_ENABLED", "故障", self.last_error)
            return False

        if not self.enable_robot():
            self.last_error = self.last_error or "机器人自动使能失败"
            self.record_alarm("运动前检查", "ENABLE_FAILED", "故障", self.last_error)
            return False

        self.last_error = ""
        return True

    def mark_modbus_program_finished(self, success, mode=MODE_AUTO, failure_status=None):
        if success:
            self._modbus_hook_status = 2
            self._last_fault_code = 0
            self._write_modbus_status(STATUS_HOOK_OK, mode=mode)
        else:
            self._modbus_hook_status = 3
            self._write_modbus_status(failure_status or STATUS_HOOK_ERR, mode=mode)

    def reset_modbus_status_to_standby(self, mode=MODE_AUTO):
        self._modbus_hook_status = 0
        self._write_modbus_status(STATUS_STANDBY, mode=mode)

    def reset_modbus_status_to_idle(self, mode=MODE_AUTO):
        self._modbus_hook_status = 0
        self._write_modbus_status(STATUS_IDLE, mode=mode)

    def begin_modbus_delay_wait(self):
        """Publish 40001=5 and arm 40001=1 as the current delay release signal."""
        with self._modbus_flow_state_lock:
            self._modbus_delay_release_event.clear()
            self._modbus_delay_waiting = True
        self._write_modbus_status(STATUS_DELAY_WAIT)

    def is_modbus_delay_released(self):
        return self._modbus_delay_release_event.is_set()

    def end_modbus_delay_wait(self, restore_running=True):
        """Disarm delay release and restore 40001=4 while the flow continues."""
        with self._modbus_flow_state_lock:
            self._modbus_delay_waiting = False
            self._modbus_delay_release_event.clear()
        if restore_running and self._active_flow_thread is not None:
            self._write_modbus_status(STATUS_RUNNING)

    def _release_modbus_delay_if_waiting(self):
        with self._modbus_flow_state_lock:
            if not self._modbus_delay_waiting:
                return False
            self._modbus_delay_release_event.set()
            return True

    def set_runtime_recovery_required(self, required=True, on_cleared=None):
        self._runtime_recovery_required = bool(required)
        if on_cleared is not None:
            self._runtime_recovery_cleared_callback = on_cleared
        if required:
            self._write_modbus_status(STATUS_HOOK_ERR)

    def set_runtime_maintenance(self, active=True):
        """Block PLC motion commands while Runtime is in maintenance."""
        self._runtime_maintenance = bool(active)
        if self._runtime_maintenance:
            self._write_modbus_status(STATUS_IDLE, mode=MODE_MANUAL)

    def _clear_runtime_recovery_required(self):
        self._runtime_recovery_required = False
        callback = self._runtime_recovery_cleared_callback
        if callback is not None:
            try:
                callback()
            except Exception:
                logger.exception("运行时恢复锁清除回调失败")

    def _on_modbus_command(self, cmd, mode=MODE_AUTO, hook_type=HOOK_TYPE_LOW):
        """Dispatch 40001 according to flow context.

        During normal flow execution only 0 is accepted. During a delay wait,
        0 stops and 1 releases the delay. Outside a flow, 1 resets and 3 starts.
        hook_type 来自 40004 寄存器，仅转发给 Runtime callback，不在此决定 flow_id。
        """
        logger.info("收到Modbus命令: cmd=%d, mode=%d, hook_type=%d", cmd, mode, hook_type)
        self._modbus_mode = mode
        self._last_modbus_command = int(cmd)
        self._last_modbus_command_time = time.monotonic()
        # PR 3: delegate to the runtime production state machine first.
        # The delegate returns True when it fully handled the command
        # (e.g. cmd=3 in auto mode always goes through the state machine;
        # cmd=0 only when state=RUNNING; cmd=1 only when state is
        # HOLDING_HOOK/PAUSED/ERROR/MANUAL_OFFLINE). Returning False
        # falls through to the controller's default dispatch below.
        delegate = self._modbus_command_delegate
        if delegate is not None:
            try:
                handled = bool(delegate(cmd, mode, hook_type))
            except Exception:
                logger.exception("modbus command delegate raised; falling through to default handling")
                handled = False
            if handled:
                return
        if self._runtime_recovery_required:
            if cmd == CMD_STOP:
                self._modbus_stop_immediate(mode=mode)
                self._clear_runtime_recovery_required()
                self._write_modbus_status(STATUS_IDLE, mode=mode)
            else:
                logger.warning("运行时恢复锁生效，忽略40001=%d；请先下发0", cmd)
                self._write_modbus_status(STATUS_HOOK_ERR, mode=mode)
            return
        if cmd == CMD_STOP:
            self._modbus_stop_immediate(
                mode=mode,
                auto_enable=not self._runtime_maintenance,
            )
            return
        if self._runtime_maintenance:
            logger.info(
                "Runtime维护模式下忽略Modbus运动命令: cmd=%d",
                cmd,
            )
            self._write_modbus_status(STATUS_IDLE, mode=MODE_MANUAL)
            return

        flow_active = self._active_flow_thread is not None
        if flow_active:
            if cmd == CMD_RESET and self._release_modbus_delay_if_waiting():
                logger.info("流程延时等待中收到40001=1，放行下一步")
                self._write_modbus_status(STATUS_DELAY_WAIT, mode=mode)
            else:
                with self._modbus_flow_state_lock:
                    delay_waiting = self._modbus_delay_waiting
                allowed = "0或1" if delay_waiting else "0"
                logger.info("流程运行中忽略40001=%d；当前阶段仅接受%s", cmd, allowed)
                self._write_modbus_status(
                    STATUS_DELAY_WAIT if delay_waiting else STATUS_RUNNING,
                    mode=mode,
                )
            return

        if mode == MODE_MANUAL:
            logger.info("手动模式下忽略Modbus命令: cmd=%d", cmd)
            return
        if cmd == CMD_HOOK:
            self._modbus_run_edited_program(mode=mode, hook_type=hook_type)
            return
        if not self.is_connected:
            logger.info("机械臂未连接，仅记录命令不执行: cmd=%d, mode=%d", cmd, mode)
            if cmd == CMD_RESET:
                self.record_alarm("Modbus命令", "DISCONNECTED", "故障", "机械臂未连接，命令被拒绝")
                self._write_modbus_status(STATUS_ROBOT_ERR, mode=mode)
            return

        if cmd == CMD_RESET:
            # 复位回原点：移动到 initial_point，完成后写 40001=2
            if not self._modbus_dispatch_motion(self._modbus_move_initial, "回原点"):
                self.record_alarm("Modbus回原点", "BUSY", "故障", "上一条Modbus运动仍在执行，回原点被拒绝")
                self._write_modbus_status(STATUS_HOOK_ERR, mode=mode)
        else:
            logger.warning("未知Modbus命令: %d", cmd)

    def _modbus_dispatch_motion(self, func, name):
        """Dispatch Modbus motion command to a separate thread."""
        with self._modbus_exec_lock:
            if self._modbus_exec_thread is not None and self._modbus_exec_thread.is_alive():
                logger.warning("Modbus运动命令'%s'被拒绝: 上一次运动仍在执行", name)
                return False
            self._modbus_exec_thread = threading.Thread(target=func, daemon=True)
            self._modbus_exec_thread.start()
            return True

    def _modbus_stop_immediate(self, mode=MODE_AUTO, auto_enable=True):
        """Immediately stop current robot/flow motion for external 40001=0."""
        logger.info("Modbus停止命令: 立即停止机械臂并保持40001=0")

        if self._active_flow_thread is not None and hasattr(self._active_flow_thread, '_ctx') and self._active_flow_thread._ctx is not None:
            self._active_flow_thread._ctx.stop_event.set()
        with self._modbus_flow_state_lock:
            self._modbus_delay_waiting = False
            self._modbus_delay_release_event.set()

        if self.is_connected and self.dashboard:
            try:
                response = self.dashboard.Stop()
                response_code = self.parse_response_code(response)
                if response_code not in (0, None):
                    logger.warning("Modbus Stop()响应码非0: %s, response=%s", response_code, response)
            except Exception as e:
                logger.warning("Modbus Stop()失败，尝试Pause(): %s", e)
                try:
                    self.dashboard.Pause()
                except Exception as pause_error:
                    logger.error("Modbus Pause()兜底失败: %s", pause_error)

        self._clear_faults_for_modbus_zero(auto_enable=auto_enable)
        self._modbus_hook_status = 0
        self._write_modbus_status(STATUS_IDLE, mode=mode)

    def _clear_faults_for_modbus_zero(self, auto_enable=True):
        """Best-effort cleanup for 40001=0 while keeping Modbus status at 0."""
        had_software_estop = bool(self.software_emergency_active)
        self.clear_error_retry_count = 0
        self._last_fault_code = 0
        self._robot_alarm_recorded = False
        self._last_motion_completion_reason = None
        self._last_force_guard_event = None
        self.last_error = ""

        if not self.is_connected or self.dashboard is None:
            self.software_emergency_active = False
            logger.warning("Modbus 0清故障跳过: 机器人未连接")
            return False

        cleanup_ok = True
        if had_software_estop:
            try:
                response = self.dashboard.EmergencyStop(0)
                code = self.parse_response_code(response)
                if code not in (0, None):
                    cleanup_ok = False
                    logger.warning("Modbus 0解除软件急停响应码非0: %s, response=%s", code, response)
            except Exception as e:
                cleanup_ok = False
                logger.warning("Modbus 0解除软件急停失败: %s", e)
            self.software_emergency_active = False

        clear_ok = False
        for attempt in range(1, 4):
            try:
                response = self.dashboard.ClearError()
                code = self.parse_response_code(response)
                if code not in (0, None):
                    cleanup_ok = False
                    logger.warning("Modbus 0 ClearError响应码非0: attempt=%d code=%s response=%s", attempt, code, response)
                    time.sleep(0.1)
                    continue

                time.sleep(0.1)
                state = self.get_motion_safety_state()
                if state.error_status == 0 and state.robot_mode not in (9, 11):
                    clear_ok = True
                    break
                cleanup_ok = False
                logger.warning(
                    "Modbus 0 ClearError后机器人仍报警: attempt=%d error_status=%s robot_mode=%s",
                    attempt, state.error_status, state.robot_mode,
                )
            except Exception as e:
                cleanup_ok = False
                logger.warning("Modbus 0 ClearError失败: attempt=%d error=%s", attempt, e)
            time.sleep(0.1)

        if not clear_ok:
            self.last_error = "40001=0 已停止，但仍有不可清除或未解除的机器人故障"
            self.record_alarm(
                "Modbus停止",
                "CLEAR_FAILED",
                "故障",
                self.last_error,
                "检查物理急停、安全门、碰撞保护和机器人报警详情，处理后重新下发0或复位",
            )
            return False

        if auto_enable:
            if self.enable_robot():
                self.last_error = ""
            else:
                cleanup_ok = False
                self.last_error = self.last_error or "40001=0 清故障后自动使能失败"
                self.record_alarm("Modbus停止", "ENABLE_FAILED", "故障", self.last_error)

        return cleanup_ok

    def _modbus_run_edited_program(self, mode=MODE_AUTO, hook_type=HOOK_TYPE_LOW):
        with self._modbus_exec_lock:
            modbus_motion_busy = self._modbus_exec_thread is not None and self._modbus_exec_thread.is_alive()
        if modbus_motion_busy:
            logger.info("Modbus流程准备已在后台执行，忽略重复40001=3")
            self._write_modbus_status(STATUS_RUNNING, mode=mode)
            return

        runner = self._modbus_program_runner
        if runner is None:
            logger.error("Modbus执行流程失败: 未注册运动编辑流程runner")
            self.record_alarm("Modbus执行流程", "NO_RUNNER", "故障", "未注册运动编辑流程runner")
            self._write_modbus_status(STATUS_HOOK_ERR, mode=mode)
            return

        ready, readiness_message = self._check_modbus_program_readiness()
        if not ready:
            logger.error("Modbus执行流程快速检查失败: %s", readiness_message)
            self.record_alarm(
                "Modbus执行流程",
                "DEVICE_NOT_READY",
                "故障",
                readiness_message,
            )
            self._write_modbus_status(STATUS_HOOK_ERR, mode=mode)
            return

        self._modbus_hook_status = 1
        self._write_modbus_status(STATUS_RUNNING, mode=mode)
        if not self._modbus_dispatch_motion(
            lambda: self._prepare_and_start_modbus_program(runner, mode, hook_type),
            "执行流程准备",
        ):
            self._write_modbus_status(STATUS_HOOK_ERR, mode=mode)

    def _check_modbus_program_readiness(self):
        checker = self._modbus_program_readiness_checker
        if checker is None:
            ready = bool(self.is_connected)
            return ready, "设备已就绪" if ready else "机器人未连接"
        try:
            result = checker()
        except Exception as exc:
            logger.exception("Modbus流程就绪检查异常")
            return False, f"流程就绪检查异常: {exc}"
        ready = bool(getattr(result, "ok", result))
        message = str(getattr(result, "message", "设备未就绪"))
        return ready, message

    def _prepare_and_start_modbus_program(self, runner, mode, hook_type=HOOK_TYPE_LOW):
        if not self.ensure_robot_ready_for_motion(auto_enable=True):
            message = self.last_error or "机器人未就绪"
            logger.error("Modbus流程后台准备失败: %s", message)
            self.record_alarm("Modbus执行流程", "PREPARE_FAILED", "故障", message)
            self._write_modbus_status(STATUS_HOOK_ERR, mode=mode)
            return

        ready, readiness_message = self._check_modbus_program_readiness()
        if not ready:
            logger.error("Modbus流程启动前设备状态已变化: %s", readiness_message)
            self.record_alarm(
                "Modbus执行流程",
                "DEVICE_CHANGED",
                "故障",
                readiness_message,
            )
            self._write_modbus_status(STATUS_HOOK_ERR, mode=mode)
            return

        try:
            accepted = bool(self._invoke_program_runner(runner, hook_type))
        except Exception as e:
            logger.error("Modbus执行流程runner异常: %s", e)
            self.record_alarm("Modbus执行流程", "RUNNER_EXCEPTION", "故障", "运动编辑流程runner异常", raw=e)
            self._write_modbus_status(STATUS_HOOK_ERR, mode=mode)
            return

        if not accepted:
            logger.warning("Modbus执行流程请求被拒绝")
            self.record_alarm("Modbus执行流程", "REJECTED", "故障", "运动编辑流程请求被拒绝")
            self._write_modbus_status(STATUS_HOOK_ERR, mode=mode)
            return

    @staticmethod
    def _invoke_program_runner(runner, hook_type):
        """调用运动编辑流程 runner，当 runner 签名接受 hook_type 时转发钩子类型。

        PR 1 协议层：仅转发 hook_type，不在此决定 low_hook/high_hook flow_id。
        旧版 runner（无 hook_type 参数）保持无参调用以维持向后兼容。
        """
        try:
            sig = inspect.signature(runner)
        except (TypeError, ValueError):
            return runner()
        for param in sig.parameters.values():
            if param.name == "hook_type" or param.kind == inspect.Parameter.VAR_KEYWORD:
                return runner(hook_type=hook_type)
        return runner()

    def _modbus_move_initial(self):
        """Move to initial_point for external 40001=1 reset command, then report 40001=2."""
        if not self.ensure_robot_ready_for_motion(auto_enable=True):
            self.record_alarm("Modbus回原点", "ROBOT_NOT_READY", "故障", self.last_error or "机器人未就绪")
            self._write_modbus_status(STATUS_ROBOT_ERR)
            return
        if not self.acquire_motion("modbus"):
            logger.warning("流程运行中，Modbus回原点被拒绝")
            self.record_alarm("Modbus回原点", "BUSY", "故障", "流程运行中，回原点被拒绝")
            self._write_modbus_status(STATUS_HOOK_ERR)
            return
        try:
            self.initial_pose = get_initial_point()
            if not self.initial_pose:
                logger.error("Modbus回原点失败: initial_point 不存在")
                self.record_alarm("Modbus回原点", "NO_INITIAL_POINT", "故障", "initial_point 不存在")
                self._write_modbus_status(STATUS_HOOK_ERR)
                return

            self._modbus_hook_status = 1
            self._write_modbus_status(STATUS_RUNNING)
            success = self.move_to_point(
                self.initial_pose,
                move_type="MovJ",
                speed_percentage=self.current_speed or 20,
                verify_start_pose=False,
                verify_end_pose=False,
            )
            if success:
                self._last_fault_code = 0
                self.reset_modbus_status_to_standby()
                logger.info("Modbus回原点完成，已到达 initial_point")
            else:
                logger.error("Modbus回原点失败: 移动到 initial_point 失败")
                self.record_alarm("Modbus回原点", "MOVE_FAILED", "故障", "移动到 initial_point 失败")
                self._write_modbus_status(STATUS_HOOK_ERR)
        except Exception as e:
            logger.error("Modbus回原点异常: %s", e)
            self.record_alarm("Modbus回原点", "EXCEPTION", "故障", "回原点执行异常", raw=e)
            self._write_modbus_status(STATUS_HOOK_ERR)
        finally:
            self.release_motion("modbus")

    def _modbus_reset(self):
        """复位：清除故障、使能、移动到待机位，完成后写 40001=2"""
        if not self.is_connected:
            return
        if not self.acquire_motion("modbus"):
            logger.warning("流程运行中，Modbus复位被拒绝")
            self._modbus_status_override = STATUS_HOOK_ERR
            self.record_alarm("Modbus复位", "BUSY", "故障", "流程运行中，复位被拒绝")
            if self.modbus_server:
                self.modbus_server.update_status_registers(status=STATUS_HOOK_ERR, mode=MODE_AUTO)
            return
        try:
            self._modbus_status_override = STATUS_RUNNING
            if self.modbus_server:
                self.modbus_server.update_status_registers(status=STATUS_RUNNING, mode=getattr(self, '_modbus_mode', MODE_AUTO))
            # 清除故障
            self.clear_error(auto_enable=True)
            self._modbus_status_override = None
            self._modbus_hook_status = 0
            self._last_fault_code = 0
            # 移动到待机位
            pose = self.initial_pose
            if pose:
                success = self.move_to_point(
                    pose,
                    move_type="MovJ",
                    speed_percentage=self.current_speed or 20,
                    verify_start_pose=False,
                    verify_end_pose=False,
                )
                if not success:
                    logger.error("复位：移动到待机位失败")
                    self._modbus_status_override = STATUS_ROBOT_ERR
                    self.record_alarm("Modbus复位", "MOVE_FAILED", "故障", "移动到待机位失败")
                else:
                    # 复位完成，写 40001=2（待机）
                    self._modbus_status_override = STATUS_STANDBY
                    logger.info("复位完成，待机位准备好")
        except Exception as e:
            logger.error("Modbus复位失败: %s", e)
            self._modbus_status_override = STATUS_ROBOT_ERR
            self.record_alarm("Modbus复位", "EXCEPTION", "故障", "Modbus复位失败", raw=e)
        finally:
            self.release_motion("modbus")

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

    def _emergency_stop_direct(self, mode=1):
        """Send EmergencyStop via independent temporary Dashboard connection.

        This avoids being blocked by the main Dashboard connection's __globalLock.
        Returns True if command was sent successfully, False otherwise.
        """
        try:
            temp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            temp_socket.settimeout(3.0)
            temp_socket.connect((self.robot_ip, 29999))
            cmd = f"EmergencyStop({mode})"
            temp_socket.sendall(cmd.encode('utf-8') + b";")
            try:
                response = temp_socket.recv(1024).decode('utf-8').strip()
            except socket.timeout:
                response = ""
            temp_socket.close()

            if not response:
                logger.warning("急停独立连接已发送但未确认: EmergencyStop(%d)", mode)
                return True

            code = self.parse_response_code(response)
            if code == 0:
                logger.info("急停独立连接成功: EmergencyStop(%d), 响应=%s", mode, response)
                return True
            else:
                logger.warning("急停独立连接响应码非0: EmergencyStop(%d), code=%s, 响应=%s", mode, code, response)
                return False
        except Exception as e:
            logger.warning("急停独立连接发送失败: %s", e)
            return False

    def emergency_stop(self):
        if not self.is_connected:
            logger.error("❌ 机器人未连接，无法软件急停")
            self.record_alarm("软件急停", "DISCONNECTED", "故障", "机器人未连接，无法执行软件急停")
            return False

        # Immediately mark as active - don't wait for Dashboard response
        self.software_emergency_active = True
        self._modbus_status_override = 5
        self.is_enabled = False
        self._last_speed_factor = None

        # Signal active flow thread to stop immediately
        if self._active_flow_thread is not None and hasattr(self._active_flow_thread, '_ctx') and self._active_flow_thread._ctx is not None:
            self._active_flow_thread._ctx.stop_event.set()

        # Try independent connection first (avoids __globalLock blocking)
        direct_ok = self._emergency_stop_direct(mode=1)
        if not direct_ok:
            # Fallback to main Dashboard connection
            try:
                old_timeout = self.dashboard.socket_dobot.gettimeout()
                self.dashboard.socket_dobot.settimeout(2.0)
                try:
                    response = self.dashboard.EmergencyStop(1)
                    response_code = self.parse_response_code(response)
                    if response_code == 0:
                        direct_ok = True
                    else:
                        logger.warning("软件急停主连接响应码非0: %s", response_code)
                finally:
                    self.dashboard.socket_dobot.settimeout(old_timeout)
            except Exception as e:
                logger.warning("软件急停主连接异常: %s", e)

        if not direct_ok:
            logger.error("软件急停所有连接方式均失败")
            self.record_alarm("软件急停", "ALL_FAILED", "故障", "软件急停独立连接和主连接均失败")

        if self.modbus_server:
            self.modbus_server.update_status_registers(status=STATUS_ROBOT_ERR, mode=MODE_AUTO)

        self.record_alarm("软件急停", "0", "急停", "软件急停信号已触发", "复位软件急停信号后清除报警并重新使能", "")
        logger.warning("软件急停已触发 (独立连接=%s)", "成功" if direct_ok else "失败")
        return True

    def release_emergency_stop(self):
        if not self.is_connected:
            logger.error("❌ 机器人未连接，无法解除软件急停")
            self.record_alarm("解除软件急停", "DISCONNECTED", "故障", "机器人未连接，无法解除软件急停")
            return False

        # Try independent connection first
        direct_ok = self._emergency_stop_direct(mode=0)
        if not direct_ok:
            # Fallback to main Dashboard connection
            try:
                old_timeout = self.dashboard.socket_dobot.gettimeout()
                self.dashboard.socket_dobot.settimeout(2.0)
                try:
                    response = self.dashboard.EmergencyStop(0)
                    response_code = self.parse_response_code(response)
                    if response_code == 0:
                        direct_ok = True
                    else:
                        logger.warning("解除急停主连接响应码非0: %s", response_code)
                finally:
                    self.dashboard.socket_dobot.settimeout(old_timeout)
            except Exception as e:
                logger.warning("解除急停主连接异常: %s, 尝试独立连接", e)

        if not direct_ok:
            logger.error("解除急停所有连接方式均失败")
            self.record_alarm("解除软件急停", "ALL_FAILED", "故障", "解除软件急停独立连接和主连接均失败")
            return False

        self.software_emergency_active = False
        if self._modbus_status_override == 5:
            self._modbus_status_override = None
        if self.modbus_server:
            self.modbus_server.update_status_registers(status=STATUS_STANDBY, mode=MODE_AUTO)
        logger.info("软件急停信号已解除 (独立连接=%s)", "成功" if direct_ok else "失败")
        return True

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

    def _modbus_auto_hook(self):
        """执行自动提钩控制流程（状态机：3→4→5 或 3→4→110）"""
        if not self.is_connected:
            return
        if not self.acquire_motion("modbus"):
            logger.warning("流程运行中，自动提钩被拒绝")
            self._modbus_status_override = STATUS_HOOK_ERR
            self.record_alarm("Modbus提钩", "BUSY", "故障", "流程运行中，提钩被拒绝")
            if self.modbus_server:
                self.modbus_server.update_status_registers(status=STATUS_HOOK_ERR, mode=MODE_AUTO)
            return
        try:
            # 从 config.json 读取提钩目标
            target = get_hook_target()
            speed_mm_s = float(target.get("speed_mm_s", 50.0))
            speed_mm_s = min(max(speed_mm_s, 1.0), 1000.0)
            speed_pct = min(int(speed_mm_s / 10.0), 100)
            speed_pct = max(speed_pct, 1)

            target_pose = [
                target.get("x", 0.0),
                target.get("y", 0.0),
                target.get("z", 0.0),
                target.get("rx", 0.0),
                target.get("ry", 0.0),
                target.get("rz", 0.0),
            ]

            # 运动安全校验
            result = validate_absolute_pose(self, target_pose)
            if not result:
                logger.error("提钩目标校验失败: %s (code=%d)", result.message, result.code)
                self._modbus_hook_status = 3
                self._modbus_status_override = STATUS_HOOK_ERR
                self.record_alarm("Modbus提钩", str(result.code), "故障", f"提钩目标校验失败: {result.message}")
                if self.modbus_server:
                    self.modbus_server.update_status_registers(status=STATUS_HOOK_ERR, mode=MODE_AUTO)
                return

            # 设置状态：运行中 (40001=4)
            self._modbus_hook_status = 1
            self._modbus_status_override = STATUS_RUNNING
            if self.modbus_server:
                self.modbus_server.update_status_registers(status=STATUS_RUNNING, mode=MODE_AUTO)

            # 执行运动到目标位姿
            success = self.move_to_point(
                target_pose,
                move_type="MovJ",
                speed_percentage=speed_pct,
                verify_start_pose=False,
                verify_end_pose=False,
            )

            if not success:
                # 提钩失败 (40001=110)
                self._modbus_hook_status = 3
                self._modbus_status_override = STATUS_HOOK_ERR
                self.record_alarm("Modbus提钩", "REJECTED", "故障", "提钩运动指令被拒绝或超时")
                if self.modbus_server:
                    self.modbus_server.update_status_registers(status=STATUS_HOOK_ERR, mode=MODE_AUTO)
            else:
                # 提钩OK (40001=5)
                self._modbus_hook_status = 2
                self._modbus_status_override = STATUS_HOOK_OK
                self._last_fault_code = 0
                if self.modbus_server:
                    self.modbus_server.update_status_registers(status=STATUS_HOOK_OK, mode=MODE_AUTO)
                logger.info("自动提钩流程完成")
        except Exception as e:
            logger.error("自动提钩失败: %s", e)
            self._modbus_hook_status = 3
            self._modbus_status_override = STATUS_HOOK_ERR
            self.record_alarm("Modbus提钩", "EXCEPTION", "故障", "提钩执行异常", raw=e)
            if self.modbus_server:
                self.modbus_server.update_status_registers(status=STATUS_HOOK_ERR, mode=MODE_AUTO)
        finally:
            self.release_motion("modbus")

    def close(self):
        self.stop_feedback()
        if self.dashboard:
            self.dashboard.close()
        self.release_control_lease()
