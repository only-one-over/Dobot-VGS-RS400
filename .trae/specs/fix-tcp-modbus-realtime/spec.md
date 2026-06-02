# TCP-IP 通信逻辑优化 & Modbus 实时状态 Spec

## Why
当前 TCP-IP 通信层存在阻塞死循环风险（send_data/reConnect），反馈数据接收线程无异常保护，Modbus 200ms 周期不够稳定，GUI 缺少实时通信状态显示。

## What Changes
- **BREAKING** 修复 `dobot_api.py` 中 `send_data` 和 `reConnect` 的无限阻塞循环
- 修复 `_feed_loop` 中 `feedBackData()` 异常导致线程崩溃的问题
- 将 Modbus 200ms 周期从 `threading.Timer` 改为独立线程+条件变量，确保严格周期
- GUI Modbus 选项卡新增实时通信状态面板（周期计数、通信速率、客户端数量）
- 寄存器表格刷新周期从 500ms 改为 200ms，与后端同步

## Impact
- Affected code:
  - `dobot_move/dobot_api.py` - `send_data()`, `reConnect()`, `close()`
  - `dobot_move/robot_controller.py` - `_feed_loop()`, `_modbus_check_loop()`, `start_modbus()`, `stop_modbus()`
  - `dobot_move/modbus_server.py` - 添加 `get_cycle_count()`
  - `dobot_move/gui_app.py` - Modbus 选项卡添加实时状态面板

## ADDED Requirements

### Requirement: TCP 通信层阻塞保护
系统 SHALL 在 `send_data` 和 `reConnect` 中添加最大重试次数限制（10次），超限后抛出异常而非无限阻塞。

#### Scenario: 机器人断网时发送命令
- **WHEN** 机器人网络断开
- **THEN** `send_data` 重试 10 次后抛出异常，调用方可捕获处理，不阻塞

### Requirement: 反馈线程异常保护
系统 SHALL 在 `_feed_loop` 中捕获 `feedBackData()` 的所有异常，线程不因数据包异常而终止。

#### Scenario: 数据包不完整
- **WHEN** 30004 端口收到不完整数据包
- **THEN** `_feed_loop` 记录警告并继续轮询，线程不崩溃

### Requirement: Modbus 200ms 严格周期
系统 SHALL 使用独立线程+事件等待实现 Modbus 200ms 周期，确保误差 < 10ms。

#### Scenario: Modbus 周期测量
- **WHEN** Modbus 服务启动
- **THEN** 每次 check+update 间隔稳定在 200ms±10ms，周期计数器递增

### Requirement: Modbus 实时状态显示
GUI SHALL 在 Modbus 选项卡顶部显示实时通信状态：
- 周期计数（已完成多少轮）
- 上次更新耗时（ms）
- 当前状态（运行中/已停止/错误）
- Modbus 服务器 IP:端口

#### Scenario: 查看 Modbus 运行状态
- **WHEN** 用户打开 Modbus 选项卡
- **THEN** 可看到周期计数实时递增，每轮耗时时长，连接状态

## MODIFIED Requirements

### Requirement: Modbus 表格刷新
GUI 的 Modbus 寄存器表格 SHALL 以 200ms 间隔刷新（原 500ms），与后端周期同步。