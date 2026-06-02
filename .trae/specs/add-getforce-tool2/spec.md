# 添加工具坐标系2的GetForce()支持 Spec

## Why
用户需要使用工具坐标系2（工具）来获取力传感器数值，当前dobot_api.py缺少GetForce()指令，且GUI和robot_controller未集成该功能。

## What Changes
- 在dobot_api.py中添加GetForce(tool)指令
- 在robot_controller中添加get_force()方法，默认使用工具坐标系2
- 在GUI中显示力传感器数值

## Impact
- 受影响的代码：
  - `dobot_move/dobot_api.py` - 添加GetForce指令
  - `dobot_move/robot_controller.py` - 添加get_force()方法
  - `dobot_move/gui_app.py` - 可选：显示力传感器数值

## ADDED Requirements

### Requirement: GetForce指令
dobot_api.py中提供GetForce(tool)方法

#### Scenario: 获取力传感器数值
- **WHEN** 调用GetForce(2)
- **THEN** 返回工具坐标系2下的Fx, Fy, Fz, Mx, My, Mz

### Requirement: robot_controller.get_force()
提供便捷方法，默认使用工具坐标系2

#### Scenario: 获取力数据
- **WHEN** 调用get_force()
- **THEN** 默认使用tool=2获取力数据并解析返回值
