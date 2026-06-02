# Tasks

- [x] Task 1: 相机内参动态获取 — 移除硬编码内参，改为从 profile 动态获取彩色相机内参
  - [x] SubTask 1.1: 将 `self.fx/fy/cx/cy` 改为从 `color_intrin` 获取
  - [x] SubTask 1.2: 移除硬编码值 `588.64174516, 589.11302626, 329.41480686, 236.65985072`
  - [x] SubTask 1.3: 更新日志输出，打印动态获取的内参值

- [x] Task 2: 深度范围参数调整 — 将 min_depth 从 0.1 改为 0.5，max_depth 从 3.0 改为 2.2
  - [x] SubTask 2.1: 修改 `__init__` 中的 `self.min_depth` 和 `self.max_depth` 默认值

- [x] Task 3: 新增深度补偿方法 — 添加 `extract_mask_point_cloud_with_median_compensation`
  - [x] SubTask 3.1: 将 shibie2.py 中的 `extract_mask_point_cloud_with_median_compensation` 适配为 VisionSystem 的实例方法
  - [x] SubTask 3.2: 使用 `self.fx/fy/cx/cy` 替代全局变量
  - [x] SubTask 3.3: 使用 `self.min_depth/max_depth` 替代全局参数

- [x] Task 4: 新增面积过滤方法 — 添加 `filter_detections_by_area`
  - [x] SubTask 4.1: 将 shibie2.py 中的 `filter_detections_by_area` 适配为 VisionSystem 的实例方法

- [x] Task 5: 改进 calculate_object_position — 集成深度补偿逻辑
  - [x] SubTask 5.1: 使用深度补偿方法获取填充后的深度图
  - [x] SubTask 5.2: 从补偿后的深度图获取中心点深度值
  - [x] SubTask 5.3: 保留原有80%位置抓取点计算逻辑

- [x] Task 6: 后处理集成面积过滤 — 在 `_postprocess_yolov8_py` 末尾调用面积过滤
  - [x] SubTask 6.1: 在返回检测结果前调用 `filter_detections_by_area`

- [x] Task 7: 增强调试日志
  - [x] SubTask 7.1: 在 `_postprocess_yolov8_py` 中添加输出形状、NMS前后数量日志
  - [x] SubTask 7.2: 在 `calculate_object_position` 中添加补偿信息日志
  - [x] SubTask 7.3: 在 `run_detection` 中添加检测数量日志

# Task Dependencies
- [Task 3] depends on [Task 1] (深度补偿方法需要使用动态内参)
- [Task 5] depends on [Task 3] (calculate_object_position 需要深度补偿方法)
- [Task 6] depends on [Task 4] (后处理需要面积过滤方法)
