# 点位控制Tab改进 - Spec

## Why
当前"点动控制"Tab只有点动按钮，缺少实时坐标/关节位置显示和目标位置输入功能。用户需要在点动时看到实时位置，并能输入目标坐标直接运动到位。

## What Changes
- `gui_app.py` — 重构"点动控制"Tab，添加模式切换（坐标模式/轴模式）
- `gui_app.py` — 坐标模式：显示实时TCP坐标(X/Y/Z/Rx/Ry/Rz) + 目标坐标输入框 + 运动按钮 + 点动按钮
- `gui_app.py` — 轴模式：显示实时关节角度(J1-J4) + 目标角度输入框 + 运动按钮 + 点动按钮
- `gui_app.py` — 新增定时器更新实时坐标/角度显示

## Impact
- Affected specs: simplify-gui-add-jog（修改其创建的"点动控制"Tab）
- Affected code: `dobot_move/gui_app.py`

## ADDED Requirements

### Requirement: 模式切换
"点动控制"Tab SHALL 提供模式切换（坐标模式/轴模式），切换时更新显示内容。

#### Scenario: 切换到坐标模式
- **WHEN** 用户选择"坐标模式"
- **THEN** 显示实时TCP坐标(X/Y/Z/Rx/Ry/Rz)、目标坐标输入框、坐标点动按钮

#### Scenario: 切换到轴模式
- **WHEN** 用户选择"轴模式"
- **THEN** 显示实时关节角度(J1-J4)、目标角度输入框、关节点动按钮

### Requirement: 实时位置显示
坐标模式下 SHALL 实时显示TCP坐标值，轴模式下 SHALL 实时显示关节角度值，数据来自反馈数据 `ToolVectorActual` 和 `QActual`。

#### Scenario: 机器人连接后实时更新
- **GIVEN** 机器人已连接
- **WHEN** 切换到"点动控制"Tab
- **THEN** 实时坐标/角度值每200ms更新一次

### Requirement: 目标位置输入与运动
坐标模式和轴模式下 SHALL 提供目标值输入框和"运动到目标"按钮，点击后机器人运动到指定位置。

#### Scenario: 坐标模式运动到目标
- **GIVEN** 坐标模式下用户输入目标坐标 X=500, Y=0, Z=300, Rx=180, Ry=0, Rz=0
- **WHEN** 点击"运动到目标"按钮
- **THEN** 机器人以MovJ运动到目标坐标

#### Scenario: 轴模式运动到目标
- **GIVEN** 轴模式下用户输入目标角度 J1=0, J2=90, J3=-90, J4=0
- **WHEN** 点击"运动到目标"按钮
- **THEN** 机器人以MovJ(coordinateMode=1)运动到目标关节角度

## MODIFIED Requirements

### Requirement: 点动控制Tab重构
"点动控制"Tab SHALL 使用模式切换替代当前同时显示关节和坐标按钮的布局，根据模式动态显示对应内容。
