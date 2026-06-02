# 严格按TCP文档修复机器人通信和力控显示 Spec

## Why
当前TCP通信存在根本性缺陷：连接后未消费欢迎消息导致所有命令超时；未调用RequestControl()切换TCP模式；力控数据字节偏移错误；GUI力控标签从未更新。

## What Changes
- 修复`DobotApiDashboard.connect()`：连接后必须先读取并消费机器人发送的欢迎消息
- 修复`DobotApiDashboard.send_command()`：增加超时时间，正确处理响应格式
- 修复`robot_controller.py`：连接后先调用RequestControl()切换TCP模式
- 修复`torque_monitor.py`：根据TCP文档修正力控数据的字节偏移
- 修复`gui_app.py`：力控选项卡中的关节力矩标签需要正确更新
- **BREAKING**: EnableRobot()参数格式修正（无参数时不应该发送0值）

## Impact
- 受影响的功能：机器人连接、使能、力控数据显示
- 受影响的代码：
  - `dobot_move/dobot_api.py` - TCP通信核心
  - `dobot_move/robot_controller.py` - 机器人控制流程
  - `dobot_move/torque_monitor.py` - 力控数据读取
  - `dobot_move/gui_app.py` - GUI力控显示

## ADDED Requirements

### Requirement: 连接后消费欢迎消息
根据TCP文档，连接到29999端口后机器人会发送欢迎消息，必须先消费此消息才能发送命令

#### Scenario: 正确的连接流程
- **WHEN** 连接到Dashboard端口29999
- **THEN** 系统必须先读取并消费欢迎消息，然后再发送任何命令

### Requirement: RequestControl切换TCP模式
根据TCP文档，只有在TCP模式下才可执行其他TCP指令

#### Scenario: 切换TCP模式
- **WHEN** 连接到机器人后
- **THEN** 必须先调用RequestControl()切换到TCP模式

### Requirement: 力控数据字节偏移修正
根据TCP文档，ActualTCPForce从字节576开始，每个值8字节

#### Scenario: 正确的力控数据读取
- **WHEN** 从30004端口读取实时反馈数据
- **THEN** Fx=bytes[576:584], Fy=bytes[584:592], Fz=bytes[592:600]

### Requirement: GUI力控标签更新
力控选项卡中的关节力矩标签需要正确更新

#### Scenario: 力控数据更新
- **WHEN** 接收到力矩数据
- **THEN** GUI中的关节力矩标签和力控选项卡都应正确显示数据

## MODIFIED Requirements

### Requirement: send_command超时处理
PowerOn需要约10秒完成，超时时间应设为15秒

### Requirement: EnableRobot参数格式
根据文档，EnableRobot()不携带参数时不应发送0值参数
