# Dobot-VGS-RS400

基于 Intel RealSense D400 深度相机的越疆 CR 系列机械臂视觉引导系统

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux-green.svg)]()
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

基于 Python + PySide6 的越疆 CR 系列机械臂视觉定位控制系统。集成双 RealSense 深度相机（D435i + D405）、YOLO 实例分割、ByteTrack 目标跟踪、3D 卡尔曼滤波、手眼标定、视觉伺服和普通圆弧运动，实现从目标识别到精准定位的全自动化流程。

## 功能特性

- 🎯 **双相机协作** — D435i 粗定位 + D405 精细识别（掩码几何中心）
- 🧠 **YOLO 实例分割** — YOLO11s-seg / YOLO26 端到端 + ByteTrack 多目标跟踪 + 3D Kalman 滤波
- 📐 **手眼标定** — D435i/D405 双相机独立标定
- 🎮 **视觉伺服** — 自适应增益迭代逼近，2mm 收敛阈值
- ↪ **原生圆弧运动** — ArcTrajectoryPlanner + ArcMotionController，使用 Dobot Arc()
- 🔌 **Modbus TCP** — 本地 PC 作为 Modbus TCP 从站/服务器，供外部主站 PC 访问
- ⚡ **C++ 加速** — 可选 dobot_core pybind11 模块，5-20 倍加速，Python 回退
- 🔀 **流程步骤编辑器** — 拖拽排序步骤，实时状态图标（待执行/执行中/已完成/失败）
- 💾 **ConfigService** — 统一防抖配置写入，避免频繁磁盘 I/O
- 🎨 **PySide6 兼容** — qt_compat.py 抽象层，实现 Qt 框架无关性
- 🔒 **运动互斥锁** — acquire_motion/release_motion，流程和 Modbus 运动互斥，急停始终优先
- ⚡ **30004 反馈状态机** — 速度归零+位姿到位+连续稳定判定运动完成，减少 Dashboard 查询
- 🆔 **指令 ID 追踪** — 按官方 TCP-IP-Python-V4 模式，CurrentCommandId 精确判定运动完成
- 🛑 **急停独立连接** — 独立临时 Dashboard 连接发送 EmergencyStop，避免主连接锁阻塞
- 📊 **统一反馈快照** — get_motion_feedback_snapshot() 一次性返回位姿、速度、队列状态、运行状态
- 🔄 **Modbus 异步执行** — 运动命令投递独立线程，`40001=0` 停止走快速路径，不被长时间运动阻塞
- 🛡️ **7×24 后台加固** — 崩溃恢复锁、流程看门狗、反馈断流先停、相机预检和独立进程外看门狗
- 🔐 **跨进程控制租约** — GUI 与后台互斥占用机器人控制权，避免重复连接和重复 Modbus 服务
- 📋 **连续相对路径编辑器** — 15 列段表、stop_each/queued 执行模式、段级参数覆盖
- 🧲 **TCP 力到位保护** — 运动中监控 ActualTCPForce，超过用户阈值即 Stop 当前运动并继续下一步
- 🎯 **saved_point 目标** — 直线运动支持已保存点位/相机识别坐标/初始位置三种目标
- 🔧 **统一 user/tool 参数** — Arc/MovJ/MovL/RelMovL/RelMovJ 从配置统一传入 user_index/tool_index
- 📦 **send_relative_command 封装** — queued 和单段相对移动复用统一命令发送、响应解析、command_id 追踪
- 🛡️ **ServoP 队列保护** — TCP 往返超伺服周期时自动跳帧降频，连续失败暂停重试
- 📝 **报警详情补全** — 异步获取 GetError 详情后自动追加到报警记录
- 🧩 **Runtime 去 Qt 化** — 后台流程执行器纯 Python 实现，不依赖 QThread/QImage/pyqtSignal，可在无 Qt 环境运行
- 🌐 **Remote REST API** — 独立 HTTP 服务供外部平板/MES 只读查询机器人状态、30004 反馈、Modbus 寄存器和生产状态，Token 认证 + CORS + 旧路径 301 重定向

## 快速开始

### 快速开始 · 开发模式

适用于本地开发、调试 GUI 和视觉功能。

```powershell
git clone https://github.com/only-one-over/Dobot-VGS-RS400.git
cd Dobot-VGS-RS400

# 创建虚拟环境（推荐 Python 3.12 x64）
python -m venv .venv
.\.venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt

# 启动 GUI
python run.py
```

### 快速开始 · Windows Service 部署

适用于生产环境 7×24 无人值守运行。使用 WinSW 将 Runtime + Watchdog 注册为 Windows 服务。

#### 默认路径

