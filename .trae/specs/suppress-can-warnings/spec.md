# 消除python-can库Windows警告信息 Spec

## Why
battery_monitor.py导入python-can库时在Windows平台产生两个警告：`socket.CMSG_SPACE not available`和`uptime library not available`。这些警告虽然不影响功能，但会混淆用户。

## What Changes
- 修改battery_monitor导入方式，抑制python-can的警告信息
- 或延迟导入，仅在需要时才导入can库

## Impact
- 受影响的代码：
  - `dobot_move/battery_monitor.py` - 抑制CAN库警告

## MODIFIED Requirements

### Requirement: 抑制CAN库警告
在导入python-can时抑制警告信息，不在控制台输出。
