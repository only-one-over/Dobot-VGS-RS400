# Dobot-VGS-RS400 用户使用指南

本指南面向 Dobot CR 系列机械臂视觉引导系统的现场操作人员和工程师，涵盖从硬件准备、安装部署到日常操作、生产部署和故障排查的全流程。所有命令均给出 Windows PowerShell / bash 示例，可直接复制执行。

深入阅读：

- [docs/runtime_agent.md](docs/runtime_agent.md) — Runtime 后台运行与异常恢复
- [docs/windows_service.md](docs/windows_service.md) — WinSW 服务部署详解
- [docs/gpu_environment.md](docs/gpu_environment.md) — GPU 环境完整部署指南
- [docs/cpp_acceleration.md](docs/cpp_acceleration.md) — C++ 加速模块构建与接口契约
- [docs/dev_workflow.md](docs/dev_workflow.md) — 开发工作流

---

## 1. 概述与硬件要求

### 1.1 项目用途

本项目是基于 Intel RealSense D400 深度相机的越疆 CR 系列机械臂视觉引导系统，集成 YOLO 实例分割、ByteTrack 目标跟踪、3D 卡尔曼滤波、手眼标定和视觉伺服，实现从目标识别到精准定位抓取的全自动化流程。

### 1.2 硬件清单

| 设备 | 型号 / 规格 | 用途 | 备注 |
|------|-------------|------|------|
| 机械臂 | Dobot CR5 / CR10 / CRA 系列 | TCP/IP 协议控制 | 默认 IP `192.168.1.50` |
| 中距深度相机 | Intel RealSense D435i | 粗定位 | 有效深度 0.5–2.2 m |
| 近距深度相机 | Intel RealSense D405 | 精细识别（掩码几何中心） | 有效深度 0.07–0.8 m |
| 力传感器 | Dobot 内置六轴力传感器 | TCP 力到位保护、力控监测 | FT 系列 |
| 网络设备 | 以太网交换机 | 机器人与 PC 同网段通信 | 建议千兆有线 |
| GPU（可选） | NVIDIA 计算能力 6.0+（Pascal 及以上） | YOLO 推理加速 | 无 GPU 自动回退 CPU |

### 1.3 软件环境要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Windows 10/11 x64（推荐），Linux 亦可运行 |
| Python | 3.10+，推荐 3.12（避免 3.13 兼容性风险） |
| RealSense SDK | Intel RealSense SDK 2.0（与 Python 版本匹配） |
| NVIDIA 驱动 | >= 525.60.13（仅 GPU 模式需要） |
| CMake | 3.15+（仅 C++ 加速构建需要） |
| C++ 编译器 | C++17，Windows 推荐 Visual Studio Build Tools（仅 C++ 加速需要） |

---

## 2. 安装部署

### 2.1 创建虚拟环境并安装 Python 依赖

```powershell
# 进入项目根目录
cd C:\Users\13571\Desktop\Dobot-VGS-RS400

# 创建虚拟环境（推荐 Python 3.12 x64）
python -m venv .venv

# 激活虚拟环境
.\.venv\Scripts\activate

# 升级 pip
python -m pip install --upgrade pip

# 安装依赖（基础 + GPU 可选 + C++ 可选全部包含在 requirements.txt 中）
pip install -r requirements.txt
```

`requirements.txt` 依赖分区说明：

| 分区 | 包 | 说明 |
|------|----|------|
| 基础依赖 | PySide6、numpy、opencv-python、scipy、pyrealsense2、pymodbus、minimalmodbus、pyserial、python-can、lapx、requests | 必装 |
| GPU 推理（可选） | `onnxruntime-gpu[cuda,cudnn]` | 需 NVIDIA GPU，无 GPU 时安装失败不影响 CPU 推理 |
| C++ 加速（可选） | `pybind11`、`cmake` | 用于构建 `dobot_core` 模块 |

### 2.2 安装 Intel RealSense SDK 2.0

