# 连接超时修复、IP可编辑与碰撞等级设置 Spec

## Why
当前 `connect()` 仅创建 `DobotApiDashboard` 对象就返回 True，即使网络不通也显示"连接成功"。用户需要可编辑IP地址，以及设置碰撞检测等级（力限制）。

## What Changes
- 修复 `connect()` 添加 3 秒超时验证，连接后发送 `RobotMode()` 指令验证 TCP 通信是否真正成功
- GUI 中新增 IP 地址编辑框，连接时使用用户输入的 IP
- GUI 中新增碰撞检测等级设置（SetCollisionLevel，0-5），参考 TCP-IP API 文档
- 关于"力量限制"：参考 API 中有 `SetCollisionLevel`（碰撞检测等级 0-5）和 `SetFCCollision(force, torque)`（力控碰撞阈值），用户说的"力量限制"最对应 `SetCollisionLevel`

## Impact
- Affected specs: 机器人连接、IP配置、碰撞检测
- Affected code:
  - `dobot_move/robot_controller.py` - connect 添加超时验证 + set_collision_level 方法
  - `dobot_move/gui_app.py` - IP 编辑框 + 碰撞等级设置

## ADDED Requirements

### Requirement: 连接 3 秒超时验证
`connect()` SHALL 在创建 socket 连接后，发送 `RobotMode()` 验证通信是否成功，3 秒内无响应则返回 False。

#### Scenario: 网络不通
- **WHEN** 目标 IP 不可达
- **THEN** 3 秒超时后返回 False，GUI 显示"连接机器人失败"

#### Scenario: 网络正常
- **WHEN** 目标 IP 可达且机器人在线
- **THEN** RobotMode() 返回有效响应，连接成功

### Requirement: IP 地址可编辑
GUI SHALL 提供 IP 地址编辑框，默认值 "192.168.5.1"，连接时使用编辑框中的 IP。

#### Scenario: 修改 IP 后连接
- **WHEN** 用户修改 IP 后点击"连接机器人"
- **THEN** 使用新 IP 连接机器人

### Requirement: 碰撞检测等级设置
GUI SHALL 提供碰撞检测等级设置（0-5），调用 `SetCollisionLevel(level)`。

#### Scenario: 设置碰撞等级
- **WHEN** 用户选择碰撞等级并点击设置
- **THEN** 调用 SetCollisionLevel(level)，0=关闭，1-5灵敏度递增

## MODIFIED Requirements

### Requirement: connect 添加真实连接验证
`connect()` SHALL 设置 socket 超时 3 秒，创建连接后发送 RobotMode() 验证，失败则关闭连接返回 False。

## REMOVED Requirements
无
