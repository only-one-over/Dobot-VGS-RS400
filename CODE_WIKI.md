# Dobot-VGS-RS400 Code Wiki

> 基于 Intel RealSense D400 深度相机的越疆 CR 系列机械臂视觉引导系统完整技术文档

---

## 目录

1. [项目概述](#1-项目概述)
2. [整体架构](#2-整体架构)
3. [项目目录结构](#3-项目目录结构)
4. [入口与运行方式](#4-入口与运行方式)
5. [核心模块详解](#5-核心模块详解)
   - 5.1 [机器人控制模块 (robot)](#51-机器人控制模块-robot)
   - 5.2 [视觉感知模块 (vision)](#52-视觉感知模块-vision)
   - 5.3 [流程编排模块 (flow)](#53-流程编排模块-flow)
   - 5.4 [运行时模块 (runtime)](#54-运行时模块-runtime)
   - 5.5 [通信模块 (communication)](#55-通信模块-communication)
   - 5.6 [配置管理模块 (config)](#56-配置管理模块-config)
   - 5.7 [用户界面模块 (ui)](#57-用户界面模块-ui)
   - 5.8 [远程API模块 (remote_api)](#58-远程api模块-remote_api)
   - 5.9 [Windows服务模块 (windows_service)](#59-windows服务模块-windows_service)
   - 5.10 [C++加速模块 (cpp_core)](#510-c加速模块-cpp_core)
6. [关键类与函数索引](#6-关键类与函数索引)
7. [模块间依赖关系](#7-模块间依赖关系)
8. [数据流与控制流](#8-数据流与控制流)
9. [配置体系](#9-配置体系)
10. [安全机制](#10-安全机制)
11. [依赖清单](#11-依赖清单)
12. [测试体系](#12-测试体系)

---

## 1. 项目概述

**Dobot-VGS-RS400** 是一套基于 Python + PySide6 的越疆 CR 系列机械臂视觉定位控制系统。集成双 RealSense 深度相机（D435i + D405）、YOLO 实例分割、ByteTrack 多目标跟踪、3D 卡尔曼滤波、手眼标定、视觉伺服和原生圆弧运动，实现从目标识别到精准定位的全自动化抓取流程。

**核心能力：**

- 双相机协作：D435i 粗定位 + D405 精细识别
- YOLO 实例分割 + ByteTrack 多目标跟踪 + 3D Kalman 滤波
- 手眼标定（D435i/D405 双相机独立标定）
- 视觉伺服（自适应增益迭代逼近，2mm 收敛阈值）
- 原生圆弧运动（ArcTrajectoryPlanner + ArcMotionController）
- Modbus TCP 从站通信（供外部主站 PC 访问）
- C++ 可选加速（pybind11，5-20 倍加速，Python 自动回退）
- 7x24 后台加固（崩溃恢复锁、流程看门狗、反馈断流检测）
- Remote REST API（只读查询机器人状态/反馈/Modbus/生产状态）

**技术栈：** Python 3.10+, PySide6, ONNX Runtime (GPU/CPU), RealSense SDK 2.0, pymodbus 3.0+, pybind11/CMake (可选)

---

## 2. 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                      GUI (PySide6)                               │
│              DobotMainWindow + 7 Mixins                          │
├──────────┬──────────┬──────────┬──────────┬─────────────────────┤
│  机器人    │  视觉     │  力控/圆弧 │  Modbus   │  流程编排        │
│  控制      │  系统     │  运动     │  通信     │                  │
├──────────┼──────────┼──────────┼──────────┼─────────────────────┤
│DobotApi  │VisionSys │ArcMotion │ModbusServ│FlowExecutor       │
│Dashboard │+Tracker  │Controller│ModbusCli │FlowLibrary        │
│Feedback  │+Kalman3D │ArcPlanner│          │FlowResult         │
│+Safety   │+DepthProc│          │          │                   │
├──────────┴──────────┴──────────┴──────────┴─────────────────────┤
│                  Runtime (无 Qt 依赖，纯 Python)                  │
│    RuntimeAgent + ProductionStateMachine + RecoveryPolicy         │
│    RuntimeIpcServer + RuntimePublicationStore + Watchdog          │
├──────────────────────────────────────────────────────────────────┤
│              dobot_core (C++ pybind11, 可选)                       │
│         transforms / nms / yolo / depth_position                  │
└──────────────────────────────────────────────────────────────────┘
```

**分层原则：**

| 层级 | 职责 | Qt 依赖 |
|------|------|---------|
| UI 层 | 图形界面、用户交互 | PySide6 |
| 业务层 | 机器人控制、视觉感知、流程执行 | 无 |
| Runtime 层 | 后台无头运行、生产状态机、看门狗 | 无 |
| 加速层 | C++ pybind11 后处理加速 | 无 |

---

## 3. 项目目录结构

```
Dobot-VGS-RS400/
├── dobot_move/                     # 主代码包
│   ├── robot/                      #   机械臂控制
│   │   ├── robot_controller.py     #     机器人控制器（核心，~142KB）
│   │   ├── dobot_api.py            #     TCP/IP 协议 API（Dashboard + Feedback）
│   │   ├── visual_servo_controller.py  # 视觉伺服控制器
│   │   ├── arc_motion_controller.py    # 圆弧运动控制器
│   │   ├── arc_trajectory_planner.py   # 圆弧轨迹规划器
│   │   ├── gripper_controller.py   #     夹爪控制器（Modbus RTU）
│   │   ├── hand_eye_calib.py       #     手眼标定管理器
│   │   ├── transform_utils.py      #     坐标变换工具
│   │   ├── motion_safety.py        #     运动安全校验
│   │   └── robot_pose_buffer.py    #     位姿环形缓冲区
│   ├── vision/                     #   视觉感知
│   │   ├── vision_system.py        #     视觉系统主类（YOLO推理+3D定位）
│   │   ├── capture_worker.py       #     纯Python帧采集线程
│   │   ├── depth_processor.py      #     4级RealSense深度滤波链
│   │   ├── tracker.py              #     ByteTrack多目标跟踪
│   │   └── kalman_filter_3d.py     #     6状态3D Kalman滤波器
│   ├── flow/                       #   流程编排
│   │   ├── flow_executor.py        #     纯Python流程执行器
│   │   ├── flow_library.py         #     流程库（版本化存储+角色映射）
│   │   ├── flow_readiness.py       #     流程就绪性检查
│   │   ├── flow_result.py          #     结构化流程结果
│   │   ├── flow_step_list.py       #     流程步骤列表（拖拽排序）
│   │   ├── qt_workers.py           #     Qt适配（FlowThread包装）
│   │   ├── camera_test_worker.py   #     相机测试Worker
│   │   └── workers.py             #     向后兼容shim
│   ├── runtime/                    #   生产后端
│   │   ├── runtime_agent.py        #     后台代理（设备监督+流程看门狗）
│   │   ├── runtime_watchdog.py     #     外部看门狗（卡死检测+进程重启）
│   │   ├── runtime_resilience.py   #     韧性基础（状态持久化+单实例锁）
│   │   ├── runtime_ipc.py          #     跨进程IPC服务器
│   │   ├── runtime_contract.py     #     IPC命令契约校验
│   │   ├── runtime_publication.py  #     运行时状态发布
│   │   ├── production_state.py     #     生产状态机枚举
│   │   ├── production_context.py   #     生产任务上下文
│   │   ├── production_flow_router.py  #  流程路由（hook_type → flow_id）
│   │   ├── recovery_policy.py      #     恢复策略
│   │   ├── reset_strategy.py       #     复位策略
│   │   ├── runtime_vision_debug.py #     视觉调试
│   │   └── startup_connection.py   #     启动连接管理
│   ├── communication/              #   Modbus通信
│   │   ├── modbus_server.py        #     Modbus TCP服务器
│   │   └── modbus_utils.py         #     Modbus工具函数
│   ├── config/                     #   配置管理
│   │   ├── config_manager.py       #     配置管理器（JSON读写+防抖）
│   │   ├── alarm_history.py        #     报警历史记录
│   │   ├── config.example.json     #     配置示例
│   │   └── grasp_flow_modules.default.json  # 默认流程模板
│   ├── ui/                         #   界面层
│   │   ├── gui_app.py              #     主窗口（PySide6）
│   │   ├── main_control_panel.py   #     主控面板
│   │   ├── runtime_facade.py       #     Runtime外观模式
│   │   ├── gui_ipc_client.py       #     IPC客户端
│   │   ├── gui_runtime_status.py   #     Runtime状态显示
│   │   ├── gui_connection.py       #     GUI连接管理
│   │   ├── gui_debug_widgets.py    #     调试组件
│   │   ├── qt_compat.py            #     Qt框架兼容层
│   │   ├── ui_theme.py             #     UI主题
│   │   ├── logging_config.py       #     日志配置
│   │   ├── realtime_feedback_dialog.py  # 实时反馈对话框
│   │   ├── camera_test_worker.py   #     GUI相机测试Worker
│   │   └── mixins/                 #     功能混入
│   │       ├── robot_control_mixin.py   # 机器人控制Mixin
│   │       ├── vision_mixin.py         # 视觉Mixin
│   │       ├── modbus_mixin.py         # Modbus Mixin
│   │       ├── grasp_flow_mixin.py     # 抓取流程Mixin
│   │       ├── point_management_mixin.py  # 点位管理Mixin
│   │       └── startup_connection_mixin.py  # 启动连接Mixin
│   ├── remote_api/                 #   远程REST API
│   │   ├── app.py                  #     HTTP服务主应用
│   │   ├── handlers.py             #     端点处理器
│   │   ├── config.py               #     Remote API配置
│   │   ├── feedback_worker.py      #     30004反馈Worker
│   │   ├── modbus_client.py        #     Modbus客户端
│   │   └── __main__.py             #     模块入口
│   └── windows_service/            #   Windows服务封装
│       ├── service_config.py       #     服务配置
│       ├── generate_config.py      #     WinSW配置生成
│       └── preflight.py            #     预检脚本
├── cpp_core/                       # C++加速模块源码
│   ├── CMakeLists.txt              #   CMake构建脚本
│   ├── include/dobot_core/         #   C++头文件
│   │   ├── transforms.h            #     坐标变换
│   │   ├── nms.h                   #     NMS
│   │   ├── yolo.h                  #     YOLO后处理
│   │   └── depth_position.h        #     深度位置计算
│   └── src/                        #   C++源文件
│       ├── pybind_module.cpp       #     pybind11绑定
│       ├── transforms.cpp          #     坐标变换实现
│       ├── nms.cpp                 #     NMS实现
│       ├── yolo.cpp                #     YOLO后处理实现
│       └── depth_position.cpp      #     深度位置计算实现
├── tests/                          # 测试目录（60+测试文件）
├── scripts/                        # 部署脚本
│   ├── install_windows_services.ps1    # 安装WinSW服务
│   ├── uninstall_windows_services.ps1  # 卸载服务
│   ├── rollback_windows_services.ps1   # 回滚服务
│   └── test_windows_services.ps1       # 测试服务
├── docs/                           # 文档目录
├── user_data/                      # 用户数据（运行时生成，升级保留）
│   ├── config.json                 #   现场配置
│   ├── grasp_flow_modules.json     #   流程库
│   ├── alarm_history.json          #   报警记录
│   ├── runtime_*.json              #   运行时状态
│   └── logs/                       #   运行时日志
├── run.py                          # GUI入口
├── runtime_agent.py                # Runtime入口（兼容层）
├── runtime_watchdog.py             # Watchdog入口（兼容层）
├── remote_api.py                   # Remote API入口（兼容层）
├── build_cpp.py                    # C++模块构建脚本
└── requirements.txt                # Python依赖
```

---

## 4. 入口与运行方式

### 4.1 启动方式

| 方式 | 命令 | 用途 |
|------|------|------|
| GUI 模式 | `python run.py` 或 `python -m dobot_move` | 工程调试和参数编辑 |
| Runtime 模式 | `python runtime_agent.py` 或 `python -m dobot_move.runtime_agent` | 生产现场 7x24 后台运行 |
| Watchdog 模式 | `python runtime_watchdog.py` 或 `python -m dobot_move.runtime_watchdog` | 独立看门狗，检测 Runtime 卡死并重启 |
| Remote API | `python remote_api.py` 或 `python -m dobot_move.remote_api --host 0.0.0.0 --port 8000` | 外部只读 HTTP 查询服务 |
| C++ 构建 | `python build_cpp.py` | 编译可选 C++ 加速模块 |

### 4.2 入口文件说明

**`run.py`** → 调用 `dobot_move.ui.gui_app.main()`，启动 PySide6 GUI

**`runtime_agent.py`** → 调用 `dobot_move.runtime.runtime_agent.main()`，启动无头后台代理

**`runtime_watchdog.py`** → 调用 `dobot_move.runtime.runtime_watchdog.main()`，启动外部看门狗

**`remote_api.py`** → 调用 `dobot_move.remote_api.app.main()`，启动 HTTP 服务

**`build_cpp.py`** → 调用 CMake 构建 `cpp_core/` 并将编译产物复制到项目根目录

### 4.3 生产部署

推荐 **WinSW 双服务 + 独立 Runtime + localhost TCP IPC + 独立 GUI**：

- `DobotRuntimeService`：后台生产服务，独占机器人、D405/D435i、Modbus 502、流程执行和 IPC
- `DobotRuntimeWatchdog`：独立看门狗服务，检测 Runtime 卡死后先尝试安全 Stop()，再重启 Runtime
- GUI 只作为工程调试工具，由登录用户手动启动

---

## 5. 核心模块详解

### 5.1 机器人控制模块 (robot)

#### 5.1.1 DobotController (`robot_controller.py`)

**职责：** 机器人控制的核心枢纽，管理连接、使能、运动指令下发、反馈接收和急停。

| 类/方法 | 说明 |
|---------|------|
| `DobotController` | 机器人控制器主类 |
| `.__init__(robot_ip, enforce_single_instance)` | 初始化，可选跨进程控制租约 |
| `.connect()` | 连接 Dashboard (29999) + Feedback (30004) |
| `.enable_robot()` / `.disable_robot()` | 使能/下使能机器人 |
| `.movj(pose, v, ...)` / `.movl(pose, v, ...)` | 绝对关节/直线运动 |
| `.rel_movl(offsets, ...)` / `.rel_movj(offsets, ...)` | 相对直线/关节运动 |
| `.servo_p(pose, t, aheadtime, gain)` | ServoP 伺服运动 |
| `.arc(mid, end, ...)` | 圆弧运动 |
| `.emergency_stop()` | 急停（独立临时连接，避免主连接锁阻塞） |
| `.get_current_pose_from_feedback(max_age)` | 从 30004 反馈读取当前位姿 |
| `.get_motion_feedback_snapshot()` | 统一反馈快照（位姿+速度+队列+运行状态） |
| `.acquire_motion()` / `.release_motion()` | 运动互斥锁（流程和 Modbus 互斥） |
| `.get_motion_safety_state()` | 获取安全状态缓存 |
| `.pose_buffer` | `RobotPoseBuffer` 实例，位姿时间序列缓冲 |

**内部线程：**
- `FeedbackThread`：持续接收 30004 端口反馈，更新 `latest_pose` / `latest_robot_mode` / `latest_tcp_speed`

**运动完成判定三级优先级：**
1. 指令 ID 优先短路：`CurrentCommandId == command_id && RobotMode == 5`
2. 30004 反馈状态机：速度归零 + 位姿到位 + 连续稳定 3 次
3. Dashboard 兜底：按冷却间隔查询 RobotMode

#### 5.1.2 DobotApiDashboard / DobotApiFeedBack (`dobot_api.py`)

**职责：** 越疆 CR 系列机械臂 TCP/IP 协议的 Python 封装。

| 类 | 端口 | 说明 |
|----|------|------|
| `DobotApiDashboard` | 29999 | Dashboard 命令通道（连接/使能/运动/急停等） |
| `DobotApiFeedBack` | 30004 | 实时反馈通道（位姿/速度/力/状态等） |

**关键 Dashboard 方法：**
- `EnableRobot()` / `DisableRobot()` / `EmergencyStop()`
- `MovJ()` / `MovL()` / `RelMovL()` / `RelMovJ()` / `ServoP()` / `Arc()`
- `SpeedFactor()` / `RobotMode()` / `SpeedJ()` / `SpeedL()`
- `GetError()` / `ClearError()` / `ResetRobot()`
- `ConfigSafeStopEnable()` / `SpeedFactor()`

**30004 反馈结构体 (`MyType`)：** 包含 ToolVectorActual（TCP位姿）、TCPSpeedActual、ActualTCPForce、QActual（关节角度）、RobotMode、RunningStatus、ErrorStatus、CurrentCommandId 等字段。

#### 5.1.3 VisualServoController (`visual_servo_controller.py`)

**职责：** 多线程缓存式视觉伺服控制器，实现 10-20Hz 的上位机视觉闭环修正。

| 类 | 说明 |
|----|------|
| `TargetObservation` | 视觉目标观测数据结构（采集时刻/来源/置信度/预测年龄/协方差） |
| `TargetCache` | 线程安全目标缓存（target_base 主路径 + target_end fallback 路径） |
| `VisionThread` | 视觉检测线程：持续采集 + 低频 YOLO + 高频复用 + 3D 定位 |
| `ServoThread` | 伺服控制线程：固定周期读取缓存 + 计算误差 + ServoP 下发 |
| `VisualServoController` | 顶层控制器：协调 VisionThread + ServoThread |

**伺服控制流程：**
1. VisionThread 持续采集 D405 图像，低频 YOLO + 高频复用
2. 检测时刻按 `pose_buffer` 插值位姿预计算 `target_base`
3. ServoThread 固定周期读取 `target_base` + 当前位姿，计算误差
4. 自适应增益 + 自适应步长 + 安全钳位
5. ServoP 下发指令，收敛阈值判断

**安全门控：**
- `prediction_age_gate`：预测超期拒绝（默认 0.5s）
- `covariance_gate`：协方差 trace 超限拒绝（默认 100mm²）
- 预测时降速/限步长 + 连续预测软停止
- ServoP 队列延迟保护（超伺服周期自动跳帧降频）

#### 5.1.4 ArcMotionController (`arc_motion_controller.py`)

**职责：** 原生 Dobot Arc() 圆弧运动控制器。

| 方法 | 说明 |
|------|------|
| `.configure_arc(center, radius, start_angle, end_angle, ...)` | 配置圆弧参数并生成航点 |
| `.execute(set_speed)` | 执行 Dobot Arc() 命令（mid + end 两点） |

#### 5.1.5 ArcTrajectoryPlanner (`arc_trajectory_planner.py`)

**职责：** 圆弧航点生成器。

| 方法 | 说明 |
|------|------|
| `.generate_waypoints()` | 生成圆弧路径航点列表 [x,y,z,rx,ry,rz] |
| `.get_arc_info()` | 返回圆弧信息（中心/半径/弧长） |

支持 X/Y/Z 三轴旋转，Dobot Arc() 实际使用 3 个航点（首/中/末）。

#### 5.1.6 GripperController (`gripper_controller.py`)

**职责：** Modbus RTU 夹爪控制器。

| 方法 | 说明 |
|------|------|
| `.open()` | 开启夹爪（写入重启寄存器 + 速度 + 位置） |
| `.close()` | 关闭夹爪（写入位置 0） |
| `.read_position()` | 读取当前位置 |

通信参数：默认 COM6, 9600 baud, RTU 模式, slave_id=1。

#### 5.1.7 HandEyeCalibManager (`hand_eye_calib.py`)

**职责：** 手眼标定矩阵管理。

| 方法 | 说明 |
|------|------|
| `.get_matrix(camera_type)` | 获取指定相机的手眼矩阵 |
| `.set_matrix_from_poses(camera_type, cam_to_flange_pose)` | 由相机相对法兰位姿存储手眼矩阵 |
| `.set_matrix_direct(camera_type, matrix_4x4)` | 将 4x4 矩阵转为位姿后存储 |
| `.get_poses(camera_type)` | 返回 `{"cam_to_flange_pose": [...]}` |
| `.reset_to_default(camera_type)` | 重置为默认标定 |

手眼矩阵计算方式：`T_cam2gripper = pose2matrix(cam_to_flange_pose)`（旧版双位姿格式自动迁移）

#### 5.1.8 transform_utils (`transform_utils.py`)

**职责：** 坐标变换工具函数（C++ 优先，Python 回退）。

| 函数 | 说明 |
|------|------|
| `euler2rot(rx, ry, rz, degree)` | 欧拉角 → 3x3 旋转矩阵（ZYX） |
| `pose2matrix(x, y, z, rx, ry, rz)` | 位姿 → 4x4 齐次变换矩阵 |

#### 5.1.9 motion_safety (`motion_safety.py`)

**职责：** 统一的运动目标校验网关。

| 函数/类 | 说明 |
|---------|------|
| `MotionSafetyConfig` | 运动安全配置（工作空间边界/速度范围/偏移上限等） |
| `MotionSafetyState` | 运动安全状态（只读缓存：连接/使能/急停/错误） |
| `MotionValidationResult` | 校验结果（ok/code/message） |
| `validate_absolute_pose(controller, pose, ...)` | 绝对位姿校验（长度/NaN/工作空间/姿态角/机器人状态） |
| `validate_relative_delta(controller, offsets, ...)` | 相对运动偏移校验（偏移上限/投影终点校验） |
| `validate_servo_p_params(t, aheadtime, gain, servo_period)` | ServoP 参数 clamp |

#### 5.1.10 RobotPoseBuffer (`robot_pose_buffer.py`)

**职责：** 线程安全的位姿环形缓冲区，支持时间索引插值/外推。

| 方法 | 说明 |
|------|------|
| `.push(timestamp, pose)` | 写入位姿样本 |
| `.pose_at(t)` | 按时间查询位姿：区间插值 / 末尾外推 / 单样本退化 |

容量默认 200 样本，外推窗口 50ms。

---

### 5.2 视觉感知模块 (vision)

#### 5.2.1 VisionSystem (`vision_system.py`)

**职责：** 视觉系统主类，集成 YOLO 推理、深度计算、3D 定位、手眼标定和目标跟踪。

| 类/方法 | 说明 |
|---------|------|
| `FramePacket` | 线程安全帧数据包（seq/timestamp/color/depth/capture_time） |
| `VisionSystem` | 视觉系统主类 |
| `.connect_camera(serial_number, model_path, ...)` | 连接 RealSense 相机并加载 ONNX 模型 |
| `.capture_frames()` | 采集原始 rs.frame 对 |
| `.capture_numpy_packet(seq)` | 采集并返回 FramePacket |
| `.run_detection(color_image)` | YOLO 推理（YOLO11s-seg / YOLO26 端到端） |
| `.run_detection_tracked(color_image)` | YOLO 推理 + ByteTrack 跟踪 |
| `.calculate_object_position(depth, color, target)` | 深度计算 + 3D 定位（含 Kalman 平滑） |
| `.calculate_object_position_smoothed(...)` | 含平滑的3D定位（detection/prediction/smoothed 三种来源） |
| `.convert_to_end_coords(camera_coords)` | 相机坐标 → 末端坐标 |
| `.convert_to_base_coords(end_coords, pose)` | 末端坐标 → 基座坐标 |
| `.reset_tracking()` | 重置 ByteTrack 跟踪器 |

**GPU 推理：** 优先 CUDA，自动回退 CPU。GPU 模式 YOLO 推理 ~20-50ms，CPU 模式 ~100-300ms。

#### 5.2.2 BYTETracker (`tracker.py`)

**职责：** ByteTrack 多目标跟踪算法实现。

| 类/函数 | 说明 |
|---------|------|
| `iou_distance(atracks, btracks)` | 计算 IoU 距离矩阵 |
| `linear_assignment(cost_matrix, thresh)` | 匈牙利算法匹配 |
| `STrack` | 单目标跟踪轨迹（含 BBox Kalman 滤波） |
| `BYTETracker` | ByteTrack 主跟踪器 |

#### 5.2.3 KalmanFilter3D (`kalman_filter_3d.py`)

**职责：** 6 状态 3D Kalman 滤波器（位置 + 速度），恒速（CV）模型。

| 属性/方法 | 说明 |
|-----------|------|
| `.predict(dt)` | 预测步骤，累积 prediction_age |
| `.update(z, dt)` | 更新步骤，含 Mahalanobis 距离门控 |
| `.prediction_age` | 距上次成功更新的累积时间 |
| `.gate_threshold` | Mahalanobis 距离门限（默认 3.0） |
| `.prediction_gate` | 预测超时门限（默认 0.5s） |
| `.get_covariance()` | 获取 3x3 位置协方差矩阵 |

#### 5.2.4 DepthProcessor (`depth_processor.py`)

**职责：** 4 级 RealSense 深度滤波链。

| 滤波级 | 算法 | 说明 |
|--------|------|------|
| 1 | Decimation Filter | 降采样 |
| 2 | Spatial Filter | 空间平滑 + 孔洞填充 |
| 3 | Temporal Filter | 时间平滑 + 持久化 |
| 4 | Hole Filling Filter | 孔洞填充 |

#### 5.2.5 CaptureWorker (`capture_worker.py`)

**职责：** 纯 Python 帧采集线程（无 Qt 依赖），供 Runtime 使用。

| 类 | 说明 |
|----|------|
| `CaptureWorker(threading.Thread)` | 后台帧采集线程 |
| `.run()` | 持续采集 FramePacket |
| `.get_latest()` | 返回最新 (FramePacket, capture_ms) |

---

### 5.3 流程编排模块 (flow)

#### 5.3.1 FlowExecutor (`flow_executor.py`)

**职责：** 纯 Python 流程执行器，无 Qt 依赖，支持多种流程模块类型。

| 类/函数 | 说明 |
|---------|------|
| `FlowRunContext` | 流程运行上下文（run_id/start_time/stop_event/运动代数） |
| `normalize_module_type(module)` | 模块类型兼容（force_arc → arc_motion） |
| `build_force_guard(params)` | 构建力保护配置 |
| `coerce_float_vector(value, min_len, label)` | 向量类型转换 |

**支持的模块类型：**

| 类型 | 说明 |
|------|------|
| `move` | 直线运动（MovJ/MovL），支持 saved_point/camera/initial_position 三种目标 |
| `arc_motion` | 圆弧运动（Dobot Arc()） |
| `relative_move` | 相对移动（RelMovL/RelMovJ） |
| `continuous_relative_path` | 连续相对路径（多段，stop_each/queued） |
| `camera` | 相机识别（D435i/D405，多帧检测+置信度提前退出） |
| `visual_servo` | 视觉伺服（D405 闭环迭代逼近） |
| `joint_rotate` | 关节旋转（RelJointMovJ） |
| `delay` | 延时等待 |
| `gripper_open` / `gripper_close` | 夹爪开合 |
| `reset_robot` | 机器人复位 |

#### 5.3.2 FlowLibrary (`flow_library.py`)

**职责：** 版本化流程存储与选择。

| 类/常量 | 说明 |
|---------|------|
| `FLOW_SCHEMA_VERSION = 3` | 当前流程格式版本 |
| `DEFAULT_FLOW_ROLES` | 默认角色映射（low_hook/high_hook/error_recovery） |
| `FlowLibrary` | 流程库主类（CRUD + 角色映射 + v3 迁移） |
| `required_camera_types(modules)` | 分析流程所需相机类型 |

#### 5.3.3 FlowResult (`flow_result.py`)

**职责：** 结构化流程执行结果，供恢复策略决策。

| 类 | 说明 |
|----|------|
| `FailureKind` | 失败分类枚举（VISION_PROCESS/ROBOT/CAMERA/FLOW/PROTOCOL） |
| `FlowResult` | 结构化结果（success/code/message/failure_kind/recoverable） |
| `FlowResult.success_result()` | 构建成功结果 |
| `FlowResult.failure(...)` | 构建失败结果 |

#### 5.3.4 FlowReadiness (`flow_readiness.py`)

**职责：** 流程就绪性检查（设备连接/相机可用/流程有效）。

#### 5.3.5 FlowStepList (`flow_step_list.py`)

**职责：** 流程步骤列表组件，支持拖拽排序和实时状态图标（待执行/执行中/已完成/失败）。

#### 5.3.6 qt_workers (`qt_workers.py`)

**职责：** Qt 适配层，`FlowThread` 包装 `FlowExecutor`，回调桥接到 `pyqtSignal`。

---

### 5.4 运行时模块 (runtime)

#### 5.4.1 RuntimeAgent (`runtime_agent.py`)

**职责：** 后台无头运行代理，设备监督、流程看门狗、健康状态和崩溃恢复。**无 Qt 依赖**。

| 类/方法 | 说明 |
|---------|------|
| `RobotConnectionState` | 机器人连接状态枚举（DISCONNECTED/CONNECTING/CONNECTED） |
| `DobotRuntimeAgent` | Runtime 代理主类 |
| `.main()` | 入口函数（命令行参数解析 + 主循环） |

**核心功能：**
- 单实例锁（跨进程互斥）
- Modbus TCP 服务器启动
- 机器人 + 相机并发连接（5 秒观察窗口）
- 生产状态机（IDLE → STANDBY → STARTING → RUNNING → ...）
- 40001 命令协议（0=停止, 1=复位, 3=执行流程）
- 40004 hook_type 路由（0=低钩子, 1=高钩子）
- 流程看门狗（超时检测 + 安全停止）
- 反馈断流先停
- 崩溃恢复锁
- IPC 服务器（跨进程控制租约）
- 运行时状态发布

#### 5.4.2 RuntimeWatchdog (`runtime_watchdog.py`)

**职责：** 外部看门狗进程，检测 Runtime 卡死后先尝试安全 Stop()，再重启。

| 类 | 说明 |
|----|------|
| `WindowsServiceController` | Windows SCM 适配器（sc.exe 命令封装） |
| `.restart(timeout_s)` | 重启服务 |

**核心逻辑：**
1. 定期检查 Runtime 进程健康（心跳/状态文件）
2. 卡死检测 → 发送安全 Stop()
3. 通过 Windows Service Control Manager 重启 Runtime
4. 重启熔断（窗口期内连续重启限制）

#### 5.4.3 RuntimeResilience (`runtime_resilience.py`)

**职责：** 韧性基础原语，供 Runtime 和 Watchdog 共享。

| 类/函数 | 说明 |
|---------|------|
| `RuntimeState` | 运行时状态枚举（STARTING/READY/RUNNING/.../RECOVERY_REQUIRED） |
| `atomic_write_json(path, payload)` | 原子写入 JSON（tmp + os.replace） |
| `RuntimeStateStore` | 运行时状态持久化（不恢复旧流程） |
| `SingleInstanceLock` | 跨进程单实例锁 |
| `RestartWindow` | 重启熔断窗口 |
| `flow_timeout_seconds()` / `module_timeout_seconds()` | 超时预算 |
| `get_process_metrics()` | 进程资源指标 |

#### 5.4.4 RuntimeIpcServer (`runtime_ipc.py`)

**职责：** 本地 JSON Lines IPC 服务器，支持 GUI 与 Runtime 跨进程控制。

| 类/常量 | 说明 |
|---------|------|
| `DEFAULT_IPC_HOST = "127.0.0.1"` | IPC 监听地址（仅本地） |
| `DEFAULT_IPC_PORT = 8765` | IPC 命令端口 |
| `DEFAULT_STOP_PORT = 8766` | IPC 紧急停止端口（旁路队列） |
| `RuntimeIpcServer` | IPC 服务器主类 |
| `load_ipc_token(path)` | 加载 IPC 认证 token |
| `IpcCommandError` | IPC 命令错误 |

**Stop 通道旁路设计：** 紧急停止命令（safe_stop/stop_current_task/stop_debug_flow）走独立端口 8766，即使命令队列被长时间运动阻塞也能立即响应。

#### 5.4.5 ProductionState (`production_state.py`)

**职责：** 生产状态机枚举和 Modbus 状态映射。

| 状态 | Modbus 40001 值 |
|------|-----------------|
| IDLE | 0 |
| STANDBY | 2 |
| RUNNING | 4 |
| PAUSED | 0 |
| HOLDING_HOOK | 5 |
| FLOW_ERROR | 110 |
| ROBOT_ERROR | 111 |
| CAMERA_ERROR | 112 |

#### 5.4.6 ProductionTaskContext (`production_context.py`)

**职责：** 单次生产任务上下文，保存任务 ID/hook_type/流程 ID/失败信息/恢复状态。

#### 5.4.7 ProductionFlowRouter (`production_flow_router.py`)

**职责：** 将 Modbus 40004 hook_type 值路由到对应流程 ID。

| 方法 | 说明 |
|------|------|
| `.resolve_primary(hook_type)` | hook_type 0→low_hook, 1→high_hook |
| `.resolve_recovery()` | 解析错误恢复流程 ID |

#### 5.4.8 RecoveryPolicy (`recovery_policy.py`)

**职责：** 决定主流程失败后是否可以执行恢复流程。

**判定条件：**
- FlowResult.recoverable == True
- 失败类型非 ROBOT
- 机器人已连接
- 30004 反馈健康
- RobotMode 不在 {9(急停), 11(故障)}
- ErrorStatus == 0

#### 5.4.9 RuntimeContract (`runtime_contract.py`)

**职责：** IPC 命令契约校验，定义合法命令和参数格式。

#### 5.4.10 RuntimePublication (`runtime_publication.py`)

**职责：** 运行时状态发布，将 Runtime 内部状态写入 JSON 供外部读取。

#### 5.4.11 StartupConnection (`startup_connection.py`)

**职责：** 启动时设备连接管理（机器人+相机并发连接，5秒观察窗口）。

---

### 5.5 通信模块 (communication)

#### 5.5.1 ModbusServer (`modbus_server.py`)

**职责：** 本地 PC 作为 Modbus TCP 从站/服务器，供外部主站 PC 访问。

| 常量/类 | 说明 |
|---------|------|
| `REG_CMD_STATUS = 40001` | 命令/状态寄存器 |
| `REG_MODE = 40002` | 运行模式寄存器 |
| `REG_HEARTBEAT = 40003` | 心跳寄存器 |
| `REG_HOOK_TYPE = 40004` | 提钩杆类型寄存器 |
| `CMD_STOP = 0` / `CMD_RESET = 1` / `CMD_HOOK = 3` | 命令值 |
| `STATUS_IDLE = 0` / `STATUS_RUNNING = 4` / `STATUS_HOOK_OK = 5` | 状态值 |
| `STATUS_HOOK_ERR = 110` / `STATUS_ROBOT_ERR = 111` / `STATUS_CAMERA_ERR = 112` | 错误状态值 |
| `DobotModbusServer` | Modbus TCP 服务器主类 |

**命令协议（40001）：**
- 0：空闲/中停
- 1：非运行时复位/延时等待时放行
- 3：执行流程
- 5：延时等待/流程完成

#### 5.5.2 modbus_utils (`modbus_utils.py`)

**职责：** Modbus 工具函数（寄存器读写辅助）。

---

### 5.6 配置管理模块 (config)

#### 5.6.1 ConfigManager (`config_manager.py`)

**职责：** 统一配置管理，支持防抖写入、快照读取和自动迁移。

| 函数/类 | 说明 |
|---------|------|
| `USER_DATA_DIR` | 用户数据目录（`user_data/`，升级保留） |
| `CONFIG_FILE` / `GRASP_FLOW_FILE` / ... | 数据文件路径常量 |
| `ConfigService` | 防抖配置写入服务（避免频繁磁盘 I/O） |
| `load_config()` / `get_config()` | 加载/获取配置 |
| `reload_config()` | 重新加载配置 |
| `use_config_snapshot()` | 配置快照上下文管理器 |
| `get_robot_ip()` / `get_modbus_port()` / ... | 各配置项 getter |
| `get_calibration(camera_type)` | 获取手眼标定参数 |
| `get_camera_handeye_matrix(camera_type)` | 获取手眼标定矩阵 |
| `resolve_point(point_name)` | 解析点位（支持 saved_point/camera/initial_position） |
| `set_point(name, coords)` | 设置点位 |
| `resolve_camera_model_path(camera_type)` | 解析相机模型路径 |
| `_migrate_legacy_paths()` | 自动迁移旧路径数据到 `user_data/` |

**路径层级：**
- `_MODULE_DIR` = `dobot_move/config/`
- `_PACKAGE_DIR` = `dobot_move/`
- `_PROJECT_ROOT` = `Dobot-VGS-RS400/`
- `USER_DATA_DIR` = `Dobot-VGS-RS400/user_data/`

---

### 5.7 用户界面模块 (ui)

#### 5.7.1 DobotMainWindow (`gui_app.py`)

**职责：** PySide6 主窗口，集成 7 个 Mixin 实现各功能面板。

**Mixin 组合：**
- `RobotControlMixin`：机器人连接/使能/运动控制
- `VisionMixin`：相机连接/识别/视觉伺服
- `ModbusMixin`：Modbus 服务器控制
- `GraspFlowMixin`：抓取流程编辑/运行
- `PointManagementMixin`：点位管理
- `StartupConnectionMixin`：启动连接

#### 5.7.2 MainControlPanel (`main_control_panel.py`)

**职责：** 主控面板组件，基于信号通信，包含机器人状态/视觉/流程控制等卡片。

#### 5.7.3 RuntimeFacade (`runtime_facade.py`)

**职责：** Runtime 外观模式，封装 IPC 客户端调用，为 GUI 提供统一接口。

#### 5.7.4 qt_compat (`qt_compat.py`)

**职责：** Qt 框架兼容层（PySide6），抽象 Qt 类导入，实现框架无关性。

#### 5.7.5 其他 UI 组件

| 文件 | 说明 |
|------|------|
| `gui_ipc_client.py` | Runtime IPC 客户端（GUI 侧） |
| `gui_runtime_status.py` | Runtime 健康状态读取与显示 |
| `gui_connection.py` | GUI 连接管理 |
| `gui_debug_widgets.py` | 调试组件（误差趋势图等） |
| `ui_theme.py` | UI 主题与样式 |
| `logging_config.py` | 日志配置 |
| `realtime_feedback_dialog.py` | 实时反馈对话框 |
| `camera_test_worker.py` | GUI 专用相机测试 Worker（QImage/QThread） |

---

### 5.8 远程API模块 (remote_api)

#### 5.8.1 RemoteApiApp (`app.py`)

**职责：** 独立 HTTP 服务供外部平板/MES 只读查询。

**端点：**

| 端点 | 认证 | 说明 |
|------|------|------|
| `/api/v1/health` | 免认证 | 健康检查 |
| `/api/v1/status` | Bearer Token | 机器人状态 |
| `/api/v1/feedback/all` | Bearer Token | 30004 完整反馈 |
| `/api/v1/modbus/registers` | Bearer Token | Modbus 寄存器 |
| `/api/v1/production/status` | Bearer Token | 生产状态 |

**特性：** 旧路径 `/api/status` 等返回 301 重定向到 v1；CORS `Access-Control-Allow-Origin: *`；零新第三方依赖（标准库 `ThreadingHTTPServer`）。

#### 5.8.2 handlers (`handlers.py`)

**职责：** 响应构建器，解析 30004 反馈数据并组装 API 响应。

| 函数 | 说明 |
|------|------|
| `parse_feedback(fb)` | 解析 30004 numpy 结构化数组为 dict |
| `build_status(fb, health, age, ...)` | 构建 `/api/v1/status` 响应 |
| `build_health(health, ...)` | 构建健康检查响应 |
| `build_feedback_all(fb)` | 构建完整反馈响应 |
| `build_production_status(state, ...)` | 构建生产状态响应 |

#### 5.8.3 FeedbackWorker / ModbusClient

| 类 | 说明 |
|----|------|
| `FeedbackWorker` | 30004 反馈后台连接线程 |
| `read_registers(host, port, ...)` | Modbus TCP 客户端寄存器读取 |

---

### 5.9 Windows服务模块 (windows_service)

**职责：** Windows 服务封装，使用 WinSW 将 Runtime 和 Watchdog 注册为 Windows 服务。

| 文件 | 说明 |
|------|------|
| `service_config.py` | 服务配置定义 |
| `generate_config.py` | WinSW XML 配置生成 |
| `preflight.py` | 服务安装预检 |

**服务依赖：** Watchdog 服务通过 WinSW 的 `<depend>DobotRuntimeService</depend>` 声明对 Runtime 服务的依赖，确保系统启动时 Runtime 先于 Watchdog 启动；Runtime 服务停止时 SCM 也会联动停止 Watchdog，避免在 Runtime 不可用时 Watchdog 误判卡死并触发重启。

---

### 5.10 C++加速模块 (cpp_core)

**职责：** pybind11 加速模块，提供坐标变换、NMS、YOLO 后处理和深度位置计算的 C++17 实现，5-20 倍加速。

#### Python 侧 API

```python
import dobot_core

# 坐标变换
R = dobot_core.transforms.euler2rot(rx, ry, rz, degree=True)    # → 3x3 numpy
T = dobot_core.transforms.pose2matrix(x, y, z, rx, ry, rz)      # → 4x4 numpy
p = dobot_core.transforms.transform_point(matrix, point)         # → 3D numpy

# NMS
keep = dobot_core.nms.nms(boxes, scores, iou_threshold=0.5)     # → list[int]

# YOLO 后处理
dets = dobot_core.yolo.postprocess_yolov8(outputs, original_size, ...)
dets = dobot_core.yolo.postprocess_yolo26(outputs, original_size, ...)
masks = dobot_core.yolo.process_mask(protos, masks_in, bboxes, ...)

# 深度位置计算
pos = dobot_core.depth.calculate_object_position(depth_image, mask, bbox, fx, fy, ...)
```

#### C++ 侧结构

| 头文件 | 函数 | 说明 |
|--------|------|------|
| `transforms.h` | `euler2rot`, `pose2matrix`, `transform_point` | 坐标变换 |
| `nms.h` | `nms` | 非极大值抑制 |
| `yolo.h` | `postprocess_yolov8`, `postprocess_yolo26`, `process_mask` | YOLO 后处理（支持 YOLO11s-seg 和 YOLO26） |
| `depth_position.h` | `calculate_object_position` | 深度图像位置计算 |

**构建：** CMake 3.15+ + pybind11 + C++17，`build_cpp.py` 自动调用 CMake configure + build + 复制 .pyd/.so 到项目根目录。

**回退机制：** `dobot_core` 不可用时（未编译/不支持平台），所有函数自动回退到纯 Python 实现。

---

## 6. 关键类与函数索引

### 核心类

| 类名 | 模块 | 职责 |
|------|------|------|
| `DobotController` | `robot.robot_controller` | 机器人控制核心枢纽 |
| `DobotApiDashboard` | `robot.dobot_api` | Dashboard 命令通道 (29999) |
| `DobotApiFeedBack` | `robot.dobot_api` | 实时反馈通道 (30004) |
| `VisualServoController` | `robot.visual_servo_controller` | 多线程视觉伺服控制器 |
| `VisionThread` | `robot.visual_servo_controller` | 视觉检测线程 |
| `ServoThread` | `robot.visual_servo_controller` | 伺服控制线程 |
| `TargetCache` | `robot.visual_servo_controller` | 线程安全目标缓存 |
| `ArcMotionController` | `robot.arc_motion_controller` | 圆弧运动控制器 |
| `ArcTrajectoryPlanner` | `robot.arc_trajectory_planner` | 圆弧轨迹规划器 |
| `GripperController` | `robot.gripper_controller` | 夹爪控制器 (Modbus RTU) |
| `HandEyeCalibManager` | `robot.hand_eye_calib` | 手眼标定管理器 |
| `RobotPoseBuffer` | `robot.robot_pose_buffer` | 位姿环形缓冲区 |
| `VisionSystem` | `vision.vision_system` | 视觉系统主类 |
| `BYTETracker` | `vision.tracker` | ByteTrack 多目标跟踪器 |
| `STrack` | `vision.tracker` | 单目标跟踪轨迹 |
| `KalmanFilter3D` | `vision.kalman_filter_3d` | 6 状态 3D Kalman 滤波器 |
| `DepthProcessor` | `vision.depth_processor` | 4 级深度滤波链 |
| `CaptureWorker` | `vision.capture_worker` | 纯 Python 帧采集线程 |
| `FlowExecutor` | `flow.flow_executor` | 流程执行器（无 Qt） |
| `FlowLibrary` | `flow.flow_library` | 版本化流程库 |
| `FlowResult` | `flow.flow_result` | 结构化流程结果 |
| `DobotRuntimeAgent` | `runtime.runtime_agent` | 后台运行代理 |
| `WindowsServiceController` | `runtime.runtime_watchdog` | Windows SCM 适配器 |
| `RuntimeStateStore` | `runtime.runtime_resilience` | 运行时状态持久化 |
| `SingleInstanceLock` | `runtime.runtime_resilience` | 跨进程单实例锁 |
| `RuntimeIpcServer` | `runtime.runtime_ipc` | IPC 服务器 |
| `ProductionState` | `runtime.production_state` | 生产状态机枚举 |
| `ProductionTaskContext` | `runtime.production_context` | 生产任务上下文 |
| `ProductionFlowRouter` | `runtime.production_flow_router` | 流程路由器 |
| `RecoveryPolicy` | `runtime.recovery_policy` | 恢复策略 |
| `DobotModbusServer` | `communication.modbus_server` | Modbus TCP 服务器 |
| `DobotMainWindow` | `ui.gui_app` | PySide6 主窗口 |
| `ConfigService` | `config.config_manager` | 防抖配置写入服务 |

### 核心函数

| 函数 | 模块 | 说明 |
|------|------|------|
| `euler2rot(rx,ry,rz)` | `robot.transform_utils` | 欧拉角 → 旋转矩阵 |
| `pose2matrix(x,y,z,rx,ry,rz)` | `robot.transform_utils` | 位姿 → 齐次矩阵 |
| `validate_absolute_pose()` | `robot.motion_safety` | 绝对位姿安全校验 |
| `validate_relative_delta()` | `robot.motion_safety` | 相对偏移安全校验 |
| `validate_servo_p_params()` | `robot.motion_safety` | ServoP 参数 clamp |
| `atomic_write_json()` | `runtime.runtime_resilience` | 原子写入 JSON |
| `required_camera_types()` | `flow.flow_library` | 分析流程所需相机 |
| `resolve_point()` | `config.config_manager` | 解析点位 |

---

## 7. 模块间依赖关系

```
                    ┌──────────────┐
                    │  ui/gui_app  │  PySide6 GUI
                    └──────┬───────┘
                           │ imports
            ┌──────────────┼──────────────┐
            ▼              ▼              ▼
    ┌──────────────┐ ┌──────────┐ ┌────────────┐
    │ ui/mixins/*  │ │ui/runtime│ │flow/qt_wkrs│
    └──────┬───────┘ │_facade   │ └─────┬──────┘
           │         └────┬─────┘       │
           ▼              ▼             ▼
    ┌──────────────────────────────────────────┐
    │           robot/ (机器人控制)              │
    │  DobotController ← DobotApiDashboard     │
    │                 ← DobotApiFeedBack        │
    │                 ← VisualServoController   │
    │                 ← ArcMotionController     │
    │                 ← GripperController       │
    │                 ← MotionSafety            │
    │                 ← RobotPoseBuffer         │
    └──────────┬──────────────────┬────────────┘
               │                  │
               ▼                  ▼
    ┌──────────────────┐  ┌──────────────────┐
    │  vision/ (视觉)   │  │communication/    │
    │  VisionSystem    │  │  ModbusServer    │
    │  +Tracker        │  └──────────────────┘
    │  +KalmanFilter3D │
    │  +DepthProcessor │
    └────────┬─────────┘
             │
             ▼
    ┌──────────────────┐     ┌──────────────────┐
    │ config/ (配置)    │     │  flow/ (流程)     │
    │ ConfigManager    │◄────│  FlowExecutor     │
    │ ConfigService    │     │  FlowLibrary      │
    └──────────────────┘     │  FlowResult       │
                             └────────┬─────────┘
                                      │
                                      ▼
                             ┌──────────────────┐
                             │ runtime/ (运行时)  │
                             │ RuntimeAgent      │
                             │ RuntimeWatchdog   │
                             │ RuntimeResilience │
                             │ RuntimeIpcServer  │
                             │ ProductionState   │
                             │ RecoveryPolicy    │
                             └──────────────────┘
                                      │
                                      ▼
                             ┌──────────────────┐
                             │ remote_api/       │
                             │  App + Handlers   │
                             │  + ModbusClient   │
                             └──────────────────┘
```

**关键依赖链：**

1. **GUI → Runtime IPC：** GUI 通过 `RuntimeIpcClient` + `RuntimeFacade` 与后台 Runtime 通信
2. **FlowExecutor → Robot + Vision：** 流程执行器调用 `DobotController`（运动）和 `VisionSystem`（识别）
3. **VisualServoController → Robot + Vision：** 视觉伺服依赖反馈位姿和目标检测
4. **RuntimeAgent → Modbus + Robot + Flow：** 后台代理整合 Modbus 协议、机器人控制和流程执行
5. **VisionSystem → dobot_core (可选)：** C++ 加速模块可选，不可用时自动 Python 回退
6. **Remote API → 30004 Feedback + Modbus Client：** 只读查询，不暴露控制命令

---

## 8. 数据流与控制流

### 8.1 抓取流程数据流

```
拍照位 → D435i 粗识别 → 移动至 D435i 目标上方
→ 视觉伺服逼近 → D405 精细识别（掩码几何中心）
→ 计算目标点 → 移动至目标位置
→ 原生圆弧运动或相对移动（可选） → 抬升 → 放置
```

### 8.2 视觉伺服数据流

```
FeedbackThread (30004) ──→ latest_pose ──→ RobotPoseBuffer.push()
                                                    │
VisionThread ──→ YOLO检测 ──→ 3D定位 ──→ TargetCache.update_from_detection()
                                        │         │
                                        │    pose_buffer.pose_at(capture_time)
                                        │         │
                                        └──→ target_base (预计算)
                                                    │
ServoThread ──→ read target_base + current_pose ──→ 误差计算
                                                    │
                                        ┌───────────┴───────────┐
                                        │ 自适应增益 + 步长钳位  │
                                        └───────────┬───────────┘
                                                    │
                                        ServoP 下发 → 机器人运动
```

### 8.3 Modbus 控制流

```
外部主站 PC ──→ Modbus TCP 写 40001=3 ──→ DobotModbusServer
                                                    │
                                        RuntimeAgent 读取 40001
                                                    │
                                        ProductionFlowRouter.resolve(hook_type)
                                                    │
                                        FlowExecutor.run(flow_id)
                                                    │
                                        写 40001=5(完成) / 110(错误)
```

### 8.4 IPC 控制流

```
GUI ──→ RuntimeIpcClient ──→ TCP 127.0.0.1:8765 ──→ RuntimeIpcServer
                                                            │
                                                command_handler() ──→ RuntimeAgent
                                                            │
                                                response ──→ GUI
                                                    
GUI(紧急停止) ──→ TCP 127.0.0.1:8766 ──→ Stop通道(旁路队列) ──→ 立即执行
```

---

## 9. 配置体系

### 9.1 配置文件位置

| 文件 | 位置 | 说明 |
|------|------|------|
| `config.json` | `user_data/config.json` | 现场配置（标定/点位/IP/模型路径） |
| `grasp_flow_modules.json` | `user_data/grasp_flow_modules.json` | 用户编辑的流程库 |
| `alarm_history.json` | `user_data/alarm_history.json` | 运行时报警记录 |
| `runtime_health.json` | `user_data/runtime_health.json` | Runtime 健康状态 |
| `runtime_state.json` | `user_data/runtime_state.json` | Runtime 运行状态 |
| `runtime_publication.json` | `user_data/runtime_publication.json` | Runtime 发布状态 |
| `runtime_ipc.token` | `user_data/runtime_ipc.token` | IPC 认证 token |
| `config.example.json` | `dobot_move/config/config.example.json` | 配置示例模板 |

### 9.2 核心配置项

| 字段 | 类型 | 说明 | 示例 |
|------|------|------|------|
| `robot_ip` | string | 机器人 IP 地址 | `"192.168.1.50"` |
| `photo_position` | float[6] | 拍照位 (x,y,z,rx,ry,rz) | `[900.98, -403.82, 166.76, ...]` |
| `target_offset` | float[3] | 目标偏移 (dx,dy,dz) | `[0, 0, 0]` |
| `calibration.D435i/D405` | object | 手眼标定参数 | `{cam_to_flange_pose: [x,y,z,rx,ry,rz]}` |
| `camera.models.D435i/D405` | string | ONNX 模型绝对路径 | `"D:\\models\\d435i.onnx"` |
| `points` | object | 点位表（支持 saved_point/camera/initial_position） |
| `modbus_port` | int | Modbus 服务器端口 | `502` |
| `user_index` / `tool_index` | int | 用户/工具坐标系索引 | `0` |

### 9.3 性能配置

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `flow_wait_poll_interval` | 0.05 | 流程等待轮询间隔 (s) |
| `robot_mode_dashboard_fallback_interval` | 1.0 | Dashboard 查询冷却间隔 (s) |
| `pose_cache_max_age` | 0.3 | 位姿缓存最大年龄 (s) |
| `motion_settle_time` | 0.15 | 运动后最小稳定时间 (s) |
| `motion_done_speed_threshold` | 1.0 | 线速度归零阈值 (mm/s) |
| `motion_done_stable_samples` | 3 | 连续稳定采样次数 |

### 9.4 配置升级迁移

`config_manager._migrate_legacy_paths()` 在导入时自动执行：
- 将旧位置数据（`dobot_move/config.json`、`dobot_move/gui_mixins/grasp_flow_modules.json` 等）迁移到 `user_data/`
- 幂等操作：目标已存在时跳过
- 保留原文件（复制，非移动）

---

## 10. 安全机制

| 机制 | 说明 |
|------|------|
| **运动互斥锁** | `acquire_motion()`/`release_motion()`，流程和 Modbus 运动互斥执行 |
| **急停独立连接** | 通过独立临时 TCP 连接发送 EmergencyStop，避免主连接锁阻塞 |
| **急停始终优先** | 急停触发时立即设置 stop_event，流程线程马上停止下发 |
| **运动安全校验** | `validate_absolute_pose()`/`validate_relative_delta()` 校验工作空间/姿态角/速度范围 |
| **ServoP 参数 clamp** | `validate_servo_p_params()` 确保 t/aheadtime/gain 在安全范围 |
| **视觉伺服安全** | Z 轴安全限位 + 最大误差拒绝 + 队列延迟保护 + 预测门控 |
| **跨进程控制租约** | `SingleInstanceLock` 保证 GUI 与 Runtime 互斥占用机器人控制权 |
| **IPC 认证** | Token 认证 + Stop 通道旁路（独立端口 8766） |
| **配置防抖** | `ConfigService` 避免频繁磁盘 I/O |
| **看门狗** | 流程超时检测 + 反馈断流先停 + 崩溃恢复锁 + 外部看门狗卡死检测 |
| **重启熔断** | `RestartWindow` 限制窗口期内连续重启次数 |
| **生产状态机** | 严格状态转换，错误状态分类（FLOW/ROBOT/CAMERA） |
| **恢复策略** | `RecoveryPolicy` 保守判定，任何机器人健康疑虑即拒绝恢复运动 |
| **急停按钮防抖** | 500ms 时间戳防抖，始终可点击 |

---

## 11. 依赖清单

### Python 依赖

| 包 | 版本 | 必选/可选 | 用途 |
|----|------|-----------|------|
| `PySide6` | >=6.0 | 必选 | Qt GUI 框架 |
| `numpy` | - | 必选 | 数值计算 |
| `requests` | - | 必选 | HTTP 请求 |
| `pymodbus` | >=3.0 | 必选 | Modbus TCP 服务器/客户端 |
| `opencv-python` | - | 必选 | 图像处理 |
| `scipy` | - | 必选 | 匈牙利算法 (linear_sum_assignment) |
| `pyrealsense2` | - | 必选 | Intel RealSense SDK |
| `minimalmodbus` | - | 必选 | 夹爪 Modbus RTU 通信 |
| `pyserial` | - | 必选 | 串口通信 |
| `python-can` | - | 必选 | CAN 总线（电池监测） |
| `lapx` | - | 必选 | 线性分配 (ByteTrack) |
| `onnxruntime-gpu[cuda,cudnn]` | - | 可选 | GPU YOLO 推理 (NVIDIA GPU) |
| `pybind11` | - | 可选 | C++ 加速模块构建 |
| `cmake` | - | 可选 | C++ 加速模块构建 |

### 硬件依赖

| 设备 | 型号 | 用途 |
|------|------|------|
| 机械臂 | Dobot CR5/CR10/CRA 系列 | TCP/IP 协议控制 |
| 中距相机 | Intel RealSense D435i | 粗定位，深度 0.5-2.2m |
| 近距相机 | Intel RealSense D405 | 精细识别，深度 0.07-0.8m |
| 力传感器 | 内置六轴力传感器 | TCP 力到位保护 |

### 构建依赖（可选）

- CMake 3.15+
- C++17 编译器（Windows: Visual Studio Build Tools; Linux: GCC/Clang）
- NVIDIA GPU + 驱动 >= 525.60.13（GPU 推理）

---

## 12. 测试体系

项目包含 **60+ 测试文件**，覆盖各核心模块。测试框架使用 `pytest`。

### 测试分类

| 类别 | 测试文件 | 覆盖范围 |
|------|----------|----------|
| Modbus 通信 | `test_modbus_*` | 服务器/客户端/死锁/回调/hook |
| 配置管理 | `test_config_manager.py` | 配置加载/迁移/防抖 |
| 机器人控制 | `test_dobot_api_transport.py` | TCP/IP 协议 |
| 运动安全 | `test_motion_safety.py` | 工作空间/速度/状态校验 |
| 位姿缓冲 | `test_robot_pose_buffer.py`, `test_pose_buffer_*` | 插值/外推/重连/遥测 |
| 视觉系统 | `test_tracker.py`, `test_kalman_*`, `test_*camera*` | 跟踪/滤波/相机模型 |
| 视觉伺服 | `test_visual_servo_params.py`, `test_*servo*` | 参数/门控 |
| 流程执行 | `test_flow_*` | 执行器/库/恢复/就绪性 |
| 运行时 | `test_runtime_*`, `test_production_*` | Agent/IPC/韧性/状态机 |
| GUI | `test_gui_*` | IPC/状态/安全停止 |
| Windows 服务 | `test_windows_service_*` | 服务配置/脚本 |
| 远程 API | `test_remote_api_handlers.py` | 端点/响应 |

### 运行测试

```bash
pytest tests/ -v
```

---

> 本文档由项目源码分析自动生成，最后更新：2026-07-10
