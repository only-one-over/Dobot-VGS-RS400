# 双相机同时连接与流程选择 Spec

## Why
当前实现只能选择连接一台相机（D435i 或 D405），但实际使用场景需要同时连接两部相机：D435i 做粗识别（目标中心点），D405 做精识别（铁钩两端端点）。流程中应能自由选择使用哪台相机，而非只能用一台。

## What Changes
- 修改 GUI 相机连接逻辑：从"选择一台连接"改为"同时连接两部相机"，各自独立初始化
- 修改 `gui_app.py`：`self.vision` 从单个 VisionSystem 改为 `self.vision_d435i` + `self.vision_d405` 两个独立实例
- 修改 FlowThread：接收两个 VisionSystem 实例，流程中根据 camera_type 参数选择使用哪个
- 修改相机连接/断开 UI：两个独立的连接/断开按钮，分别控制 D435i 和 D405
- 修改 VisionSystem：通过 RealSense 序列号指定打开哪台相机，避免同时启动时设备冲突
- **BREAKING**: `self.vision` 属性拆分为 `self.vision_d435i` 和 `self.vision_d405`

## Impact
- Affected specs: add-dual-camera-handeye-calib（上一轮实现，需修正逻辑）
- Affected code: `vision_system.py`, `gui_app.py`
- Affected behavior: 相机连接从单选变为同时连接，流程中自由切换

## ADDED Requirements

### Requirement: 双相机同时连接
系统 SHALL 支持同时连接 D435i 和 D405 两台相机，各自独立初始化为独立的 VisionSystem 实例。

#### Scenario: 同时连接两部相机
- **WHEN** 用户点击"连接相机"按钮
- **THEN** 系统尝试同时初始化 D435i 和 D405 两个 VisionSystem 实例，各自使用对应的标定矩阵和深度范围
- **THEN** 任一相机连接失败不影响另一台，失败的那台标记为不可用

#### Scenario: 单独断开某台相机
- **WHEN** 用户点击某台相机的断开按钮
- **THEN** 仅断开该台相机，另一台保持连接

### Requirement: 通过序列号指定相机设备
VisionSystem SHALL 接受 `serial_number` 参数，通过 RealSense 设备序列号指定打开哪台相机，避免两台相机同时启动时的设备冲突。

#### Scenario: 指定序列号启动
- **WHEN** VisionSystem 初始化时传入序列号
- **THEN** 仅打开该序列号对应的相机设备

#### Scenario: 未指定序列号
- **WHEN** VisionSystem 初始化时未传入序列号
- **THEN** 打开第一个可用的 RealSense 设备（向后兼容）

### Requirement: 流程中自由选择相机
抓取流程的相机模块 SHALL 支持选择 D435i 或 D405，执行时使用对应的 VisionSystem 实例。

#### Scenario: D435i 粗识别
- **WHEN** 流程中相机模块选择 D435i
- **THEN** 使用 D435i VisionSystem 实例进行识别，返回目标中心点坐标

#### Scenario: D405 精识别
- **WHEN** 流程中相机模块选择 D405
- **THEN** 使用 D405 VisionSystem 实例进行识别，返回铁钩两端端点坐标和抓取位置

#### Scenario: 选中的相机未连接
- **WHEN** 流程中指定使用 D405 但 D405 未连接
- **THEN** 报错提示该相机未连接，流程终止

### Requirement: 相机连接状态显示
GUI SHALL 分别显示 D435i 和 D405 的连接状态。

#### Scenario: 查看连接状态
- **WHEN** 用户查看相机区域
- **THEN** 分别显示 D435i 和 D405 的连接状态（已连接/未连接/连接失败）

## MODIFIED Requirements

### Requirement: GUI 相机连接区域
相机连接区域 SHALL 从"下拉选择+连接/断开"改为"D435i 连接/断开 + D405 连接/断开"两组独立按钮，各自显示连接状态。

### Requirement: VisionSystem 初始化
VisionSystem 的 `__init__` 方法 SHALL 接受 `serial_number` 参数（可选），用于指定打开哪台 RealSense 设备：
```python
def __init__(self, camera_type="D435i", serial_number=None):
```

### Requirement: FlowThread 相机选择
FlowThread SHALL 接收 `vision_d435i` 和 `vision_d405` 两个参数（而非单个 `vision`），根据模块参数中的 `camera_type` 选择使用哪个实例。

## REMOVED Requirements

### Requirement: 相机类型下拉选择框
**Reason**: 不再需要"选择一台连接"，改为同时连接两部相机
**Migration**: 移除 `camera_type_combo` 下拉框，替换为两组独立的连接/断开按钮
