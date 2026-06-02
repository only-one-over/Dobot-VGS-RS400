# 简化使能逻辑与连接超时检测 Spec

## Why
当前 `enable_robot()` 做了过多前置操作（ClearError、RobotMode检查、Stop脚本），用户期望使能就是一个简单的使能指令。同时 UI 的 `StatusUpdateThread` 仅读取静态 `is_connected` 标志，无法检测实际 TCP 连接断开，需要基于反馈数据时间戳实现 2 秒超时检测。

## What Changes
- 简化 `robot_controller.py` 中 `enable_robot()` 方法，移除 ClearError/RobotMode/Stop 等前置操作，直接调用 `EnableRobot()`
- 简化 `disable_robot()` 方法，直接调用 `DisableRobot()`
- 修改 `gui_app.py` 中 `StatusUpdateThread`，基于 `get_feed_data()` 是否在 2 秒内有更新来判断连接状态
- 在 `robot_controller.py` 的 `_feed_loop()` 中记录最后收到反馈数据的时间戳

## Impact
- Affected specs: 机器人连接与使能
- Affected code:
  - `dobot_move/robot_controller.py` - 简化 enable_robot/disable_robot + 添加 `last_feed_time` 时间戳
  - `dobot_move/gui_app.py` - StatusUpdateThread 改用反馈数据超时检测

## MODIFIED Requirements

### Requirement: 简化使能机器人
`enable_robot()` SHALL 直接调用 `EnableRobot()` 命令，不再执行 ClearError/RobotMode/Stop 等前置操作。

#### Scenario: 使能成功
- **WHEN** 用户点击"使能机器人"且机器人已连接
- **THEN** 直接发送 EnableRobot 指令，根据返回码判断成功/失败

#### Scenario: 未连接时使能
- **WHEN** 用户点击"使能机器人"且机器人未连接
- **THEN** 自动执行连接后使能

### Requirement: 简化下使能机器人
`disable_robot()` SHALL 直接调用 `DisableRobot()` 命令。

#### Scenario: 下使能成功
- **WHEN** 用户点击"下使能机器人"且机器人已使能
- **THEN** 直接发送 DisableRobot 指令，根据返回码判断成功/失败

### Requirement: 2秒超时连接检测
`StatusUpdateThread` SHALL 基于反馈数据最后更新时间戳判断连接状态。

#### Scenario: 连接正常
- **WHEN** 2 秒内收到有效的反馈数据
- **THEN** 显示"机器人状态: 已连接"

#### Scenario: 连接断开
- **WHEN** 超过 2 秒未收到有效的反馈数据
- **THEN** 显示"机器人状态: 未连接"，同时更新 `controller.is_connected = False`
