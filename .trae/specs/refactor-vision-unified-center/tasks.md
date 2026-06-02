# Tasks

- [x] Task 1: 重构 vision_system.py — 移除端点检测，统一几何中心
  - [x] SubTask 1.1: 移除 `calculate_object_endpoints` 方法
  - [x] SubTask 1.2: 移除 `_skeletonize_mask`、`_find_skeleton_endpoints`、`_find_hull_endpoints`、`_classify_endpoints`、`_pixel_to_3d` 方法
  - [x] SubTask 1.3: 修改 `calculate_object_position`：移除 D405 分支，统一使用掩码几何中心（mean_x, mean_y），不再使用 0.8 偏移
  - [x] SubTask 1.4: 修改 `calculate_object_position_smoothed`：移除 D405 分支，统一调用 `calculate_object_position`

- [x] Task 2: 重构 visual_servo_controller.py — 移除端点目标类型
  - [x] SubTask 2.1: 移除 `servo_to_target` 中 `handle_end` / `hook_tip` 目标类型分支
  - [x] SubTask 2.2: 简化 `_update_points`：移除 `p_u405` / `p_n405` 更新逻辑

- [x] Task 3: 重构 gui_app.py — CameraTestWorker 适配 + 新增 D435iLowFpsWorker
  - [x] SubTask 3.1: CameraTestWorker 移除 D405 端点坐标返回逻辑
  - [x] SubTask 3.2: 新增 `D435iLowFpsWorker` 类：5fps 低帧率持续识别线程，每帧更新坐标并发射信号

- [x] Task 4: 重构 gui_mixins/vision_mixin.py — 新增低帧率识别按钮逻辑
  - [x] SubTask 4.1: 新增 `start_d435i_low_fps` 方法：启动 D435iLowFpsWorker
  - [x] SubTask 4.2: 新增 `stop_d435i_low_fps` 方法：停止 D435iLowFpsWorker
  - [x] SubTask 4.3: 新增 `_on_low_fps_result` 方法：处理低帧率识别结果，更新 GUI 显示和点位
  - [x] SubTask 4.4: 移除 D405 端点坐标显示逻辑（cam_test_handle_coords / cam_test_tip_coords / cam_test_hook_length）

- [x] Task 5: 重构 gui_mixins/grasp_flow_mixin.py — FlowThread D405 逻辑简化
  - [x] SubTask 5.1: FlowThread 中 D405 相机识别模块不再更新 p_u405 / p_n405，统一更新 p_d435i 风格单点点位
  - [x] SubTask 5.2: 移除 FlowThread 中 D405 端点坐标日志输出

# Task Dependencies
- [Task 2] depends on [Task 1] (visual_servo_controller 依赖 vision_system 的接口变更)
- [Task 3] depends on [Task 1] (CameraTestWorker 依赖 vision_system 的接口变更)
- [Task 4] depends on [Task 3] (vision_mixin 依赖 D435iLowFpsWorker)
- [Task 5] depends on [Task 1] (FlowThread 依赖 vision_system 的接口变更)
- [Task 1] 可独立执行
