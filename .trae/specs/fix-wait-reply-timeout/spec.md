# 修复 GetPose 偶尔获取位置失败 - Spec

## Why
机器人在连接且已使能状态下，点击"获取位置"按钮**偶尔**返回"获取位置失败"。根因是 `dobot_api.py` 中 `wait_reply()` 方法在 `socket.timeout` 时错误地执行重连并返回空字符串，导致已发送命令的响应被丢弃。同时 `reConnect()` 未关闭旧 socket 造成资源泄漏。

## What Changes
- **修复 `wait_reply()` timeout 处理**：发生 `socket.timeout` 时不再重连，直接返回空字符串让上层处理
- **修复 `reConnect()` 资源泄漏**：创建新 socket 前关闭旧 socket
- **增强 `sendRecvMsg()` 超时保护**：添加整体超时机制，防止锁被长时间持有
- 不影响任何对外接口签名

## Impact
- Affected specs: 无
- Affected code:
  - `dobot_move/dobot_api.py` L161-L179 (`wait_reply`)、L204-L212 (`reConnect`)
  - `dobot_move/robot_controller.py` L549-L596 (`get_current_pose`) — 检查是否需要调整

## MODIFIED Requirements
### Requirement: wait_reply 超时处理
`wait_reply()` SHALL 仅在下述异常时重连：
- `ConnectionResetError` / `ConnectionAbortedError` — 连接被对方重置
- `BrokenPipeError` — 管道断开
- `OSError` 且 errno 为 10054/10053（Windows 连接重置/中止）

`wait_reply()` SHALL NOT 在以下情况重连：
- `socket.timeout` — 仅数据未及时到达，连接本身有效，返回空字符串即可

#### Scenario: GetPose 超时
- **GIVEN** 机器人已连接且 socket 超时设为 3 秒
- **WHEN** 调用 `GetPose()` 后 `recv(1024)` 在 3 秒内未收到数据
- **THEN** `wait_reply` 返回空字符串 `""`，不创建新 socket，不重连
- **AND** `get_current_pose` 正常进入重试逻辑

### Requirement: reConnect 关闭旧 socket
`reConnect()` SHALL 在创建新 socket 前尝试关闭已存在的 `self.socket_dobot`（如果非 0 且有效）。

#### Scenario: 连接断开后重连
- **GIVEN** socket 因网络中断而断开
- **WHEN** `wait_reply` 捕获到连接断开异常并调用 `reConnect`
- **THEN** 旧 socket 被正确关闭，新 socket 创建并连接成功
