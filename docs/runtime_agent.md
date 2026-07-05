# 后台 Runtime 与开机自启动

`dobot_move/runtime_agent.py` 是生产现场使用的无界面后台模块，通过 `python -m dobot_move.runtime_agent` 启动。
项目根目录的 `runtime_agent.py` 只保留为旧命令兼容入口。
它不会打开 PyQt 界面，会自动启动 Modbus TCP 从站、持续连接机器人，并按主站写入 `40001` 的命令运行对应程序。

## 手动启动

在项目根目录运行：

```powershell
python -m dobot_move.runtime_agent
```

参数说明：

- `--startup-delay`：仅保留旧命令兼容；即使设置该参数，首次设备探测也会立即开始。
- `--poll-interval 1`：后台 watchdog 周期，默认 1 秒。
- `--health-path runtime_health.json`：健康状态文件路径。
- `--state-path runtime_state.json`：崩溃恢复状态文件路径。
- `--lock-path runtime_agent.lock`：后台进程单实例锁路径。
- `--log-dir logs`：运行日志目录。

## 运行状态文件

- `logs/runtime.log`：后台运行日志，自动滚动。
- `logs/runtime_watchdog.log`：独立看门狗日志。
- `runtime_health.json`：每秒更新的健康状态，包括 PID、启动编号、流程模块、设备心跳、线程、内存和磁盘空间。
- `runtime_state.json`：原子保存的诊断状态，只用于判断是否异常退出，不会自动续跑流程。
- `runtime_agent.lock`：后台进程单实例锁。
- `robot_control.lock`：GUI 与后台共享的机器人控制租约。
- `runtime_watchdog_restarts.json`：看门狗最近 10 分钟的重启记录。
- `runtime_watchdog_lockout.json`：重启次数超限后的人工恢复锁。

现场排查时优先查看以下文件：

```powershell
Get-Content .\runtime_health.json
Get-Content .\logs\runtime.log -Tail 100
Get-Content .\logs\runtime_watchdog.log -Tail 100
```

### 健康状态关键字段

| 字段 | 说明 |
|------|------|
| `schema_version` | 健康文件结构版本，当前为 `2` |
| `boot_id` | 本次后台启动的唯一编号 |
| `runtime.state` | `STARTING/READY/RUNNING/WAITING_DELAY/DEGRADED/RECOVERY_REQUIRED/STOPPING` |
| `runtime.recovery_required` | 是否必须先执行 `40001=0` |
| `runtime.startup_errors` | 配置文件或流程文件启动校验错误 |
| `startup_connection.main_flow_id/main_flow_name` | 当前主流程 |
| `startup_connection.deadline_at_monotonic` | 本轮启动连接截止时间 |
| `startup_connection.required_cameras` | 主流程实际引用的相机 |
| `startup_connection.missing_devices` | 当前缺失的机器人或相机 |
| `startup_connection.deadline_elapsed` | 5 秒启动观察窗口是否结束 |
| `startup_connection.fault_latched/fault_code` | 兼容字段，固定为 `false/null` |
| `startup_connection.retrying` | 是否有机器人或相机连接任务正在后台执行 |
| `robot.feedback_age_s` | 距离最近反馈包的秒数 |
| `robot.feedback_thread_alive` | 30004 反馈线程是否存活 |
| `modbus.thread_alive` | Modbus 服务线程是否存活 |
| `flow.module_index/module_name` | 当前执行模块 |
| `flow.orphaned_flow` | 超时流程线程是否未能退出 |
| `process.thread_count/rss_mb` | 线程数和常驻内存 |
| `process.disk_free_mb` | 健康文件所在磁盘剩余空间 |

## Modbus 协议

- `40001=0`：立即停止当前机器人/流程运动，并保持 `40001=0`。
- 程序未运行时：
  - 写 `40001=1`：移动到 `initial_point`；运动中写 `4`；完成后保持 `2`。
  - 写 `40001=3`：运行保存的运动流程。
- 程序普通运行阶段保持 `40001=4`，只接受 `40001=0`；写入 `1` 或 `3` 会被忽略。
- 程序进入“40001放行或超时”延时模块时保持 `40001=5`：
  - 写 `40001=1`：提前结束当前延时并进入下一步。
  - 写 `40001=0`：停止整个流程。
  - 未写入 `1` 时，达到模块设置的最长等待时间后仍正常进入下一步。
- 延时结束且流程尚未结束时恢复 `40001=4`；整个流程成功完成后保持 `40001=5`。
- 启动后 5 秒仅用于观察机器人和主流程相机状态；未就绪不报码、不锁定，后台继续低频重连。
- 写 `40001=3` 时只读检查机器人连接、反馈缓存和主流程所需相机；缺少设备立即写 `110`，不等待连接或抓帧。
- `110` 只拒绝本次流程启动。设备恢复后 PLC 可直接再次写 `3`，无需先写 `0`。
- 流程运行中检测到机器人反馈或相机采集断线时立即停止并写 `110`；后台重连后不自动续跑。

断线期间收到的运动命令不会排队，避免机器人重连后执行过期动作。

## 异常退出恢复

后台发现上次未正常退出或退出时仍在运行流程，会进入 `RECOVERY_REQUIRED` 并保持 `40001=110`：

