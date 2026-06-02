# 防止使能卡死、2秒超时与新增连接按钮 Spec

## Why
当前 `EnableRobot()`/`DisableRobot()` 通过 `sendRecvMsg()` 同步调用，TCP 无超时机制，网络不通时会永久阻塞导致 UI 卡死。同时 GUI 在未连接时点击使能会自动尝试连接，用户期望直接报错。此外缺少独立的连接按钮。

## What Changes
- 在 `robot_controller.py` 的 `enable_robot()`/`disable_robot()` 中给 socket 设置 2 秒超时，超时则返回失败
- 将 `gui_app.py` 中的使能/下使能/连接操作移至后台线程执行，防止 UI 卡死
- 未连接时点击使能按钮直接弹窗报错"机器人未连接"，不再自动连接
- 新增"连接机器人"按钮，点击后在后台线程执行连接
- `connect()` 不再自动调用 `enable_robot()`，连接和使能分离

## Impact
- Affected specs: 机器人连接与使能
- Affected code:
  - `dobot_move/robot_controller.py` - 添加 socket 超时、移除 connect 中的自动使能
  - `dobot_move/gui_app.py` - 使能/下使能/连接移至后台线程 + 新增连接按钮

## MODIFIED Requirements

### Requirement: 使能/下使能 2 秒超时
`enable_robot()` 和 `disable_robot()` SHALL 在调用 `EnableRobot()`/`DisableRobot()` 前设置 socket 超时为 2 秒，超时或异常则返回 False。

#### Scenario: 正常使能
- **WHEN** 网络正常，dashboard.EnableRobot() 在 2 秒内返回
- **THEN** 正常处理返回码，成功/失败

#### Scenario: 超时
- **WHEN** dashboard.EnableRobot() 超过 2 秒无返回
- **THEN** 捕获 socket.timeout，返回 False，打印"使能超时"

### Requirement: 使能/下使能后台执行
GUI 中的使能、下使能、连接操作 SHALL 在后台 QThread 中执行，不阻塞主 UI 线程。

#### Scenario: 点击使能
- **WHEN** 用户点击"使能机器人"
- **THEN** 创建后台线程执行，UI 保持响应，完成后通过信号通知结果

### Requirement: 未连接时使能直接报错
当机器人未连接时点击使能或下使能，SHALL 直接弹窗提示"机器人未连接，请先连接"。

#### Scenario: 未连接点击使能
- **WHEN** 机器人未连接，用户点击"使能机器人"
- **THEN** 弹窗"机器人未连接，请先连接"，不执行任何操作

### Requirement: 新增连接按钮
界面 SHALL 新增"连接机器人"按钮，点击后在后台线程连接机器人。

#### Scenario: 点击连接
- **WHEN** 用户点击"连接机器人"
- **THEN** 后台线程执行 DobotController.connect()，完成后弹出成功/失败提示

### Requirement: 连接与使能分离
`connect()` SHALL 仅建立 TCP 连接和启动反馈线程，不再自动调用 `enable_robot()`。

#### Scenario: 连接后状态
- **WHEN** connect() 成功
- **THEN** is_connected=True, is_enabled=False，用户需手动点击使能
