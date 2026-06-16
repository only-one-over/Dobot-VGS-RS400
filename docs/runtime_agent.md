# 后台 Runtime 与开机自启动

`runtime_agent.py` 是生产现场使用的无界面后台入口，和 `run.py` 位于项目根目录。
它不会打开 PyQt 界面，会自动启动 Modbus TCP 从站、持续连接机器人，并按主站写入 `40001` 的命令运行对应程序。

## 手动启动

在项目根目录运行：

```powershell
python runtime_agent.py --startup-delay 20
```

参数说明：

- `--startup-delay 20`：开机后等待网络和机器人稳定 20 秒，再开始连接机器人。
- `--poll-interval 1`：后台 watchdog 周期，默认 1 秒。
- `--health-path runtime_health.json`：健康状态文件路径。
- `--log-dir logs`：运行日志目录。

## 运行状态文件

- `logs/runtime.log`：后台运行日志，自动滚动。
- `runtime_health.json`：当前运行状态，包括机器人连接、反馈状态、Modbus 状态、最后一次主站命令和最后错误。

现场排查时优先看这两个文件：

```powershell
Get-Content .\runtime_health.json
Get-Content .\logs\runtime.log -Tail 100
```

## Modbus 协议

- `40001=0`：立即停止当前机器人/流程运动，并保持 `40001=0`。
- `40001=1`：移动到 `initial_point`；运动中写 `4`；完成后保持 `2`。
- `40001=3`：运行保存的运动流程；运动中写 `4`；完成后保持 `5`。
- 机器人未连接、报警、急停未解除、自动使能失败或反馈断流时，不执行运动，写机器人错误状态。

断线期间收到的运动命令不会排队，避免机器人重连后执行过期动作。

## 安装开机自启动

以管理员身份打开 PowerShell，在项目根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_runtime_task.ps1
```

指定项目路径、Python 路径和启动延迟：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_runtime_task.ps1 `
  -TaskName DobotRuntimeAgent `
  -ProjectRoot D:\桌面\dobot_move_python `
  -PythonExe D:\桌面\dobot_move_python\.venv\Scripts\python.exe `
  -StartupDelaySeconds 20
```

安装脚本会注册 Windows Task Scheduler 任务：

- 任务名：`DobotRuntimeAgent`
- 触发：开机启动
- 工作目录：项目根目录
- 启动命令：`python runtime_agent.py --startup-delay <秒数>`
- 权限：最高权限运行
- 失败恢复：失败后 1 分钟自动重启
- 运行时间：不限制

## 查看、停止和删除开机任务

查看任务：

```powershell
Get-ScheduledTask -TaskName DobotRuntimeAgent
Get-ScheduledTaskInfo -TaskName DobotRuntimeAgent
```

手动启动任务：

```powershell
Start-ScheduledTask -TaskName DobotRuntimeAgent
```

停止任务：

```powershell
Stop-ScheduledTask -TaskName DobotRuntimeAgent
```

删除任务：

```powershell
Unregister-ScheduledTask -TaskName DobotRuntimeAgent -Confirm:$false
```

## 现场确认流程

1. 管理员 PowerShell 执行安装脚本。
2. 重启工控机。
3. 打开任务计划程序，确认 `DobotRuntimeAgent` 为运行中。
4. 确认 `logs/runtime.log` 持续写入。
5. 确认 `runtime_health.json` 中 `modbus.is_running=true`。
6. 机器人上电并网络可达后，确认 `robot.connected=true`。
7. 主站依次写入 `40001=0/1/3` 做联调。

## 注意事项

- 现场生产建议运行 `runtime_agent.py`，不要依赖打开 PyQt UI 来维持生产通信。
- PyQt UI 可以手动打开用于配置和查看，但后台 runtime 才是 7x24 运行入口。
- 如果端口 `502` 被占用，Modbus 从站无法启动，需要先关闭占用端口的进程。
