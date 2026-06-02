# 删除夹爪UI + 点位重构 + D435i低帧率集成 + 文档更新 Spec

## Why
项目需要精简界面（移除夹爪相关UI和代码）、统一初始点位为两个（d435i 和 d405）、将 D435i 5fps 低帧率识别功能集成到 GUI 模块中（含 UI 控件）、并同步更新说明文档。

## What Changes
- 删除夹爪相关的 UI 控件、按钮、布局和对应的方法代码
- 删除 `gripper_controller.py` 的初始化和引用
- 将初始点位从 `p_d435i` / `p_u405` / `p_n405` 三个改为 `d435i` / `d405` 两个
- 在 GUI 视觉选项卡中添加 D435i 低帧率识别的 UI 控件（启动/停止按钮、状态标签、坐标显示）
- 将 FlowThread 中 D405 识别更新点位改为 `d405`（而非 `p_d435i`）
- 更新 README.md 和 PORTING_GUIDE.md

## Impact
- Affected code:
  - `dobot_move/gui_app.py` — 删除夹爪 UI、夹爪模块参数、FlowThread 夹爪逻辑
  - `dobot_move/gui_mixins/robot_control_mixin.py` — 删除夹爪方法、夹爪监控线程
  - `dobot_move/gui_mixins/vision_mixin.py` — 添加 D435i 低帧率识别 UI 控件
  - `dobot_move/workers.py` — 删除夹爪初始化逻辑
  - `dobot_move/config_manager.py` — 修改默认点位为 d435i / d405
  - `dobot_move/config.json` — 修改点位结构
  - `dobot_move/visual_servo_controller.py` — 点位名更新
  - `README.md` / `PORTING_GUIDE.md` — 文档更新

## ADDED Requirements

### Requirement: D435i 低帧率识别 UI 集成
系统 SHALL 在视觉选项卡中提供 D435i 低帧率识别的 UI 控件，包括启动按钮、停止按钮、状态标签、相机/末端/基座坐标显示。

#### Scenario: 用户通过 UI 启动低帧率识别
- **WHEN** 用户点击"D435i 低帧率识别"区域的"启动"按钮
- **THEN** D435iLowFpsWorker 开始以 5fps 运行，UI 显示"运行中"状态，坐标实时更新

### Requirement: D405 识别更新 d405 点位
系统 SHALL 在 D405 相机识别到目标时更新 `d405` 点位（而非 `p_d435i`）。

#### Scenario: D405 识别更新 d405 点位
- **WHEN** FlowThread 中 D405 相机识别到目标并计算基座坐标
- **THEN** 更新 `d405` 点位坐标

## MODIFIED Requirements

### Requirement: 初始点位为 d435i 和 d405 两个
`_DEFAULT_POINTS` SHALL 仅包含 `d435i` 和 `d405` 两个默认点位，不再包含 `p_d435i`、`p_u405`、`p_n405`。

### Requirement: 删除夹爪相关 UI 和代码
系统 SHALL 移除所有夹爪相关的 UI 控件（开/关按钮、位置标签、参数编辑器）、方法（`gripper_open`、`gripper_close`、`update_gripper_position`）、初始化逻辑和监控线程。FlowThread 中移除 `gripper` 模块类型。模块拼接工具中移除"夹爪开合"选项。

## REMOVED Requirements

### Requirement: 夹爪控制器
**Reason**: 用户要求删除夹爪相关功能
**Migration**: `gripper_controller.py` 文件保留但不再被项目代码引用

### Requirement: p_u405 / p_n405 点位
**Reason**: 统一为 d435i / d405 两个点位
**Migration**: 旧点位从 config.json 中移除