| 项目 | 默认值 | 自定义参数 |
|------|--------|------------|
| 项目根目录 | `C:\DobotRuntime` | `-ProjectRoot <路径>` |
| Python 解释器 | `<ProjectRoot>\.venv\Scripts\python.exe` | `-PythonExe <路径>` |
| 服务用户 | `.\DobotRuntimeSvc` | `-ServiceUser <用户名>` |
| 用户数据目录 | `<ProjectRoot>\user_data\` | — |
| WinSW 包装日志 | `<ProjectRoot>\logs\` | — |
| Runtime 日志 | `<ProjectRoot>\user_data\logs\` | — |
| IPC Token | `<ProjectRoot>\user_data\runtime_ipc.token` | config `runtime.ipc_token_path` |
| 健康文件 | `<ProjectRoot>\user_data\runtime_health.json` | — |

#### 步骤 1：准备项目目录和虚拟环境

```powershell
# 方式 A：使用默认路径 C:\DobotRuntime
mkdir C:\DobotRuntime
cd C:\DobotRuntime
# 将项目文件复制到 C:\DobotRuntime（或 git clone 到此目录）

# 方式 B：使用自定义路径（例如 D:\DobotProd）
# git clone https://github.com/only-one-over/Dobot-VGS-RS400.git D:\DobotProd
# cd D:\DobotProd

# 创建虚拟环境
python -m venv .venv

# 安装依赖
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

#### 步骤 2：安装 Windows 服务

以**管理员身份**运行 PowerShell：

```powershell
# 使用默认路径 C:\DobotRuntime
powershell -ExecutionPolicy Bypass `
  -File .\scripts\install_windows_services.ps1 `
  -CreateServiceUser

# 或使用自定义路径
powershell -ExecutionPolicy Bypass `
  -File .\scripts\install_windows_services.ps1 `
  -ProjectRoot D:\DobotProd `
  -PythonExe D:\DobotProd\.venv\Scripts\python.exe `
  -CreateServiceUser
```

安装过程会自动：
1. 检查管理员权限、Python 和 WinSW 哈希
2. 创建服务账户 `DobotRuntimeSvc`（自动生成强密码）
3. 生成 IPC token 并限制文件权限
4. 安装并启动 `DobotRuntimeService` + `DobotRuntimeWatchdog` 两个服务
5. 验证服务状态、健康文件和 IPC 连通性

#### 步骤 3：检查服务状态

```powershell
# 查看服务状态
Get-Service DobotRuntimeService
Get-Service DobotRuntimeWatchdog

# 查看健康文件
Get-Content .\user_data\runtime_health.json

# 查看 Runtime 日志（最后 100 行）
Get-Content .\user_data\logs\runtime.log -Tail 100

# 运行状态检查脚本
powershell -ExecutionPolicy Bypass `
  -File .\scripts\test_windows_services.ps1 `
  -ProjectRoot C:\DobotRuntime
```

#### 步骤 4：卸载与回滚

```powershell
# 仅卸载服务
powershell -ExecutionPolicy Bypass `
  -File .\scripts\uninstall_windows_services.ps1 `
  -ProjectRoot C:\DobotRuntime

# 卸载服务并恢复旧任务计划
powershell -ExecutionPolicy Bypass `
  -File .\scripts\rollback_windows_services.ps1 `
  -ProjectRoot C:\DobotRuntime `
  -StartLegacyTasks
