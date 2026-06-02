# 点位表格与运动编辑修复 Spec

## Why
点位管理表格中默认相机点位仍显示禁用的 QDoubleSpinBox 控件导致数值框重叠和未对齐，且运动编辑模块切换到"点位模式"后无法正确选定点位管理中的点。

## What Changes
- 默认相机点位（p_d435i、p_u405、p_n405）使用 QTableWidgetItem 纯文本显示坐标，不使用 QDoubleSpinBox
- 自定义点位 QDoubleSpinBox 添加紧凑样式，消除重叠和对齐问题
- 增大行高至 56px
- 修复运动编辑点位模式 combo 选择后无反馈的问题，添加坐标预览标签
- 确保 _refresh_point_combos 在所有必要时机被调用

## Impact
- Affected code: `gui_app.py`（refresh_points_table、_refresh_point_combos、_on_linear_mode_changed、_on_fa_mode_changed）

## ADDED Requirements

### Requirement: 默认点位纯文本显示
默认相机点位（p_d435i、p_u405、p_n405）SHALL 使用 QTableWidgetItem 纯文本显示坐标值，不使用任何可编辑控件。

#### Scenario: 查看默认点位行
- **WHEN** 用户查看点位管理表格中的默认点位
- **THEN** 坐标列显示纯文本数值，无 QDoubleSpinBox 控件，无任何可编辑元素

#### Scenario: 相机识别更新默认点位
- **WHEN** 流程中执行相机识别
- **THEN** 默认点位坐标通过 refresh_points_table 刷新显示新值

### Requirement: 自定义点位数值框紧凑无重叠
自定义点位的 QDoubleSpinBox SHALL 使用紧凑样式，消除控件重叠和列对齐问题。

#### Scenario: 查看自定义点位行
- **WHEN** 用户查看点位管理表格中的自定义点位
- **THEN** 各列 QDoubleSpinBox 完整显示在单元格内，不与相邻列重叠，与表头对齐

### Requirement: 运动编辑点位模式可选定点位
运动编辑切换到"点位模式"后，SHALL 能从下拉框选定点位管理中的点，并显示该点坐标预览。

#### Scenario: 直线运动选定点位
- **WHEN** 用户在直线运动模块切换到"点位模式"并从下拉框选择一个点位
- **THEN** 下拉框下方显示该点位的坐标预览（X/Y/Z/Rx/Ry/Rz），保存参数时使用该点位名称

#### Scenario: 力控圆弧选定点位
- **WHEN** 用户在力控圆弧模块切换到"点位模式"并从下拉框选择一个点位
- **THEN** 下拉框下方显示该点位的坐标预览（X/Y/Z/Rx/Ry/Rz），保存参数时使用该点位名称

#### Scenario: 点位管理新增/删除点位后 combo 同步
- **WHEN** 用户在点位管理中新增或删除点位
- **THEN** 运动编辑的点位下拉框自动同步更新

## MODIFIED Requirements
无。

## REMOVED Requirements
无。
