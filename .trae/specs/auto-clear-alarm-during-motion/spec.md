# 运行中自动清除报警 - Spec

## Why
当前 `_wait_for_motion_done` 检测到 robot_mode==9 时直接返回 False 导致流程终止，但很多报警（如轻微碰撞）可以通过 ClearError 自动恢复。需要在运动等待过程中自动清除报警并继续等待运动完成。

## What Changes
- `robot_controller.py` — `_wait_for_motion_done` 中 robot_mode==9 时自动调用 `clear_error()` 清除报警，然后继续等待

## Impact
- Affected specs: remove-speed-add-pause（改进其自动清除逻辑）
- Affected code: `dobot_move/robot_controller.py`

## MODIFIED Requirements

### Requirement: 运动等待中自动清除报警
`_wait_for_motion_done` SHALL 在检测到 robot_mode==9 时自动调用 `clear_error()` 清除报警，然后继续等待运动完成，而非直接返回 False。

#### Scenario: 运动中轻微碰撞报警
- **GIVEN** 机器人正在执行运动指令
- **WHEN** 发生轻微碰撞导致 robot_mode 变为 9
- **THEN** 自动调用 `clear_error()` 清除报警，等待0.5秒后继续检查运动状态

#### Scenario: 报警无法清除
- **GIVEN** 连续3次自动清除报警后 robot_mode 仍为 9
- **WHEN** 超过最大重试次数
- **THEN** 返回 False，流程终止
