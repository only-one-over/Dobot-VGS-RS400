# PC 双向 Modbus TCP 通信 & 机械臂状态转发 Spec

## Why
程序运行在 PC 上，PC 同时连接机械臂（Dobot TCP-IP）和小车（Modbus TCP）。PC 需要作为 Modbus Slave 让小车读取机械臂状态，同时作为 Modbus Master 读写小车的寄存器。

## What Changes
- **保留** `modbus_server.py`：PC 作为 Slave，小车读写寄存器 50001-50045
- **新增** `modbus_client.py`：PC 作为 Master，主动连接小车 Modbus 服务器，周期读取小车状态寄存器
- 机械臂状态（位置、模式）每 200ms 转发到 Slave 寄存器 50030-50045
- GUI Modbus 选项卡新增小车 Modbus 客户端控制（IP、端口、连接/断开）
- 寄存器表格同时显示 Slave 状态寄存器 + Master 读取的小车寄存器

## Impact
- Affected code:
  - 新增 `dobot_move/modbus_client.py`
  - `dobot_move/gui_app.py` - Modbus 选项卡重构为双面板（服务器+客户端）
  - `dobot_move/robot_controller.py` - 添加 modbus_client，状态转发优化

## ADDED Requirements

### Requirement: PC 作为 Modbus TCP Slave（服务器）
系统 SHALL 运行 Modbus TCP 服务器（已实现），监听端口 502，供小车连接。

| 寄存器 | 方向 | 含义 |
|--------|------|------|
| 50001 | 小车写→PC读 | 命令：1=复位, 2=回安全位, 3=提钩 |
| 50003 | 小车写→PC读 | 提钩使能 |
| 50010-50019 | 小车写→PC读 | 目标位置/速度(F32) |
| 50030 | PC写→小车读 | 状态：1空闲/2运行/3完成/4故障/5急停 |
| 50031 | PC写→小车读 | 故障代码 |
| 50032 | PC写→小车读 | 在位标志 |
| 50040-50045 | PC写→小车读 | 当前X/Y/Z(F32) |

### Requirement: PC 作为 Modbus TCP Master（客户端）
系统 SHALL 可作为 Modbus TCP 客户端连接小车 Modbus 服务器，读取小车状态寄存器：

| 寄存器 | 方向 | 含义 |
|--------|------|------|
| 40001 | PC读←小车写 | 小车状态(1空闲/2运行/3故障) |
| 40002 | PC读←小车写 | 故障代码 |
| 40010-40015 | PC读←小车写 | 小车位置X/Y/Z(F32) |

#### Scenario: 连接小车 Modbus
- **WHEN** 用户输入小车 IP 和端口，点击"连接小车Modbus"
- **THEN** PC 作为 Master 连接小车 Modbus 服务器，周期读取状态寄存器

### Requirement: 机械臂状态实时转发
系统 SHALL 每 200ms 从 Dobot FeedBack 读取机械臂位置和状态，写入 Slave 寄存器 50030-50045。

#### Scenario: 状态转发
- **WHEN** Modbus 服务器运行且机械臂已连接
- **THEN** 50040-50045 实时显示机械臂当前位置，小车读取即获得最新值

### Requirement: GUI 双面板 Modbus 选项卡
GUI SHALL 显示两个 Modbus 控制面板：
- **上半部分**：Modbus 服务器面板（PC=Slave）— 启停、端口、周期计数、寄存器表格
- **下半部分**：Modbus 客户端面板（PC=Master）— 小车 IP/端口、连接/断开、小车状态显示

#### Scenario: 查看 Modbus 通信全貌
- **WHEN** 用户打开 Modbus 选项卡
- **THEN** 可同时看到服务器状态和客户端连接状态