```

#### 步骤 5：更新代码后重启 Windows 服务

修改 `dobot_move/runtime/runtime_agent.py`、`dobot_move/runtime/*.py` 或其他 Runtime 代码后，**必须重启 `DobotRuntimeService` 才能加载新代码**——Windows Service 进程在启动时已将旧代码载入内存，热替换文件不会立即生效。

以**管理员身份**运行 PowerShell：

```powershell
# 1. 重启 Runtime 服务（Watchdog 会随后自动对齐，无需单独重启）
Restart-Service DobotRuntimeService -Force

# 2. 验证服务状态（应为 Running）
Get-Service DobotRuntimeService

# 3. 验证健康文件已重置为新会话
Get-Content .\user_data\runtime_health.json
```

关键行为说明：

- `Restart-Service -Force` 会先发送停止信号，等待最多 30 秒让 Runtime 完成优雅停止（关闭相机、机器人连接、Modbus、写入 `runtime_health.json` 中的 `clean_shutdown=true` 标记），再启动新进程。
- 新进程启动时会读取 `runtime_health.json`，若上次未正常关闭（`clean_shutdown=false`、JSON 损坏或仍处于 ACTIVE 状态），Runtime 会进入 `RECOVERY_REQUIRED` 状态，等待操作员通过 PLC 寄存器 40001=0 或 IPC `clear_recovery` 命令清除恢复锁。
- Watchdog 服务在 Runtime 停止期间不会误触发重启，因为它检测到 SCM 主动停止信号后会等待 Runtime 自行退出；只有在 Runtime 卡死（健康文件长时间未更新）时才会独立发送 `Stop()` 并通过 SCM 重启。
- 仅修改 GUI 代码（`dobot_move/ui/*.py`）**无需重启服务**——GUI 是登录用户独立启动的进程，关闭并重新打开 GUI 即可加载新代码。
- 修改 `scripts/install_windows_services.ps1` 等安装脚本后**无需重启服务**，下次执行安装/卸载脚本时自动生效。

> 完整的部署细节、安全说明和故障排查请参阅 **[docs/windows_service.md](docs/windows_service.md)**。

### 快速开始 · 内网工控机离线部署

适用于无法访问互联网的工控机（产线内网环境）。核心思路：在联网开发机上下载所有依赖 wheel 并打包，再拷贝到工控机用 `pip install --no-index` 离线安装。

#### 联网开发机：准备离线包

```powershell
# 1. 在开发机（与工控机相同的 Windows x64 + Python 3.11 x64）执行
cd C:\path\to\Dobot-VGS-RS400

# 2. 确认 requirements_lock.txt 存在（锁定精确版本，避免在线解析）
# 若不存在，先在干净 venv 中生成：
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
pip freeze > requirements_lock.txt

# 3. 下载所有依赖 wheel 到 wheels/ 目录
pip download -r requirements_lock.txt -d wheels/

# 4. 打包项目（含 wheels/ 但不含 .venv/、user_data/ 数据、logs/）
Compress-Archive -Path .\dobot_move,.\scripts,.\docs,.\README.md,`
  .\USER_GUIDE.md,.\requirements.txt,.\requirements_lock.txt,`
  .\run.py,.\remote_api.py,.\runtime_agent.py,.\runtime_watchdog.py,`
  .\build_cpp.py,.\wheels,.\dobot_move\windows_service\vendor `
  -DestinationPath .\dobot-vgs-offline.zip -Force
```

可选：将 RealSense SDK、CUDA 12.x 独立安装包一并打包（工控机若无 CUDA，会自动回退到 CPU 推理，但帧率会显著下降）。

#### 工控机：离线安装

```powershell
# 1. 解压离线包到 C:\DobotRuntime
Expand-Archive .\dobot-vgs-offline.zip -DestinationPath C:\DobotRuntime -Force
cd C:\DobotRuntime

# 2. 创建虚拟环境（工控机已预装 Python 3.11 x64）
python -m venv .venv
.\.venv\Scripts\activate

# 3. 离线安装依赖（--no-index 禁用 PyPI，--find-links 指向本地 wheels/）
pip install --no-index --find-links=wheels\ -r requirements_lock.txt

# 4. 验证关键依赖（GPU 推理可用性）
python -c "import onnxruntime; print(onnxruntime.get_available_providers())"
# 期望输出包含 'CUDAExecutionProvider'；若仅 'CPUExecutionProvider' 则检查 CUDA 安装

# 5. 拷贝模型文件、标定参数、流程文件到 user_data/（离线环境手工拷贝）
#    - user_data/config.json
#    - user_data/grasp_flow_modules.json
#    - user_data/<model>.onnx
#    - user_data/hand_eye_calib_*.json

# 6. 执行配置预检（必须通过才能安装服务）
.\.venv\Scripts\python.exe -m dobot_move.runtime --check-config

# 7. 安装 Windows Service（按上面"Windows Service 部署"章节的步骤 2 执行）
powershell -ExecutionPolicy Bypass `
  -File .\scripts\install_windows_services.ps1 `
  -CreateServiceUser
```

#### 离线环境更新代码

后续推送代码更新到工控机时，只需拷贝 `dobot_move/` 目录和入口脚本即可，**不要覆盖 `user_data/`**（保留生产配置和标定数据）：

```powershell
# 1. 暂停服务（避免文件被占用）
Stop-Service DobotRuntimeService -Force

# 2. 拷贝新的 dobot_move/、run.py、runtime_agent.py 等到 C:\DobotRuntime
# （仅替换代码目录，保留 user_data/、.venv/、wheels/）

# 3. 若依赖变化，离线更新 wheel
pip install --no-index --find-links=wheels\ -r requirements_lock.txt --upgrade

# 4. 重启服务加载新代码
Start-Service DobotRuntimeService
```

#### 离线部署注意事项

- **Python 版本一致**：开发机和工控机必须使用相同 Python 版本和位数（推荐 Python 3.11 x64），否则 wheel 不兼容。
- **CUDA 版本匹配**：`onnxruntime-gpu` 1.16+ 要求 CUDA 12.x；工控机若装 CUDA 11.x，需下载对应 `onnxruntime-gpu==1.15` 的 wheel。
- **wheel 完整性**：拷贝前在开发机执行 `pip install --no-index --find-links=wheels\ -r requirements_lock.txt` 验证一次，确保所有依赖齐全。
- **不要复制 `.venv`**：每台工控机必须重新创建虚拟环境，直接复制其他机器的 `.venv` 会导致路径硬编码和 Python 解释器不匹配。
- **user_data 隔离**：`user_data/` 目录包含工控机特定的 IP、标定参数、流程定义，绝对不要用开发机的同名文件覆盖。

### 快速开始 · Remote REST API（可选）

Remote REST API 是独立 HTTP 服务，供外部平板/MES 只读查询机器人状态、30004 反馈、Modbus 寄存器和生产状态。

```powershell
# 使用默认配置（host=0.0.0.0, port=8000, 无 token）
python -m dobot_move.remote_api

# 或指定 host 和 port
python -m dobot_move.remote_api --host 0.0.0.0 --port 8000

# 或使用根目录入口脚本
python remote_api.py
```

默认配置（可通过 `user_data/config.json` 的 `remote_api` 段覆盖）：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `host` | `0.0.0.0` | 监听地址 |
| `port` | `8000` | 监听端口 |
| `token` | `""` | 为空时禁用 Token 认证 |
| `feedback_port` | `30004` | Dobot 反馈端口 |
| `modbus_host` | `127.0.0.1` | Modbus 读取地址 |

> 完整的 API 端点和安全说明请参阅 **[docs/architecture.md](docs/architecture.md)** 的"Remote REST API"小节。

### 配置文件位置速查表

| 文件 | 默认路径 | 说明 |
|------|----------|------|
| 运行配置 | `<ProjectRoot>\user_data\config.json` | 机器人 IP、相机、标定、Modbus 等 |
| 流程文件 | `<ProjectRoot>\user_data\grasp_flow_modules.json` | 生产流程定义 |
| Runtime 健康 | `<ProjectRoot>\user_data\runtime_health.json` | 服务模式状态 |
| Runtime 状态 | `<ProjectRoot>\user_data\runtime_state.json` | 运行时状态快照 |
| IPC Token | `<ProjectRoot>\user_data\runtime_ipc.token` | 跨进程认证 token |
| Runtime 日志 | `<ProjectRoot>\user_data\logs\runtime.log` | Runtime 主日志 |
| Remote API 日志 | `<ProjectRoot>\user_data\logs\remote_api.log` | Remote API 日志 |
| Remote API 健康 | `<ProjectRoot>\user_data\remote_api_health.json` | Remote API 状态 |
| WinSW 日志 | `<ProjectRoot>\logs\` | 服务包装器日志 |
| 报警历史 | `<ProjectRoot>\user_data\alarm_history.json` | 历史报警记录 |

> 完整的安装、配置、标定、操作、部署和故障排查指南请参阅 **[USER_GUIDE.md](USER_GUIDE.md)**。

## 文档导航

| 文档 | 说明 |
|------|------|
| **[USER_GUIDE.md](USER_GUIDE.md)** | 用户使用指南 — 从安装到运维的完整流程 |
| **[CODE_WIKI.md](CODE_WIKI.md)** | 代码 Wiki — 架构、模块、类与函数索引 |
| [docs/architecture.md](docs/architecture.md) | 系统架构 — 分层设计、资源所有权、IPC |
| [docs/runtime_agent.md](docs/runtime_agent.md) | Runtime 后台 — 无头运行、状态文件、异常恢复 |
| [docs/windows_service.md](docs/windows_service.md) | WinSW 服务 — 双服务部署、安装卸载回滚 |
| [docs/gpu_environment.md](docs/gpu_environment.md) | GPU 环境 — CUDA 部署、ONNX Runtime 验证 |
| [docs/cpp_acceleration.md](docs/cpp_acceleration.md) | C++ 加速 — pybind11 构建与 API |
| [docs/dev_workflow.md](docs/dev_workflow.md) | 开发工作流 — 依赖管理、启动命令 |
| [docs/ui_spec.md](docs/ui_spec.md) | UI 规格 — 界面设计与交互 |
| [docs/roadmap.md](docs/roadmap.md) | 路线图 — 开发计划 |

## 许可证

本项目基于 MIT 许可证授权——详见 [LICENSE](LICENSE) 文件。
