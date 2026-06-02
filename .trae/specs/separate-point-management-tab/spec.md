# 点位管理独立选项卡 Spec

## Why
当前点位管理 UI 嵌入在运动编辑选项卡中，占据大量空间导致运动编辑区域拥挤。将点位管理拆为独立选项卡，使两个功能区域各自有充足的操作空间。

## What Changes
- 将"点位管理" GroupBox 从运动编辑选项卡中移出
- 新增"点位管理"独立选项卡
- 运动编辑选项卡恢复为仅包含模块拼接工具和流程操作

## Impact
- Affected code: `gui_app.py`
- Affected behavior: 点位管理从运动编辑 tab 移到独立 tab，功能不变

## ADDED Requirements

### Requirement: 点位管理独立选项卡
系统 SHALL 在 GUI 中新增"点位管理"独立选项卡，包含原运动编辑选项卡中的点位管理 GroupBox 的全部内容。

#### Scenario: 点位管理选项卡内容
- **WHEN** 用户切换到点位管理选项卡
- **THEN** 显示点位表格（名称/X/Y/Z/Rx/Ry/Rz/相对/基准点位）和操作按钮（添加/删除/刷新），与原嵌入版本功能完全一致

#### Scenario: 运动编辑选项卡恢复
- **WHEN** 用户切换到运动编辑选项卡
- **THEN** 仅显示模块拼接工具和流程操作区域，不再显示点位管理

## MODIFIED Requirements

### Requirement: 选项卡布局
选项卡顺序 SHALL 为：主功能 → 参数设置 → 运动编辑 → 点位管理 → 电池电量 → 力控显示 → Modbus → 手眼标定

## REMOVED Requirements
无。
