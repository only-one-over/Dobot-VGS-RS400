# Tasks

- [x] Task 1: 修复 `wait_reply()` — 仅对连接中断类异常执行重连，`socket.timeout` 直接返回空字符串
  - 修改 `dobot_api.py` L161-L179 的 `wait_reply` 方法
  - 区分 `socket.timeout`（不重连）与 `ConnectionResetError`/`BrokenPipeError`/OSError 10054/10053（重连）
  - 发生 `socket.timeout` 时返回 `""`，不清空旧 socket

- [x] Task 2: 修复 `reConnect()` — 创建新 socket 前关闭旧 socket
  - 修改 `dobot_api.py` L204-L212 的 `reConnect` 方法
  - 在 `for` 循环之前，先尝试关闭 `self.socket_dobot`（如果非 0）
  - 异常时忽略关闭错误

- [x] Task 3: 增加 `sendRecvMsg()` 整体超时保护
  - 修改 `dobot_api.py` L192-L199，添加发送-接收整体超时（默认 5 秒）
  - 超时后抛出 `TimeoutError`，防止 `__globalLock` 被长时间持有

# Task Dependencies
- Task 2 与 Task 1 无顺序依赖，可并行执行
- Task 3 依赖 Task 1（wait_reply 修复后才有意义）
