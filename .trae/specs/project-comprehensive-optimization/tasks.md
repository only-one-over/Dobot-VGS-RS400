# Tasks

- [x] Task 1: 创建日志配置模块并初始化
  - [x] SubTask 1.1: 在 `dobot_move/` 下创建 `logging_config.py`，定义 `setup_logging(level=logging.INFO)` 函数，配置统一格式 `[%(name)s] %(levelname)s: %(message)s`，输出到控制台
  - [x] SubTask 1.2: 在 `gui_app.py` 的 `main()` 函数中调用 `setup_logging()`，默认 INFO 级别

- [x] Task 2: 将 robot_controller.py 的 print 替换为 logging，并清理重复导入
  - [x] SubTask 2.1: 在文件顶部添加 `import logging` 和 `logger = logging.getLogger(__name__)`
  - [x] SubTask 2.2: 删除方法内部的 `import re`（L141、L189、L217）和 `import time`（L240），确认模块顶部已有对应导入
  - [x] SubTask 2.3: 将所有 `print()` 替换为对应级别的 `logger.info()`/`logger.warning()`/`logger.error()`/`logger.debug()`

- [x] Task 3: 将 vision_system.py 的 print 替换为 logging
  - [x] SubTask 3.1: 在文件顶部添加 `import logging` 和 `logger = logging.getLogger(__name__)`
  - [x] SubTask 3.2: 将所有 `print()` 替换为对应级别的日志调用（检测中间数据用 DEBUG，关键结果用 INFO，错误用 ERROR）

- [x] Task 4: 将其余模块的 print 替换为 logging
  - [x] SubTask 4.1: `modbus_server.py` — 添加 logger，替换 print
  - [x] SubTask 4.2: `modbus_client.py` — 添加 logger，替换 print
  - [x] SubTask 4.3: `force_arc_controller.py` — 添加 logger，替换 print
  - [x] SubTask 4.4: `force_feedback_monitor.py` — 添加 logger，替换 print
  - [x] SubTask 4.5: `config_manager.py` — 添加 logger，替换 print
  - [x] SubTask 4.6: `workers.py` — 添加 logger，替换 print
  - [x] SubTask 4.7: `battery_monitor.py` — 添加 logger，替换 print
  - [x] SubTask 4.8: `gripper_controller.py` — 添加 logger，替换 print
  - [x] SubTask 4.9: `realtime_feedback_dialog.py` — 添加 logger，替换 print
  - [x] SubTask 4.10: `visual_servo_controller.py` — 添加 logger，替换 print
  - [x] SubTask 4.11: `depth_processor.py` — 添加 logger，替换 print

- [x] Task 5: 修复 dobot_api.py 的 wait_reply 响应截断问题
  - [x] SubTask 5.1: 将 `wait_reply` 中的 `self.socket_dobot.recv(1024)` 改为循环接收，直到收到完整响应（以 `;` 结尾或连接关闭）
  - [x] SubTask 5.2: 添加 `import logging` 和 `logger = logging.getLogger(__name__)`，将 print 替换为日志

- [x] Task 6: 统一 robot_controller.py 的 socket 超时管理
  - [x] SubTask 6.1: 创建 `_temp_timeout` 上下文管理器方法，进入时设置超时，退出时恢复原超时
  - [x] SubTask 6.2: 将 `enable_robot`、`disable_robot`、`set_collision_level`、`get_current_pose` 中的 `settimeout/settimeout(None)` 配对替换为 `with self._temp_timeout(seconds):`

- [x] Task 7: 拆分 gui_app.py 的 DobotMainWindow 为 Mixin 类
  - [x] SubTask 7.1: 创建 `gui_mixins/` 目录和 `__init__.py`
  - [x] SubTask 7.2: 提取 `RobotControlMixin` — 包含 enable/disable/clear_error/pause/continue/connect_robot 等方法
  - [x] SubTask 7.3: 提取 `VisionMixin` — 包含 connect_d435i/disconnect_d435i/connect_d405/disconnect_d405/camera_test 等方法
  - [x] SubTask 7.4: 提取 `ModbusMixin` — 包含 start/stop_modbus_server/connect/disconnect_cart_modbus 等方法
  - [x] SubTask 7.5: 提取 `PointManagementMixin` — 包含 add/delete/refresh_points 等方法
  - [x] SubTask 7.6: 提取 `ForceArcMixin` — 包含力控圆弧配置和执行方法
  - [x] SubTask 7.7: 提取 `GraspFlowMixin` — 包含 add/remove_module/save/load/run_grasp_flow 等方法
  - [x] SubTask 7.8: 提取 `JogMixin` — 包含 jog 控制、坐标移动等方法
  - [x] SubTask 7.9: 修改 `DobotMainWindow` 通过多继承组合所有 Mixin，确保功能不变
  - [x] SubTask 7.10: 将 gui_app.py 中的 print 替换为 logging

# Task Dependencies
- [Task 1] 是所有 logging 替换任务（Task 2-5, 7.10）的前置依赖
- [Task 2] 和 [Task 3] 可并行执行
- [Task 4] 中的子任务可并行执行
- [Task 5] 独立于其他任务
- [Task 6] 独立于其他任务
- [Task 7] 依赖 [Task 1]（logging 初始化），但不依赖 Task 2-6 的完成
