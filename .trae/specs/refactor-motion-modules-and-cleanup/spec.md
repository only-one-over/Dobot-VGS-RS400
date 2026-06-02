# 运动模块重构与冗余清理 Spec

## Why
当前直线运动模块的坐标模式依赖相机识别结果+偏移量，逻辑不够直观；圆弧运动模块缺少点位/坐标模式切换；项目中存在少量未使用的导入和冗余代码。

## What Changes
- 直线运动逻辑重构：坐标模式改为直接输入目标坐标（不再依赖相机识别+偏移），增加"读取当前位置"按钮
- 圆弧运动模块增加点位/坐标模式切换
- 清理 gui_app.py 中未使用的导入（QSlider、QIcon）
- **不修改 dobot_api.py**

## Impact
- Affected code: `gui_app.py`（直线运动 UI + 逻辑、圆弧运动 UI + 逻辑、FlowThread 执行逻辑）
- Affected behavior: 直线运动坐标模式从"偏移量"改为"目标坐标"，圆弧运动新增点位模式

## ADDED Requirements

### Requirement: 直线运动坐标模式改为目标坐标输入
直线运动坐标模式 SHALL 直接输入目标坐标（X/Y/Z/Rx/Ry/Rz），不再使用"偏移值"概念。

#### Scenario: 坐标模式输入目标
- **WHEN** 用户在直线运动模块选择坐标模式
- **THEN** 显示6个目标坐标输入框（X/Y/Z/Rx/Ry/Rz）和速度输入框，标签为"目标 X"而非"偏移值 X"

#### Scenario: 读取当前位置填入目标
- **WHEN** 用户点击"读取当前位置"按钮
- **THEN** 系统读取机器人当前位姿并填入6个目标坐标输入框

#### Scenario: FlowThread 执行直线运动坐标模式
- **WHEN** FlowThread 执行直线运动模块且 mode="coords"
- **THEN** 直接使用模块参数中的 target_coords 作为目标坐标执行 MovL，不依赖 base_coords（相机识别结果）

### Requirement: 圆弧运动点位/坐标模式切换
圆弧运动模块 SHALL 支持点位模式和坐标模式切换。

#### Scenario: 圆弧运动坐标模式
- **WHEN** 用户在圆弧运动模块选择坐标模式
- **THEN** 显示半径和速度输入框（现有行为不变）

#### Scenario: 圆弧运动点位模式
- **WHEN** 用户在圆弧运动模块选择点位模式
- **THEN** 显示点位选择下拉框和坐标预览标签，选择点位后该点位坐标作为圆弧终点

#### Scenario: FlowThread 执行圆弧运动点位模式
- **WHEN** FlowThread 执行圆弧运动模块且 mode="point"
- **THEN** 使用 resolve_point 解析点位坐标作为圆弧终点，结合当前位姿和半径计算中间点，执行 MovC

### Requirement: 清理冗余代码
gui_app.py 中 SHALL 移除未使用的导入。

#### Scenario: 移除未使用导入
- **WHEN** 清理完成
- **THEN** QSlider 和 QIcon 从导入语句中移除

## MODIFIED Requirements

### Requirement: 直线运动参数编辑
直线运动参数编辑区域 SHALL 将"偏移值"改为"目标坐标"，增加"读取当前位置"按钮。坐标模式下参数名为 target_coords（6维），不再使用 offset。

### Requirement: 圆弧运动参数编辑
圆弧运动参数编辑区域 SHALL 新增模式切换控件（坐标模式/点位模式），点位模式下显示点位选择下拉框和坐标预览。

### Requirement: FlowThread 直线运动执行
FlowThread 中直线运动模块在坐标模式下 SHALL 直接使用 target_coords 作为目标位姿，不再依赖相机识别的 base_coords。

### Requirement: FlowThread 圆弧运动执行
FlowThread 中圆弧运动模块 SHALL 支持点位模式，从点位名称解析终点坐标。

## REMOVED Requirements
无。
