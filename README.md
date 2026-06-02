# Dobot Move Python — 越疆机械臂视觉定位控制系统

## 项目简介
基于 Python + PyQt6 的越疆 CR5 机械臂视觉定位与控制系统。集成双 RealSense 深度相机（D435i + D405）、YOLO11s-seg 实例分割与掩码几何中心识别、ByteTrack 目标跟踪、3D 卡尔曼滤波、手眼标定、视觉伺服和力控圆弧等功能，实现从目标识别到精准定位的全自动化流程。

核心特性：
- 双相机协同：D435i 粗定位 + D405 精识别（掩码几何中心）
- D435i 低帧率实时识别（5fps），持续跟踪目标位置
- YOLO11s-seg 实例分割 + ByteTrack 多目标跟踪 + 3D 卡尔曼滤波
- 手眼标定：支持 D435i/D405 双相机独立标定
- 视觉伺服：迭代式接近目标，自适应增益，收敛阈值 2mm
- 力控圆弧：ArcTrajectoryPlanner + ForceFeedbackMonitor + ForceArcController
- Modbus TCP 双向通信：PC 作为 Master/Server
- C++ 加速模块（可选）：dobot_core pybind11 模块加速视觉后处理和坐标变换

## 系统架构

```
┌─────────────────────────────────────────────────┐
│                   GUI (PyQt6)                    │
│           DobotMainWindow + 7 Mixins             │
├─────────┬──────────┬──────────┬─────────────────┤
│ 机器人   │  视觉     │  力控     │   Modbus        │
│ 控制器   │  系统     │  圆弧     │   通信          │
├─────────┼──────────┼──────────┼─────────────────┤
│DobotApi │VisionSys │ForceArc  │ ModbusServer    │
│Dashboard│ +Tracker │+FBMonitor│ ModbusClient    │
│Feedback │ +Kalman3D│+ArcPlanner│                │
├─────────┴──────────┴──────────┴─────────────────┤
│          dobot_core (C++ pybind11, 可选)          │
│     transforms / nms / yolo (后处理加速)          │
└─────────────────────────────────────────────────┘
```

### 核心模块

| 模块 | 文件 | 职责 |
|------|------|------|
| 主界面 | `gui_app.py` | PyQt6 主窗口，7 个 Mixin 组合 |
| 机器人控制器 | `robot_controller.py` | 运动控制、状态管理、Modbus 集成 |
| 通信协议 | `dobot_api.py` | TCP/IP Dashboard (29999) + Feedback (30004) |
| 视觉系统 | `vision_system.py` | YOLO 推理、目标检测、3D 定位 |
| 目标跟踪 | `tracker.py` | ByteTrack 多目标跟踪 |
| 3D 滤波 | `kalman_filter_3d.py` | 6 状态 3D 卡尔曼滤波 |
| 深度处理 | `depth_processor.py` | 4 级 RealSense 深度滤波链 |
| 手眼标定 | `hand_eye_calib.py` | 手眼标定矩阵管理 |
| 坐标变换 | `transform_utils.py` | euler2rot / pose2matrix |
| 视觉伺服 | `visual_servo_controller.py` | 迭代式视觉伺服控制 |
| 力控圆弧 | `force_arc_controller.py` | 力控 + 圆弧轨迹联合控制 |
| 力反馈 | `force_feedback_monitor.py` | 力传感器监控线程 |
| 圆弧规划 | `arc_trajectory_planner.py` | 圆弧路点生成 |
| 电池监控 | `battery_monitor.py` | CAN 总线电池监控 |
| Modbus 服务 | `modbus_server.py` | Modbus TCP Server |
| Modbus 客户端 | `modbus_client.py` | Modbus TCP Client (小车) |
| 配置管理 | `config_manager.py` | JSON 配置读写 |
| 工作线程 | `workers.py` | 设备初始化、状态更新等后台线程 |
| 实时反馈 | `realtime_feedback_dialog.py` | 实时位姿/力反馈弹窗 |
| 日志配置 | `logging_config.py` | 统一日志格式 |
| C++ 核心 | `cpp_core/` | pybind11 加速模块 |

