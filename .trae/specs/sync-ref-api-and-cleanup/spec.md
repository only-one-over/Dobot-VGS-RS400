# 同步参考API并精简项目 Spec

## Why
当前项目的 `dobot_api.py` 是简化版本（109行），缺少 `DobotApiFeedBack` 类。`RealTimeFeedback` 和 `TorqueMonitor` 各自独立连接同一30004端口，存在冲突风险。需要基于 `TCP-IP-Python-V4-main` 参考代码统一API实现，并删除多余文件精简项目。

## What Changes
- 用参考版本的 `dobot_api.py` 替换当前简化版本，获得完整的 `DobotApiDashboard` + `DobotApiFeedBack` 类
- 更新 `robot_controller.py` 适配新API方法签名（MovJ/MovL/MovC增加coordinateMode参数）
- 将 `RealTimeFeedback` 和 `TorqueMonitor` 的功能整合到 `robot_controller.py`，统一通过 `DobotApiFeedBack` 获取30004端口数据
- 更新 `gui_app.py` 移除对已删除模块的引用
- 更新 `realtime_feedback_dialog.py` 使用 `DobotApiFeedBack`
- **BREAKING**: `DobotApiDashboard` 的方法签名变更（MovJ/MovL/MovC/GetPose需传coordinateMode）

## Impact
- Affected specs: 所有TCP通信相关功能
- Affected code:
  - `dobot_move/dobot_api.py` - 替换为参考版本
  - `dobot_move/robot_controller.py` - 方法调用适配 + 整合FeedBack
  - `dobot_move/gui_app.py` - 移除已删除模块引用
  - `dobot_move/realtime_feedback_dialog.py` - 适配新API

## ADDED Requirements

### Requirement: 完整DobotApi模块
系统SHALL使用参考版本 `dobot_api.py`，包含 `DobotApi`（基类）、`DobotApiDashboard`（29999端口控制指令）和 `DobotApiFeedBack`（30004端口实时反馈）三个类。

#### Scenario: Dashboard控制指令
- **WHEN** 调用 `DobotApiDashboard` 的运动指令
- **THEN** 使用 `sendRecvMsg()` 同步发送接收，支持MovJ/MovL/MovC/RelJointMovJ等指令

#### Scenario: 实时反馈数据获取
- **WHEN** 调用 `DobotApiFeedBack.feedBackData()`
- **THEN** 返回numpy结构化数组，包含机器人模式、关节位置/速度、TCP力觉等完整状态

### Requirement: 统一30004端口数据源
系统SHALL仅通过 `DobotApiFeedBack` 获取30004端口数据，不再有多个模块同时连接该端口。

#### Scenario: 实时反馈和力矩数据统一获取
- **WHEN** robot_controller需要关节状态、TCP力觉数据
- **THEN** 统一通过 DobotApiFeedBack 获取，避免端口冲突

## MODIFIED Requirements

### Requirement: robot_controller适配新API
`robot_controller.py` SHALL适配参考版本 `DobotApiDashboard` 的方法签名：
- `MovJ(x, y, z, rx, ry, rz, 0)` 增加coordinateMode=0
- `MovL(x, y, z, rx, ry, rz, 0)` 增加coordinateMode=0
- `MovC(target... middle... 0)` 增加coordinateMode=0
- `GetPose()` 签名兼容

### Requirement: gui_app移除已删除模块引用
`gui_app.py` SHALL移除对 `RealTimeFeedback` 和 `TorqueMonitor` 的直接导入和初始化，改为通过 `robot_controller` 统一获取数据。

### Requirement: realtime_feedback_dialog使用新API
`realtime_feedback_dialog.py` SHALL使用 `DobotApiFeedBack` 替代 `RealTimeFeedback` 获取实时数据。

## REMOVED Requirements

### Requirement: 独立RealTimeFeedback模块
**Reason**: 与 DobotApiFeedBack 功能重复，且占用同一30004端口
**Migration**: 功能整合到 robot_controller.py 通过 DobotApiFeedBack 实现

### Requirement: 独立TorqueMonitor模块
**Reason**: 与 DobotApiFeedBack 功能重复，且占用同一30004端口
**Migration**: 力矩数据从 DobotApiFeedBack 的 ActualTCPForce 字段获取

### Requirement: build_cpp.py C++编译脚本
**Reason**: 引用的 cpp_core 目录不存在，无法使用
**Migration**: 直接删除

### Requirement: build_app.py PyInstaller打包脚本
**Reason**: 非核心业务逻辑，属于部署工具
**Migration**: 直接删除

### Requirement: dist/ 打包产物目录
**Reason**: 可重新生成，不需纳入源码管理
**Migration**: 直接删除

### Requirement: tcp_test/ 测试目录
**Reason**: 测试代码，非核心业务逻辑
**Migration**: 直接删除
