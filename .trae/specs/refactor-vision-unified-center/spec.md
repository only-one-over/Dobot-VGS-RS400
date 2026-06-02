# 视觉系统重构：D435i 双模式 + D405 几何中心识别 Spec

## Why
当前 D435i 相机识别在抓取流程中是"一次性拍5帧取最佳"的模式，无法实时更新坐标；D405 使用骨架化端点检测逻辑复杂且不稳定。需要：1) 为 D435i 设计低帧率持续识别模块（5fps 实时更新坐标）和关闭识别模块；2) 统一 D435i/D405 均识别掩码几何中心，移除 D405 的骨架化端点检测。

## What Changes
- **vision_system.py**：移除 `calculate_object_endpoints` 及所有骨架化/端点检测方法；`calculate_object_position` 不再区分 D435i/D405，统一使用掩码几何中心；新增 `start_low_fps_recognition` / `stop_low_fps_recognition` 方法
- **gui_app.py**：`CameraTestWorker` 适配 D405 不再返回端点坐标；新增 D435i 低帧率识别工作线程 `D435iLowFpsWorker`
- **gui_mixins/vision_mixin.py**：新增 D435i 低帧率识别/停止按钮逻辑；移除 D405 端点坐标显示
- **gui_mixins/grasp_flow_mixin.py**：FlowThread 中 D405 相机识别模块不再更新 p_u405/p_n405 端点点位，统一更新 p_d435i 风格的单点点位
- **visual_servo_controller.py**：移除 `handle_end` / `hook_tip` 目标类型支持，仅保留 `grasp_point`（几何中心）
- **BREAKING**：移除 D405 端点检测相关点位 `p_u405` / `p_n405` 的自动更新逻辑

## Impact
- Affected specs: 视觉系统核心逻辑、抓取流程、视觉伺服
- Affected code:
  - `dobot_move/vision_system.py` — 移除端点检测，统一几何中心，新增低帧率识别
  - `dobot_move/gui_app.py` — CameraTestWorker 适配，新增 D435iLowFpsWorker
  - `dobot_move/gui_mixins/vision_mixin.py` — 新增低帧率识别按钮逻辑
  - `dobot_move/gui_mixins/grasp_flow_mixin.py` — FlowThread D405 逻辑简化
  - `dobot_move/visual_servo_controller.py` — 移除端点目标类型

## ADDED Requirements

### Requirement: D435i 低帧率持续识别模块
系统 SHALL 提供 D435i 低帧率（5fps）持续识别模式，在后台线程中持续运行检测并实时更新目标坐标到点位表。

#### Scenario: 启动低帧率识别
- **WHEN** 用户点击"D435i 低帧率识别"按钮
- **THEN** 系统以 5fps 频率持续检测，每帧检测到目标后实时更新 `p_d435i` 点位坐标，GUI 显示当前检测坐标

#### Scenario: 关闭低帧率识别
- **WHEN** 用户点击"停止识别"按钮
- **THEN** 低帧率识别线程停止，不再更新坐标

### Requirement: D435i 识别关闭模块
系统 SHALL 提供关闭 D435i 实时识别的功能，停止后台检测线程。

#### Scenario: 识别关闭
- **WHEN** 低帧率识别正在运行时用户点击"停止识别"
- **THEN** 识别线程安全退出，相机保持连接状态，可随时重新启动识别

### Requirement: D405 统一几何中心识别
系统 SHALL 将 D405 相机的识别逻辑从"骨架化端点检测"改为"掩码几何中心"，与 D435i 使用完全相同的坐标计算方式。

#### Scenario: D405 识别几何中心
- **WHEN** D405 相机检测到目标
- **THEN** 返回掩码几何中心的 3D 坐标（与 D435i 格式一致），不再返回 handle_end_coords / hook_tip_coords / hook_length_mm

## MODIFIED Requirements

### Requirement: calculate_object_position 统一逻辑
`calculate_object_position` SHALL 不再根据 `camera_type` 分支到 `calculate_object_endpoints`，而是对 D435i 和 D405 统一使用掩码几何中心计算。当前 D435i 的几何中心计算使用 `center_y = y_min + (y_max - y_min) * 0.8`（偏下 80%），修改为使用真正的掩码几何中心 `(mean_x, mean_y)`。

### Requirement: FlowThread D405 相机识别模块简化
FlowThread 中 D405 相机识别模块 SHALL 与 D435i 使用相同的逻辑：检测几何中心 → 转换坐标 → 更新单点点位。不再更新 `p_u405` 和 `p_n405` 点位。

### Requirement: VisualServoController 仅支持几何中心
`VisualServoController.servo_to_target` SHALL 移除 `handle_end` 和 `hook_tip` 目标类型，仅保留 `grasp_point`（几何中心）。`_update_points` 方法不再更新 `p_u405` / `p_n405`。

### Requirement: CameraTestWorker 适配
`CameraTestWorker` SHALL 不再为 D405 单独返回 `handle_end_coords` / `hook_tip_coords` / `hook_length_mm`，统一返回 `camera_coords`。

## REMOVED Requirements

### Requirement: D405 骨架化端点检测
**Reason**: 统一为几何中心识别，简化逻辑
**Migration**: `calculate_object_endpoints`、`_skeletonize_mask`、`_find_skeleton_endpoints`、`_find_hull_endpoints`、`_classify_endpoints`、`_pixel_to_3d` 方法全部移除

### Requirement: D405 端点点位自动更新
**Reason**: 不再检测端点，p_u405 / p_n405 不再由视觉系统自动更新
**Migration**: 保留点位定义在 config.json 中（用户可手动设置），但视觉流程不再写入
