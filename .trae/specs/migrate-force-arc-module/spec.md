# 力控圆弧功能模块移植 Spec

## Why
当前 GUI 流程系统中的"圆弧运动"模块仅使用简单的 MovC 指令（三点定弧），而项目已有完整的力控圆弧功能（ArcTrajectoryPlanner + ForceFeedbackMonitor + ForceArcController），但尚未集成到 GUI 流程系统中。需要按照移植指南将力控圆弧功能作为新的功能模块集成到 GUI。

## What Changes
- 在模块选择下拉框中新增"力控圆弧"模块类型
- 创建力控圆弧参数 UI 面板（圆弧参数 + 力控参数）
- 在 FlowThread 中新增力控圆弧执行分支
- 在添加模块、参数面板切换、参数更新、流程显示中支持力控圆弧
- 修改 ForceArcController 使其可接受外部 dashboard 对象（复用已有连接）

## Impact
- Affected code: `gui_app.py`（UI + FlowThread + 模块管理）、`force_arc_controller.py`（支持外部 dashboard）
- Affected specs: 无

## ADDED Requirements
### Requirement: 力控圆弧模块集成
系统 SHALL 在 GUI 流程系统中提供"力控圆弧"功能模块，支持配置圆弧参数和力控参数，并通过 ForceArcController 执行力控引导的圆弧运动。

#### Scenario: 添加力控圆弧模块
- **WHEN** 用户在模块选择下拉框中选择"力控圆弧"并点击添加
- **THEN** 流程中新增一个 type="force_arc" 的模块，包含圆弧参数和力控参数

#### Scenario: 编辑力控圆弧参数
- **WHEN** 用户选中力控圆弧模块并修改参数面板中的值
- **THEN** 圆心、半径、起止角度、旋转轴、路点数、速度、力控轴、修正增益等参数被保存到模块

#### Scenario: 执行力控圆弧运动
- **WHEN** 流程执行到力控圆弧模块
- **THEN** 使用 ForceArcController 沿圆弧轨迹运动，实时力反馈修正旋转方向

#### Scenario: 流程显示力控圆弧信息
- **WHEN** 流程列表中显示力控圆弧模块
- **THEN** 显示圆心、半径、角度范围、旋转轴、力控增益等关键参数

## MODIFIED Requirements
无

## REMOVED Requirements
无
