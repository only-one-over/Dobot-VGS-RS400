# 修复TCP连接和使能流程 Spec

## Why
robot_controller.py中connect()重复调用了RequestControl()（DobotApiDashboard.connect()已调用），导致第二次调用失败可能影响后续命令；需要确保连接后自动清除错误并正确使能，处理机器人各种状态

## What Changes
- 移除robot_controller.py中重复的RequestControl()调用
- 确保connect()后自动调用ClearError()清除错误
- 增强enable_robot()的状态检查和错误处理

## Impact
- 受影响的功能：机器人连接和使能流程
- 受影响的代码：
  - `dobot_move/robot_controller.py` - 连接和使能逻辑
  - `dobot_move/dobot_api.py` - TCP通信（已自动调用RequestControl）

## ADDED Requirements

### Requirement: 连接后自动清除错误
连接成功后自动清除可能存在的错误状态

#### Scenario: 连接成功
- **WHEN** 成功连接到机器人
- **THEN** 自动调用ClearError()清除历史错误

### Requirement: 避免重复RequestControl
DobotApiDashboard已自动调用RequestControl，robot_controller不应再次调用

#### Scenario: 连接流程
- **WHEN** robot_controller.connect()被调用
- **THEN** 不重复调用RequestControl，直接使用TCP模式

## MODIFIED Requirements

### Requirement: enable_robot()状态处理
使能前检查所有可能的异常状态并正确处理

#### Scenario: 机器人处于各种状态
- **WHEN** 使能前
- **THEN** 检查RobotMode，处理运行/暂停/错误等状态
