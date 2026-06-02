# 同步dobot_move_boject的TCP通信实现 Spec

## Why
经过对比发现，dobot_move_boject可以连接机器人，而dobot_move_python连接失败。核心差异在dobot_api.py的send_command()方法：可工作版本使用简单的单次recv(1024)，不可工作版本使用循环等待分号的复杂逻辑导致超时。

## What Changes
- 简化dobot_api.py的send_command()方法，使用单次recv(1024)而非循环等待分号
- 移除connect()中的自动RequestControl()调用（可工作版本没有调用）
- 简化connect()方法，不读取欢迎消息，不自动RequestControl

## Impact
- 受影响的功能：TCP通信
- 受影响的代码：
  - `dobot_move/dobot_api.py` - TCP通信核心

## MODIFIED Requirements

### Requirement: send_command简化
使用单次recv(1024)接收响应，不等待分号

### Requirement: connect()简化
连接成功后不读取欢迎消息，不自动RequestControl
