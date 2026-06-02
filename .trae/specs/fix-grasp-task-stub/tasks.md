# Tasks

- [x] Task 1: 修复 `run_grasping_task()` — 调用 `run_grasp_flow()` 执行完整流程
  - 修改 `gui_app.py` L1062-L1086 的 `run_grasping_task` 方法
  - 保留前置检查（相机已连接、机器人已连接、机器人已使能）
  - 移除 stub 弹窗 `QMessageBox.information(self, "提示", "抓取任务已启动")`
  - 改为直接调用 `self.run_grasp_flow()`

- [x] Task 2: 修复 `run_grasp_flow()` — camera_detected 无 base_coords 时报错
  - 修改 `gui_app.py` L1607 的条件分支
  - 当 `target == "camera_detected"` 但 `base_coords` 为 None 时，弹窗报错并 `return`

# Task Dependencies
- Task 1 与 Task 2 无顺序依赖，可并行执行
