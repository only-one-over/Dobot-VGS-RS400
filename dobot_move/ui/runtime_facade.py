"""RuntimeFacade: 同步外观，封装 GUI 异步 Runtime IPC 调用。

每个方法返回 ``(success: bool, message: str)`` 元组，使 GUI 槽函数可以
更新状态栏并向调用方回传布尔结果，同时不阻塞 Qt 事件循环。实际的 IPC
发送通过 ``send_ipc_func`` 走 ``RuntimeIpcRequestThread`` 异步通道；
Runtime 侧的错误随后通过既有的完成回调抵达（调试面板 / 状态栏）。

渐进式策略：Runtime 端尚未实现的命令（如 ``enable_robot``、
``connect_camera``、``start_modbus`` 等）仍照常发送，Runtime 会返回
``unknown_command`` 错误并由既有完成处理器显示。当 Runtime 后续补充
命令处理器时，本外观无需改动。
"""
from __future__ import annotations

from typing import Any, Callable, Optional


class RuntimeFacade:
    """同步外观，包装 GUI 既有的异步 Runtime IPC 发送逻辑。

    Parameters
    ----------
    ipc_client:
        ``RuntimeIpcClient`` 实例（保留引用，供未来同步查询使用）。
    send_ipc_func:
        ``gui_app._send_runtime_ipc`` 绑定方法，异步发送，立即返回。
    is_online_func:
        返回 Runtime 是否在线的零参可调用对象。
    send_stop_func:
        ``gui_app._send_runtime_ipc_stop`` 绑定方法，走独立 Stop 通道
        （可选）；未提供时 ``safe_stop`` 退回普通通道。
    """

    def __init__(
        self,
        ipc_client: Any,
        send_ipc_func: Callable[..., Any],
        is_online_func: Callable[[], bool],
        send_stop_func: Optional[Callable[..., Any]] = None,
    ):
        self._ipc_client = ipc_client
        self._send_ipc = send_ipc_func
        self._is_online = is_online_func
        self._send_stop = send_stop_func

    # -- 内部辅助 --------------------------------------------------------

    def _send(
        self,
        command: str,
        data: Optional[dict] = None,
        action_name: str = "",
    ) -> tuple[bool, str]:
        """发送一条 IPC 命令，返回 ``(success, message)``。

        不抛异常：离线或发送失败都包成 ``(False, msg)`` 返回。
        """
        try:
            if not self._is_online():
                return False, f"{action_name}失败：Runtime 离线"
            self._send_ipc(command, data)
            return True, f"{action_name}命令已发送"
        except Exception as exc:
            return False, f"{action_name}失败：{exc}"

    # -- 机器人控制 ------------------------------------------------------

    def enable_robot(self) -> tuple[bool, str]:
        return self._send("enable_robot", action_name="使能机器人")

    def disable_robot(self) -> tuple[bool, str]:
        return self._send("disable_robot", action_name="下使能机器人")

    def clear_alarms(self) -> tuple[bool, str]:
        return self._send("clear_alarms", action_name="清除故障")

    def connect_robot(self, ip: Optional[str] = None) -> tuple[bool, str]:
        data = {"ip": ip} if ip else None
        return self._send("connect_robot", data, action_name="连接机器人")

    def set_collision_level(self, level: Optional[int] = None) -> tuple[bool, str]:
        data = {"level": level} if level is not None else None
        return self._send("set_collision_level", data, action_name="设置碰撞等级")

    def safe_stop(self) -> tuple[bool, str]:
        action_name = "安全停止"
        try:
            if not self._is_online():
                return False, f"{action_name}失败：Runtime 离线"
            if self._send_stop is not None:
                self._send_stop("safe_stop")
            else:
                self._send_ipc("safe_stop")
            return True, f"{action_name}命令已发送"
        except Exception as exc:
            return False, f"{action_name}失败：{exc}"

    # -- 运动 ------------------------------------------------------------

    def move_to_point(
        self,
        name: str,
        motion_type: str = "MovJ",
        speed: float = 10.0,
    ) -> tuple[bool, str]:
        data = {
            "point_name": name,
            "motion_type": motion_type,
            "speed": speed,
        }
        return self._send("move_to_point", data, action_name="运动到点位")

    def move_to_initial_position(self) -> tuple[bool, str]:
        return self._send(
            "move_to_point",
            {"point_name": "initial_point", "motion_type": "MovJ", "speed": 10.0},
            action_name="回到初始位置",
        )

    def get_current_pose(self) -> tuple[bool, str]:
        return self._send("get_current_pose", action_name="获取当前位置")

    def get_point(self, name: Optional[str] = None) -> tuple[bool, str]:
        data = {"point_name": name} if name else None
        return self._send("get_point", data, action_name="读取当前点位")

    # -- 相机 ------------------------------------------------------------

    def connect_camera(self, cam_type: str) -> tuple[bool, str]:
        return self._send(
            "connect_camera",
            {"camera_type": cam_type},
            action_name=f"连接 {cam_type}",
        )

    def disconnect_camera(self, cam_type: str) -> tuple[bool, str]:
        return self._send(
            "disconnect_camera",
            {"camera_type": cam_type},
            action_name=f"断开 {cam_type}",
        )

    def camera_test(self, cam_type: str) -> tuple[bool, str]:
        command = "test_d405" if cam_type == "D405" else "test_d435i"
        return self._send(command, action_name=f"相机测试 {cam_type}")

    def open_realtime_feedback(self) -> tuple[bool, str]:
        return self._send("get_vision_snapshot", action_name="实时反馈")

    # -- 调试流程 --------------------------------------------------------

    def run_step(self, module: Any) -> tuple[bool, str]:
        return self._send("run_step", {"module": module}, action_name="单步执行")

    def run_flow(self, flow_id: Optional[str] = None) -> tuple[bool, str]:
        data = {"flow_id": flow_id} if flow_id else None
        return self._send("start_debug_flow", data, action_name="运行流程")

    def pause_flow(self) -> tuple[bool, str]:
        return self._send("pause_debug_flow", action_name="暂停流程")

    def resume_flow(self) -> tuple[bool, str]:
        return self._send("resume_debug_flow", action_name="继续流程")

    def stop_flow(self) -> tuple[bool, str]:
        return self._send("stop_debug_flow", action_name="停止流程")

    def clear_alarm_history(self) -> tuple[bool, str]:
        return self._send("clear_alarm_history", action_name="清空报警历史")

    # -- Modbus ----------------------------------------------------------

    def start_modbus(self) -> tuple[bool, str]:
        return self._send("start_modbus", action_name="启动 Modbus 服务")

    def stop_modbus(self) -> tuple[bool, str]:
        return self._send("stop_modbus", action_name="停止 Modbus 服务")
