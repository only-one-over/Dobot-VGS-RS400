# 删除C++模块并修复TCP控制问题 Spec

## Why
1. C++模块(cpp_core)使用pybind11编译，增加了项目复杂度，且Python已有回退实现，可以完全用Python替代
2. TCP连接成功但无法控制机械臂：连接后欢迎消息读取可能不完整，且未调用RequestControl()切换TCP模式，导致所有命令超时无响应

## What Changes
- 删除cpp_core目录及其所有内容
- 删除test_tcp_interface.py旧测试脚本（不调用RequestControl，每次测试创建新连接）
- 修复dobot_api.py的send_command()方法：欢迎消息可能不以";"结尾，需要特殊处理
- 确保DobotApiDashboard.connect()后自动调用RequestControl()
- vision_system.py和torque_monitor.py中移除dobot_core引用，只保留Python实现

## Impact
- 受影响的功能：C++加速模块、TCP通信、视觉处理、力矩监控
- 受影响的代码：
  - `cpp_core/` - 整个目录删除
  - `dobot_move/dobot_api.py` - TCP通信核心
  - `dobot_move/vision_system.py` - 移除dobot_core引用
  - `dobot_move/torque_monitor.py` - 移除dobot_core引用
  - `test_tcp_interface.py` - 删除旧测试脚本

## ADDED Requirements

### Requirement: connect()后自动RequestControl
DobotApiDashboard连接后必须自动调用RequestControl()切换TCP模式

#### Scenario: 连接后自动切换TCP模式
- **WHEN** DobotApiDashboard连接成功
- **THEN** 自动调用RequestControl()，确保后续命令可执行

### Requirement: 欢迎消息不以分号结尾
机器人欢迎消息可能不以";"结尾，connect()中读取欢迎消息不应依赖分号

#### Scenario: 读取欢迎消息
- **WHEN** 连接到29999端口
- **THEN** 读取欢迎消息（可能以\n结尾而非;），不阻塞后续操作

## MODIFIED Requirements

### Requirement: 移除C++依赖
所有dobot_core引用替换为纯Python实现

#### Scenario: 无C++模块运行
- **WHEN** dobot_core模块不可用
- **THEN** 系统使用Python回退实现正常运行

## REMOVED Requirements

### Requirement: C++加速模块
**Reason**: 增加项目复杂度，Python回退实现已足够
**Migration**: 删除cpp_core目录，移除所有dobot_core导入
