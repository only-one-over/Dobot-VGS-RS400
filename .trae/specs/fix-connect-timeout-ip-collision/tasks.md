# Tasks

## [x] Task 1: 修复 robot_controller connect() 添加 3 秒超时验证
- **Priority**: P0
- **Depends On**: None
- **Description**:
  - `connect()` 中创建 `DobotApiDashboard` 后，设置 `self.dashboard.socket_dobot.settimeout(3)`
  - 发送 `self.dashboard.RobotMode()` 验证通信，如果超时或异常则 `self.dashboard.close()` 并返回 False
  - 验证成功后恢复 `settimeout(None)`，设置 `self.is_connected = True`
  - 添加 `set_collision_level(level)` 方法，调用 `self.dashboard.SetCollisionLevel(level)`
  - 添加 `set_robot_ip(ip)` 方法，更新 `self.robot_ip`

## [x] Task 2: gui_app 新增 IP 编辑框和碰撞等级设置
- **Priority**: P0
- **Depends On**: Task 1
- **Description**:
  - 在 `init_ui()` 中连接按钮旁新增 `QLineEdit` 作为 IP 输入框，默认值 "192.168.5.1"
  - `connect_robot()` 连接前调用 `self.controller.set_robot_ip(ip)` 更新 IP
  - 在设置区域新增碰撞等级 `QComboBox`（0-5），加"设置碰撞等级"按钮
  - 按钮点击调用 `self.controller.set_collision_level(level)`，通过 RobotCmdThread 后台执行

# Task Dependencies
- Task 2 depends on Task 1
