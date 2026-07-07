# WinSW 双服务部署

生产环境使用两个独立 Windows Service：

- `DobotRuntimeService`：独占机器人、D405、D435i、Modbus 502、流程执行器和 localhost IPC。
- `DobotRuntimeWatchdog`：检查健康文件，卡死时先独立发送 `Stop()`，再通过 SCM 重启 Runtime 服务。

GUI 不注册为服务，由登录用户独立启动。关闭 GUI 不会停止 Runtime。

## 环境要求

- Windows 10/11 x64。
- 项目默认部署到 `C:\DobotRuntime`；使用其他目录时显式传入 `-ProjectRoot`。
- 每台设备重新创建 `.venv` 并安装 `requirements.txt`，不要复制其他设备的虚拟环境。
- 使用管理员 PowerShell 安装服务。
- Runtime 默认使用专用本地账户 `.\DobotRuntimeSvc`，Watchdog 使用 `LocalSystem`。

项目离线携带 WinSW 2.12.0 x64：

```text
dobot_move\windows_service\vendor\WinSW-x64.exe
dobot_move\windows_service\vendor\WinSW-x64.sha256
```

安装脚本会强制校验 SHA256，不匹配时拒绝安装。

## 安装

固定目录部署：

```powershell
cd C:\DobotRuntime
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

powershell -ExecutionPolicy Bypass `
  -File .\scripts\install_windows_services.ps1 `
  -CreateServiceUser
```

当前项目目录部署：

```powershell
powershell -ExecutionPolicy Bypass `
  -File .\scripts\install_windows_services.ps1 `
  -ProjectRoot D:\桌面\dobot_move_python `
  -PythonExe D:\桌面\dobot_move_python\.venv\Scripts\python.exe `
  -CreateServiceUser
```

安装过程会：

1. 检查管理员权限、Python导入和WinSW哈希。
2. 创建或验证 `DobotRuntimeSvc`，通过安全凭据窗口读取密码。
3. 生成 `runtime_ipc.token` 并限制其文件权限。
4. 备份、停止并禁用旧任务计划，但不删除任务定义。
5. 安装并启动 Runtime 和 Watchdog 服务。
6. 检查服务状态、健康文件和带认证的 IPC ping。
7. 验证失败时卸载服务并恢复旧任务原有的启用和运行状态。

安装脚本只在 WinSW 安装期间将凭据写入受限 XML，并立即重新生成无凭据的永久 XML；密码不会写入 Git、配置发布包或日志。

## 状态检查

```powershell
powershell -ExecutionPolicy Bypass `
  -File .\scripts\test_windows_services.ps1 `
  -ProjectRoot C:\DobotRuntime

Get-Service DobotRuntimeService
Get-Service DobotRuntimeWatchdog
Get-Content .\runtime_health.json
Get-Content .\logs\runtime.log -Tail 100
```

Runtime 的 WinSW 停止超时为30秒。收到服务停止后，Runtime依次停止流程、发送机器人 `Stop()`、停止Modbus、关闭相机和机器人连接，然后写入正常停止标记。Watchdog看到该标记后不会重新拉起人工停止的Runtime；Runtime下次启动会清除标记。

## 卸载与回滚

仅卸载服务：

```powershell
powershell -ExecutionPolicy Bypass `
  -File .\scripts\uninstall_windows_services.ps1 `
  -ProjectRoot C:\DobotRuntime
```

卸载服务并恢复旧任务计划：

```powershell
powershell -ExecutionPolicy Bypass `
  -File .\scripts\rollback_windows_services.ps1 `
  -ProjectRoot C:\DobotRuntime `
  -StartLegacyTasks
```

卸载顺序固定为先Watchdog、后Runtime，避免Watchdog在Runtime正常停止期间将其重新启动。

## 安全说明

- IPC只监听 `127.0.0.1:8765`，服务模式还必须提供 `runtime_ipc.token`。
- token不进入日志和 `runtime_publication.json`。
- GUI只能通过IPC调试，不能直接创建机器人、相机或Modbus连接。
- SCM异常重启后仍遵守恢复锁，绝不自动续跑上一次机器人流程。
- 不要同时启用旧Runtime任务计划和Windows Service。

## 现场部署检查清单

安装前：

- 使用 Windows 10/11 x64，确认管理员 PowerShell 可用。
- 每台设备重新创建 `.venv` 并安装 `requirements.txt`，不要复制其他机器的虚拟环境。
- 确认 `dobot_move\windows_service\vendor\WinSW-x64.exe` 存在，并且 SHA256 与 `WinSW-x64.sha256` 一致。
- 确认模型文件、`dobot_move\config.json`、流程文件和标定参数已经放到目标项目目录。
- 确认 502、8765、29999、30004 端口不会被其他进程或旧任务占用。

安装后：

- `Get-Service DobotRuntimeService` 应显示 Runtime 服务存在，正常运行时为 `Running`。
- `Get-Service DobotRuntimeWatchdog` 应显示 Watchdog 服务存在，正常运行时为 `Running`。
- `runtime_health.json` 中应包含 `service_mode=true`、服务名、进程 PID、启动编号、Runtime 状态和设备连接状态。
- GUI 可独立打开和关闭，不应影响 Runtime 服务、Modbus 502、机器人连接或 RealSense 管线。
- 服务停止后 Watchdog 不应把人工停止的 Runtime 自动拉起；异常卡死时才由 Watchdog 执行安全停止和重启。

回滚原则：

- 服务方案验证失败时，先运行 `scripts\rollback_windows_services.ps1`，恢复安装前被禁用的旧任务计划。
- 不要手工删除 WinSW 目录、token 或旧任务定义后再回滚；脚本需要这些信息恢复现场状态。
- 回滚后确认 Windows Service 已停止或卸载，再重新启用旧任务计划，避免两个后台实例同时占用机器人和 Modbus 端口。
