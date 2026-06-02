# 界面精简与点动控制 - Spec

## Why
参数设置中的速度设置与主功能Tab的速度滑块重复；机器人力控Tab中历史数据和预警为占位功能未实现；缺少关节/坐标轴点动控制页面，无法手动微调机器人位置。

## What Changes
- `gui_app.py` — 删除"参数设置"Tab中的"运行速度设置"QGroupBox及其相关代码
- `gui_app.py` — 精简"机器人力控"Tab，删除"力矩历史数据"和"力矩异常预警"QGroupBox，仅保留"关节力矩数据"
- `gui_app.py` — 新增"点动控制"Tab，提供关节轴(J1-J4)和坐标轴(X/Y/Z/Rx/Ry/Rz)的正反向点动按钮
- `robot_controller.py` — 新增 `move_jog(axis_id, coordtype)` 和 `stop_jog()` 方法，调用 `dashboard.MoveJog()`

## Impact
- Affected specs: 无
- Affected code: `dobot_move/gui_app.py`, `dobot_move/robot_controller.py`

## ADDED Requirements

### Requirement: 点动控制Tab
GUI SHALL 提供"点动控制"Tab页，包含关节轴和坐标轴的点动按钮。按下按钮开始点动，松开按钮停止点动。

#### Scenario: 关节轴点动
- **GIVEN** 机器人已连接且已使能
- **WHEN** 用户按下"J1+"按钮
- **THEN** 机器人关节1正方向点动运动
- **WHEN** 用户松开"J1+"按钮
- **THEN** 机器人停止点动

#### Scenario: 坐标轴点动
- **GIVEN** 机器人已连接且已使能
- **WHEN** 用户按下"X+"按钮
- **THEN** 机器人沿X轴正方向点动运动
- **WHEN** 用户松开"X+"按钮
- **THEN** 机器人停止点动

#### Scenario: 机器人未连接
- **GIVEN** 机器人未连接
- **WHEN** 用户点击点动按钮
- **THEN** 状态栏提示"请先连接并使能机器人"

### Requirement: robot_controller 点动方法
`DobotController` SHALL 提供 `move_jog(axis_id, coordtype=1)` 和 `stop_jog()` 方法。

#### Scenario: 开始点动
- **GIVEN** 机器人已连接
- **WHEN** 调用 `move_jog("J1+")`
- **THEN** 发送 `MoveJog("J1+")` 指令

#### Scenario: 停止点动
- **WHEN** 调用 `stop_jog()`
- **THEN** 发送 `MoveJog("")` 指令停止所有点动

## MODIFIED Requirements

### Requirement: 参数设置Tab精简
"参数设置"Tab SHALL 不再包含"运行速度设置"QGroupBox，速度控制由主功能Tab的速度滑块承担。

### Requirement: 机器人力控Tab精简
"机器人力控"Tab SHALL 仅保留"关节力矩数据"QGroupBox（4个关节力矩值），删除"力矩历史数据"和"力矩异常预警"QGroupBox。

## REMOVED Requirements

### Requirement: 运行速度设置QGroupBox
**Reason**: 与主功能Tab速度滑块功能重复
**Migration**: 速度控制统一使用主功能Tab的速度滑块

### Requirement: 力矩历史数据QGroupBox
**Reason**: 仅为占位符，未实现实际功能
**Migration**: 无需迁移

### Requirement: 力矩异常预警QGroupBox
**Reason**: 仅为占位符，未实现实际功能
**Migration**: 无需迁移