## 硬件要求

| 设备 | 型号 | 说明 |
|------|------|------|
| 机械臂 | 越疆 CR5 / CR10 / CRA 系列 | TCP/IP 协议控制 |
| 中距相机 | Intel RealSense D435i | 粗定位，深度 0.5-2.2m |
| 近距相机 | Intel RealSense D405 | 精识别，深度 0.07-0.8m |
| 力传感器 | 机械臂内置 6 轴力传感器 | 越疆 FT 系列力传感器 |
| 网络 | 以太网 | 机器人 IP 默认 192.168.1.50 |

## 环境安装

### 1. Python 环境

要求 Python 3.10+（推荐 3.12），建议使用虚拟环境：

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# Linux
source venv/bin/activate
```

### 2. 安装 Python 依赖

```bash
pip install -r requirements.txt
```

主要依赖包括：
- `PyQt6` — GUI 框架
- `numpy` — 数值计算
- `opencv-python` — 图像处理
- `pyrealsense2` — RealSense 相机 SDK
- `onnxruntime` — ONNX 模型推理
- `pymodbus` — Modbus TCP 通信
- `python-can` — CAN 总线电池监控
- `scipy` — 匈牙利算法（目标跟踪）

### 3. 编译 C++ 加速模块（可选）

C++ 模块可将视觉后处理和坐标变换加速 5-20 倍。不编译时程序自动回退到纯 Python 实现。

**前置依赖：**
- CMake 3.15+
- C++17 编译器（MSVC / GCC / Clang）
- pybind11

```bash
pip install pybind11 cmake
python build_cpp.py
```

编译成功后会在项目根目录生成 `dobot_core.cp3XX-win_amd64.pyd`（Windows）或 `dobot_core.cpython-3XX-linux-x86_64.so`（Linux）。

### 4. 验证安装

```bash
# 验证 Python 依赖
python -c "import PyQt6, numpy, cv2, pyrealsense2, onnxruntime; print('Python 依赖 OK')"

