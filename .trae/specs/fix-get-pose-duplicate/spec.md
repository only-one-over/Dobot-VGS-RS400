# 修复无法获取机械臂位置 - Spec

## Why
机器人在连接且已使能状态下，点击"获取位置"按钮始终返回"获取位置失败"。根因是 `robot_controller.py` 中存在两个同名的 `get_current_pose` 方法，第二个（第1181行）覆盖了第一个（第549行），且被覆盖的版本传入错误参数 `GetPose(0)` 导致返回错误字符串。

## What Changes
- 删除 `robot_controller.py` 第1181-1192行重复的 `get_current_pose` 方法，保留第549行正确实现
- 修复保留的 `get_current_pose` 方法中的 socket timeout 恢复逻辑（异常时也需要恢复）

## Impact
- Affected specs: 无
- Affected code: `dobot_move/robot_controller.py`

## REMOVED Requirements
### Requirement: 重复的 get_current_pose 方法（第1181行）
**Reason**: 该方法覆盖了正确实现，且调用 `GetPose(0)` 传入错误参数，导致 `GetPose` 返回错误字符串而非坐标数据
**Migration**: 无需迁移，保留第549行的正确实现即可
