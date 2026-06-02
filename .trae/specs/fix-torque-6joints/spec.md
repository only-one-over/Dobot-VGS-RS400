# 机器人力控6关节力显示 - Spec

## Why
当前"机器人力控"Tab只显示4个关节力矩，且使用 `ActualJointTorque` 键在反馈数据结构中不存在，导致数据永远无法更新。需要根据TCP反馈数据结构，使用正确的字段 `IActual` 显示6个关节的实时力/电流数据。

## What Changes
- `gui_app.py` — 将4个关节力矩Label扩展为6个（J1-J6）
- `gui_app.py` — 将数据更新从 `ActualJointTorque` 改为 `IActual`（6个关节实际电流）

## Impact
- Affected specs: simplify-gui-add-jog（修改了机器人力控Tab）
- Affected code: `dobot_move/gui_app.py`

## MODIFIED Requirements

### Requirement: 6关节力显示
"机器人力控"Tab SHALL 显示6个关节（J1-J6）的实时电流/力数据，数据来自反馈数据的 `IActual` 字段。

#### Scenario: 机器人连接后实时更新
- **GIVEN** 机器人已连接
- **WHEN** 反馈数据正常接收
- **THEN** 6个关节Label每200ms更新一次，显示 `IActual` 的值

#### Scenario: 6关节数据
- **GIVEN** 反馈数据中 `IActual` 有6个值
- **WHEN** 更新力控界面
- **THEN** J1-J6 Label分别显示 `IActual[0]` 到 `IActual[5]` 的值
