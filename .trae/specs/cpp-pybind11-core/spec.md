# C++ 核心瓶颈 + Pybind11 绑定 Spec

## Why
当前项目视觉处理（YOLOv8 后处理、NMS、掩码处理、坐标变换）均由纯 Python 实现，在实时机器人抓取场景中成为性能瓶颈。将计算密集型核心用 C++ 重写并通过 Pybind11 暴露给 Python，可显著降低延迟，提升实时性。

## What Changes
- 新增 `cpp_core/` 目录，包含 C++ 源码和 CMakeLists.txt 构建系统
- 用 C++ 实现以下核心模块，通过 Pybind11 绑定为 Python 模块 `dobot_core`：
  - **坐标变换**：`euler2rot`、`pose2matrix`、齐次坐标变换（相机→末端→基座）
  - **NMS（非极大值抑制）**：替代 Python 纯 NumPy 实现
  - **YOLOv8 后处理**：检测框解码 + 掩码生成（`process_mask` + `postprocess_yolov8`）
- 修改 `vision_system.py`，将瓶颈函数调用替换为 `dobot_core` 模块
- 修改 `transform_utils.py`，将坐标变换替换为 `dobot_core` 模块
- 添加构建脚本 `build_cpp.py`，一键编译 C++ 扩展

## Impact
- Affected specs: 视觉系统后处理管线、坐标变换
- Affected code:
  - `dobot_move/vision_system.py` — 调用替换为 `dobot_core`
  - `dobot_move/transform_utils.py` — 坐标变换替换为 `dobot_core`
  - 新增 `cpp_core/` 目录 — C++ 源码 + 构建系统
  - 新增 `build_cpp.py` — 构建脚本

## ADDED Requirements

### Requirement: C++ 坐标变换模块
系统 SHALL 提供 C++ 实现的坐标变换函数，通过 `dobot_core.transforms` 模块暴露：
- `euler2rot(rx, ry, rz, degree=True)` → 返回 3x3 旋转矩阵（numpy array）
- `pose2matrix(x, y, z, rx, ry, rz)` → 返回 4x4 齐次变换矩阵（numpy array）
- `transform_point(matrix, point)` → 齐次矩阵乘点坐标，返回 3D 坐标

#### Scenario: 坐标变换结果与 Python 版本一致
- **WHEN** 对相同输入分别调用 Python `euler2rot` / `pose2matrix` 和 C++ `dobot_core.transforms.euler2rot` / `dobot_core.transforms.pose2matrix`
- **THEN** 输出结果在浮点精度 1e-6 范围内一致

### Requirement: C++ NMS 模块
系统 SHALL 提供 C++ 实现的非极大值抑制函数，通过 `dobot_core.nms` 模块暴露：
- `nms(boxes, scores, iou_threshold=0.5)` → 返回保留的索引列表

#### Scenario: NMS 结果与 Python 版本一致
- **WHEN** 对相同输入分别调用 Python `VisionSystem._nms_py` 和 C++ `dobot_core.nms.nms`
- **THEN** 返回的保留索引列表完全一致

### Requirement: C++ YOLOv8 后处理模块
系统 SHALL 提供 C++ 实现的 YOLOv8 后处理函数，通过 `dobot_core.yolo` 模块暴露：
- `postprocess_yolov8(outputs, original_size, scale, offset, new_size, num_classes, conf_threshold, iou_threshold)` → 返回检测结果列表
- `process_mask(protos, masks_in, bboxes, shape, scale, offset, new_size, threshold)` → 返回掩码列表

#### Scenario: YOLOv8 后处理结果与 Python 版本一致
- **WHEN** 对相同模型输出分别调用 Python 和 C++ 后处理
- **THEN** 检测框坐标差异 < 1 像素，掩码 IoU > 0.95

### Requirement: 构建系统
系统 SHALL 提供 CMakeLists.txt 和 `build_cpp.py` 脚本，支持一键编译 C++ 扩展为 Python 模块。

#### Scenario: 一键构建
- **WHEN** 运行 `python build_cpp.py`
- **THEN** 成功编译生成 `dobot_core` Python 扩展模块，可被 `import dobot_core` 导入

### Requirement: Python 回退机制
系统 SHALL 在 `dobot_core` 模块不可用时自动回退到纯 Python 实现，确保无 C++ 编译环境时程序仍可正常运行。

#### Scenario: C++ 模块不可用时回退
- **WHEN** `import dobot_core` 失败（未编译或平台不支持）
- **THEN** 程序自动使用原有 Python 实现，打印警告信息，功能不受影响

## MODIFIED Requirements

### Requirement: vision_system.py 使用 C++ 核心模块
`vision_system.py` 中的 `nms`、`process_mask`、`postprocess_yolov8` SHALL 优先调用 `dobot_core` 中的 C++ 实现；当 `dobot_core` 不可用时回退到现有 Python 实现。

### Requirement: transform_utils.py 使用 C++ 坐标变换
`transform_utils.py` 中的 `euler2rot`、`pose2matrix` SHALL 优先调用 `dobot_core.transforms` 中的 C++ 实现；当 `dobot_core` 不可用时回退到现有 Python 实现。

## REMOVED Requirements
无移除项。所有现有 Python 实现保留作为回退。
