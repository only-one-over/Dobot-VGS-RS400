# Tasks

## [x] Task 1: robot_controller 添加 2 秒超时 + connect 不再自动使能
- **Priority**: P0
- **Depends On**: None
- **Description**:
  - `connect()` 移除自动调用 `self.enable_robot()` 的逻辑，连接后仅 is_connected=True
  - `enable_robot()` 中在调用 `self.dashboard.EnableRobot()` 前设置 `self.dashboard.socket_dobot.settimeout(2)`，调用后恢复为 `None`。用 try/except socket.timeout 包裹，超时返回 False
  - `disable_robot()` 同样设置 2 秒超时
  - 在 `robot_controller.py` 顶部 `import socket`

## [x] Task 2: gui_app 新增连接按钮并更新布局
- **Priority**: P0
- **Depends On**: Task 1
- **Description**:
  - 在 `init_ui()` 的 button_layout 中，使能按钮上方新增"连接机器人"按钮
  - 按钮 `connect_robot_btn` 点击绑定 `self.connect_robot()`
  - 设置蓝色默认样式

## [x] Task 3: gui_app 使能/下使能/连接移至后台线程 + 未连接报错
- **Priority**: P0
- **Depends On**: Task 1
- **Description**:
  - 添加 `RobotCmdThread(QThread)` 类，包含 `set_cmd(cmd_name, cmd_func)` 方法
  - 信号：`cmd_finished = pyqtSignal(str, bool)`  (操作名称, 成功/失败)
  - `enable_robot()` 修改为：检查 is_connected，未连接则弹出 QMessageBox.warning "机器人未连接，请先连接"；已连接则创建 RobotCmdThread 后台执行 `controller.enable_robot()`
  - `disable_robot()` 同理：未连接弹警告；已连接后台执行 `controller.disable_robot()`
  - `connect_robot()` 新方法：后台线程执行 `controller.connect()`
  - `cmd_finished` 信号处理：根据成功/失败弹出 QMessageBox

# Task Dependencies
- Task 2 depends on Task 1
- Task 3 depends on Task 1
