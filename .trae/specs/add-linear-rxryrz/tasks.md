# Tasks

- [x] Task 1: 直线运动参数面板添加Rx/Ry/Rz输入框
  - [x] SubTask 1.1: 在 linear_params 中添加 Rx/Ry/Rz 的 QDoubleSpinBox（范围-360~360，默认值0）
  - [x] SubTask 1.2: 布局调整为4行，第3行为速度

- [x] Task 2: 更新参数保存和执行逻辑
  - [x] SubTask 2.1: update_module_params 中 offset 保存为 [x, y, z, rx, ry, rz] 6个值
  - [x] SubTask 2.2: FlowThread.run() 直线运动中 target_pose 旋转部分使用 current_pose[3:] + offset[3:] 
  - [x] SubTask 2.3: view_current_grasp_flow 显示偏移值完整信息（已自动覆盖，offset列表含6个值）

# Task Dependencies
- 无
