# TCP命令超时和力控显示问题修复 Spec

## Why
当前实现存在两个主要问题：
1. TCP命令发送后超时无响应，这是因为指令顺序不正确，应该先PowerOn再EnableRobot
2. 力控部分显示异常，需要检查相关的数据解析和显示逻辑

## What Changes
- 修复TCP指令顺序问题，确保先PowerOn再EnableRobot
- 修复力控部分数据显示问题

## Impact
- 受影响的功能：
  - 机器人连接和使能流程
  - 力控数据显示
- 受影响的代码：
  - `dobot_move/dobot_api.py` - TCP通信实现
  - `dobot_move/robot_controller.py` - 机器人控制流程
  - `dobot_move/gui_app.py` - GUI显示

## ADDED Requirements

### Requirement: TCP指令顺序修复
机器人使能前必须先上电

#### Scenario: 正确的使能流程
- **WHEN** 调用enable_robot()
- **THEN** 系统应该先发送PowerOn()，等待响应后再发送EnableRobot()

### Requirement: 力控数据显示修复
力控数据应该正确解析和显示

#### Scenario: 力矩数据显示
- **WHEN** 接收到力矩数据
- **THEN** GUI应该正确显示Fx, Fy, Fz和合力值

## MODIFIED Requirements

### Requirement: send_command超时处理
超时时间需要合理设置，避免长时间等待

#### Scenario: 命令超时
- **WHEN** 发送命令后在超时时间内没有收到响应
- **THEN** 应该返回None并提示超时错误
