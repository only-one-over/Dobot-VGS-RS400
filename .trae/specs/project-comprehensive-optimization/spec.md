# 项目综合优化 Spec

## Why
项目当前存在全局 print 调试泛滥（290处）、重复导入（`import re` 在 robot_controller.py 内部重复3次、`import time` 在 connect 方法内重复）、dobot_api.py 的 `wait_reply` 使用 `recv(1024)` 可能截断响应、socket 超时管理混乱（多处 settimeout/settimeout(None) 配对但缺少异常安全保证）、以及 `gui_app.py` 超过3200行导致维护困难等问题。这些系统性问题影响可维护性、运行稳定性和调试效率。

## What Changes
- 引入 `logging` 模块替代全部 `print()` 调试语句，支持日志级别控制
- 清除方法内部的重复 `import` 语句（`re`、`time`），提升到模块级
- 修复 `dobot_api.py` 的 `wait_reply` 方法，循环接收确保完整响应
- 统一 socket 超时管理，使用上下文管理器模式确保超时恢复
- 将 `gui_app.py` 的 `DobotMainWindow` 类拆分为多个混入类（Mixin），按功能域组织

## Impact
- Affected specs: `optimize-code-efficiency`（已完成，本次为后续优化）
- Affected code:
  - `dobot_move/gui_app.py` — logging 替换 + Mixin 拆分
  - `dobot_move/robot_controller.py` — logging 替换 + 重复导入清理
  - `dobot_move/vision_system.py` — logging 替换
  - `dobot_move/dobot_api.py` — wait_reply 修复 + 超时管理
  - `dobot_move/modbus_server.py` — logging 替换
  - `dobot_move/modbus_client.py` — logging 替换
  - `dobot_move/force_arc_controller.py` — logging 替换
  - `dobot_move/force_feedback_monitor.py` — logging 替换
  - `dobot_move/config_manager.py` — logging 替换
  - `dobot_move/workers.py` — logging 替换
  - `dobot_move/battery_monitor.py` — logging 替换
  - `dobot_move/gripper_controller.py` — logging 替换
  - `dobot_move/realtime_feedback_dialog.py` — logging 替换
  - `dobot_move/visual_servo_controller.py` — logging 替换
  - `dobot_move/depth_processor.py` — logging 替换

## ADDED Requirements

### Requirement: 结构化日志系统
系统 SHALL 使用 Python 标准 `logging` 模块替代所有 `print()` 调试语句，每个模块使用 `logger = logging.getLogger(__name__)` 创建独立日志器，支持通过日志级别（DEBUG/INFO/WARNING/ERROR）控制输出。

#### Scenario: 生产环境关闭调试日志
- **GIVEN** 程序以 INFO 级别运行
- **WHEN** 视觉系统执行目标检测
- **THEN** 检测过程中的详细中间数据（如每个像素的深度值）不输出到控制台，仅输出 INFO 级别以上的日志

#### Scenario: 开发环境启用调试日志
- **GIVEN** 程序以 DEBUG 级别运行
- **WHEN** 视觉系统执行目标检测
- **THEN** 所有中间数据和处理步骤均输出到控制台

### Requirement: 消除方法内部重复导入
`robot_controller.py` 中方法内部的 `import re`（L141、L189、L217）和 `import time`（L240）SHALL 提升到模块级导入，消除运行时重复导入开销。

#### Scenario: 模块级导入覆盖所有内部使用
- **GIVEN** `robot_controller.py` 已在模块顶部导入 `re` 和 `time`
- **WHEN** 调用 `validate_ip`、`_validate_robot_mode`、`_validate_get_angle`、`connect` 等方法
- **THEN** 这些方法内部不再有 `import re` 或 `import time` 语句

### Requirement: API 响应完整接收
`dobot_api.py` 的 `wait_reply` 方法 SHALL 循环接收数据直到获取完整响应（以分号或换行符为结束标志），而非单次 `recv(1024)` 可能截断长响应。

#### Scenario: 接收超过 1024 字节的响应
- **GIVEN** 机器人返回一个超过 1024 字节的响应
- **WHEN** `wait_reply` 被调用
- **THEN** 方法循环接收直到获取完整响应，不截断数据

### Requirement: Socket 超时上下文管理
`robot_controller.py` 中多处 `settimeout/settimeout(None)` 配对 SHALL 使用上下文管理器模式，确保即使发生异常也能恢复原始超时设置。

#### Scenario: 异常时超时设置自动恢复
- **GIVEN** 当前 socket 超时为 None（阻塞模式）
- **WHEN** 调用 `enable_robot` 设置2秒超时后发生异常
- **THEN** socket 超时自动恢复为 None（阻塞模式），不会遗留2秒超时

### Requirement: GUI 类按功能域拆分为 Mixin
`gui_app.py` 中的 `DobotMainWindow` 类（3200+行）SHALL 拆分为多个 Mixin 类，按功能域组织：`RobotControlMixin`（机器人控制）、`VisionMixin`（视觉相关）、`ModbusMixin`（Modbus通信）、`PointManagementMixin`（点位管理）、`ForceArcMixin`（力控圆弧）、`GraspFlowMixin`（抓取流程）、`JogMixin`（点动控制），最终 `DobotMainWindow` 通过多继承组合。

#### Scenario: 修改视觉相关功能不影响其他模块
- **GIVEN** `DobotMainWindow` 已拆分为 Mixin
- **WHEN** 开发者需要修改相机连接逻辑
- **THEN** 只需修改 `VisionMixin`，不影响 `RobotControlMixin` 等其他 Mixin 的代码

## MODIFIED Requirements

### Requirement: 日志输出格式统一
所有模块的日志 SHALL 使用统一格式：`[模块名] 级别: 消息`，例如 `[robot_controller] INFO: 机器人连接成功`。现有的 emoji 前缀（✅、❌、⚠️）在 INFO/WARNING/ERROR 级别日志中保留。
