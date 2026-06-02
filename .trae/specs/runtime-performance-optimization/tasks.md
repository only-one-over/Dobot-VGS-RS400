# Tasks

- [x] Task 1: 骨架化算法最大迭代次数保护
  - [x] SubTask 1.1: 在 `vision_system.py` 的 `_skeletonize_mask` 方法中添加 `MAX_ITERATIONS = 200` 常量
  - [x] SubTask 1.2: 将 `while True` 改为 `for _ in range(MAX_ITERATIONS)`，并添加 `else` 分支在达到上限时使用 `cv2.ximgproc.thinning` 降级
  - [x] SubTask 1.3: 在 `_skeletonize_mask` 方法的降级分支中添加 logger 警告日志

- [x] Task 2: Modbus 周期从缓存 feed_data 提取位姿
  - [x] SubTask 2.1: 在 `robot_controller.py` 的 `_update_modbus_status` 方法中，将 `pose = self.get_current_pose()` 替换为从 `self.feed_data` 的 `ToolVectorActual` 字段提取坐标
  - [x] SubTask 2.2: 添加 `feed_data` 为 None 时的短路保护，跳过位姿更新

- [x] Task 3: CameraTestWorker 帧率控制与图像拷贝精简
  - [x] SubTask 3.1: 在 `gui_app.py` `CameraTestWorker.__init__` 中添加 `self.last_frame_time = 0` 和 `self.frame_interval = 1.0 / 30.0`
  - [x] SubTask 3.2: 在 `CameraTestWorker.run()` 开头添加帧率控制：`elapsed = time.time() - self.last_frame_time; if elapsed < self.frame_interval: time.sleep(self.frame_interval - elapsed)`
  - [x] SubTask 3.3: 删除 `display_image = color_image.copy()`，直接使用 `np.asanyarray(color_frame.get_data())` 作为绘图画布
  - [x] SubTask 3.4: 将 `from time import sleep` 添加到 CameraTestWorker 所在的 import 区域

- [x] Task 4: 实时反馈对话框 sleep 间隔优化
  - [x] SubTask 4.1: 将 `realtime_feedback_dialog.py` `_feed_loop` 中的 `time.sleep(0.001)` 改为 `time.sleep(0.005)`

- [x] Task 5: ONNX Runtime 延迟导入
  - [x] SubTask 5.1: 从 `vision_system.py` 模块顶部删除 `import onnxruntime as ort`
  - [x] SubTask 5.2: 在 `VisionSystem.__init__` 方法中 `_load_onnx_model()` 调用之前，添加局部 `import onnxruntime as ort`
  - [x] SubTask 5.3: 同步修改 `gui_app.py` 视觉依赖检测块：确认 `import onnxruntime as ort` 已位于 try 块内
  - [x] SubTask 5.4: 确保 `_missing_deps` 中 `onnxruntime` 的检测逻辑仍然有效

- [x] Task 6: 点位表增量更新
  - [x] SubTask 6.1: 修改 `point_management_mixin.py` `refresh_points_table` 方法，仅当 `rowCount() != len(points)` 时才调整行数
  - [x] SubTask 6.2: 对已存在的行，仅更新 SpinBox 的 `setValue()` 和 CheckBox/ComboBox 的当前状态，不重新创建 widget
  - [x] SubTask 6.3: 在此过程中屏蔽信号连接，使用 `blockSignals(True)` / `blockSignals(False)` 避免更新触发 `_on_point_coord_changed` 回调

- [x] Task 7: resolve_point 移除副作用
  - [x] SubTask 7.1: 在 `config_manager.py` `resolve_point` 函数中，删除 `set_points(points)` 调用
  - [x] SubTask 7.2: 保留 `point["coords"] = list(resolved)` 的内存更新逻辑（更新缓存中的值）

# Task Dependencies
- 所有 7 个任务修改不同文件或同一文件的不同区域，无相互依赖，**可完全并行执行**
- Task 5 修改 `vision_system.py` 和 `gui_app.py` 的导入区，与 Task 1（修改 vision_system.py 方法内部）和 Task 3（修改 gui_app.py 方法内部）无冲突
