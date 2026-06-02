# 运动模块点位化与圆弧运动移除 Spec

## Why
直线运动应直接选定点位管理中的点作为目标点，无需手动输入坐标；圆弧运动与力控圆弧功能重叠，只保留力控圆弧；力控圆弧的圆心也应支持从点位管理中选取。

## What Changes
- 直线运动简化为直接选定点位作为目标点，移除坐标模式/点位模式切换，改为始终显示点位选择下拉框 + 坐标预览 + "读取当前位置"按钮
- **BREAKING** 删除圆弧运动模块（MovC），从模块下拉框、add_module、FlowThread、参数面板中移除所有相关代码
- 力控圆弧的圆心输入增加点位选择功能：坐标模式手动输入圆心坐标，点位模式从点位管理选取

## Impact
- Affected code: `gui_app.py`（直线运动 UI、圆弧运动全部移除、力控圆弧圆心点位选择、FlowThread）
- Affected behavior: 直线运动不再有坐标/点位模式切换，始终用点位选择；圆弧运动模块不再可用；力控圆弧圆心可选点位

## ADDED Requirements

### Requirement: 直线运动直接选定点位作为目标
直线运动 SHALL 直接通过点位选择下拉框选取目标点位，同时保留"读取当前位置"按钮用于快速创建点位。

#### Scenario: 选定点位作为目标
- **WHEN** 用户在直线运动模块中选择一个点位
- **THEN** 下方显示该点位的坐标预览，保存参数时使用该点位名称

#### Scenario: 读取当前位置
- **WHEN** 用户点击"读取当前位置"按钮
- **THEN** 系统读取机器人当前位姿并显示在坐标预览中，同时将当前位姿写入一个临时目标坐标

#### Scenario: FlowThread 执行直线运动
- **WHEN** FlowThread 执行直线运动模块
- **THEN** 通过 resolve_point 解析选定点位坐标作为目标，执行 MovL

### Requirement: 力控圆弧圆心支持点位选择
力控圆弧的圆心 SHALL 支持坐标模式和点位模式切换。

#### Scenario: 坐标模式输入圆心
- **WHEN** 用户在力控圆弧模块选择坐标模式
- **THEN** 显示圆心 X/Y/Z 手动输入框（现有行为不变）

#### Scenario: 点位模式选取圆心
- **WHEN** 用户在力控圆弧模块选择点位模式
- **THEN** 显示点位选择下拉框和坐标预览，选定点位后该点位坐标作为圆心

#### Scenario: FlowThread 执行力控圆弧点位模式
- **WHEN** FlowThread 执行力控圆弧模块且 mode="point"
- **THEN** 使用 resolve_point 解析点位坐标作为圆心

## MODIFIED Requirements

### Requirement: 直线运动参数编辑
直线运动参数编辑区域 SHALL 移除坐标模式/点位模式切换，改为始终显示点位选择下拉框 + 坐标预览 + 速度输入 + "读取当前位置"按钮。参数中不再使用 target_coords，统一使用 point_name。

### Requirement: 力控圆弧参数编辑
力控圆弧参数编辑区域 SHALL 在圆心输入部分增加坐标模式/点位模式切换，点位模式下显示点位选择下拉框和坐标预览。

## REMOVED Requirements

### Requirement: 圆弧运动模块
**Reason**: 与力控圆弧功能重叠，用户决定只保留力控圆弧
**Migration**: 已有的圆弧运动模块数据在流程中不再可用，用户需手动替换为力控圆弧模块