# 验证 C++ 模块（可选）
python -c "import dobot_core; print('C++ 模块 OK:', dir(dobot_core))"
```

## 配置说明

### config.json

配置文件位于 `dobot_move/config.json`，主要字段：

| 字段 | 类型 | 说明 | 示例 |
|------|------|------|------|
| `robot_ip` | string | 机器人 IP 地址 | `"192.168.1.50"` |
| `photo_position` | float[6] | 拍照位置 (x,y,z,rx,ry,rz) mm/deg | `[900.98, -403.82, 166.76, -83.92, 1.30, -89.06]` |
| `target_offset` | float[3] | 目标偏移 (dx,dy,dz) mm | `[0, 0, 0]` |
| `calibration.D435i` | object | D435i 手眼标定参数 | 见下方 |
| `calibration.D405` | object | D405 手眼标定参数 | 见下方 |
| `points` | object | 点位表 | 见下方 |
| `cart_ip` | string | 小车 IP 地址 | `"192.168.5.2"` |
| `cart_port` | int | 小车 Modbus 端口 | `502` |
| `modbus_port` | int | 本机 Modbus 服务端口 | `502` |

#### 手眼标定参数

每个相机的标定数据包含两个字段：

```json
{
  "tool_base_calib_pose": [x, y, z, rx, ry, rz],
  "cam_base_calib_pose": [x, y, z, rx, ry, rz]
}
```

- `tool_base_calib_pose`：标定板上工具点相对于基座的位姿
- `cam_base_calib_pose`：相机原点相对于基座的位姿

系统根据这两个位姿计算手眼标定矩阵 `T_cam2gripper = inv(T_tool2base) @ T_cam2base`。

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

| 字段 | 说明 |
|------|------|
| `coords` | 绝对坐标 (mm, deg) |
| `is_relative` | 是否为相对点位 |
| `relative_to` | 基准点位名称（相对点位时） |
| `offset` | 相对偏移量 |
| `is_default` | 系统默认点位（不可删除） |

系统预置两个默认点位：`d435i`（D435i 识别目标中心）和 `d405`（D405 识别目标中心），由视觉系统自动更新。

### 相机序列号

如果连接了多台 RealSense 相机，需要在代码中指定序列号。在 `vision_system.py` 初始化时传入 `serial_number` 参数，或在 GUI 中配置。

## 运行方式

### 启动 GUI 程序

```bash
cd dobot_move
python gui_app.py
```

### 首次使用流程

1. **连接机器人**：在 GUI 中输入机器人 IP，点击"连接"
2. **使能机器人**：连接成功后点击"使能"
3. **手眼标定**（如需重新标定）：
   - 切换到"手眼标定"选项卡
   - 输入标定板上工具点位和相机原点位姿
   - 点击"计算"生成标定矩阵
4. **连接相机**：点击"连接相机"，选择 D435i 或 D405
5. **测试视觉**：点击"相机测试"确认检测效果
6. **执行抓取**：在"抓取流程"选项卡中启动自动抓取

### D435i 低帧率实时识别

在视觉选项卡中，提供 D435i 低帧率（5fps）持续识别功能：

1. 连接 D435i 相机
2. 点击"D435i 低帧率识别"区域的"启动"按钮
3. 系统以 5fps 频率持续检测目标，实时更新 `d435i` 点位坐标
4. GUI 显示当前相机坐标、末端坐标、基座坐标
5. 点击"停止"按钮关闭识别

此功能适用于需要实时跟踪目标位置的场景。

### 抓取流程

完整抓取流程如下：

```
拍照位置 → D435i 粗识别 → 移动到 D435i 目标上方
→ 视觉伺服接近 → D405 精识别（掩码几何中心）
→ 计算目标点 → 移动到目标位置
→ 力控圆弧（可选） → 抬升 → 放置
```

## C++ 加速模块

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

### API 接口

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

### 回退机制

当 `dobot_core` 模块不可用时（未编译或平台不支持），程序自动回退到纯 Python 实现，功能不受影响。回退时无额外日志输出。

### 编译

```bash
pip install pybind11 cmake
python build_cpp.py
```

## 常见问题

### Q: 启动时报错 "缺少依赖 opencv-python"
```bash
pip install opencv-python
```

### Q: 相机连接失败
- 确认 RealSense 相机已通过 USB 连接
- 确认已安装 Intel RealSense SDK 2.0
- 检查 `pyrealsense2` 版本与 SDK 版本匹配
- 多相机时需指定序列号

### Q: 机器人连接失败
- 确认机器人和 PC 在同一网段
- 检查 `config.json` 中的 `robot_ip` 是否正确
- 确认机器人已开机且网络连通（`ping 192.168.1.50`）

### Q: C++ 模块编译失败
- 确认已安装 CMake 3.15+ 和 C++17 编译器
- Windows 需安装 Visual Studio Build Tools
- 不编译 C++ 模块不影响使用，程序会自动回退到 Python 实现

### Q: YOLO 模型检测效果差
- 确认 `best.onnx` 模型文件存在于 `dobot_move/` 目录
- 检查光照条件，避免强反光
- 如更换检测目标，需重新训练模型并替换 `best.onnx`
- 注意：新模型的类别数、mask 系数维度需与代码中的硬编码一致（1 类、32 mask_coeff）

### Q: 手眼标定精度不够
- 确认标定板上工具点位姿记录准确
- 检查欧拉角约定（本项目使用 ZYX 旋转顺序）
- 建议多次标定取平均
- 标定误差应 < 5mm
