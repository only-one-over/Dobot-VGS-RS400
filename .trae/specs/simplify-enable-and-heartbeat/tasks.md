# Tasks

## [x] Task 1: 简化 robot_controller.py 的 enable/disable 逻辑
- **Priority**: P0
- **Depends On**: None
- **Description**:
  - 简化 `enable_robot()`: 移除 ClearError、RobotMode 检查、Stop 脚本等前置步骤，仅检查 is_connected 后直接调用 `self.dashboard.EnableRobot()`
  - 简化 `disable_robot()`: 仅检查 is_connected 和 is_enabled 后直接调用 `self.dashboard.DisableRobot()`
  - 在 `enable_robot()` 成功后 sleep(1) 等待使能生效（保留短暂等待）
  - 在 `_feed_loop()` 中每次成功获取数据后记录 `self.last_feed_time = time.time()`
  - 在 `__init__` 中初始化 `self.last_feed_time = 0`
  - 添加 `get_last_feed_time()` 方法返回最后接收反馈数据的时间戳

## [x] Task 2: 更新 gui_app.py StatusUpdateThread 实现超时检测
- **Priority**: P0
- **Depends On**: Task 1
- **Description**:
  - 修改 `StatusUpdateThread.run()` 中的机器人状态检测逻辑
  - 改用 `self.controller.get_last_feed_time()` 判断：如果 `time.time() - self.controller.get_last_feed_time() > 2` 秒，则显示"未连接"并设置 `self.controller.is_connected = False`
  - 如果在 2 秒内收到数据，显示"已连接"
  - 保持相机状态检测逻辑不变

# Task Dependencies
- Task 2 depends on Task 1
