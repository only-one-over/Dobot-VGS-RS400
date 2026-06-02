# 视觉系统升级：ByteTrack + 卡尔曼滤波 + RealSense 滤波链 Spec

## Why
当前视觉系统单帧检测无记忆，检测丢失即失败，3D 坐标帧间抖动 ±5-10mm，深度图空洞用简单中位数补偿。需要引入多目标跟踪、时域平滑和 RealSense 官方深度滤波链，将检测成功率提升至 98%+，坐标抖动降至 ±1-2mm。

## What Changes
- 新增 `tracker.py`：ByteTrack 多目标跟踪器（STrack + BYTETracker），实现帧间目标关联、低分检测利用、丢失轨迹保持
- 新增 `kalman_filter_3d.py`：3D 位置卡尔曼滤波器（6 状态 [x,y,z,vx,vy,vz]，3 观测 [x,y,z]），实现坐标时域平滑和丢失预测
- 新增 `depth_processor.py`：深度处理增强模块，集成 RealSense 官方滤波链（Decimation → Spatial → Temporal → Hole-Filling）+ 空域 inpainting 回退
- 修改 `vision_system.py`：集成 ByteTrack 跟踪、卡尔曼平滑、深度处理增强，新增 `run_detection_tracked()`、`calculate_object_position_smoothed()` 方法，保留原方法作为回退
- 修改 `gui_app.py` FlowThread 相机模块：支持多帧采集 + 跟踪 + 平滑，加入置信度门控
- 修改 `requirements.txt`：新增 `scipy`（已有）、`lapx`（ByteTrack 线性分配依赖）

## Impact
- Affected specs: 无（新功能）
- Affected code: `vision_system.py`（核心修改）、`gui_app.py`（FlowThread 相机模块）、`requirements.txt`
- 新增文件: `tracker.py`、`kalman_filter_3d.py`、`depth_processor.py`

## ADDED Requirements

### Requirement: ByteTrack 多目标跟踪
系统 SHALL 在每帧检测结果上运行 ByteTrack 跟踪，为目标分配唯一 track_id，实现帧间关联。

#### Scenario: 正常跟踪
- **WHEN** 连续帧检测到同一目标
- **THEN** 该目标保持相同 track_id，bbox/mask 逐帧更新

#### Scenario: 低分检测利用
- **WHEN** 目标被部分遮挡导致检测置信度低于 track_thresh（0.5）但仍高于 detect_thresh（0.1）
- **THEN** ByteTrack 第二轮匹配将该低分检测与已有轨迹关联，轨迹不丢失

#### Scenario: 短暂丢失保持
- **WHEN** 目标在 track_buffer（30）帧内未被检测到
- **THEN** 轨迹标记为 lost 但保留，重新检测到时恢复 track_id

### Requirement: 3D 卡尔曼滤波平滑
系统 SHALL 对 3D 坐标进行卡尔曼滤波，减少帧间抖动，并在检测丢失时提供预测位置。

#### Scenario: 正常平滑
- **WHEN** 连续帧获得有效 3D 观测
- **THEN** 输出平滑后的坐标，抖动 < ±2mm

#### Scenario: 检测丢失预测
- **WHEN** 当前帧检测丢失但轨迹仍在 track_buffer 内
- **THEN** 卡尔曼滤波器基于运动模型预测位置，返回 predicted=True 标记和置信度

#### Scenario: 置信度评估
- **WHEN** 滤波器运行
- **THEN** 基于协方差矩阵迹输出 0-1 置信度分数，用于 GUI 层门控判断

### Requirement: RealSense 官方滤波链
系统 SHALL 使用 pyrealsense2 内置滤波器对深度图进行硬件级处理，替代自定义中位数补偿。

#### Scenario: 滤波链处理
- **WHEN** 获取一帧深度数据
- **THEN** 依次通过 Decimation Filter（降采样去噪）→ Spatial Filter（边缘感知平滑）→ Temporal Filter（时域加权平均）→ Hole-Filling Filter（空洞填充），输出处理后的深度帧

#### Scenario: 滤波链可配置
- **WHEN** 用户需要调整深度处理参数
- **THEN** 可通过 VisionSystem 构造参数控制滤波器开关和参数（如 temporal_filter_alpha、spatial_filter_alpha 等）

### Requirement: 多帧采集 + 置信度门控
系统 SHALL 在流程执行时连续采集多帧，累积跟踪和滤波结果，达到置信度阈值后输出。

#### Scenario: 高置信度快速输出
- **WHEN** 连续采集 N 帧（默认 5 帧）中某帧置信度 > 0.9
- **THEN** 提前退出采集，使用该帧结果

#### Scenario: 低置信度失败
- **WHEN** N 帧采集完毕最高置信度 < 0.3
- **THEN** 流程报告检测失败

### Requirement: 向后兼容
系统 SHALL 保留原有 `run_detection()`、`calculate_object_position()`、`calculate_object_endpoints()` 方法，新增方法为可选增强。

#### Scenario: 关闭增强功能
- **WHEN** VisionSystem 初始化时设置 `enable_tracking=False`
- **THEN** 行为与升级前完全一致

## MODIFIED Requirements
无。

## REMOVED Requirements
无。
