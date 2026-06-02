# 修复抓取任务执行第一步后停止 - Spec

## Why
用户点击"运行抓取任务"按钮后，机器人移动到初始位置就停止了，不会继续执行后续的相机识别、直线运动、圆弧运动等步骤。根因有二：

1. **`run_grasping_task()` 是未完成的占位函数（Stub）**：该方法仅执行使能+移动初始位置后直接弹窗结束，注释 `#这里可以添加抓取任务的可视化执行流程` 表明该功能从未完成实现。
2. **`run_grasp_flow()` 中存在静默跳过 bug**：当 move 模块的 target 为 `camera_detected` 但 `base_coords` 为 None 时，该步骤被静默跳过，没有任何错误提示。

## What Changes
- `gui_app.py` — `run_grasping_task()` SHALL 调用 `run_grasp_flow()` 执行完整流程，不再是空壳
- `gui_app.py` — `run_grasp_flow()` 中当 move 模块 target 为 `camera_detected` 但 base_coords 为 None 时 SHALL 弹窗报错并停止，不再静默跳过

## Impact
- Affected specs: 无
- Affected code: `dobot_move/gui_app.py` L1062-L1086, L1607

## MODIFIED Requirements
### Requirement: run_grasping_task 执行完整流程
`run_grasping_task()` SHALL 在完成前置检查（相机已连接、机器人已连接、机器人已使能）后，直接调用 `run_grasp_flow()` 执行完整的抓取流程。

#### Scenario: 点击运行抓取任务
- **GIVEN** 相机已连接、机器人已连接且已使能
- **WHEN** 用户点击"运行抓取任务"按钮
- **THEN** 执行完整的抓取流程（多个步骤连续执行），直到所有步骤完成或某步骤失败

### Requirement: camera_detected 无 base_coords 时报错
`run_grasp_flow()` 中 move 模块当 `target == "camera_detected"` 且 `base_coords` 为 None 时 SHALL 弹窗提示错误并停止执行，不再静默跳过该步骤。

#### Scenario: 流程缺少前置相机步骤
- **GIVEN** 流程中包含 target 为 `camera_detected` 的 move 步骤，但 base_coords 为 None
- **WHEN** 执行到该步骤
- **THEN** 弹出错误提示"相机未识别到物体坐标，请确保流程中先有相机识别步骤"
- **AND** 流程停止执行
