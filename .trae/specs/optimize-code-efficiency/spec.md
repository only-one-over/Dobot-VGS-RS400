# 代码效率优化 Spec

## Why
当前代码库存在大量重复逻辑、冗余代码、低效的数据结构和运行时性能问题，导致维护困难、运行效率低下。通过系统性地优化代码逻辑和效率，可以显著提升程序的可维护性和运行性能。

## What Changes
- 消除 `gui_app.py` 中重复的默认抓取流程定义和重复的导入语句
- 合并 `gui_app.py` 中三个高度相似的监控线程类（GripperThread、BatteryThread、TorqueThread）为一个泛型监控线程
- 提取 `robot_controller.py` 中重复的错误码处理逻辑为共享方法
- 将 `vision_system.py` 中重复定义的 `euler2rot` 和 `pose2matrix` 函数提升为类方法或模块级函数
- 为 `config_manager.py` 添加配置缓存机制，避免每次读写都进行文件 I/O
- 优化 `gui_app.py` 中 `view_current_grasp_flow` 的 UI 刷新逻辑，避免不必要的全量重建
- 修复 `dobot_api.py` 中 `recv(1024)` 可能截断响应的问题
- 清除 `vision_system.py` 中的无效代码（`Z_mm = Z_mm`）
- 统一 `test_gui.py` 的 PyQt 版本与主程序一致（PyQt6）
- 将方法内部的延迟导入提升为模块级导入

## Impact
- Affected specs: 所有模块的导入和初始化逻辑
- Affected code:
  - `dobot_move/gui_app.py` — 主要重构目标
  - `dobot_move/robot_controller.py` — 错误码处理重构
  - `dobot_move/vision_system.py` — 工具函数去重
  - `dobot_move/config_manager.py` — 添加缓存
  - `dobot_move/dobot_api.py` — 修复响应接收
  - `test_gui.py` — PyQt 版本修正

## ADDED Requirements

### Requirement: 泛型监控线程
系统 SHALL 提供一个泛型 `MonitorThread` 类，替代现有的 `GripperThread`、`BatteryThread` 和 `TorqueThread` 三个高度相似的线程类。

#### Scenario: 使用泛型监控线程替代重复线程类
- **WHEN** 需要创建新的设备监控线程
- **THEN** 通过传入数据读取函数和信号对象即可创建，无需编写新的线程子类

### Requirement: 配置缓存机制
系统 SHALL 在 `config_manager.py` 中实现配置缓存，避免每次调用 getter/setter 都重新读取文件。

#### Scenario: 连续读取配置不触发重复文件 I/O
- **WHEN** 在短时间内多次调用 `get_photo_position()` 或 `get_target_offset()`
- **THEN** 仅第一次触发文件读取，后续从内存缓存返回数据

#### Scenario: 配置更新时自动刷新缓存
- **WHEN** 调用 `set_photo_position()` 或 `set_target_offset()` 修改配置
- **THEN** 缓存自动更新，下次读取返回最新值

### Requirement: 错误码处理统一方法
系统 SHALL 在 `DobotController` 中提供统一的错误码解析和描述方法，替代 `enable_robot` 和 `disable_robot` 中重复的错误码处理代码。

#### Scenario: 错误码转换为可读描述
- **WHEN** 机器人返回非零响应码
- **THEN** 通过统一方法将响应码转换为对应的中文错误描述

### Requirement: API 响应完整接收
系统 SHALL 在 `DobotApiDashboard.send_command` 中确保完整接收机器人响应，避免 `recv(1024)` 截断长响应。

#### Scenario: 接收长响应不被截断
- **WHEN** 机器人返回超过 1024 字节的响应
- **THEN** 系统循环接收直到获取完整响应

### Requirement: UI 列表增量更新
系统 SHALL 优化 `view_current_grasp_flow` 的流程显示逻辑，仅更新变化的步骤标签，而非每次全量重建。

#### Scenario: 选中步骤时仅更新样式
- **WHEN** 用户点击某个步骤
- **THEN** 仅更新被点击步骤和之前选中步骤的样式，不重建整个列表

## MODIFIED Requirements

### Requirement: 模块级导入
所有模块 SHALL 将必要的导入语句放在文件顶部，而非在方法内部延迟导入。`gui_app.py` 中的 `json` 和 `os` 导入、`robot_controller.py` 中的 `config_manager` 导入、`vision_system.py` 中的工具函数定义 SHALL 统一提升到模块级或类级。

### Requirement: 默认抓取流程单一定义
`gui_app.py` 中的默认抓取流程模块列表 SHALL 只定义一次，在加载失败和文件不存在两种情况下复用同一份数据，消除约 40 行重复代码。

### Requirement: 视觉系统工具函数去重
`vision_system.py` 中的 `euler2rot` 和 `pose2matrix` 函数 SHALL 定义为类方法或模块级函数，消除 `__init__` 和 `convert_to_base_coords` 中的重复定义。

## REMOVED Requirements

### Requirement: 无效赋值代码
**Reason**: `vision_system.py` 第 214 行 `Z_mm = Z_mm` 是无意义的自我赋值，应删除。
**Migration**: 无需迁移，直接删除该行。
