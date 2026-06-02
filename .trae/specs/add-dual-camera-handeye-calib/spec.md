# 双相机支持与手眼标定模块 Spec

## Why
当前系统仅支持单台 D435i 相机，手眼标定矩阵硬编码在代码中无法修改。需要增加 D405 相机支持，让用户可以在 GUI 中查看和修改手眼标定矩阵，并且 D405 识别铁钩两端端点而非中心点。

## What Changes
- 新增手眼标定管理模块 `hand_eye_calib.py`，支持多相机标定矩阵的读取、修改和持久化存储
- 修改 `config.json` 结构，支持多相机标定数据（D435i 和 D405 各自独立的标定矩阵）
- 修改 `config_manager.py`，增加多相机标定配置的读写接口
- 修改 `vision_system.py`，VisionSystem 接受相机类型参数，D435i 识别目标中心点，D405 识别铁钩两端端点
- 修改 `gui_app.py`，新增"手眼标定"选项卡，相机连接时允许选择相机类型，抓取流程中相机模块增加相机选择参数

## Impact
- Affected specs: 视觉系统、配置管理、GUI 界面
- Affected code: `vision_system.py`, `config_manager.py`, `gui_app.py`, `config.json`
- **BREAKING**: `config.json` 中 `calibration` 字段结构从单相机变为多相机

## ADDED Requirements

### Requirement: 手眼标定管理模块
系统 SHALL 提供独立的手眼标定管理模块 `hand_eye_calib.py`，支持多相机标定矩阵的读取、修改和持久化存储。

#### Scenario: 读取标定矩阵
- **WHEN** 用户通过模块读取指定相机的标定矩阵
- **THEN** 返回该相机的 4x4 齐次变换矩阵

#### Scenario: 修改标定矩阵
- **WHEN** 用户修改指定相机的标定矩阵并保存
- **THEN** 标定数据永久写入 `config.json`，下次启动时自动加载

#### Scenario: 列出所有相机标定
- **WHEN** 用户查询所有已标定的相机
- **THEN** 返回所有相机名称及其标定矩阵

### Requirement: GUI 手眼标定选项卡
系统 SHALL 在 GUI 中新增"手眼标定"选项卡，允许用户查看和修改每个相机的手眼标定矩阵。

#### Scenario: 查看标定矩阵
- **WHEN** 用户切换到手眼标定选项卡
- **THEN** 显示所有相机的标定矩阵（4x4 表格形式），每个矩阵元素可编辑

#### Scenario: 修改并保存标定矩阵
- **WHEN** 用户修改矩阵中的某个值并点击保存
- **THEN** 新值永久写入配置文件，并更新运行时内存中的标定矩阵

#### Scenario: 重置标定矩阵
- **WHEN** 用户点击重置按钮
- **THEN** 该相机的标定矩阵恢复为默认值并保存

### Requirement: 相机类型选择
系统 SHALL 允许用户在连接相机时选择相机类型（D435i 或 D405），不同相机使用各自独立的标定矩阵。

#### Scenario: 选择 D435i 相机
- **WHEN** 用户选择 D435i 相机并连接
- **THEN** 使用 D435i 的标定矩阵，识别结果返回目标中心点坐标

#### Scenario: 选择 D405 相机
- **WHEN** 用户选择 D405 相机并连接
- **THEN** 使用 D405 的标定矩阵，识别结果返回铁钩两端端点坐标

### Requirement: D405 端点识别模式
系统 SHALL 在使用 D405 相机时，识别铁钩的两端端点（柄端和钩尖端），而非仅识别中心点。

#### Scenario: D405 识别铁钩两端
- **WHEN** 使用 D405 相机进行识别
- **THEN** 返回结果包含 `handle_end`（柄端）和 `hook_tip`（钩尖端）两个 3D 坐标，以及基于两端点计算的抓取位置

#### Scenario: D435i 识别目标中心
- **WHEN** 使用 D435i 相机进行识别
- **THEN** 返回结果与现有行为一致，仅包含目标中心点坐标

### Requirement: 抓取流程相机选择参数
系统 SHALL 在抓取流程的相机模块中增加"相机选择"参数，允许用户指定使用哪台相机进行识别。

#### Scenario: 流程中使用指定相机
- **WHEN** 用户在抓取流程的相机模块中选择 D405 相机
- **THEN** 执行该模块时使用 D405 相机进行识别，返回端点坐标

## MODIFIED Requirements

### Requirement: 配置文件结构
`config.json` 中 `calibration` 字段 SHALL 从单相机结构改为多相机结构：

**旧结构**:
```json
{
  "calibration": {
    "tool_base_calib_pose": [...],
    "cam_base_calib_pose": [...]
  }
}
```

**新结构**:
```json
{
  "calibration": {
    "D435i": {
      "tool_base_calib_pose": [...],
      "cam_base_calib_pose": [...]
    },
    "D405": {
      "tool_base_calib_pose": [...],
      "cam_base_calib_pose": [...]
    }
  }
}
```

### Requirement: VisionSystem 初始化
VisionSystem 的 `__init__` 方法 SHALL 接受 `camera_type` 参数（默认 `"D435i"`），根据相机类型加载对应的标定矩阵和相机配置。

### Requirement: VisionSystem 位置计算
VisionSystem 的 `calculate_object_position` 方法 SHALL 根据相机类型返回不同格式的结果：
- D435i: 返回 `{'camera_coords': [X, Y, Z]}`（与现有一致）
- D405: 返回 `{'camera_coords': [X, Y, Z], 'handle_end_coords': [X, Y, Z], 'hook_tip_coords': [X, Y, Z]}`

## REMOVED Requirements
无移除的需求。
