# 点位表格 UI 修复 Spec

## Why
点位管理表格存在三个问题：默认相机点位不应显示相对坐标相关列；输入框宽度和列宽不合理；选取相对基准点位后无反应。

## What Changes
- 默认点位行隐藏"相对"和"基准点位"列的控件，仅显示名称和坐标数值
- 调整表格列宽分配：名称列固定宽度，坐标列等宽拉伸，相对/基准点位列适当宽度
- 修复相对点位选取后不触发坐标重算的 bug

## Impact
- Affected code: `gui_app.py`（refresh_points_table 方法及相关）

## ADDED Requirements

### Requirement: 默认点位不显示相对坐标列
默认点位（p_d435i、p_u405、p_n405）的"相对"和"基准点位"列 SHALL 不显示任何控件，仅显示空白。

#### Scenario: 查看默认点位行
- **WHEN** 用户查看点位管理表格中的默认点位
- **THEN** "相对"列和"基准点位"列为空白，不显示复选框或下拉框

### Requirement: 表格列宽优化
点位表格 SHALL 设置合理的列宽分配，名称列固定宽度，坐标列等宽拉伸。

#### Scenario: 查看表格列宽
- **WHEN** 用户查看点位管理表格
- **THEN** 名称列宽度约 100px，X/Y/Z/Rx/Ry/Rz 列等宽拉伸填满剩余空间，"相对"列约 60px，"基准点位"列约 100px

### Requirement: 相对点位选取后触发坐标重算
选取相对基准点位后 SHALL 立即触发坐标重算并更新显示。

#### Scenario: 选择基准点位
- **WHEN** 用户勾选"相对"并选择基准点位
- **THEN** 当前点位的坐标立即更新为基准点位坐标+偏移量的计算结果

#### Scenario: 勾选相对复选框
- **WHEN** 用户勾选"相对"复选框
- **THEN** 基准点位下拉框启用，且当前坐标立即根据基准点位+偏移量重算

## MODIFIED Requirements
无。

## REMOVED Requirements
无。
