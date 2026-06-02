# 点位管理界面优化 Spec

## Why
点位管理表格中行间距太小导致点位显示重叠，且默认点位（p_d435i、p_u405、p_n405）的坐标不应允许用户手动编辑，只能通过相机识别自动更新。

## What Changes
- 增大点位表格行高，避免行内容重叠
- 默认点位（is_default=True）的坐标列设为只读，用户不可手动修改
- 默认点位的"相对"复选框和"基准点位"下拉框也设为不可操作

## Impact
- Affected code: `gui_app.py`（refresh_points_table 方法）

## ADDED Requirements

### Requirement: 点位表格行间距增大
点位管理表格 SHALL 设置足够的行高，避免行内容重叠。

#### Scenario: 查看点位表格
- **WHEN** 用户查看点位管理选项卡
- **THEN** 每行高度足够显示 QDoubleSpinBox 控件，不出现文字或控件重叠

### Requirement: 默认点位只读
默认点位（p_d435i、p_u405、p_n405）的坐标 SHALL 为只读，用户只能通过相机识别更新，不能手动编辑。

#### Scenario: 查看默认点位
- **WHEN** 用户查看点位管理表格中的默认点位
- **THEN** 坐标列显示数值但不可编辑（QDoubleSpinBox 禁用），"相对"复选框禁用，"基准点位"下拉框禁用

#### Scenario: 相机识别更新默认点位
- **WHEN** 流程中执行相机识别
- **THEN** 默认点位坐标正常更新（程序内部调用 set_point）

#### Scenario: 自定义点位可编辑
- **WHEN** 用户查看自定义点位
- **THEN** 坐标列、"相对"复选框、"基准点位"下拉框均可正常编辑

## MODIFIED Requirements
无。

## REMOVED Requirements
无。