1. PLC 写 `40001=0`，停止并解除恢复锁。
2. PLC 写 `40001=1`，机器人复位完成后保持 `40001=2`。
3. PLC 再写 `40001=3`，启动新流程。

后台不会从 `runtime_state.json` 恢复上次模块，避免重复抓取或跳过动作。GUI 和后台共用 `robot_control.lock`；后台运行时 GUI 不允许再次连接机器人或启动第二个 Modbus 服务。

如果 `config.json`、流程文件损坏或机器人 IP/Modbus 端口无效，也会保持 `RECOVERY_REQUIRED`。修复文件后重新写 `40001=0`，后台会再次校验；校验仍失败时恢复锁不会解除。

## 可选运行配置

`config.json` 可增加 `runtime` 对象；字段缺失时使用默认值：

```json
{
  "runtime": {
    "startup_connect_timeout_s": 5.0,
    "camera_retry_interval_s": 10.0,
    "poll_interval": 1,
    "health_path": "runtime_health.json",
    "state_path": "runtime_state.json",
    "disk_free_min_mb": 512,
    "camera_retry_count": 3,
    "reconnect_stable_seconds": 10,
    "reconnect_jitter_ratio": 0.2
  }
}
```

## 安装开机自启动

以管理员身份打开 PowerShell，在项目根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_runtime_task.ps1
```

指定项目路径和 Python 路径：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_runtime_task.ps1 `
  -TaskName DobotRuntimeAgent `
  -ProjectRoot D:\桌面\dobot_move_python `
  -PythonExe D:\桌面\dobot_move_python\.venv\Scripts\python.exe
```

安装脚本会注册两个 Windows Task Scheduler 任务：

- 任务名：`DobotRuntimeAgent`
- 看门狗任务名：`DobotRuntimeWatchdog`
- 触发：开机启动
- 工作目录：项目根目录
- 启动命令：`python -m dobot_move.runtime_agent --startup-delay 0`（参数仅为旧版本兼容）
- 权限：最高权限运行
- 单实例策略：忽略重复启动
- 失败恢复：失败后 1 分钟自动重启，最多 3 次
- 运行时间：不限制

看门狗每 5 秒检查健康文件，超过 15 秒未更新时先尝试停止正在运行的机器人流程，再结束卡死进程并重启后台。10 分钟内达到 3 次重启会生成 `runtime_watchdog_lockout.json` 并停止自动恢复；排除故障后需手动删除该文件。

手动运行看门狗：

```powershell
python -m dobot_move.runtime_watchdog --task-name DobotRuntimeAgent
```

默认参数：

- 健康超时：15 秒。
- 检查周期：5 秒。
- 独立 `Stop()` 超时：2 秒。
- 重启限制：10 分钟内 3 次。
- 看门狗启动后先等待至少 30 秒，避免和系统开机过程冲突。

## 查看、停止和删除开机任务

查看任务：

```powershell
Get-ScheduledTask -TaskName DobotRuntimeAgent
Get-ScheduledTask -TaskName DobotRuntimeWatchdog
Get-ScheduledTaskInfo -TaskName DobotRuntimeAgent
```

手动启动任务：

```powershell
Start-ScheduledTask -TaskName DobotRuntimeAgent
Start-ScheduledTask -TaskName DobotRuntimeWatchdog
```

停止任务：

```powershell
Stop-ScheduledTask -TaskName DobotRuntimeAgent
Stop-ScheduledTask -TaskName DobotRuntimeWatchdog
```

删除任务：

```powershell
Unregister-ScheduledTask -TaskName DobotRuntimeAgent -Confirm:$false
Unregister-ScheduledTask -TaskName DobotRuntimeWatchdog -Confirm:$false
```

解除看门狗熔断：

```powershell
Stop-ScheduledTask -TaskName DobotRuntimeAgent
Remove-Item .\runtime_watchdog_lockout.json -ErrorAction SilentlyContinue
Remove-Item .\runtime_watchdog_restarts.json -ErrorAction SilentlyContinue
Start-ScheduledTask -TaskName DobotRuntimeAgent
```

## 现场确认流程

1. 管理员 PowerShell 执行安装脚本。
2. 重启工控机。
3. 打开任务计划程序，确认 `DobotRuntimeAgent` 和 `DobotRuntimeWatchdog` 均为运行中。
4. 确认 `logs/runtime.log` 和 `logs/runtime_watchdog.log` 持续写入。
5. 确认 `runtime_health.json` 中 `modbus.is_running=true`。
6. 机器人上电并网络可达后，确认 `robot.connected=true`。
7. 主站依次写入 `40001=0/1/3` 做联调。

## 注意事项

- 现场生产建议运行 `python -m dobot_move.runtime_agent`，不要依赖打开 PyQt UI 来维持生产通信。
- PyQt UI 可以打开用于查看配置，但后台持有 `robot_control.lock` 时 UI 连接机器人会被拒绝。
- 如果端口 `502` 被占用，Modbus 从站无法启动，需要先关闭占用端口的进程。
- 看门狗独立 `Stop()` 只是补充保护，不能替代物理急停、安全门和安全 PLC。