1. 从 [Intel RealSense SDK 2.0](https://github.com/IntelRealSense/librealsense/releases) 下载与系统匹配的 Windows SDK 安装包。
2. 安装完成后插入 RealSense 相机，打开 RealSense Viewer 确认相机可正常识别并出流。
3. 确保 `pyrealsense2` 的版本与 SDK 版本匹配（一般 pip 安装的版本自带运行时）。

```powershell
# 验证 Python 端 RealSense 绑定
python -c "import pyrealsense2 as rs; print('RealSense version:', rs.__version__)"
```

### 2.3 GPU 可选环境配置（精简版）

GPU 部署关键点：

- 只需安装 NVIDIA 驱动（>= 525.60.13）；CUDA Runtime 和 cuDNN 会随 `onnxruntime-gpu[cuda,cudnn]` 自动安装到 `.venv`，**无需单独下载 CUDA Toolkit**。
- `onnxruntime` 和 `onnxruntime-gpu` 不能同时安装，装了 GPU 版后必须先卸载 CPU 版。

```powershell
# 确认 GPU 驱动
nvidia-smi

# GPU 真实启用验证（必须实际创建 CUDA session 并执行一次推理）
.\.venv\Scripts\python.exe -c "import numpy as np, onnxruntime as ort; from dobot_move.vision_system import preload_onnx_runtime_dlls; preload_onnx_runtime_dlls(ort); s=ort.InferenceSession('dobot_move/best.onnx',providers=['CUDAExecutionProvider','CPUExecutionProvider']); s.disable_fallback(); i=s.get_inputs()[0]; s.run(None,{i.name:np.zeros(tuple(i.shape),dtype=np.float32)}); print('GPU inference OK:',s.get_providers())"
```

完整 GPU 部署步骤、错误排查详见 [docs/gpu_environment.md](docs/gpu_environment.md)。

### 2.4 C++ 加速模块可选构建（精简版）

```powershell
# 安装构建工具
pip install pybind11 cmake

# 一键构建
python build_cpp.py

# 或使用原生 CMake
cmake -S cpp_core -B cpp_core/build
cmake --build cpp_core/build --config Release

# 验证
python -c "import dobot_core; print('C++ module OK:', dir(dobot_core))"
```

构建失败不影响使用，程序自动回退 Python 实现。完整接口契约与回退测试见 [docs/cpp_acceleration.md](docs/cpp_acceleration.md)。

### 2.5 安装验证命令

```powershell
# 1. 基础依赖验证
python -c "import PySide6, numpy, cv2, pyrealsense2, onnxruntime; print('All dependencies OK')"

# 2. GPU 真实启用验证（仅 GPU 模式）
python -c "import onnxruntime as ort; s = ort.InferenceSession('dobot_move/best.onnx', providers=['CUDAExecutionProvider']); print('Active providers:', s.get_providers())"
# 通过标准：输出包含 CUDAExecutionProvider

# 3. C++ 加速模块验证（可选）
python -c "import dobot_core; print('C++ module OK:', dir(dobot_core))"

# 4. 配置预检（首次配置完成后执行）
python run.py --check-config
```

---

## 3. 首次配置

### 3.1 复制配置模板

```powershell
# 在项目根目录执行
# Windows
Copy-Item .\dobot_move\config\config.example.json .\user_data\config.json

# Linux / Git Bash
cp ./dobot_move/config/config.example.json ./user_data/config.json
```

若 `user_data/` 目录不存在，先创建：

```powershell
New-Item -ItemType Directory -Path .\user_data
```

### 3.2 必改项清单

打开 `user_data/config.json`，按以下表格修改标注 `[必改]` 的字段：

| 字段路径 | 默认值 | 必改 | 说明 |
|---------|--------|------|------|
| `robot_ip` | `"192.168.5.1"` | [必改] | 机器人的局域网 IP 地址，需与现场一致 |
| `photo_position` | `[0,0,0,0,0,0]` | [必改] | 拍照位 `[x,y,z,rx,ry,rz]`（mm / deg），机器人从此位置拍照识别目标 |
| `camera.models.D435i` | `""` | [必改] | D435i ONNX 模型绝对路径，留空则使用 `dobot_move/best.onnx` |
| `camera.models.D405` | `""` | [必改] | D405 ONNX 模型绝对路径，留空则使用 `dobot_move/best.onnx` |
| `calibration.D435i.cam_to_flange_pose` | `[0,0,0,0,0,0]` | [必改] | D435i 相机相对法兰的位姿 `[x,y,z,rx,ry,rz]`（mm / deg） |
| `calibration.D405.cam_to_flange_pose` | `[0,0,0,0,0,0]` | [必改] | D405 相机相对法兰的位姿 `[x,y,z,rx,ry,rz]`（mm / deg） |
| `modbus_port` | `502` | [选改] | Modbus TCP 服务器端口，被占用时修改 |
| `modbus_slave_id` | `5` | [选改] | Modbus 从站地址 |
| `target_offset` | `[0,0,0]` | [选改] | 抓取目标偏移 `[dx,dy,dz]`（mm） |
| `remote_api.host` | `"0.0.0.0"` | [选改] | Remote API 监听地址 |
| `remote_api.port` | `8000` | [选改] | Remote API 监听端口 |
| `remote_api.token` | `""` | [选改] | Bearer Token，生产环境必填非空值 |

### 3.3 环境变量覆盖机制

以下环境变量可覆盖 `config.json` 中的对应字段，优先级：**环境变量 > config.json > 代码默认值**。适用于多机部署差异化配置或 CI 测试场景。

| 环境变量 | 覆盖字段 | 示例 |
|----------|----------|------|
| `DOBOT_ROBOT_IP` | `robot_ip` | `set DOBOT_ROBOT_IP=192.168.1.50` |
| `DOBOT_MODBUS_PORT` | `modbus_port` | `set DOBOT_MODBUS_PORT=502` |
| `DOBOT_MODBUS_SLAVE` | `modbus_slave_id` | `set DOBOT_MODBUS_SLAVE=5` |
| `DOBOT_D435I_MODEL` | `camera.models.D435i` | `set DOBOT_D435I_MODEL=D:\models\d435i.onnx` |
| `DOBOT_D405_MODEL` | `camera.models.D405` | `set DOBOT_D405_MODEL=D:\models\d405.onnx` |
| `DOBOT_REMOTE_API_PORT` | `remote_api.port` | `set DOBOT_REMOTE_API_PORT=8000` |

PowerShell 设置环境变量（仅当前会话）：

```powershell
$env:DOBOT_ROBOT_IP = "192.168.1.50"
```

永久设置（用户级）：

```powershell
[Environment]::SetEnvironmentVariable("DOBOT_ROBOT_IP", "192.168.1.50", "User")
```

### 3.4 `--check-config` 预检命令

部署完成后必须运行预检，验证配置完整性和文件可访问性：

```powershell
python run.py --check-config
```

或：

```powershell
python -m dobot_move --check-config
```

输出示例（成功）：

```text
[OK] config.json 已加载
[OK] robot_ip 已配置: 192.168.1.50
[OK] photo_position 已配置且非全零
[OK] D435i 模型路径可访问: D:\models\d435i.onnx
[OK] D405 模型路径可访问: D:\models\d405.onnx
[OK] D435i 标定参数已配置
[OK] D405 标定参数已配置
[OK] Modbus 端口 502 可用
配置预检通过
```

输出示例（失败，退出码非零）：

```text
[FAIL] photo_position 仍为全零，必须修改为现场拍照位
[FAIL] D435i 标定参数仍为默认值，请先完成手眼标定
配置预检失败，请按提示修改 user_data/config.json
```

---

## 4. 首次标定

首次部署或更换相机/末端工具后必须重新执行手眼标定，否则视觉定位精度不达标。

### 4.1 标定 GUI 操作步骤

```powershell
# 启动 GUI
python run.py
```

操作流程：

1. 在主控制页输入机器人 IP，点击 **连接**。
2. 连接成功后点击 **使能**，机器人进入运动就绪状态。
3. 切换到 **手眼标定** 选项卡。
4. 在 D435i 标定区填写：
   - **标定板上工具点位姿**（机器人末端的当前位姿，可点击"读取当前位姿"自动填充）
   - **相机原点位姿**（相机识别到的标定板坐标系原点）
5. 点击 **计算** 生成 D435i 手眼矩阵。
6. 切换到 D405 标定区，重复步骤 4–5。
7. 标定结果会自动写入 `user_data/config.json` 的 `calibration.D435i` / `calibration.D405` 块。

### 4.2 标定参数说明

每个相机的标定数据包含一个字段：

```json
{
  "calibration": {
    "D435i": {
      "cam_to_flange_pose": [x, y, z, rx, ry, rz]
    },
    "D405": {
      "cam_to_flange_pose": [x, y, z, rx, ry, rz]
    }
  }
}
```

| 字段 | 单位 | 说明 |
|------|------|------|
| `cam_to_flange_pose` | mm / deg | 相机相对法兰（末端）的位姿 `[x, y, z, rx, ry, rz]` |

系统直接将 `cam_to_flange_pose` 转为 4x4 齐次矩阵作为手眼矩阵 `T_cam2flange`。

> 注意：旧版配置使用 `tool_base_calib_pose` + `cam_base_calib_pose` 双位姿格式，系统检测到旧格式时会自动迁移（计算 `inv(T_tool2base) @ T_cam2base`），无需手动转换。本项目使用 **ZYX 旋转顺序** 的欧拉角约定，外部标定数据导入时需确认顺序一致。建议多次标定取平均值，标定误差应 < 5 mm。

### 4.3 点位设置说明

`points` 配置块首次运行时自动创建三个默认点位，可在 GUI 中编辑：

| 点位名 | 用途 | 是否默认 |
|--------|------|----------|
| `initial_point` | 机器人复位/待机位，Modbus `40001=1` 移动到此点 | 是（不可删除） |
| `d435i` | D435i 识别的目标中心，由视觉系统自动更新 | 是（不可删除） |
| `d405` | D405 识别的目标中心，由视觉系统自动更新 | 是（不可删除） |

点位数据格式：

```json
{
  "d435i": {
    "coords": [x, y, z, rx, ry, rz],
    "is_relative": false,
    "relative_to": null,
    "offset": [0, 0, 0, 0, 0, 0],
    "is_default": true
  }
}
```

### 4.4 相机 ONNX 模型选择步骤

1. 准备 `.onnx` 模型文件（必须使用固定 NCHW 输入尺寸，输出当前后处理支持的 YOLO 检测或实例分割张量）。
2. 在 GUI 主控制页 **D435i 相机** 区域，点击 **选择模型**，浏览并选择对应 `.onnx` 文件，路径保存到 `camera.models.D435i`。
3. 在 GUI 主控制页 **D405 相机** 区域，重复操作选择 D405 模型，保存到 `camera.models.D405`。
4. 相机连接期间需先 **断开** 才能更换模型。
5. 模型文件未配置时，程序兼容使用包内 `dobot_move/best.onnx`；模型文件丢失或不兼容时会拒绝连接，不会静默使用其他模型。
6. `*.onnx` 已被 Git 忽略，现场模型文件需单独部署到工控机。

---

## 5. 日常操作

### 5.1 GUI 启动命令

```powershell
# 激活虚拟环境
.\.venv\Scripts\activate

# 方式一：使用根目录入口脚本
python run.py

# 方式二：使用模块入口（推荐）
python -m dobot_move

# 部署预检（不启动 GUI）
python run.py --check-config
```

### 5.2 Runtime 后台启动命令

生产现场 7×24 后台运行使用包内模块（无 Qt 依赖，可在无 PySide6 环境运行）：

```powershell
# 方式一：使用根目录兼容入口
python runtime_agent.py

# 方式二：使用模块入口（推荐）
python -m dobot_move.runtime_agent
```

可选参数：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--startup-delay` | 0 | 仅保留旧命令兼容，即使设置也立即开始设备探测 |
| `--poll-interval` | 1 | 后台 watchdog 周期（秒） |
| `--health-path` | `runtime_health.json` | 健康状态文件路径 |
| `--state-path` | `runtime_state.json` | 崩溃恢复状态文件路径 |
| `--lock-path` | `runtime_agent.lock` | 后台进程单实例锁路径 |
| `--log-dir` | `logs` | 运行日志目录 |

### 5.3 GUI 连接设备步骤

1. **连接机器人** — 在主控制页输入机器人 IP（与 `config.json` 中 `robot_ip` 一致），点击 **连接**。
2. **使能机器人** — 连接成功后点击 **使能**，状态指示灯变绿表示就绪。
3. **连接相机** — 主控制页分别点击 D435i、D405 相机区域的 **连接** 按钮。后台会并发连接，5 秒观察窗口结束后不阻塞、不报码。
4. **选择模型** — 连接相机前先在 D435i、D405 各自选择正确的 `.onnx` 模型；相机连接期间需先断开才能更换。
5. **相机测试** — 点击 **相机测试** 验证检测效果，查看识别框、掩码和置信度。

> 注意：Runtime 后台持有 `robot_control.lock` 时，GUI 连接机器人或启动 Modbus 服务会被拒绝。打开 GUI 不会占用硬件，关闭 GUI 也不会停止后台服务。

### 5.4 运行抓取流程

完整抓取流程：

```text
拍照位 → D435i 粗识别 → 移动至 D435i 目标上方
→ 视觉伺服逼近 → D405 精细识别（掩码几何中心）
→ 计算目标点 → 移动至目标位置
→ 原生圆弧运动或相对移动（可选） → 抬升 → 放置
```

GUI 操作步骤：

1. 在 **流程编辑页** 编辑当前流程（拖拽排序步骤、设置参数）。
2. 在 **主控制页** 选择主流程（供 Modbus `40001=3` 调用）。
3. 点击 **运行** 启动流程，运行中可 **暂停** / **继续**。
4. 主控制页运行已选主流程；运动编辑页运行当前编辑流程。

### 5.5 Modbus 触发生产协议

本地 PC 作为 Modbus TCP 从站/服务器（默认 `modbus_port=502`），外部主站 PC 通过写 `40001` 寄存器触发动作。

#### 寄存器 40001 命令值表

| 写入值 | 含义 | 适用状态 | 系统行为 |
|--------|------|----------|----------|
| `0` | 停止 | 任何状态 | 立即停止当前机器人/流程运动，并保持 `40001=0`；解除恢复锁 |
| `1` | 复位 | 程序未运行 | 移动到 `initial_point`；运动中状态保持 `4`，完成后保持 `2` |
| `3` | 执行流程 | 程序未运行 | 运行保存的主流程；运行前只读检查设备，缺少设备立即写 `110` |
| `5` | 完成 | 延时放行模块 | 延时模块中写 `1` 提前结束延时进入下一步；写 `0` 停止整个流程 |

> 程序普通运行阶段保持 `40001=4`，只接受 `40001=0`，写入 `1` 或 `3` 会被忽略。
> 延时放行模块阶段保持 `40001=5`：写 `1` 提前结束延时；写 `0` 停止流程；未写入 `1` 时达到最长等待时间后正常进入下一步。
> 流程成功完成后保持 `40001=5`。

#### Modbus 状态值表（读取 40001 当前值）

| 状态值 | 含义 | 说明 |
|--------|------|------|
| `0` | 空闲 | 已停止，等待命令 |
| `2` | 待机 | 复位完成，处于 `initial_point` |
| `4` | 运行中 | 流程执行中，只接受 `0` 停止 |
| `5` | 完成 | 流程完成或延时放行中 |
| `110` | 流程错误 | 设备缺失或运行中断线，只拒绝本次启动；设备恢复后可直接再写 `3` |
| `111` | 机器人错误 | 机器人反馈异常 |
| `112` | 相机错误 | 相机采集异常 |

#### 异常恢复流程

后台发现上次未正常退出或退出时仍在运行流程，会进入 `RECOVERY_REQUIRED` 并保持 `40001=110`：

1. PLC 写 `40001=0`，停止并解除恢复锁。
2. PLC 写 `40001=1`，机器人复位完成后保持 `40001=2`。
3. PLC 再写 `40001=3`，启动新流程。

后台不会从 `runtime_state.json` 自动续跑上次模块，避免重复抓取或跳过动作。

---

## 6. 生产部署

### 6.1 WinSW 三服务架构说明

生产环境推荐使用 WinSW 三服务架构：

| 服务名 | 职责 | 运行账户 |
|--------|------|----------|
| `DobotRuntimeService` | 独占机器人、D405、D435i、Modbus 502、流程执行器和 localhost IPC | `.\DobotRuntimeSvc`（专用本地账户） |
| `DobotRuntimeWatchdog` | 检查健康文件，卡死时先独立发送 `Stop()`，再通过 SCM 重启 Runtime 服务 | `LocalSystem` |
| `DobotRemoteApiService` | HTTP REST API 服务（状态/报警/反馈/Modbus），监听 8000 端口 | `.\DobotRuntimeSvc`（与 Runtime 共享） |

关键特性：

- GUI 不注册为服务，由登录用户独立启动；关闭 GUI 不会停止 Runtime。
- IPC 只监听 `127.0.0.1:8765`，服务模式必须提供 `runtime_ipc.token`。
- Runtime 服务异常重启后仍遵守恢复锁，绝不自动续跑上次机器人流程。
- Watchdog 独立 `Stop()` 只是补充保护，不能替代物理急停、安全门和安全 PLC。
- Remote API 服务与 Runtime 解耦，独立崩溃重启，不影响机器人运动控制。

### 6.2 安装步骤

前置条件：

- Windows 10/11 x64
- 每台设备重新创建 `.venv` 并安装 `requirements.txt`，**不要复制其他设备的虚拟环境**
- 确认 `dobot_move\windows_service\vendor\WinSW-x64.exe` 存在且 SHA256 匹配
- 确认模型文件、`user_data/config.json`、流程文件和标定参数已就位
- 确认 502、8000、8765、8766、29999、30004 端口未被占用
- 使用管理员 PowerShell

固定目录部署（推荐 `C:\DobotRuntime`）：

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
  -ProjectRoot C:\Users\13571\Desktop\Dobot-VGS-RS400 `
  -PythonExe C:\Users\13571\Desktop\Dobot-VGS-RS400\.venv\Scripts\python.exe `
  -CreateServiceUser
```

启用防火墙规则创建（可选，允许外部访问 Modbus 和 Remote API）：

```powershell
powershell -ExecutionPolicy Bypass `
  -File .\scripts\install_windows_services.ps1 `
  -ProjectRoot C:\Users\13571\Desktop\Dobot-VGS-RS400 `
  -CreateServiceUser `
  -ConfigureFirewall
```

`-ConfigureFirewall` 会创建 "Dobot Modbus"（TCP 502）和 "Dobot Remote API"（TCP 8000）两条入站规则。不启用时需手动配置防火墙。

安装脚本会：

1. 检查管理员权限、Python 导入和 WinSW 哈希。
2. 创建或验证 `DobotRuntimeSvc`，自动生成强密码（-CreateServiceUser 时）或通过安全凭据窗口读取密码。
3. 生成 `runtime_ipc.token` 并限制其文件权限。
4. 备份、停止并禁用旧任务计划，但不删除任务定义。
5. 安装并启动 Runtime、Watchdog 和 Remote API 三个服务。
6. 检查服务状态、健康文件和带认证的 IPC ping。
7. 验证失败时卸载服务并恢复旧任务原有的启用和运行状态。

### 6.3 服务检查命令

```powershell
# 运行安装校验脚本
powershell -ExecutionPolicy Bypass `
  -File .\scripts\test_windows_services.ps1 `
  -ProjectRoot C:\DobotRuntime

# 查看服务状态
Get-Service DobotRuntimeService
Get-Service DobotRuntimeWatchdog
Get-Service DobotRemoteApiService

# 查看健康状态文件
Get-Content .\runtime_health.json

# 查看运行日志
Get-Content .\logs\runtime.log -Tail 100
Get-Content .\logs\runtime_watchdog.log -Tail 100
```

### 6.4 卸载和回滚

仅卸载服务（保留任务计划定义）：

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

卸载顺序固定为 **先 Remote API、再 Watchdog、后 Runtime**，避免 Watchdog 在 Runtime 正常停止期间将其重新启动。

完整服务部署、卸载和回滚说明详见 [docs/windows_service.md](docs/windows_service.md)。

---

## 7. Remote API

Remote REST API 是供外部平板/MES 只读查询机器人状态的独立 HTTP 服务，**不暴露任何控制命令**，不影响 Runtime/Watchdog/GUI。

> **WinSW 服务模式**：当通过 `install_windows_services.ps1` 安装后，`DobotRemoteApiService` 会随系统自动启动，监听 8000 端口，无需手动运行 `python -m dobot_move.remote_api`。服务崩溃后 WinSW 会在 10 秒后自动重启。

### 7.1 启动命令

```powershell
# 方式一：根目录兼容入口
python remote_api.py

# 方式二：模块入口（推荐）
python -m dobot_move.remote_api --host 0.0.0.0 --port 8000
```

### 7.2 端点列表

| 端点 | 方法 | 认证 | 说明 |
|------|------|------|------|
| `/api/v1/health` | GET | 免认证 | 服务自身健康检查 |
| `/api/v1/status` | GET | 需要 | 机器人综合状态（连接、模式、位姿、报警） |
| `/api/v1/feedback/all` | GET | 需要 | 30004 反馈端口完整快照 |
| `/api/v1/modbus/registers` | GET | 需要 | Modbus 寄存器读取（通过本地 Modbus 客户端读 `127.0.0.1:502`） |
| `/api/v1/production/status` | GET | 需要 | 生产状态（通过读取 `user_data/remote_api_health.json` 间接获取） |

旧路径 `/api/status` 等返回 **301 重定向** 到 v1（保留 query string）。

调用示例：

```powershell
# 健康检查（免认证）
Invoke-WebRequest http://localhost:8000/api/v1/health

# 带 Token 的状态查询
$headers = @{ "Authorization" = "Bearer YOUR_TOKEN_HERE" }
Invoke-WebRequest http://localhost:8000/api/v1/status -Headers $headers
```

### 7.3 Token 认证

- 请求头格式：`Authorization: Bearer <token>`
- `token` 配置在 `user_data/config.json` 的 `remote_api.token` 字段。
- token 为空时 **禁用认证**（仅限内网调试，生产环境必须配置非空 token）。
- token 不进入日志和 `runtime_publication.json`。

### 7.4 CORS 说明

- 默认开启 CORS：`Access-Control-Allow-Origin: *`，允许外部平板/MES 浏览器直接调用。
- 通过 `remote_api.allowed_ips` 配置 IP 白名单（空数组表示不限制）。
- 零新第三方依赖，仅使用标准库 `ThreadingHTTPServer`。

### 7.5 与 Runtime 的解耦关系

- Remote API 通过 30004 反馈端口（Dobot CR 支持多客户端并发）获取机器人数据。
- 通过 Modbus TCP 客户端读取 `localhost:502`（Runtime 的 Modbus 服务）获取寄存器。
- 生产状态通过读取 `user_data/remote_api_health.json` 间接获取（Runtime 写入 `runtime_health.json`，remote_api 写入自己的健康文件）。
- 不重复开服务，不占用 502 端口。

配置示例见 [config.example.json](dobot_move/config/config.example.json) 的 `remote_api` 块。

---

## 8. 配置参考

### 8.1 config.json 完整字段表

| 字段路径 | 类型 | 默认值 | 说明 |
|----------|------|--------|------|
| `robot_ip` | string | `"192.168.5.1"` | 机器人 IP 地址 |
| `modbus_port` | int | `502` | Modbus TCP 服务器端口 |
| `modbus_slave_id` | int | `5` | Modbus 从站地址 |
| `photo_position` | float[6] | `[0,0,0,0,0,0]` | 拍照位 `[x,y,z,rx,ry,rz]`（mm/deg） |
| `target_offset` | float[3] | `[0,0,0]` | 抓取目标偏移 `[dx,dy,dz]`（mm） |
| `camera.models.D435i` | string | `""` | D435i ONNX 模型绝对路径 |
| `camera.models.D405` | string | `""` | D405 ONNX 模型绝对路径 |
| `calibration.D435i.cam_to_flange_pose` | float[6] | `[0,0,0,0,0,0]` | D435i 相机相对法兰的位姿 |
| `calibration.D405.cam_to_flange_pose` | float[6] | `[0,0,0,0,0,0]` | D405 相机相对法兰的位姿 |
| `points` | object | `{}` | 点位表（首次运行自动生成三个默认点位） |
| `user_index` | int | `0` | 用户坐标系索引 |
| `tool_index` | int | `0` | 工具坐标系索引 |
| `remote_api` | object | 见 8.4 | Remote API 配置块（缺失时使用默认值） |
| `runtime` | object | 见 9.2 | Runtime 运行配置块（可选） |

### 8.2 环境变量覆盖表

| 环境变量 | 覆盖字段 | 优先级 |
|----------|----------|--------|
| `DOBOT_ROBOT_IP` | `robot_ip` | 环境变量 > config.json > 默认值 |
| `DOBOT_MODBUS_PORT` | `modbus_port` | 同上 |
| `DOBOT_MODBUS_SLAVE` | `modbus_slave_id` | 同上 |
| `DOBOT_D435I_MODEL` | `camera.models.D435i` | 同上 |
| `DOBOT_D405_MODEL` | `camera.models.D405` | 同上 |
| `DOBOT_REMOTE_API_PORT` | `remote_api.port` | 同上 |

### 8.3 性能参数表（`performance` 配置块默认值）

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `flow_wait_poll_interval` | `0.05` | 流程等待轮询间隔（秒） |
| `robot_mode_dashboard_fallback_interval` | `1.0` | RobotMode Dashboard 查询冷却间隔（秒） |
| `pose_cache_max_age` | `0.3` | 位姿缓存最大年龄（秒） |
| `motion_settle_time` | `0.15` | 运动命令后最小稳定时间（秒） |
| `motion_done_speed_threshold` | `1.0` | 线速度归零阈值（mm/s） |
| `motion_done_rotation_speed_threshold` | `1.0` | 角速度归零阈值（°/s） |
| `motion_done_pose_tolerance` | `2.0` | 位姿到位容差（mm） |
| `motion_done_rotation_tolerance` | `2.0` | 旋转到位容差（°） |
| `motion_done_stable_samples` | `3` | 连续稳定采样次数 |
| `motion_done_use_feedback` | `true` | 是否使用 30004 反馈辅助判定 |
| `feedback_stale_fail_age` | `2.0` | 反馈断流失败判定时间（秒） |

### 8.4 Remote API 配置表

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `host` | string | `"0.0.0.0"` | HTTP 监听地址 |
| `port` | int | `8000` | HTTP 监听端口 |
| `token` | string | `""` | Bearer Token，为空禁用认证 |
| `feedback_port` | int | `30004` | 30004 反馈端口 |
| `feedback_reconnect_interval_s` | float | `2.0` | 反馈断流后重连间隔（秒） |
| `feedback_stale_ok_s` | float | `0.3` | 反馈新鲜阈值（秒） |
| `feedback_stale_fail_s` | float | `2.0` | 反馈失效阈值（秒） |
| `modbus_client_timeout_s` | float | `3.0` | Modbus 客户端读取超时（秒） |
| `modbus_host` | string | `"127.0.0.1"` | Modbus 客户端目标主机 |
| `allowed_ips` | array | `[]` | IP 白名单（空数组不限制） |

### 8.5 Runtime 可选配置（`runtime` 块）

```json
{
  "runtime": {
    "ipc_host": "127.0.0.1",
    "ipc_port": 8765,
    "ipc_stop_port": 8766,
    "ipc_command_timeout_s": 5.0,
    "ipc_token_path": "user_data/runtime_ipc.token",
    "health_path": "user_data/runtime_health.json",
    "service_stop_marker_path": "user_data/runtime_service_stopped.json",
    "startup_connect_timeout_s": 5.0,
    "camera_retry_interval_s": 10.0
  }
}
```

| 字段 | 默认值 | 说明 |
|------|--------|------|
| ipc_host | 127.0.0.1 | IPC 服务器监听地址 |
| ipc_port | 8765 | IPC 主通道端口 |
| ipc_stop_port | 8766 | 安全停止通道端口 |
| ipc_command_timeout_s | 5.0 | IPC 命令超时（秒） |
| ipc_token_path | user_data/runtime_ipc.token | IPC 认证 token 路径 |
| health_path | user_data/runtime_health.json | 健康状态文件路径 |
| service_stop_marker_path | user_data/runtime_service_stopped.json | 服务停止标记路径 |

### 8.6 手眼标定数据格式

```json
{
  "cam_to_flange_pose": [x, y, z, rx, ry, rz]
}
```

- 单位：位置 `mm`，姿态 `deg`
- 欧拉角约定：ZYX 旋转顺序
- 计算方式：直接 `pose2matrix(cam_to_flange_pose)` 转为 4x4 齐次矩阵
- 旧版双位姿格式（`tool_base_calib_pose` + `cam_base_calib_pose`）会自动迁移，无需手动转换
- 标定误差应 < 5 mm

### 8.7 点位表数据格式

```json
{
  "points": {
    "initial_point": {
      "coords": [x, y, z, rx, ry, rz],
      "is_relative": false,
      "relative_to": null,
      "offset": [0, 0, 0, 0, 0, 0],
      "is_default": true
    },
    "d435i": { "..." },
    "d405": { "..." }
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `coords` | float[6] | 绝对坐标（mm, deg） |
| `is_relative` | bool | 是否为相对点位 |
| `relative_to` | string/null | 参考点名称（仅相对点位） |
| `offset` | float[6] | 相对偏移 |
| `is_default` | bool | 系统默认点位（不可删除） |

两个默认点位 `d435i`（D435i 识别目标中心）和 `d405`（D405 识别目标中心）由视觉系统自动更新。

---

## 9. 升级维护

### 9.1 升级步骤

用户升级只需用新版 `dobot_move/` 文件夹覆盖旧版即可，`user_data/` 中的配置和数据完全保留：

```powershell
# 1. 备份 user_data/（强烈建议）
Copy-Item .\user_data .\user_data_backup_$(Get-Date -Format "yyyyMMdd") -Recurse

# 2. 停止 Runtime 服务（生产环境）
Stop-Service DobotRuntimeService
Stop-Service DobotRuntimeWatchdog

# 3. 用新版 dobot_move/ 覆盖旧版
# （手动复制新版 dobot_move/ 到项目根目录，覆盖旧文件）

# 4. 重启服务
Start-Service DobotRuntimeWatchdog
Start-Service DobotRuntimeService

# 5. 运行配置预检
python run.py --check-config
```

### 9.2 自动迁移机制

首次升级时，`config_manager.py` 会自动检测旧位置的数据并迁移到 `user_data/`，用户无感知：

- 旧位置 `dobot_move/config.json` → 新位置 `user_data/config.json`
- 旧位置 `dobot_move/gui_mixins/grasp_flow_modules.json` → 新位置 `user_data/grasp_flow_modules.json`
- 其他旧位置运行时数据同样迁移

迁移是幂等的，已存在的 `user_data/` 文件不会被覆盖。

### 9.3 数据备份建议

| 备份对象 | 路径 | 频率 | 说明 |
|----------|------|------|------|
| `user_data/` 整个目录 | `user_data/` | 每次升级前 + 每周 | 包含所有配置、标定、流程、日志 |
| `config.json` | `user_data/config.json` | 标定完成后 | 关键的标定数据 |
| `grasp_flow_modules.json` | `user_data/grasp_flow_modules.json` | 流程修改后 | 用户编辑的流程库 |
| ONNX 模型文件 | 外部路径 | 模型更新后 | `*.onnx` 已被 Git 忽略，需单独保管 |

```powershell
# 一键备份 user_data
$backup = "user_data_backup_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
Copy-Item .\user_data .\$backup -Recurse
Write-Host "Backup created: $backup"
```

### 9.4 日志文件位置和查看方法

| 日志文件 | 路径 | 说明 |
|----------|------|------|
| Runtime 运行日志 | `user_data/logs/runtime.log` | 后台运行日志，自动滚动 |
| Watchdog 日志 | `user_data/logs/runtime_watchdog.log` | 独立看门狗日志 |
| 报警历史 | `user_data/alarm_history.json` | 运行时报警记录 |

```powershell
# 查看最近 100 行 Runtime 日志
Get-Content .\user_data\logs\runtime.log -Tail 100

# 实时跟踪日志
Get-Content .\user_data\logs\runtime.log -Wait

# 查看报警历史
Get-Content .\user_data\alarm_history.json
```

### 9.5 健康状态文件说明

Runtime 每秒更新 `runtime_health.json`，关键字段：

| 字段 | 说明 |
|------|------|
| `schema_version` | 健康文件结构版本，当前为 `2` |
| `boot_id` | 本次后台启动的唯一编号 |
| `runtime.state` | 状态：`STARTING/READY/RUNNING/WAITING_DELAY/DEGRADED/RECOVERY_REQUIRED/STOPPING` |
| `runtime.recovery_required` | 是否必须先执行 `40001=0` |
| `runtime.startup_errors` | 配置文件或流程文件启动校验错误 |
| `startup_connection.main_flow_id/main_flow_name` | 当前主流程 |
| `startup_connection.deadline_at_monotonic` | 本轮启动连接截止时间 |
| `startup_connection.required_cameras` | 主流程实际引用的相机 |
| `startup_connection.missing_devices` | 当前缺失的机器人或相机 |
| `startup_connection.deadline_elapsed` | 5 秒启动观察窗口是否结束 |
| `startup_connection.retrying` | 是否有设备连接任务正在后台执行 |
| `robot.feedback_age_s` | 距离最近反馈包的秒数 |
| `robot.feedback_thread_alive` | 30004 反馈线程是否存活 |
| `modbus.thread_alive` | Modbus 服务线程是否存活 |
| `flow.module_index/module_name` | 当前执行模块 |
| `flow.orphaned_flow` | 超时流程线程是否未能退出 |
| `process.thread_count/rss_mb` | 线程数和常驻内存 |
| `process.disk_free_mb` | 健康文件所在磁盘剩余空间 |

其他运行时文件：

| 文件 | 说明 |
|------|------|
| `runtime_state.json` | 原子保存的诊断状态，只用于判断是否异常退出 |
| `runtime_agent.lock` | 后台进程单实例锁 |
| `robot_control.lock` | GUI 与后台共享的机器人控制租约 |
| `runtime_watchdog_restarts.json` | 看门狗最近 10 分钟的重启记录 |
| `runtime_watchdog_lockout.json` | 重启次数超限后的人工恢复锁 |
| `runtime_ipc.token` | IPC 认证 token（仅服务模式） |

---

## 10. 故障排查

### 10.1 常见问题速查表

| 问题 | 可能原因 | 解决方案 |
|------|----------|----------|
| 机器人连接失败 | 机器人未上电；网段不一致；`robot_ip` 错误；Dashboard 端口被占 | 1. 确认机器人已开机且网络可达：`ping 192.168.1.50`<br>2. 检查 `user_data/config.json` 中 `robot_ip`<br>3. 确认 PC 与机器人同网段<br>4. 确认 29999 端口未被占用 |
| 相机连接失败 | 未安装 RealSense SDK；USB 连接松动；`pyrealsense2` 版本不匹配；多相机未指定序列号 | 1. 确认相机通过 USB 连接且 RealSense Viewer 中可识别<br>2. 安装 Intel RealSense SDK 2.0<br>3. 检查 `pyrealsense2` 版本与 SDK 匹配<br>4. 多相机场景需指定序列号 |
| YOLO 推理效果差 | 模型选择错误；光照强烈反光；模型输入尺寸不兼容 | 1. 主控制页确认 D435i、D405 各自选择了正确 `.onnx`（连接相机期间需先断开才能更换）<br>2. 检查光照，避免强烈反光<br>3. 新模型必须使用固定 NCHW 输入尺寸，并输出当前后处理支持的张量<br>4. 模型文件丢失或不兼容时会拒绝连接 |
| 手眼标定精度不足 | 标定点位姿记录错误；欧拉角顺序不一致；单次标定误差大 | 1. 确认标定板上工具点位姿记录准确<br>2. 检查欧拉角约定（本项目使用 ZYX 旋转顺序）<br>3. 建议多次标定取平均值<br>4. 标定误差应 < 5 mm |
| C++ 模块构建失败 | 缺少 CMake 3.15+；缺少 C++17 编译器；Windows 未装 VS Build Tools；pybind11 未装 | 1. 确认 CMake 3.15+ 和 C++17 编译器<br>2. Windows 需安装 Visual Studio Build Tools<br>3. `pip install pybind11 cmake`<br>4. 不构建 C++ 模块不影响使用——程序会自动回退到 Python |
| GPU 推理未启用 | 同时安装了 `onnxruntime` 和 `onnxruntime-gpu`；NVIDIA 驱动版本过低；cuDNN 子库缺失；Python 非 x64 | 1. `pip uninstall onnxruntime onnxruntime-gpu -y` 后重装 `onnxruntime-gpu[cuda,cudnn]`<br>2. 更新 NVIDIA 驱动至 >= 525.60.13<br>3. `python -c "import struct; print(struct.calcsize('P') * 8)"` 应输出 64<br>4. 详见 [docs/gpu_environment.md](docs/gpu_environment.md) |
| Modbus 通信失败 | 502 端口被占；防火墙拦截；`modbus_slave_id` 不匹配；多进程重复开服务 | 1. `netstat -ano \| findstr :502` 查找占用进程<br>2. 关闭占用 502 的进程或修改 `modbus_port`<br>3. 检查主站与从站 `slave_id` 一致<br>4. 确认未同时运行 GUI 和 Runtime（共享 `robot_control.lock`） |
| Runtime 崩溃恢复 | 上次未正常退出；`config.json` 损坏；机器人 IP/Modbus 端口无效 | 1. PLC 写 `40001=0` 解除恢复锁<br>2. 修复 `config.json` 后重写 `0` 触发再校验<br>3. 校验仍失败时恢复锁不会解除，需人工修复文件<br>4. 详见 [docs/runtime_agent.md](docs/runtime_agent.md) |

### 10.2 日志排查方法

```powershell
# 1. 查看 Runtime 最近 200 行日志
Get-Content .\user_data\logs\runtime.log -Tail 200

# 2. 实时跟踪 Runtime 日志（Ctrl+C 停止）
Get-Content .\user_data\logs\runtime.log -Wait

# 3. 过滤错误和警告
Select-String -Path .\user_data\logs\runtime.log -Pattern "ERROR|WARN|FAIL" | Select-Object -Last 50

# 4. 查看 Watchdog 日志
Get-Content .\user_data\logs\runtime_watchdog.log -Tail 100

# 5. 查看报警历史
Get-Content .\user_data\alarm_history.json
```

### 10.3 健康状态文件查看命令

```powershell
# 查看完整健康状态
Get-Content .\runtime_health.json

# 解析关键字段（PowerShell）
$health = Get-Content .\runtime_health.json | ConvertFrom-Json
Write-Host "Runtime state: $($health.runtime.state)"
Write-Host "Robot connected: $($health.robot.connected)"
Write-Host "Modbus running: $($health.modbus.is_running)"
Write-Host "Feedback age (s): $($health.robot.feedback_age_s)"
Write-Host "Missing devices: $($health.startup_connection.missing_devices)"

# 查看是否处于恢复状态
if ($health.runtime.recovery_required) {
    Write-Host "RECOVERY REQUIRED: 请先写 40001=0 解除恢复锁"
}

# 查看是否触发看门狗熔断
Test-Path .\runtime_watchdog_lockout.json
```

### 10.4 解除看门狗熔断

10 分钟内达到 3 次重启会生成 `runtime_watchdog_lockout.json` 并停止自动恢复：

```powershell
# 服务模式
Stop-Service DobotRuntimeService
Remove-Item .\runtime_watchdog_lockout.json -ErrorAction SilentlyContinue
Remove-Item .\runtime_watchdog_restarts.json -ErrorAction SilentlyContinue
Start-Service DobotRuntimeService

# 任务计划模式
Stop-ScheduledTask -TaskName DobotRuntimeAgent
Remove-Item .\runtime_watchdog_lockout.json -ErrorAction SilentlyContinue
Remove-Item .\runtime_watchdog_restarts.json -ErrorAction SilentlyContinue
Start-ScheduledTask -TaskName DobotRuntimeAgent
```

### 10.5 网络端口检查

```powershell
# 检查关键端口占用
netstat -ano | findstr ":502 "
netstat -ano | findstr ":8765 "
netstat -ano | findstr ":29999 "
netstat -ano | findstr ":30004 "
netstat -ano | findstr ":8000 "

# 测试机器人网络可达性
ping 192.168.1.50

# 测试 Dashboard 端口
Test-NetConnection -ComputerName 192.168.1.50 -Port 29999
```

### 10.6 设备验证清单

| 验证项 | 命令 | 预期结果 |
|--------|------|----------|
| Python 依赖完整性 | `python -c "import PySide6, numpy, cv2, pyrealsense2, onnxruntime; print('OK')"` | 输出 `OK` |
| RealSense 相机 | RealSense Viewer | 相机可识别并出流 |
| GPU 驱动 | `nvidia-smi` | 显示 GPU 和驱动版本 |
| GPU 推理启用 | 见 [2.3 GPU 验证](#23-gpu-可选环境配置精简版) | 输出包含 `CUDAExecutionProvider` |
| C++ 加速模块 | `python -c "import dobot_core; print('OK')"` | 输出 `OK` |
| 配置完整性 | `python run.py --check-config` | 预检通过 |
| 机器人网络 | `ping <robot_ip>` | 正常回包 |
| Runtime 健康 | `Get-Content .\runtime_health.json` | `runtime.state` 为 `READY` 或 `RUNNING` |
| Modbus 服务 | `Get-Content .\runtime_health.json` | `modbus.is_running=true` |
| 反馈线程 | `Get-Content .\runtime_health.json` | `robot.feedback_thread_alive=true` |

---

## 附录：深入阅读

| 主题 | 文档链接 |
|------|----------|
| Runtime 后台运行与异常恢复 | [docs/runtime_agent.md](docs/runtime_agent.md) |
| WinSW 服务部署详解 | [docs/windows_service.md](docs/windows_service.md) |
| GPU 环境完整部署指南 | [docs/gpu_environment.md](docs/gpu_environment.md) |
| C++ 加速模块构建与接口 | [docs/cpp_acceleration.md](docs/cpp_acceleration.md) |
| 开发工作流 | [docs/dev_workflow.md](docs/dev_workflow.md) |
| 项目总览 | [README.md](README.md) |
| 配置模板 | [dobot_move/config/config.example.json](dobot_move/config/config.example.json) |
