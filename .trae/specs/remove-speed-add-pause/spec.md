# 速度控制移除、运行中清除报警、暂停继续 - Spec

## Why
主功能Tab速度滑块仅更新标签不实际设置速度且无实际用途；运行过程中遇到报警需要手动点击清除故障按钮；抓取流程无暂停/继续机制，执行中无法中断。

## What Changes
- `gui_app.py` — 删除主功能Tab中的速度滑块(`speed_slider`/`speed_value_label`)
- `gui_app.py` — 删除系统状态栏中的速度Label(`speed_label`)，减少状态栏占用
- `gui_app.py` — 在 `run_grasp_flow` 中每个模块执行前检查RobotMode，若为报警状态(9)则自动调用 `clear_error()` 清除后继续
- `gui_app.py` — 添加暂停/继续功能：暂停按钮 + 继续按钮，用 `QThread` 运行流程
- `robot_controller.py` — 添加 `pause()` 和 `continue_motion()` 方法，调用 `dashboard.Pause()` / `dashboard.Continue()`

## Impact
- Affected specs: add-scroll-and-clear-error（修改清除故障的使用方式）, simplify-gui-add-jog（主功能Tab布局调整）
- Affected code: `dobot_move/gui_app.py`, `dobot_move/robot_controller.py`

## ADDED Requirements

### Requirement: 运行中自动清除报警
抓取流程执行过程中 SHALL 在每个模块执行前检查机器人状态，若处于报警状态则自动调用 `clear_error()` 清除报警后继续执行。

#### Scenario: 运行中发生报警
- **GIVEN** 抓取流程正在执行，机器人进入报警状态(RobotMode=9)
- **WHEN** 下一模块准备执行
- **THEN** 自动调用 `ClearError()` 清除报警并重新使能，然后继续执行后续模块

### Requirement: 暂停/继续功能
抓取流程执行期间 SHALL 支持暂停和继续操作。

#### Scenario: 暂停流程
- **GIVEN** 抓取流程正在执行
- **WHEN** 用户点击"暂停"按钮
- **THEN** 暂停标志置为True，发送 `Pause()` 指令暂停机器人运动，状态栏显示"流程已暂停"

#### Scenario: 继续流程
- **GIVEN** 流程已暂停
- **WHEN** 用户点击"继续"按钮
- **THEN** 暂停标志置为False，发送 `Continue()` 指令恢复机器人运动，流程继续执行

#### Scenario: 流程未运行
- **GIVEN** 流程未在执行
- **WHEN** 用户点击"暂停"或"继续"
- **THEN** 状态栏提示"当前没有运行中的任务"

### Requirement: 机器人控制器暂停/继续方法
`DobotController` SHALL 提供 `pause()` 和 `continue_motion()` 方法。

#### Scenario: 调用暂停
- **WHEN** 调用 `pause()`
- **THEN** 发送 `Pause()` 指令，返回True/False

#### Scenario: 调用继续
- **WHEN** 调用 `continue_motion()`
- **THEN** 发送 `Continue()` 指令，返回True/False

## MODIFIED Requirements

### Requirement: 主功能Tab简化
主功能Tab SHALL 移除速度滑块(`speed_slider`、`speed_value_label`)，状态栏移除速度Label(`speed_label`)。

## REMOVED Requirements

### Requirement: 速度滑块显示
**Reason**: 仅更新显示值，不实际设置机器人速度，无功能用途
**Migration**: 直接删除控件，速度由控制器默认值管理
