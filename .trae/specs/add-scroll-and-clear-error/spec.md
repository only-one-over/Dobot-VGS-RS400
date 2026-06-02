# 界面滚动与清除故障功能 - Spec

## Why
当前GUI窗口固定800x600，各Tab页内容较多时控件被折叠压缩，无法正常编辑操作；同时机器人报警后没有GUI入口清除故障，只能重启程序。

## What Changes
- `gui_app.py` — 为各Tab页内容添加 QScrollArea 包裹，使界面可滚动
- `gui_app.py` — 在"主功能"Tab中添加"清除故障"按钮
- `robot_controller.py` — 新增公开方法 `clear_error()`，调用 `dashboard.ClearError()` 并重新使能

## Impact
- Affected specs: 无
- Affected code: `dobot_move/gui_app.py`, `dobot_move/robot_controller.py`

## ADDED Requirements

### Requirement: Tab页可滚动
每个Tab页的内容 SHALL 被 QScrollArea 包裹，当窗口高度不足以显示所有控件时，用户可以通过滚动条滚动查看和操作所有控件。

#### Scenario: 窗口较小时编辑参数
- **GIVEN** 窗口高度不足以显示"参数设置"Tab的全部内容
- **WHEN** 用户切换到"参数设置"Tab
- **THEN** 出现垂直滚动条，用户可滚动查看拍照位置、夹爪控制等所有控件

#### Scenario: 运动编辑Tab滚动
- **GIVEN** "运动编辑"Tab内容超出窗口高度
- **WHEN** 用户编辑模块参数
- **THEN** 可滚动到"更新参数"和"执行流程"按钮

### Requirement: 清除故障按钮
"主功能"Tab SHALL 提供"清除故障"按钮，点击后调用 `robot_controller.clear_error()` 清除机器人报警并尝试重新使能。

#### Scenario: 机器人报警后清除
- **GIVEN** 机器人处于报警状态（RobotMode=9）
- **WHEN** 用户点击"清除故障"按钮
- **THEN** 调用 `ClearError()` 清除报警，清除成功后自动重新使能机器人，状态栏显示操作结果

#### Scenario: 机器人未连接时点击
- **GIVEN** 机器人未连接
- **WHEN** 用户点击"清除故障"按钮
- **THEN** 弹出提示"请先连接机器人"

### Requirement: robot_controller 公开清除故障方法
`DobotController` SHALL 提供公开方法 `clear_error()`，内部调用 `dashboard.ClearError()`，清除成功后自动重新使能机器人。

#### Scenario: 清除报警并重新使能
- **GIVEN** 机器人已连接且处于报警状态
- **WHEN** 调用 `clear_error()`
- **THEN** 执行 `ClearError()`，等待0.5秒，然后执行 `enable_robot()`，返回True/False表示是否成功

#### Scenario: 机器人未连接
- **GIVEN** 机器人未连接
- **WHEN** 调用 `clear_error()`
- **THEN** 返回False并打印错误信息
