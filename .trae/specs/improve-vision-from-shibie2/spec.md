# 参考 shibie2.py 改进识别物体代码 - Spec

## Why
当前 `vision_system.py` 的物体识别和深度获取逻辑存在不足：深度无效区域未补偿导致抓取点丢失、缺少面积过滤导致误检、相机内参硬编码不够灵活、深度范围参数过于宽松。参考已验证可工作的 `shibie2.py` 脚本，将其关键改进合并到项目中。

## What Changes
- `vision_system.py` — 新增深度补偿方法 `extract_mask_point_cloud_with_median_compensation`，对掩码区域无效深度用中位数填充
- `vision_system.py` — 新增面积过滤方法 `filter_detections_by_area`，过滤面积过小的误检
- `vision_system.py` — 相机内参改为从 profile 动态获取（彩色相机内参），移除硬编码值
- `vision_system.py` — 深度范围参数调整为 `min_depth=0.5, max_depth=2.2`
- `vision_system.py` — `calculate_object_position` 方法集成深度补偿逻辑
- `vision_system.py` — 后处理 `_postprocess_yolov8_py` 集成面积过滤
- `vision_system.py` — 增强调试日志（输出形状、NMS前后数量、补偿信息等）

## Impact
- Affected specs: 无
- Affected code: `dobot_move/vision_system.py`

## ADDED Requirements

### Requirement: 深度补偿
`VisionSystem` SHALL 提供 `extract_mask_point_cloud_with_median_compensation` 方法，对掩码区域内无深度信息的像素使用该区域有效深度的中位数进行填充补偿。

#### Scenario: 掩码中心点深度无效
- **GIVEN** 检测到物体掩码，但掩码中心点深度值为0或超出范围
- **WHEN** 调用 `calculate_object_position`
- **THEN** 使用掩码区域有效深度的中位数填充无效区域，确保抓取点深度可计算

#### Scenario: 掩码区域完全无有效深度
- **GIVEN** 掩码区域内所有像素深度值均无效
- **WHEN** 调用 `calculate_object_position`
- **THEN** 返回 None 并打印警告

### Requirement: 面积过滤
`VisionSystem` SHALL 在后处理阶段过滤面积过小的检测结果（面积 < 图像总面积的 0.5%），减少误检。

#### Scenario: 检测到多个目标含误检
- **GIVEN** 模型输出3个检测结果，其中1个面积仅为图像的0.1%
- **WHEN** 后处理完成
- **THEN** 面积过小的检测结果被过滤掉，仅保留2个有效检测

#### Scenario: 仅检测到1个目标
- **GIVEN** 模型输出1个检测结果
- **WHEN** 后处理完成
- **THEN** 不过滤，保留该检测结果

### Requirement: 相机内参动态获取
`VisionSystem` SHALL 从 RealSense profile 动态获取彩色相机内参（fx, fy, cx, cy），而非使用硬编码值。

#### Scenario: 不同相机或分辨率
- **GIVEN** 使用不同型号的 RealSense 相机或不同分辨率配置
- **WHEN** `VisionSystem` 初始化
- **THEN** 自动获取正确的相机内参，无需手动修改代码

## MODIFIED Requirements

### Requirement: 深度范围参数
`VisionSystem` SHALL 使用 `min_depth=0.5, max_depth=2.2` 作为默认深度范围，匹配实际工作距离。

#### Scenario: 物体在0.3米处
- **GIVEN** 物体距离相机0.3米
- **WHEN** 计算物体位置
- **THEN** 深度超出最小范围，返回 None 并提示

### Requirement: calculate_object_position 集成深度补偿
`calculate_object_position` SHALL 使用深度补偿逻辑获取抓取点深度，而非仅尝试中心点后简单回退。

#### Scenario: 中心点深度无效但周围有有效深度
- **GIVEN** 掩码80%位置中心点深度为0，但掩码区域有其他有效深度
- **WHEN** 调用 `calculate_object_position`
- **THEN** 使用中位数深度补偿后，计算中心点的3D坐标

### Requirement: 后处理集成面积过滤
`_postprocess_yolov8_py` SHALL 在NMS之后、返回结果之前，调用面积过滤方法过滤过小检测。

#### Scenario: 多个检测结果含小面积
- **GIVEN** NMS后保留3个检测结果
- **WHEN** 后处理返回
- **THEN** 面积小于图像0.5%的检测被过滤
