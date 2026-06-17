# Dobot-VGS-RS400

基于 Intel RealSense D400 深度相机的越疆 CR 系列机械臂视觉引导系统

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux-green.svg)]()
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

基于 Python + PySide6 的越疆 CR 系列机械臂视觉定位控制系统。集成双 RealSense 深度相机（D435i + D405）、YOLO 实例分割、ByteTrack 目标跟踪、3D 卡尔曼滤波、手眼标定、视觉伺服和普通圆弧运动，实现从目标识别到精准定位的全自动化流程。

## 目录

- [功能特性](#功能特性)
- [快速开始](#快速开始)
- [架构](#架构)
- [使用方法](#使用方法)
- [配置](#配置)
- [C++ 加速](#c-加速)
- [常见问题](#常见问题)
- [许可证](#许可证)

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
- 🔄 **Modbus 异步执行** — 运动命令投递独立线程，cmd=9 急停走快速路径，200ms 周期不阻塞
- 📋 **连续相对路径编辑器** — 15 列段表、stop_each/queued 执行模式、段级参数覆盖
- 🧲 **TCP 力到位保护** — 运动中监控 ActualTCPForce，超过用户阈值即 Stop 当前运动并继续下一步
- 🎯 **saved_point 目标** — 直线运动支持已保存点位/相机识别坐标/初始位置三种目标
- 🔧 **统一 user/tool 参数** — Arc/MovJ/MovL/RelMovL/RelMovJ 从配置统一传入 user_index/tool_index
- 📦 **send_relative_command 封装** — queued 和单段相对移动复用统一命令发送、响应解析、command_id 追踪
- 🛡️ **ServoP 队列保护** — TCP 往返超伺服周期时自动跳帧降频，连续失败暂停重试
- 📝 **报警详情补全** — 异步获取 GetError 详情后自动追加到报警记录

## 快速开始

### 前置条件

- Python 3.10+（推荐 3.12）
- Intel RealSense SDK 2.0
- CMake 3.15+ 和 C++17 编译器（可选，用于 C++ 加速）

### 安装

```bash
# 1. 克隆仓库
git clone https://github.com/only-one-over/Dobot-VGS-RS400.git
cd Dobot-VGS-RS400

# 2. 创建虚拟环境并安装依赖
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux
source .venv/bin/activate
pip install -r requirements.txt

# 3. （可选）构建 C++ 加速模块
python build_cpp.py
```

> GPU 和 C++ 依赖为可选，已包含在 requirements.txt 中（用注释标注）。无 NVIDIA GPU 时自动回退 CPU 推理。GPU 环境详细部署指南见 [docs/gpu_environment.md](docs/gpu_environment.md)。

### 验证安装

```bash
# 基础依赖验证
python -c "import PySide6, numpy, cv2, pyrealsense2, onnxruntime; print('All dependencies OK')"

# GPU 真实启用验证（必须用 best.onnx 创建 session 确认 provider）
python -c "import onnxruntime as ort; s = ort.InferenceSession('dobot_move/best.onnx', providers=['CUDAExecutionProvider']); print('Active providers:', s.get_providers())"
# 通过标准：输出包含 CUDAExecutionProvider

# 可选：验证 C++ 模块
python -c "import dobot_core; print('C++ module OK:', dir(dobot_core))"
```

> 仅检查 `get_available_providers()` 不够——它只说明 onnxruntime 识别 CUDA provider，不代表实际能创建 CUDA session。正确验证方式是创建 InferenceSession 并确认 active provider。详见 [docs/gpu_environment.md](docs/gpu_environment.md)。

## 架构

```
┌─────────────────────────────────────────────────┐
│                   GUI (PySide6)                    │
│           DobotMainWindow + 7 Mixins             │
├─────────┬──────────┬──────────┬─────────────────┤
│  机器人   │  视觉     │  力控     │   Modbus        │
│  控制     │  系统     │  圆弧    │   通信          │
├─────────┼──────────┼──────────┼─────────────────┤
│DobotApi │VisionSys │ForceArc  │ ModbusServer    │
│Dashboard│ +Tracker │+FBMonitor│ ModbusClient    │
│Feedback │ +Kalman3D│+ArcPlanner│                │
├─────────┴──────────┴──────────┴─────────────────┤
│          dobot_core (C++ pybind11, 可选)           │
│     transforms / nms / yolo (后处理)               │
└─────────────────────────────────────────────────┘
```

### 核心模块

| 模块 | 文件 | 描述 |
|------|------|------|
| 主界面 | `gui_app.py` | PySide6 主窗口 + 7 个 Mixin |
| 机器人控制器 | `robot_controller.py` | 运动控制、状态管理 |
| 通信 | `dobot_api.py` | TCP/IP Dashboard (29999) + Feedback (30004) |
| 视觉系统 | `vision_system.py` | YOLO 推理、目标检测、3D 定位 |
| 目标跟踪 | `tracker.py` | ByteTrack 多目标跟踪 |
| 3D 滤波 | `kalman_filter_3d.py` | 6 状态 3D Kalman 滤波器 |
| 深度处理 | `depth_processor.py` | 4 级 RealSense 深度滤波链 |
| 手眼标定 | `hand_eye_calib.py` | 标定矩阵管理 |
| 坐标变换 | `transform_utils.py` | euler2rot / pose2matrix |
| 视觉伺服 | `visual_servo_controller.py` | 多线程视觉伺服控制 |
| 圆弧运动 | `arc_motion_controller.py` | 原生 Dobot Arc() 运动控制 | 力传感器监测线程 |
| 圆弧规划 | `arc_trajectory_planner.py` | 圆弧航点生成 | CAN 总线电池监测 |
| Modbus 服务器 | `modbus_server.py` | Modbus TCP 服务器 | Modbus TCP 客户端（小车） |
| 配置管理 | `config_manager.py` | JSON 配置读写 |
| 主控面板 | `main_control_panel.py` | 主控面板组件，基于信号通信 |
| 流程步骤列表 | `flow_step_list.py` | 流程步骤列表，拖拽排序+状态图标 |
| Qt 兼容层 | `qt_compat.py` | Qt 框架兼容层（PySide6） |
| 工作线程 | `workers.py` | 流程执行、FlowRunContext、模块验证、运动互斥锁 |
| C++ 核心 | `cpp_core/` | pybind11 加速模块 |

### 硬件要求

| 设备 | 型号 | 备注 |
|------|------|------|
| 机械臂 | Dobot CR5 / CR10 / CRA 系列 | TCP/IP 协议控制 |
| 中距相机 | Intel RealSense D435i | 粗定位，深度 0.5-2.2m |
| 近距相机 | Intel RealSense D405 | 精细识别，深度 0.07-0.8m |
| 力传感器 | 内置六轴力传感器 | Dobot FT 系列 |
| 网络 | 以太网 | 机器人 IP 默认 192.168.1.50 |

## 使用方法

### 启动应用

```bash
python -m dobot_move
```

生产现场 7x24 后台运行使用根目录脚本：

```powershell
python runtime_agent.py --startup-delay 20
```

开机自启动和状态排查见 [docs/runtime_agent.md](docs/runtime_agent.md)。

### 首次设置

1. **连接机器人** — 在界面中输入机器人 IP，点击"连接"
2. **使能机器人** — 连接成功后，点击"使能"
3. **手眼标定**（如需重新标定）：
   - 切换到"手眼标定"选项卡
   - 输入标定板上的工具点位姿和相机原点位姿
   - 点击"计算"生成标定矩阵
4. **连接相机** — 点击"连接相机"，选择 D435i 或 D405
5. **测试视觉** — 点击"相机测试"验证检测效果
6. **运行抓取流程** — 在"抓取流程"选项卡中启动自动抓取

### 抓取流程

```
拍照位 → D435i 粗识别 → 移动至 D435i 目标上方
→ 视觉伺服逼近 → D405 精细识别（掩码几何中心）
→ 计算目标点 → 移动至目标位置
→ 原生圆弧运动或相对移动（可选） → 抬升 → 放置
```

### 流程模块类型

| 类型 | 描述 |
|------|------|
| 直线运动 | MovJ/MovL 绝对运动，支持已保存点位/相机识别坐标/初始位置三种目标 |
| 圆弧运动 | 基于当前位姿生成圆弧路径，使用 ServoP 队列运动 |
| 相对移动 | 单次 RelMovL/RelMovJ 相对运动 |
| 连续相对路径 | 多段相对运动，15列段表编辑，stop_each/queued 两种执行模式 |
| 相机识别 | 多帧检测+置信度提前退出+缓存复用，D435i/D405 双相机 |
| 视觉伺服 | D405 闭环迭代逼近，自适应增益 |
| 关节旋转 | RelJointMovJ 关节空间旋转 |

### 运动完成判定

运动完成判定采用三级优先级机制：

1. **指令 ID 优先短路**（最高优先级）：当有 command_id 且 30004 反馈新鲜时，仅使用官方模式判定（`CurrentCommandId == command_id && RobotMode == 5`），判定完成后立即返回，跳过通用速度/状态判定
2. **30004 反馈状态机**（兜底）：仅在无 command_id 或 30004 反馈失效时使用。线速度+角速度归零 + 位姿到位（绝对运动）或 RunningStatus/RunQueuedCmd 完成（相对运动）+ 连续稳定 3 次
3. **Dashboard 兜底**：仅在 30004 反馈过期时按 1.0s 冷却间隔查询 RobotMode

安全守卫：最小稳定时间（0.15s）+ 必须见过运动状态才允许判定完成。

### 安全机制

- **急停独立连接**：通过独立临时 TCP 连接发送 EmergencyStop，避免主 Dashboard 连接锁阻塞
- **运动互斥锁**：流程和 Modbus 运动互斥执行，急停始终优先
- **急停立即停止**：急停触发时立即设置 stop_event，流程线程马上停止下发
- **反馈包校验**：30004 反馈 TestValue 严格校验，校验失败不更新缓存
- **连接状态分离**：Dashboard 连接状态和 30004 反馈健康状态分开显示
- **急停响应码校验**：独立连接返回响应码非 0 时走主连接兜底；空响应（超时）记录"已发送未确认"
- **急停按钮防抖**：急停按钮始终可点击，内部 500ms 时间戳防抖，不受命令执行状态禁用

## 配置

### config.json

将 `dobot_move/config.example.json` 复制为 `dobot_move/config.json`，并根据实际环境修改配置值。

配置文件位于 `dobot_move/config.json`：

| 字段 | 类型 | 描述 | 示例 |
|------|------|------|------|
| `robot_ip` | string | 机器人 IP 地址 | `"192.168.1.50"` |
| `photo_position` | float[6] | 拍照位 (x,y,z,rx,ry,rz) mm/deg | `[900.98, -403.82, 166.76, -83.92, 1.30, -89.06]` |
| `target_offset` | float[3] | 目标偏移 (dx,dy,dz) mm | `[0, 0, 0]` |
| `calibration.D435i` | object | D435i 手眼标定参数 | 见下方 |
| `calibration.D405` | object | D405 手眼标定参数 | 见下方 |
| `points` | object | 点位表 | 见下方 | 小车 IP 地址 | `"192.168.5.2"` | 小车 Modbus 端口 | `502` |
| `modbus_port` | int | 本地 Modbus 服务器端口 | `502` |
| `user_index` | int | 用户坐标系索引 | `0` |
| `tool_index` | int | 工具坐标系索引 | `0` |

#### 性能配置

| 字段 | 默认值 | 描述 |
|------|--------|------|
| `flow_wait_poll_interval` | 0.05 | 流程等待轮询间隔（秒） |
| `robot_mode_dashboard_fallback_interval` | 1.0 | RobotMode Dashboard 查询冷却间隔（秒） |
| `pose_cache_max_age` | 0.3 | 位姿缓存最大年龄（秒） |
| `motion_settle_time` | 0.15 | 运动命令后最小稳定时间（秒） |
| `motion_done_speed_threshold` | 1.0 | 线速度归零阈值（mm/s） |
| `motion_done_rotation_speed_threshold` | 1.0 | 角速度归零阈值（°/s） |
| `motion_done_pose_tolerance` | 2.0 | 位姿到位容差（mm） |
| `motion_done_rotation_tolerance` | 2.0 | 旋转到位容差（°） |
| `motion_done_stable_samples` | 3 | 连续稳定采样次数 |
| `motion_done_use_feedback` | true | 是否使用 30004 反馈辅助判定 |
| `feedback_stale_fail_age` | 2.0 | 反馈断流失败判定时间（秒） |

#### 手眼标定

每个相机的标定数据包含两个字段：

```json
{
  "tool_base_calib_pose": [x, y, z, rx, ry, rz],
  "cam_base_calib_pose": [x, y, z, rx, ry, rz]
}
```

- `tool_base_calib_pose`：标定板上工具点相对于基座的位姿
- `cam_base_calib_pose`：相机原点相对于基座的位姿

系统计算手眼矩阵：`T_cam2gripper = inv(T_tool2base) @ T_cam2base`

#### 点位表

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

| 字段 | 描述 |
|------|------|
| `coords` | 绝对坐标 (mm, deg) |
| `is_relative` | 是否为相对点位 |
| `relative_to` | 参考点名称（用于相对点位） |
| `offset` | 相对偏移 |
| `is_default` | 系统默认点位（不可删除） |

两个默认点位：`d435i`（D435i 识别目标中心）和 `d405`（D405 识别目标中心），由视觉系统自动更新。

## C++ 加速

### 模块结构

```
cpp_core/
├── CMakeLists.txt
├── include/dobot_core/
│   ├── transforms.h
│   ├── nms.h
│   └── yolo.h
└── src/
    ├── pybind_module.cpp
    ├── transforms.cpp
    ├── nms.cpp
    └── yolo.cpp
```

### API

```python
import dobot_core

# 坐标变换
R = dobot_core.transforms.euler2rot(rx, ry, rz, degree=True)  # → 3x3 numpy array
T = dobot_core.transforms.pose2matrix(x, y, z, rx, ry, rz)    # → 4x4 numpy array
p = dobot_core.transforms.transform_point(matrix, point)       # → 3D numpy array

# NMS
keep = dobot_core.nms.nms(boxes, scores, iou_threshold=0.5)   # → list[int]

# YOLOv8 后处理
dets = dobot_core.yolo.postprocess_yolov8(outputs, original_size, scale,
       offset, new_size, num_classes, conf_threshold, iou_threshold)
masks = dobot_core.yolo.process_mask(protos, masks_in, bboxes, shape,
        scale, offset, new_size, threshold)
```

### 回退

当 `dobot_core` 不可用时（未编译或不支持的平台），程序自动回退到纯 Python 实现，不影响任何功能。

### 构建

```bash
pip install pybind11 cmake
python build_cpp.py
```

## 常见问题

### 缺少依赖 opencv-python
```bash
pip install opencv-python
```

### 相机连接失败
- 确认 RealSense 相机已通过 USB 连接
- 确认已安装 Intel RealSense SDK 2.0
- 检查 `pyrealsense2` 版本是否与 SDK 版本匹配
- 使用多台相机时需指定序列号

### 机器人连接失败
- 确认机器人与 PC 在同一网段
- 检查 `config.json` 中的 `robot_ip`
- 确认机器人已开机且网络可达（`ping 192.168.1.50`）

### C++ 模块构建失败
- 确认已安装 CMake 3.15+ 和 C++17 编译器
- Windows 需要安装 Visual Studio Build Tools
- 不构建 C++ 模块不影响使用——程序会回退到 Python

### YOLO 推理（优先 GPU，自动回退 CPU）

本项目 YOLO 推理优先使用 NVIDIA GPU + CUDA，无 GPU 时自动回退 CPU 推理。CUDA runtime 和 cuDNN 随 pip 包自动安装到虚拟环境中。

```bash
# 确认 GPU 可用
nvidia-smi

# 验证 GPU 真实启用
python -c "import onnxruntime as ort; s = ort.InferenceSession('dobot_move/best.onnx', providers=['CUDAExecutionProvider']); print('Active providers:', s.get_providers())"
```

| 模式 | YOLO 推理耗时 | 视觉伺服闭环频率 | 安装要求 | 支持状态 |
|------|--------------|-----------------|----------|----------|
| GPU (CUDA) | ~20-50ms | ~10-15 Hz | NVIDIA GPU + 驱动 + onnxruntime-gpu[cuda,cudnn] | ✅ 推荐 |
| CPU | ~100-300ms | ~3-5 Hz | 无额外要求 | ✅ 支持（自动回退） |

> 完整 GPU 环境部署指南见 [docs/gpu_environment.md](docs/gpu_environment.md)。注意 `onnxruntime` 和 `onnxruntime-gpu` 不能同时安装，装了 GPU 版后 CPU 版需先卸载。连接相机后界面"推理"卡片会显示当前模式（GPU/CPU）。

### YOLO 模型检测效果差
- 确认 `dobot_move/` 目录下存在 `best.onnx` 模型文件
- 检查光照条件，避免强烈反光
- 如更换检测目标，需重新训练模型并替换 `best.onnx`
- 注意：新模型的类别数和掩码系数维度必须与硬编码值匹配（1 类，32 mask_coeff）

### 手眼标定精度不足
- 确认标定板上工具点位姿记录准确
- 检查欧拉角约定（本项目使用 ZYX 旋转顺序）
- 建议多次标定取平均值
- 标定误差应 < 5mm

## 许可证

本项目基于 MIT 许可证授权——详见 [LICENSE](LICENSE) 文件。
