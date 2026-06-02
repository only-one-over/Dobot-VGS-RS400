# 直线运动增加Rx/Ry/Rz参数 - Spec

## Why
当前运动编辑中直线运动参数仅有X/Y/Z偏移，缺少姿态角(Rx/Ry/Rz)调整能力。用户需要在直线运动中同时调整目标姿态。

## What Changes
- `gui_app.py` — 直线运动参数区新增Rx/Ry/Rz偏移输入框
- `gui_app.py` — `update_module_params` 保存时包含rx/ry/rz
- `gui_app.py` — `FlowThread.run()` 直线运动目标姿态使用rx/ry/rz偏移
- `gui_app.py` — `view_current_grasp_flow` 显示rx/ry/rz信息

## Impact
- Affected specs: 无
- Affected code: `dobot_move/gui_app.py`

## MODIFIED Requirements

### Requirement: 直线运动支持Rx/Ry/Rz
直线运动参数编辑 SHALL 提供Rx/Ry/Rz偏移输入框，执行时目标姿态 = 当前姿态 + 偏移。

#### Scenario: 设置姿态偏移
- **GIVEN** 运动编辑中选中直线运动模块
- **WHEN** 用户设置Rx=180, Ry=0, Rz=90
- **THEN** 执行时目标姿态旋转部分为当前姿态旋转部分 + 偏移
