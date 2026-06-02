# Tasks

- [x] Task 1: 修改 config.json 结构，支持多相机标定数据
  - [x] 1.1: 将现有 `calibration` 字段迁移为多相机结构（D435i 保留现有值，D405 使用默认值）
  - [x] 1.2: 确保向后兼容，旧格式自动迁移为新格式

- [x] Task 2: 修改 config_manager.py，增加多相机标定配置的读写接口
  - [x] 2.1: 新增 `get_calibration(camera_type)` 函数，返回指定相机的标定数据
  - [x] 2.2: 新增 `set_calibration(camera_type, tool_base_calib_pose, cam_base_calib_pose)` 函数
  - [x] 2.3: 新增 `get_all_calibrations()` 函数，返回所有相机标定数据
  - [x] 2.4: 新增 `get_camera_handeye_matrix(camera_type)` 函数，直接返回计算后的 4x4 矩阵

- [x] Task 3: 新增 hand_eye_calib.py 手眼标定管理模块
  - [x] 3.1: 实现 `HandEyeCalibManager` 类，封装标定矩阵的读取、修改、保存
  - [x] 3.2: 实现标定矩阵从位姿参数计算（tool_base_calib_pose + cam_base_calib_pose → T_cam2gripper）
  - [x] 3.3: 实现标定矩阵直接设置（支持用户直接输入 4x4 矩阵）
  - [x] 3.4: 实现保存到 config.json 的持久化

- [x] Task 4: 修改 vision_system.py，支持双相机和端点识别
  - [x] 4.1: VisionSystem.__init__ 接受 `camera_type` 参数（"D435i" 或 "D405"），根据类型加载对应标定矩阵
  - [x] 4.2: 根据相机类型配置 RealSense 流（D405 使用不同分辨率/帧率）
  - [x] 4.3: 新增 `calculate_object_endpoints` 方法，从分割掩码中提取铁钩两端端点坐标
  - [x] 4.4: 修改 `calculate_object_position` 方法，D435i 返回中心点，D405 返回端点+抓取位置
  - [x] 4.5: D405 端点提取逻辑：掩码骨架化 → 端点检测 → 深度查表 → 3D 坐标

- [x] Task 5: 修改 gui_app.py，新增手眼标定选项卡和相机选择
  - [x] 5.1: 新增"手眼标定"选项卡 UI（4x4 矩阵表格 × 相机数量，保存/重置按钮）
  - [x] 5.2: 实现标定矩阵的加载、编辑、保存、重置逻辑
  - [x] 5.3: 修改相机连接区域，增加相机类型下拉框（D435i/D405）
  - [x] 5.4: 修改 `connect_camera` 方法，根据选择的相机类型初始化 VisionSystem
  - [x] 5.5: 修改抓取流程编辑器中相机模块的参数，增加"相机选择"下拉框

- [x] Task 6: 修改 FlowThread 中的相机识别逻辑
  - [x] 6.1: 相机模块根据参数中的相机选择，使用对应 VisionSystem 实例
  - [x] 6.2: D405 模式下，使用端点坐标计算抓取位置（柄端→钩尖端方向 30% 处）
  - [x] 6.3: 确保两种相机的识别结果都能正确传递给后续运动模块

# Task Dependencies
- [Task 2] depends on [Task 1]
- [Task 3] depends on [Task 2]
- [Task 4] depends on [Task 2]
- [Task 5] depends on [Task 3]
- [Task 6] depends on [Task 4, Task 5]
