# 修复实时反馈弹窗导入和API错误 Spec

## Why
RealTimeFeedbackDialog导入了不存在的模块 `from dobot_api.dobot_api import RealTimeFeedback, RobotMode`，且调用了不存在的 `get_data()` 方法，导致打开实时反馈弹窗失败。

## What Changes
- 修正RealTimeFeedback的导入路径
- 修正get_data()为get_status()
- 修正数据字典的键名以匹配RealTimeFeedback的返回格式

## Impact
- 受影响的代码：
  - `dobot_move/realtime_feedback_dialog.py` - 修复导入和API调用

## MODIFIED Requirements

### Requirement: 修正导入路径
从正确的模块导入RealTimeFeedback类。

### Requirement: 修正API调用
使用正确的get_status()方法而非get_data()。
