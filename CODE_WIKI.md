# Dobot-VGS-RS400 Code Wiki

> 基于 Intel RealSense D400 深度相机的越疆 CR 系列机械臂视觉引导系统完整技术文档
>
> 本文档基于项目源码深度分析生成，涵盖项目整体架构、模块职责、关键类与函数、依赖关系、运行方式与核心算法。

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
9. [核心算法说明](#9-核心算法说明)
10. [配置体系](#10-配置体系)
11. [安全机制](#11-安全机制)
12. [依赖清单](#12-依赖清单)
13. [测试体系](#13-测试体系)
14. [部署脚本](#14-部署脚本)

---

## 1. 项目概述

**Dobot-VGS-RS400** 是一套基于 Python + PySide6 的越疆 CR 系列机械臂视觉定位控制系统。集成双 RealSense 深度相机（D435i + D405）、YOLO 实例分割、ByteTrack 多目标跟踪、3D 卡尔曼滤波、手眼标定、视觉伺服和原生圆弧运动，实现从目标识别到精准定位的全自动化抓取流程。

**核心能力：**

- 双相机协作：D435i 粗定位 + D405 精细识别（掩码几何中心）
- YOLO 实例分割（YOLO11s-seg / YOLO26 端到端）+ ByteTrack 多目标跟踪 + 3D Kalman 滤波
- 手眼标定（D435i/D405 双相机独立标定，ZYX 欧拉角约定）
- 视觉伺服（多线程缓存式，10-20Hz 闭环，自适应增益，2mm 收敛阈值）
- 原生圆弧运动（ArcTrajectoryPlanner + ArcMotionController，使用 Dobot Arc()）
- Modbus TCP 从站通信（供外部主站 PC 访问）
- C++ 可选加速（pybind11，5-20 倍加速，Python 自动回退）
- 7x24 后台加固（崩溃恢复锁、流程看门狗、反馈断流先停、外部看门狗卡死检测）
- Remote REST API（只读查询机器人状态/反馈/Modbus/生产状态，Token 认证 + CORS）
- 跨进程控制租约（GUI 与 Runtime 互斥占用机器人控制权）

**技术栈：** Python 3.10+（推荐 3.12），PySide6，ONNX Runtime (GPU/CPU)，RealSense SDK 2.0，pymodbus 3.x，pybind11/CMake（可选）

**硬件平台：** Dobot CR20A 系列机械臂 + Intel RealSense D435i + D405 + 内置六轴力传感器

---

## 2. 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                      GUI (PySide6)                               │
│         DobotMainWindow + 5 Mixins + 9 Pages                    │
├──────────┬──────────┬──────────┬──────────┬─────────────────────┤
│  机器人    │  视觉     │  力控/圆弧 │  Modbus   │  流程编排        │
│  控制      │  系统     │  运动     │  通信     │                  │
├──────────┼──────────┼──────────┼──────────┼─────────────────────┤
│DobotApi  │VisionSys │ArcMotion │ModbusServ│FlowExecutor       │
│Dashboard │+Tracker  │Controller│ModbusCli │FlowLibrary        │
│+Feedback │+Kalman3D │ArcPlanner│          │FlowResult         │
│+Safety    │+DepthProc│          │          │                   │
│+PoseBuffer│+CaptureW │          │          │                   │
├──────────┴──────────┴──────────┴──────────┴─────────────────────┤
│                  Runtime (无 Qt 依赖，纯 Python)                  │
│    RuntimeAgent + ProductionStateMachine + RecoveryPolicy         │
│    RobotConnectionSupervisor + RuntimeProgramRunner               │
│    RuntimeIpcServer(双通道) + RuntimePublicationStore             │
│    RuntimeStateStore + SingleInstanceLock + RestartWindow         │
│    ExternalWatchdog (独立进程，卡死检测+进程重启)                   │
├──────────────────────────────────────────────────────────────────┤
│              dobot_core (C++ pybind11, 可选)                       │
│         transforms / nms / yolo / depth_position                  │
└──────────────────────────────────────────────────────────────────┘
```

**分层原则：**

| 层级 | 职责 | Qt 依赖 | 关键组件 |
|------|------|---------|----------|
| UI 层 | 图形界面、用户交互 | PySide6 | `DobotMainWindow` + Mixins + 9 Pages |
| 业务层 | 机器人控制、视觉感知、流程执行 | 无 | `DobotController` / `VisionSystem` / `FlowExecutor` |
| Runtime 层 | 后台无头运行、生产状态机、看门狗 | 无 | `DobotRuntimeAgent` / `RuntimeIpcServer` |
| 加速层 | C++ pybind11 后处理加速 | 无 | `dobot_core.transforms/nms/yolo/depth` |

**关键设计原则：**

1. **Qt 与 headless 分离**：`flow_executor.py` / `capture_worker.py` / `runtime/*` 均无 Qt 依赖，可在无 PySide6 环境运行；Qt 逻辑集中在 `qt_workers.py` / `ui/*`
2. **原子写入**：所有状态/配置/流程文件使用 `tmp + os.replace` 模式，关键状态附加 `os.fsync`
3. **双通道停止**：IPC 主通道 8765（FIFO 串行）+ Stop 通道 8766（旁路队列，即时响应）
4. **C 扩展回退**：`dobot_core` 不可用时所有函数自动回退纯 Python 实现
5. **跨进程互斥**：`SingleInstanceLock` 保证 GUI 与 Runtime 互斥占用机器人控制权

---

## 3. 项目目录结构

```
Dobot-VGS-RS400/
├── dobot_move/                     # 主代码包
│   ├── __init__.py                 #   惰性导出 DobotController/VisionSystem/DobotModbusServer
│   ├── __main__.py                 #   python -m dobot_move 入口
│   ├── robot/                      #   机械臂控制
│   │   ├── robot_controller.py     #     机器人控制器（核心，~162KB）
│   │   ├── dobot_api.py            #     TCP/IP 协议 API（Dashboard + Feedback，~142KB）
│   │   ├── visual_servo_controller.py  # 多线程视觉伺服控制器
│   │   ├── arc_motion_controller.py    # 圆弧运动控制器
│   │   ├── arc_trajectory_planner.py   # 圆弧轨迹规划器
│   │   ├── hand_eye_calib.py       #     手眼标定管理器
│   │   ├── transform_utils.py      #     坐标变换工具（C++ 优先）
│   │   ├── motion_safety.py        #     运动安全校验
│   │   └── robot_pose_buffer.py    #     位姿环形缓冲区（时间索引插值）
│   ├── vision/                     #   视觉感知
│   │   ├── vision_system.py        #     视觉系统主类（YOLO推理+3D定位）
│   │   ├── capture_worker.py       #     纯Python帧采集线程（无Qt依赖）
│   │   ├── depth_processor.py      #     4级RealSense深度滤波链
│   │   ├── kalman_filter_3d.py     #     6状态3D Kalman滤波器（CV模型）
│   │   └── tracker.py              #     ByteTrack多目标跟踪
│   ├── flow/                       #   流程编排
│   │   ├── flow_executor.py        #     纯Python流程执行器（无Qt依赖）
│   │   ├── flow_library.py         #     版本化流程库（v3 schema + 角色映射）
│   │   ├── flow_readiness.py       #     流程就绪性检查（无副作用）
│   │   ├── flow_result.py          #     结构化流程结果（FailureKind 枚举）
│   │   ├── flow_step_list.py       #     流程步骤列表（拖拽排序+状态图标）
│   │   ├── qt_workers.py           #     Qt适配（FlowThread/RobotCmdThread）
│   │   ├── camera_test_worker.py   #     shim → vision.capture_worker + ui.camera_test_worker
│   │   └── workers.py             #     向后兼容shim
│   ├── runtime/                    #   生产后端（无 Qt 依赖）
│   │   ├── runtime_agent.py        #     后台代理（设备监督+流程看门狗+状态机，~147KB）
│   │   ├── runtime_watchdog.py     #     外部看门狗（卡死检测+进程重启）
│   │   ├── runtime_resilience.py   #     韧性基础（状态持久化+单实例锁+重启熔断）
│   │   ├── runtime_ipc.py          #     跨进程IPC服务器（双通道JSON Lines）
│   │   ├── runtime_contract.py     #     IPC命令契约校验
│   │   ├── runtime_publication.py  #     运行时状态发布（草稿→批准快照）
│   │   ├── production_state.py     #     生产状态机枚举（12状态）
│   │   ├── production_context.py   #     生产任务上下文（hook_type latched）
│   │   ├── production_flow_router.py  #  流程路由（hook_type → flow_id）
│   │   ├── recovery_policy.py      #     恢复策略（保守判定）
│   │   ├── reset_strategy.py       #     复位策略（状态感知）
│   │   ├── runtime_vision_debug.py #     视觉诊断快照
│   │   └── startup_connection.py   #     启动连接管理（5秒观察窗口）
│   ├── communication/              #   Modbus通信
│   │   ├── modbus_server.py        #     Modbus TCP服务器（pymodbus 3.6+）
│   │   └── modbus_utils.py         #     Modbus工具函数（float↔regs）
│   ├── config/                     #   配置管理
│   │   ├── config_manager.py       #     配置管理器（~907行，环境变量覆盖+原子写+快照）
│   │   ├── alarm_history.py        #     报警历史记录（线程安全+滚动截断）
│   │   ├── config.example.json     #     配置示例
│   │   ├── grasp_flow_modules.default.json  # 默认流程模板
│   │   └── files/                  #     报警码定义（alarmController/Servo.json）
│   ├── ui/                         #   界面层
│   │   ├── gui_app.py              #     主窗口（PySide6，~1440行，5 Mixin + 9 Pages）
│   │   ├── main_control_panel.py   #     主控面板
│   │   ├── runtime_facade.py       #     Runtime外观模式（同步IPC包装）
│   │   ├── gui_ipc_client.py       #     IPC客户端（QThread异步）
│   │   ├── gui_runtime_status.py   #     Runtime健康状态读取
│   │   ├── gui_connection.py       #     GUI连接管理（generation防竞态）
│   │   ├── gui_debug_widgets.py    #     调试组件（误差趋势图）
│   │   ├── qt_compat.py            #     Qt框架兼容层（PySide6）
│   │   ├── ui_theme.py             #     UI主题（~400行QSS）
│   │   ├── logging_config.py       #     日志配置
│   │   ├── realtime_feedback_dialog.py  # 实时反馈对话框
│   │   ├── camera_test_worker.py   #     GUI相机测试Worker（QThread）
│   │   ├── alarm_history_page.py   #     报警记录页
│   │   ├── camera_test_page.py     #     相机测试页
│   │   ├── config_center_page.py   #     配置中心页
│   │   ├── modbus_comm_page.py     #     Modbus通信页
│   │   ├── motion_editor_page.py   #     运动编辑页（8种模块参数面板）
│   │   ├── point_management_page.py  #   点位管理页
│   │   ├── production_monitor_page.py  #  生产监控页
│   │   ├── runtime_debug_page.py   #     Runtime调试页（3 Tab）
│   │   └── mixins/                 #     功能混入
│   │       ├── robot_control_mixin.py   # 机器人控制Mixin
│   │       ├── vision_mixin.py         # 视觉Mixin
│   │       ├── modbus_mixin.py         # Modbus Mixin（只读）
│   │       ├── grasp_flow_mixin.py     # 抓取流程Mixin（~788行）
│   │       ├── point_management_mixin.py  # 点位管理Mixin
│   │       └── startup_connection_mixin.py  # 启动连接Mixin（兼容壳）
│   ├── remote_api/                 #   远程REST API
│   │   ├── app.py                  #     HTTP服务主应用（ThreadingHTTPServer）
│   │   ├── handlers.py             #     端点处理器（响应构建器）
│   │   ├── config.py               #     Remote API配置（薄封装）
│   │   ├── feedback_worker.py      #     30004反馈Worker
│   │   ├── modbus_client.py        #     Modbus客户端（pymodbus 2.x-3.6+兼容）
│   │   └── __main__.py             #     模块入口
│   └── windows_service/            #   Windows服务封装
│       ├── service_config.py       #     服务配置（WinSW XML生成）
│       ├── generate_config.py      #     WinSW配置生成CLI
│       ├── preflight.py            #     预检脚本
│       └── vendor/                 #     WinSW-x64.exe + LICENSE + sha256
├── cpp_core/                       # C++加速模块源码
│   ├── CMakeLists.txt              #   CMake构建脚本（C++17 + pybind11）
│   ├── include/dobot_core/         #   C++头文件
│   │   ├── transforms.h            #     坐标变换（euler2rot/pose2matrix/transform_point）
│   │   ├── nms.h                   #     NMS
│   │   ├── yolo.h                  #     YOLO后处理（yolov8/yolo26/process_mask）
│   │   └── depth_position.h        #     深度位置计算
│   └── src/                        #   C++源文件
│       ├── pybind_module.cpp       #     pybind11绑定（4个子模块）
│       ├── transforms.cpp          #     ZYX旋转顺序实现
│       ├── nms.cpp                 #     贪心NMS
│       ├── yolo.cpp                #     YOLO后处理（含bilinear_resize）
│       └── depth_position.cpp      #     深度反投影（中位数+针孔模型）
├── tests/                          # 测试目录（61个测试文件）
├── scripts/                        # 部署脚本（PowerShell）
│   ├── windows_service_common.ps1  #   公共模块（服务名/校验/WinSW调用）
│   ├── install_windows_services.ps1  # 安装WinSW服务
│   ├── uninstall_windows_services.ps1  # 卸载服务
│   ├── rollback_windows_services.ps1   # 回滚到旧任务计划
│   ├── test_windows_services.ps1       # 测试服务健康
│   └── install_runtime_task.ps1        # 已废弃（旧计划任务）
├── docs/                           # 文档目录
├── user_data/                      # 用户数据（运行时生成，升级保留）
├── wheels/                         # 离线 wheel 包（含 GPU/Qt/CUDA 备选）
├── run.py                          # GUI入口
├── runtime_agent.py                # Runtime入口（兼容层）
├── runtime_watchdog.py             # Watchdog入口（兼容层）
├── remote_api.py                   # Remote API入口（兼容层）
├── build_cpp.py                    # C++模块构建脚本
├── requirements.txt                # Python依赖（空，以lock为准）
└── requirements_lock.txt           # 锁定版本依赖（99个包）
```

---

## 4. 入口与运行方式

### 4.1 启动方式

| 方式 | 命令 | 用途 |
|------|------|------|
| GUI 模式 | `python run.py` 或 `python -m dobot_move` | 工程调试和参数编辑 |
| 部署预检 | `python run.py --check-config` | 验证配置完整性（不启动 GUI） |
| Runtime 模式 | `python runtime_agent.py` 或 `python -m dobot_move.runtime_agent` | 生产现场 7x24 后台运行 |
| Watchdog 模式 | `python runtime_watchdog.py` 或 `python -m dobot_move.runtime.runtime_watchdog` | 独立看门狗，检测 Runtime 卡死并重启 |
| Remote API | `python remote_api.py` 或 `python -m dobot_move.remote_api --host 0.0.0.0 --port 8000` | 外部只读 HTTP 查询服务 |
| C++ 构建 | `python build_cpp.py` | 编译可选 C++ 加速模块 |

### 4.2 入口文件说明

| 文件 | 调用 | 说明 |
|------|------|------|
| [run.py](file:///c:/DobotRuntime/run.py) | `dobot_move.ui.gui_app.main()` | 启动 PySide6 GUI；支持 `--check-config` 预检 |
| [runtime_agent.py](file:///c:/DobotRuntime/runtime_agent.py) | `dobot_move.runtime.runtime_agent.main()` | 启动无头后台代理 |
| [runtime_watchdog.py](file:///c:/DobotRuntime/runtime_watchdog.py) | `dobot_move.runtime.runtime_watchdog.main()` | 启动外部看门狗 |
| [remote_api.py](file:///c:/DobotRuntime/remote_api.py) | `dobot_move.remote_api.app.main()` | 启动 HTTP 服务 |
| [build_cpp.py](file:///c:/DobotRuntime/build_cpp.py) | `python -m cmake` | 调用 CMake 构建 `cpp_core/` 并复制 `.pyd` 到项目根目录 |

### 4.3 Runtime Agent 命令行参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--startup-delay` | 0 | 仅保留兼容，即使设置也立即开始设备探测 |
| `--poll-interval` | 1 | 后台 watchdog 周期（秒） |
| `--health-path` | `runtime_health.json` | 健康状态文件路径 |
| `--state-path` | `runtime_state.json` | 崩溃恢复状态文件路径 |
| `--lock-path` | `runtime_agent.lock` | 后台进程单实例锁路径 |
| `--log-dir` | `logs` | 运行日志目录 |

### 4.4 生产部署

推荐 **WinSW 双服务 + 独立 Runtime + localhost TCP IPC + 独立 GUI**：

| 服务名 | 职责 | 运行账户 |
|--------|------|----------|
| `DobotRuntimeService` | 后台生产服务，独占机器人、D405/D435i、Modbus 502、流程执行器和 IPC | `.\DobotRuntimeSvc`（专用本地账户） |
| `DobotRuntimeWatchdog` | 独立看门狗，检测 Runtime 卡死后先尝试安全 Stop()，再重启 Runtime | `LocalSystem` |

- Watchdog 服务通过 WinSW 的 `<depend>` 声明对 Runtime 服务的依赖
- GUI 只作为工程调试工具，由登录用户手动启动
- IPC 只监听 `127.0.0.1:8765`，服务模式必须提供 `runtime_ipc.token`

---

## 5. 核心模块详解

### 5.1 机器人控制模块 (robot)

#### 5.1.1 DobotController ([robot_controller.py](file:///c:/DobotRuntime/dobot_move/robot/robot_controller.py))

**职责：** 机器人控制的核心枢纽，管理连接、使能、运动指令下发、反馈接收、急停、运动互斥和 Modbus 状态机。约 162KB，是项目最大的单文件。

**关键初始化字段：**
- 传输层：`dashboard`、`feed_four`、`_transport_lock` (RLock)、`_connect_attempt_lock`、`_connection_generation`（连接代际号，防并发竞态）
- 反馈缓存：`latest_pose` / `latest_robot_mode` / `latest_tcp_speed` / `latest_actual_tcp_force` / `latest_running_status` / `latest_current_command_id` / `latest_tool_vector_target` / `latest_q_actual` / `latest_q_target`（各有 `_time` 时间戳）
- 运动状态：`_motion_command_sent_time`、`_has_seen_motion_state`、`_last_command_id`、`_last_motion_completion_reason`、`_last_force_guard_event`
- 互斥锁：`_motion_lock` + `_motion_owner`（运动控制权所有者）
- Modbus 状态机：`_modbus_exec_lock`、`_modbus_hook_status`、`_modbus_mode`、`_modbus_program_runner`
- 位姿缓冲：`pose_buffer = RobotPoseBuffer()`（每个 30004 Pose 都 push）

| 类/方法 | 说明 |
|---------|------|
| `DobotController(robot_ip, enforce_single_instance)` | 机器人控制器主类 |
| `.connect()` | 连接 Dashboard (29999) + Feedback (30004)，使用 `_connection_generation` 防竞态 |
| `.disconnect()` / `.close_robot_transport()` | 断开连接 / 关 socket 但不停 Modbus 不释放租约 |
| `.enable_robot()` / `.disable_robot()` | 使能/下使能机器人 |
| `.move_to_point(target_pose, move_type, speed_percentage, ...)` | 绝对运动（MovJ/MovL/MovC），含安全校验+力保护+完成判定 |
| `.move_relative(offsets, coord_system, motion_type, ...)` | 相对运动（RelMovL/RelMovJ） |
| `.send_relative_command(offsets, coord_system, motion_type, ...)` | 统一相对运动命令发送+响应解析+command_id追踪 |
| `.servo_p(pose, t, aheadtime, gain)` | ServoP 伺服运动（不等待完成） |
| `.move_joint_relative(offsets, ...)` | 关节相对运动（RelJointMovJ） |
| `.emergency_stop()` | 急停（独立临时连接，避免主连接锁阻塞） |
| `.get_current_pose_from_feedback(max_age)` | 从 30004 反馈读取当前位姿 |
| `.get_motion_feedback_snapshot()` | 统一反馈快照（pose+speed+queue+running+force+timestamp+health） |
| `.get_feedback_health(max_age)` | 反馈健康状态（ok/stale/disconnected） |
| `.get_motion_safety_state()` | 只读缓存安全状态（不发查询） |
| `.acquire_motion(owner, allow_if_idle)` / `.release_motion(owner)` | 运动互斥锁（可重入） |
| `.prepare_force_guard(force_guard)` | 校验力保护配置并采样运动前 TCP 力基线 |
| `.wait_for_motion_completion(timeout, ...)` | 运动完成判定核心算法（详见 §9.1） |
| `.start_modbus(port, slave_id)` / `.stop_modbus()` | Modbus TCP 服务器启停 |
| `.set_modbus_program_runner(runner, readiness_checker, command_delegate)` | 注册流程启动和就绪回调 |
| `.start_feedback()` / `.stop_feedback()` | 反馈线程启停 |
| `.pose_buffer` | `RobotPoseBuffer` 实例 |

**运动完成判定（`wait_for_motion_completion`）三级优先级：**

1. **力到位保护检查**（force_guard）：在 command_id 判定之前执行。计算 `_force_delta_norm`（Fx/Fy/Fz 合力增量），超过 `threshold_n` 且达到 `debounce_samples` 次则触发 Stop()，返回 True（reason=`"force_triggered"`）
2. **官方模式判定**（command_id）：`CurrentCommandId == command_id` 且 `RobotMode == 5`，连续 `stable_samples` 次则完成（reason=`"motion_done"`）。有 command_id 且 30004 新鲜时**仅走此路径**
3. **30004 反馈辅助判定**：速度归零 + 位姿到位 + 连续 `stable_samples` 次；相对运动用 `RunningStatus==0` 或 `RunQueuedCmd==0`
4. **Dashboard 兜底**：仅当 30004 反馈不新鲜时，`RobotMode==5` 完成；`==9` 自动清错（最多 3 次）

**内部线程：** `FeedbackThread` 持续接收 30004 端口反馈，魔数校验 `_FEEDBACK_MAGIC = 0x123456789ABCDEF`，每个有效 Pose 都 `pose_buffer.push()` 用于视觉时间对齐。

#### 5.1.2 DobotApiDashboard / DobotApiFeedBack ([dobot_api.py](file:///c:/DobotRuntime/dobot_move/robot/dobot_api.py))

**职责：** 越疆 CR 系列机械臂 TCP/IP 协议的 Python 封装。约 142KB，130+ 个 Dashboard 方法。

| 类 | 端口 | 说明 |
|----|------|------|
| `DobotApi` | - | TCP 通信基类，`SO_RCVBUF=144000`，`__globalLock` 同步锁 |
| `DobotApiDashboard` | 29999 | Dashboard 命令通道（使能/运动/急停/IO/坐标系/力控/安全） |
| `DobotApiFeedBack` | 30004 | 实时反馈通道（读取 1440 字节结构化数据） |

**关键 Dashboard 方法分类：**
- 使能/控制：`EnableRobot` / `DisableRobot` / `ClearError` / `PowerOn` / `Stop` / `Pause` / `Continue` / `EmergencyStop(mode)` / `SpeedFactor`
- 运动指令：`MovJ` / `MovL` / `ServoJ` / `ServoP(X,Y,Z,RX,RY,RZ,t,aheadtime,gain)` / `Arc(mid,end)` / `Circle` / `MoveJog` / `RelMovJTool` / `RelMovLTool` / `RelMovJUser` / `RelMovLUser` / `RelJointMovJ`
- 查询：`RobotMode` / `GetAngle` / `GetPose(user,tool)` / `GetErrorID` / `GetError(language)` / `GetCurrentCommandID` / `GetForce`
- IO 控制：`DO` / `DOInstant` / `GetDO` / `ToolDO` / `AO` / `DI` / `AI`
- 坐标系：`User(index)` / `SetUser` / `CalcUser` / `Tool` / `SetTool` / `CalcTool`
- Modbus：`ModbusCreate` / `ModbusRTUCreate` / `GetHoldRegs` / `SetHoldRegs`
- 力控：`EnableFTSensor` / `SixForceHome` / `GetForce` / `ForceDriveMode` / `FCForceMode` / `FCOff`
- 安全：`SetCollisionLevel` / `SetBackDistance` / `StartDrag` / `StopDrag` / `EnableSafeSkin` / `SetSafeWallEnable` / `SetWorkZoneEnable`

**30004 反馈结构体 (`MyType`, np.dtype)：** 1440 字节，包含 `RobotMode`、`TestValue`（魔数）、`SpeedScaling`、`QActual`/`QTarget`（6关节角度）、`ActualTCPForce`（6轴力）、`ToolVectorActual`/`ToolVectorTarget`（TCP位姿）、`TCPSpeedActual`、`RunningStatus`、`ErrorStatus`、`CurrentCommandId` 等字段。

#### 5.1.3 VisualServoController ([visual_servo_controller.py](file:///c:/DobotRuntime/dobot_move/robot/visual_servo_controller.py))

**职责：** 多线程缓存式视觉伺服控制器，实现 10-20Hz 的上位机视觉闭环修正。

**三线程架构：**

| 线程 | 职责 | 关键行为 |
|------|------|----------|
| `FeedbackThread`（DobotController 已有） | 持续更新 `latest_pose` → `pose_buffer` | 30004 端口 |
| `VisionThread` | 采集图像 + 低频 YOLO + 3D 定位 | 每 `yolo_every_n` 帧执行完整 YOLO，中间帧复用；按 `capture_time` 查询 `pose_buffer.pose_at(capture_time)` 预计算 `target_base` |
| `ServoThread` | 固定周期读取缓存 + 计算误差 + ServoP 下发 | 唯一允许发送 ServoP 的线程 |

**数据类：**

| 类 | 说明 |
|----|------|
| `TargetObservation` | 视觉目标观测数据结构（measurement_time/source/confidence/prediction_age/covariance） |
| `TargetCache` | 线程安全目标缓存（target_base 主路径 + target_end fallback），`update_from_detection` / `update_from_prediction` |

**安全门控参数（`ServoThread`）：**
- `prediction_age_gate = 0.5s`：预测超期拒绝
- `covariance_gate = 100.0 mm²`：协方差 trace 超限拒绝
- `prediction_max_step_ratio = 0.5`、`prediction_speed_ratio = 0.7`：预测时降速/限步长
- `max_consecutive_predictions = 5`：连续预测软停止
- `z_safety_limit`：Z 轴安全限位
- `max_error_mm = 300.0`：最大误差拒绝
- ServoP 队列延迟保护：超伺服周期自动跳帧降频

**自适应增益/步长：**
- `_adaptive_gain(error_mm)`：far/mid/near 三档增益（0.8/0.5/0.2）
- `_adaptive_max_step(error_mm)`：far/mid/near/fine 四档步长（35/18/6/2 mm）

**顶层方法：** `servo_to_target(log_callback) -> (success, final_error_mm, iterations)`

#### 5.1.4 ArcMotionController + ArcTrajectoryPlanner

**职责：** 原生 Dobot Arc() 圆弧运动。

| 类 | 方法 | 说明 |
|----|------|------|
| `ArcTrajectoryPlanner` | `.generate_waypoints()` | 生成圆弧路径航点 [x,y,z,rx,ry,rz]，支持 X/Y/Z 三轴旋转 |
| | `.get_arc_info()` | 返回 center/radius/start_angle/end_angle/arc_length |
| `ArcMotionController` | `.configure_arc(center, radius, start_angle, end_angle, ...)` | 强制 `num_waypoints=3`（Dobot Arc 需要首/中/末三点） |
| | `.execute(set_speed)` | 取中间点和终点，调用 `dashboard.Arc(mid, end)` |

#### 5.1.5 HandEyeCalibManager ([hand_eye_calib.py](file:///c:/DobotRuntime/dobot_move/robot/hand_eye_calib.py))

**职责：** 手眼标定矩阵管理。

| 方法 | 说明 |
|------|------|
| `.get_matrix(camera_type)` | 获取指定相机的 4x4 手眼矩阵 |
| `.set_matrix_from_poses(camera_type, cam_to_flange_pose)` | 由相机相对法兰位姿存储 |
| `.set_matrix_direct(camera_type, matrix_4x4)` | 将 4x4 矩阵转为位姿后存储 |
| `.reset_to_default(camera_type)` | 重置为默认标定 |

计算方式：`T_cam2flange = pose2matrix(cam_to_flange_pose)`（旧版双位姿格式自动迁移）

#### 5.1.7 transform_utils ([transform_utils.py](file:///c:/DobotRuntime/dobot_move/robot/transform_utils.py))

**职责：** 坐标变换工具函数（C++ 优先，Python 回退）。

| 函数 | 说明 |
|------|------|
| `euler2rot(rx, ry, rz, degree=True)` | 欧拉角 → 3x3 旋转矩阵（ZYX 顺序，优先 `dobot_core`） |
| `pose2matrix(x, y, z, rx, ry, rz)` | 位姿 → 4x4 齐次变换矩阵（优先 `dobot_core`） |

#### 5.1.8 motion_safety ([motion_safety.py](file:///c:/DobotRuntime/dobot_move/robot/motion_safety.py))

**职责：** 统一的运动目标校验网关。

**工作空间边界（mm，CR20A 默认）：** X/Y ∈ [-1900, 1900]，Z ∈ [-1200, 1200]
**姿态角边界：** [-360, 360] 度
**速度范围：** 1-100%（百分比），绝对速度上限 2000 mm/s

| 函数/类 | 说明 |
|---------|------|
| `MotionSafetyConfig` | 运动安全配置（工作空间/速度/偏移上限） |
| `MotionSafetyState` | 运动安全状态（只读缓存：连接/使能/急停/错误/反馈年龄） |
| `MotionValidationResult` | 校验结果（ok/code/message，`__bool__` 支持 `if not result:`） |
| `validate_absolute_pose(controller, pose, speed, ...)` | 绝对位姿校验链：长度6→finite→速度范围→工作空间→姿态角→机器人状态 |
| `validate_relative_delta(controller, offsets, coord_system, ...)` | 相对偏移校验：偏移上限(300mm/45°)→反馈新鲜度→投影终点校验 |
| `validate_servo_p_params(t, aheadtime, gain, servo_period)` | ServoP 参数 clamp：`t≥servo_period`，`aheadtime∈[20,100]`，`gain∈[200,1000]` |

**校验结果 code 定义：** 0=OK, 1=NaN, 2=长度, 3=速度, 4=加速度, 5=工作空间, 6=姿态角, 7=未连接, 8=未使能, 9=急停, 10=报警, 11=反馈过期, 12=相对偏移超限, 13=无法投影

#### 5.1.9 RobotPoseBuffer ([robot_pose_buffer.py](file:///c:/DobotRuntime/dobot_move/robot/robot_pose_buffer.py))

**职责：** 线程安全的位姿环形缓冲区，支持时间索引插值/外推。用于视觉伺服时间对齐。

| 方法 | 说明 |
|------|------|
| `.push(timestamp, pose)` | 写入 `(timestamp, pose)` 样本（perf_counter 单调秒） |
| `.pose_at(t)` | 按时间查询：空→(None,False)；单样本→退化；n≥2→二分查找区间插值/末尾线性外推（50ms 窗口） |
| `.latest()` | 返回最新样本 |

容量默认 200 样本，`deque(maxlen=200)` 滚动淘汰。

---

### 5.2 视觉感知模块 (vision)

#### 5.2.1 VisionSystem ([vision_system.py](file:///c:/DobotRuntime/dobot_move/vision/vision_system.py))

**职责：** 视觉系统主类，集成 YOLO 推理、深度计算、3D 定位、手眼标定和目标跟踪。

**关键数据类：**
- `FramePacket`（dataclass）：线程安全帧数据包（seq/timestamp/color_image/depth_image/capture_time/frame_timestamp_ms），不持有 pyrealsense2 frame 对象

**初始化流程：**
1. 加载配置，合并 `DEFAULT_PERFORMANCE_CONFIG`
2. 解析深度范围：D405 默认 0.07-0.8m，D435i 默认 0.5-2.2m
3. 解析 Z 轴过滤上限：`resolve_max_camera_z_mm`（D405→800mm / D435i→2200mm）
4. 加载手眼标定矩阵 `T_cam2flange`
5. 调用 `_initialize_onnx_model()` 加载 ONNX 模型（CUDA→CPU 回退）
6. 启动 RealSense pipeline：640×480@30，D405 强制 `enable_auto_exposure`
7. 初始化子组件：`BYTETracker` / `KalmanFilter3D` / `DepthProcessor`

| 方法 | 说明 |
|---------|------|
| `.connect_camera(serial_number, model_path, ...)` | 连接 RealSense 相机并加载 ONNX 模型 |
| `.capture_frames()` | 采集并对齐深度/彩色帧，过 `DepthProcessor` 滤波 |
| `.capture_numpy_packet(seq)` | 采集并返回 `FramePacket`（capture_time 在 wait_for_frames 返回后立即记录） |
| `.run_detection(color_image)` | YOLO 推理：letterbox预处理→session.run→后处理 |
| `.run_detection_tracked(color_image)` | YOLO 推理 + ByteTrack 跟踪 |
| `.calculate_object_position(depth, color, target)` | 深度计算 + 3D 定位（优先 C++，含中位数补偿+Z轴过滤） |
| `.calculate_object_position_smoothed(...)` | 含平滑的3D定位（detection/prediction/smoothed 三种来源） |
| `.convert_to_end_coords(camera_coords)` | 相机坐标 → 末端坐标（`T_cam2flange @ [X,Y,Z,1]`） |
| `.convert_to_base_coords(end_coords, pose)` | 末端坐标 → 基座坐标（`pose2matrix @ point_end`，ZYX） |
| `.reset_tracking()` | 重置 tracker / kalman / tracked_target_id |
| `.warmup_onnx()` | 用零张量做 dummy 推理消除 CUDA JIT 延迟 |

**GPU 推理回退链：**
1. 优先 `CUDAExecutionProvider + CPUExecutionProvider`
2. CUDA 注册但未激活 → 标记 "CPU (CUDA回退)"
3. `warmup_onnx` 首次推理失败 → 记录 `_CUDA_RUNTIME_FAILURE`（进程级），重建 CPU-only session
4. `preload_onnx_runtime_dlls` 预加载 cuDNN 9 的 `cudnn_engines_tensor_ir64_9.dll`

**模型格式自动识别：** 根据输出张量形状判断 — 第二输出为 `[N,32,H,W]` 时为分割模型；`dim1 < dim2` 为 yolov8 格式，否则为 yolo26 格式。

#### 5.2.2 BYTETracker ([tracker.py](file:///c:/DobotRuntime/dobot_move/vision/tracker.py))

**职责：** ByteTrack 多目标跟踪算法实现。

| 类/函数 | 说明 |
|---------|------|
| `iou_distance(atracks, btracks)` | 计算 IoU 代价矩阵（`1 - IoU`），向量化 |
| `linear_assignment(cost_matrix, thresh)` | 匈牙利算法匹配（`scipy.optimize.linear_sum_assignment`） |
| `STrack` | 单目标跟踪轨迹（含 8 维 bbox 卡尔曼滤波 `_BBoxKalmanFilter`） |
| `BYTETracker` | ByteTrack 主跟踪器（两阶段关联） |

**ByteTrack 算法：** 详见 §9.2

#### 5.2.3 KalmanFilter3D ([kalman_filter_3d.py](file:///c:/DobotRuntime/dobot_move/vision/kalman_filter_3d.py))

**职责：** 6 状态 3D Kalman 滤波器（位置 + 速度），恒速（CV）模型。

| 属性/方法 | 说明 |
|-----------|------|
| `.predict(dt)` | 预测步骤，`prediction_age += dt`，支持变 dt |
| `.update(z, dt)` | 更新步骤，含 Mahalanobis 距离门控（`d² > gate²` 拒绝） |
| `.prediction_age` | 距上次成功更新的累积时间 |
| `.gate_threshold` | Mahalanobis 距离门限（默认 3.0，`d² > 9` 拒收） |
| `.prediction_gate` | 预测超时门限（默认 0.5s，超时 `get_confidence` 衰减为 0） |
| `.max_miss_count` | 最大连续 miss 次数（默认 10，超限 `reset()` 重生） |
| `.get_covariance()` | 获取 3x3 位置协方差矩阵 |
| `.get_confidence()` | `1/(1+trace(P[:3,:3]))`，预测不可靠时为 0 |

**Camera Frame vs Base Frame：** `kalman_3d`（Camera Frame）标记为 TODO 弃用；D405 路径迁移到 `kalman_3d_base`（Base Frame）。

#### 5.2.4 DepthProcessor ([depth_processor.py](file:///c:/DobotRuntime/dobot_move/vision/depth_processor.py))

**职责：** 4 级 RealSense 深度滤波链。

| 滤波级 | 算法 | 默认参数 | 说明 |
|--------|------|----------|------|
| 1 | Decimation Filter | magnitude=2 | 降采样（默认关闭） |
| 2 | Spatial Filter | alpha=0.5, delta=20, magnitude=2 | 空间平滑 + 孔洞填充 |
| 3 | Temporal Filter | alpha=0.4, delta=20, persist_mode=2 | 时间平滑 + 持久化 |
| 4 | Hole Filling Filter | mode=1 | 孔洞填充 |

`process_depth_image` 是独立的 numpy 路径，用 `cv2.inpaint(INPAINT_NS)` 修补 0 值像素。

#### 5.2.5 CaptureWorker ([capture_worker.py](file:///c:/DobotRuntime/dobot_move/vision/capture_worker.py))

**职责：** 纯 Python 帧采集线程（无 Qt 依赖），供 Runtime 和 GUI 复用。

| 类 | 说明 |
|----|------|
| `CaptureWorker(threading.Thread)` | 后台帧采集线程（daemon=True） |
| `.run()` | 持续采集 `FramePacket`，加锁更新最新帧 |
| `.get_latest()` | 返回 `(FramePacket, capture_ms)` |

模块级别名：`CaptureThread = CaptureWorker`（向后兼容）

---

### 5.3 流程编排模块 (flow)

#### 5.3.1 FlowExecutor ([flow_executor.py](file:///c:/DobotRuntime/dobot_move/flow/flow_executor.py))

**职责：** 纯 Python 流程执行器，无 Qt 依赖。Qt 调用方应使用 `qt_workers.FlowThread` 包装。

**关键数据类/函数：**
- `FlowRunContext`：流程运行上下文（run_id/start_time/stop_event/module_timings/motion_generation）
- `normalize_module_type(module)`：兼容旧 `force_arc → arc_motion`
- `build_force_guard(params)`：构建归一化力保护配置（`mode="resultant_delta"`）
- `validate_grasp_flow_modules(modules)`：执行前校验（force_guard 阈值/相机前置/点位存在性/圆弧参数/段非全零/延时范围）
- `wait_for_flow_delay_or_signal(...)`：可被 stop/release/pause 中断的延时

**支持的模块类型：**

| 类型 | 说明 | 关键 params |
|------|------|-------------|
| `move` | 直线运动 | `target ∈ {initial_position, camera_detected, saved_point}`、`motion_type ∈ {MovL, MovJ}`、`point_name`、`speed`、`force_guard` |
| `arc_motion` | 圆弧运动 | `center_offset_z`、`radius`、`sweep_angle`、`arc_direction ∈ {cw, ccw}`、`speed` |
| `relative_move` | 相对移动 | `offsets[6]`、`coord_system ∈ {user, tool, joint}`、`motion_type ∈ {linear, joint}`、`speed`、`acceleration`、`cp` |
| `relative_path` | 连续相对路径（多段） | `segments[]`、`execution_mode ∈ {stop_each, queued}`、全局默认参数 |
| `camera` | 相机识别 | `camera_type ∈ {D435i, D405}` |
| `visual_servo` | 视觉伺服（D405 专用） | `servo_period`、增益三档、收敛阈值、最大迭代、安全限位 |
| `joint_move` | 关节旋转 | `offsets[6]`、`acceleration`、`speed` |
| `delay` | 延时 | `duration_s`、`wait_mode ∈ {time, modbus_or_timeout}` |

**`run()` 主循环数据流：**
```
run() -> FlowResult
  ├─ controller.acquire_motion("flow")
  ├─ _set_camera_test_flow_active(True)
  ├─ for module in grasp_flow_modules:
  │    ├─ 检查 stop_event / is_paused_ref
  │    ├─ normalize_module_type + build_force_guard
  │    ├─ 运动模块前置: get_feedback_health 检查
  │    ├─ 自动同步 is_enabled
  │    ├─ 按 type 分派执行
  │    │     ├─ camera: _detect_camera_object_for_flow → set_point
  │    │     ├─ visual_servo: VisualServoController.servo_to_target()
  │    │     ├─ move/arc/relative: controller.move_*/ArcMotionController
  │    │     └─ delay: wait_for_flow_delay_or_signal (modbus_or_timeout 传 release_event)
  │    └─ 失败 → _fail_module (FlowResult.failure, on_finished)
  ├─ FlowResult.success_result()
  └─ finally: _set_camera_test_flow_active(False), release_motion("flow")
```

**相机识别复用机制：** 若 `camera_test_workers` 中对应相机有活跃 worker，则通过 `get_flow_detection_snapshot` 复用其识别结果（避免第二条 pipeline）；否则懒导入 `CaptureWorker` 自建采集线程。

**relative_path 两种模式：**
- `queued`：先全部下发再统一等待，最后一段强制 `r=-1` 精确到达；启用 force_guard 时自动降级为 `stop_each`
- `stop_each`：逐段等待

#### 5.3.2 FlowLibrary ([flow_library.py](file:///c:/DobotRuntime/dobot_move/flow/flow_library.py))

**职责：** 版本化流程存储与选择。

| 常量 | 说明 |
|---------|------|
| `FLOW_SCHEMA_VERSION = 3` | 当前流程格式版本 |
| `DEFAULT_FLOW_ROLES` | 默认角色映射：`low_hook → flow-low-hook`、`high_hook → flow-high-hook`、`error_recovery → flow-error-recovery` |
| `SUPPORTED_CAMERA_TYPES = {"D435i", "D405"}` | |

**关键特性：**
- 角色 flow（`flow-low-hook`/`flow-high-hook`/`flow-error-recovery`）**不可重命名、不可删除**
- `_migrate_to_v3`：v2→v3 迁移，补 `flow_roles` + 缺失角色 flow + 修复悬空引用
- `save` 原子写：`.bak` 备份 + `.{name}.{uuid}.tmp` + `os.replace` + `os.fsync`
- `required_camera_types(modules)`：扫描 modules 分析所需相机（`visual_servo` 强制需要 D405）

#### 5.3.3 FlowResult ([flow_result.py](file:///c:/DobotRuntime/dobot_move/flow/flow_result.py))

**职责：** 结构化流程执行结果，供恢复策略决策。仅依赖 stdlib，可被 `runtime_agent.py` 无 Qt 导入。

| 类 | 说明 |
|----|------|
| `FailureKind(str, Enum)` | 失败分类：`VISION_PROCESS`/`ROBOT`/`CAMERA`/`FLOW`/`PROTOCOL`（继承 str 兼容字符串比较） |
| `FlowResult` | `success/code/message/failure_kind/failed_module_index/failed_module_name/recoverable` |
| `FlowResult.success_result()` | 构建成功结果 |
| `FlowResult.failure(...)` | 构建失败结果 |

#### 5.3.4 FlowReadiness ([flow_readiness.py](file:///c:/DobotRuntime/dobot_move/flow/flow_readiness.py))

**职责：** 无副作用的流程就绪性检查（不查询硬件、不采帧）。

| 类/函数 | 说明 |
|---------|------|
| `FlowReadinessResult` (frozen dataclass) | `ok/missing_devices/reasons`，`primary_failure_kind` 按优先级 robot > camera > flow |
| `check_flow_readiness(controller, vision_d435i, vision_d405, modules)` | 检查 controller 连接+反馈健康 + 所需相机可用 |

#### 5.3.5 其他 flow 组件

| 文件 | 说明 |
|------|------|
| `flow_step_list.py` | Qt 流程步骤列表组件（拖拽排序+状态图标），自定义 MIME `application/x-flow-step-index` |
| `qt_workers.py` | Qt 适配层：`FlowThread(QThread)` 包装 `FlowExecutor`，`RobotCmdThread(QThread)` 包装单次指令 |
| `workers.py` | 向后兼容 shim（导入会拉入 Qt） |
| `camera_test_worker.py` | shim → `vision.capture_worker` + `ui.camera_test_worker` |

---

### 5.4 运行时模块 (runtime)

#### 5.4.1 DobotRuntimeAgent ([runtime_agent.py](file:///c:/DobotRuntime/dobot_move/runtime/runtime_agent.py))

**职责：** 后台无头运行代理，设备监督、流程看门狗、生产状态机、健康状态发布和崩溃恢复。**无 Qt 依赖**。约 147KB。

**核心组件：**

| 组件 | 职责 |
|------|------|
| `RobotConnectionSupervisor` | 机器人 Dashboard/反馈连接保活（不触碰 Modbus），指数回退重连+jitter |
| `RuntimeProgramRunner` | 后台线程跑 motion flow，相机预检，动态超时监控 |
| `RuntimeStateStore` | 运行时诊断状态持久化（不恢复流程） |
| `SingleInstanceLock` | 跨进程单实例锁 |
| `RuntimeIpcServer` | IPC 服务器（双通道） |
| `ResetStrategy` | 状态感知复位 |
| `RecoveryPolicy` | 恢复策略判定 |
| `ProductionFlowRouter` | hook_type → flow_id 路由 |

**关键方法：**

| 方法 | 说明 |
|------|------|
| `.main()` | 入口函数（命令行参数解析 + `SingleInstanceLock` + 主循环） |
| `.tick()` | 单次循环：相机重载+ensure_modbus+supervisor.step+延迟reonline+磁盘检查+状态转换+write_health |
| `.run()` | `begin_boot`（判断恢复）→ `validate_startup_inputs` → 启动 IPC/Modbus → 循环 `tick()` |
| `.start_new_task(hook_type)` | **原子序列**（`_task_start_lock`）：校验→STARTING→创建context→build_request→start_request→RUNNING |
| `._on_production_flow_finished(result)` | 成功→HOLDING_HOOK(5)；失败按 failure_kind：ROBOT→111(永不恢复)、CAMERA→112、其他→110；可恢复则进 ERROR_RECOVERY |
| `._dispatch_command(cmd, mode, hook_type)` | RESETTING 守卫 + CMD_HOOK→`_handle_hook_command` + CMD_STOP→`_handle_pause_command` + CMD_RESET→`_handle_reset_command` |
| `._handle_reset_command()` | MANUAL_OFFLINE→reonline；HOLDING_HOOK/PAUSED/ERROR_STATES→RESETTING+ResetStrategy→STANDBY(2)/FLOW_ERROR(110) |
| `._enter_manual_offline()` | 停流程+Stop+关机器人+状态 MANUAL_OFFLINE |
| `.build_health_payload()` | schema_version=2，含 runtime/robot/modbus/ipc/publication/flow/production/startup_connection/process |

**生产状态机转换（详见 §9.4）：** IDLE/STANDBY →(40001=3)→ STARTING →(成功)→ RUNNING →(完成)→ HOLDING_HOOK(5)；→(失败)→ FLOW_ERROR(110)/ROBOT_ERROR(111)/CAMERA_ERROR(112)

**40001 单一所有权：** 生产模式下 40001 仅由生产状态机（`_set_production_state` via `MODBUS_STATUS_MAP`）写；调试模式由 `mark_modbus_program_finished` 写。

**延时放行：** `delay` 模块 + `wait_mode=modbus_or_timeout` 时，`on_progress` 写 40001=5 并 clear `release_event`；PLC 下 40001=1 时 `_dispatch_command` 检测到延时等待则 `release_event.set()` 放行而非复位。

**防递归恢复：** `ProductionTaskContext.recovery_started` 标志阻止同一任务二次派发恢复 hook；`run_recovery_sync` 故意不设 `on_finished`、不调 `on_production_finished`、不改 RuntimeState、保留原错误码。

#### 5.4.2 RuntimeWatchdog ([runtime_watchdog.py](file:///c:/DobotRuntime/dobot_move/runtime/runtime_watchdog.py))

**职责：** 外部看门狗进程，检测 Runtime 卡死后先尝试安全 Stop()，再重启。

| 类 | 说明 |
|----|------|
| `WindowsServiceController` | Windows SCM 适配器（`sc.exe` 命令封装），`restart(stop_timeout_s, ...)` |
| `RuntimeWatchdog` | 核心看门狗，`check_once(now) -> str` |

**`check_once` 算法：**
1. `lockout_path` 存在 → `"locked_out"`（已达重启上限，需人工）
2. service 模式：服务 STOPPED 且 stop_marker 存在 → `"intentionally_stopped"`；transition 中 → `"service_transition"`
3. 心跳新鲜（`now - heartbeat <= stale_after_s`）→ `"healthy"`
4. `RestartWindow.allow_and_record` 失败 → 写 lockout 文件 → `"locked_out"`
5. 流程曾活跃 → 独立 Dashboard Stop()
6. task 模式：`taskkill /T /F` + `schtasks /Run`；service 模式：`sc.exe` stop/start

**重启熔断：** `RestartWindow` 滚动窗口限流（默认 600s 内 3 次），超限写 `runtime_watchdog_lockout.json` 需人工介入。

**两种重启模式：** `task`（`schtasks /Run` + `taskkill`）与 `service`（`sc.exe` stop/start，带 stop_marker 识别故意停止）

#### 5.4.3 RuntimeResilience ([runtime_resilience.py](file:///c:/DobotRuntime/dobot_move/runtime/runtime_resilience.py))

**职责：** 韧性基础原语，供 Runtime 和 Watchdog 共享。

| 类/函数 | 说明 |
|---------|------|
| `RuntimeState(str, Enum)` | `STARTING/READY/RUNNING/WAITING_DELAY/MAINTENANCE_REQUESTED/MAINTENANCE/DEGRADED/RECOVERY_REQUIRED/STOPPING` |
| `atomic_write_json(path, payload, durable=False)` | 原子写入 JSON（tmp + os.replace，durable=True 时 fsync） |
| `RuntimeStateStore` | 运行时状态持久化（`begin_boot()` 判断是否需恢复，`mark_clean_shutdown()`） |
| `SingleInstanceLock` | 跨进程非阻塞锁（`msvcrt.locking` / `fcntl.flock`） |
| `RestartWindow` | 滚动窗口重启限流器（持久化到 JSON） |
| `flow_timeout_seconds(modules)` | 流程总超时 = `max(60, sum(模块超时)*1.2 + 30)` |
| `module_timeout_seconds(module)` | 按模块类型估算：delay/camera/visual_servo/relative_path/运动类 |
| `get_process_metrics(path)` | 返回 `{pid, thread_count, rss_mb, disk_free_mb}` |

#### 5.4.4 RuntimeIpcServer ([runtime_ipc.py](file:///c:/DobotRuntime/dobot_move/runtime/runtime_ipc.py))

**职责：** 本地 JSON Lines IPC 服务器，双通道架构。

| 常量 | 值 | 说明 |
|------|----|------|
| `DEFAULT_IPC_HOST` | `127.0.0.1` | 仅本地 |
| `DEFAULT_IPC_PORT` | 8765 | 主通道（FIFO 串行） |
| `DEFAULT_STOP_PORT` | 8766 | Stop 通道（旁路队列） |
| `ALLOWED_STOP_COMMANDS` | `{safe_stop, stop_current_task, stop_debug_flow}` | Stop 通道允许的命令 |

**双通道架构：**
- **主通道（8765）**：每客户端一线程 → 命令入 `_command_queue` → 单 worker `_command_loop` 串行执行 → 经 `response_queue` 回传。保证命令顺序，但长命令会阻塞后续
- **Stop 通道（8766）**：独立 listener，命令同步直接执行，**不进 FIFO**，确保即使主通道有长命令阻塞也能立即停止

**认证：** `secrets.compare_digest` 防 timing attack，token 从 `runtime_ipc.token` 文件加载（≥32 字符）

#### 5.4.5 ProductionState ([production_state.py](file:///c:/DobotRuntime/dobot_move/runtime/production_state.py))

**职责：** 生产状态机枚举（12 状态）和 Modbus 状态映射。

| 状态 | Modbus 40001 值 | 说明 |
|------|-----------------|------|
| `MANUAL_OFFLINE` | (缺失) | 手动下线 |
| `IDLE` | 0 | 空闲 |
| `STANDBY` | 2 | 待机 |
| `STARTING` | (缺失) | 启动中（保持原值） |
| `RUNNING` | 4 | 运行中 |
| `PAUSED` | 0 | 暂停 |
| `HOLDING_HOOK` | 5 | 提钩完成 |
| `RESETTING` | (缺失) | 复位中 |
| `ERROR_RECOVERY` | (缺失) | 错误恢复中 |
| `FLOW_ERROR` | 110 | 流程错误 |
| `ROBOT_ERROR` | 111 | 机器人错误 |
| `CAMERA_ERROR` | 112 | 相机错误 |

`ERROR_STATES = frozenset({FLOW_ERROR, ROBOT_ERROR, CAMERA_ERROR})`

#### 5.4.6 其他 runtime 组件

| 文件 | 类 | 说明 |
|------|-----|------|
| `production_context.py` | `ProductionTaskContext` | 单任务上下文，`hook_type` 在启动时 latched |
| `production_flow_router.py` | `ProductionFlowRouter` | `resolve_primary(hook_type)`：0→low_hook, 1→high_hook；`resolve_recovery()`→error_recovery |
| `recovery_policy.py` | `RecoveryPolicy` | `can_recover(result, controller)`：保守判定，ROBOT 故障永不恢复 |
| `reset_strategy.py` | `ResetStrategy` | `execute(source_state, ...)`：HOLDING_HOOK→撤离；PAUSED→Stop+撤离；ERROR→清错+使能+撤离 |
| `runtime_contract.py` | `CommandSpec` + `COMMAND_SPECS` | IPC 命令契约（35+ 命令），`validate_payload()` |
| `runtime_publication.py` | `RuntimePublicationStore` | 草稿→批准快照版本化发布，`publish_drafts(validator)` |
| `runtime_vision_debug.py` | `capture_vision_snapshot()` | 只读视觉诊断（帧+检测+坐标+标定+深度+性能） |
| `startup_connection.py` | `StartupConnectionState` | 启动设备就绪与故障锁定（5秒观察窗口） |

**RecoveryPolicy 判定条件：**
1. `result is None` → False
2. `not result.recoverable` → False
3. `failure_kind == ROBOT` → False（机器人故障永不恢复）
4. `controller` 未连接 → False
5. `get_feedback_health()` 非 ok → False
6. `RobotMode in {9,11}`（急停/故障）或 `ErrorStatus != 0` → False
7. 否则 True

---

### 5.5 通信模块 (communication)

#### 5.5.1 DobotModbusServer ([modbus_server.py](file:///c:/DobotRuntime/dobot_move/communication/modbus_server.py))

**职责：** 基于 `pymodbus` 3.6+ 的 Modbus TCP 服务器。

**寄存器协议：**

| 寄存器 | 地址 | 说明 |
|--------|------|------|
| `REG_CMD_STATUS` | 40001 | 命令/状态寄存器 |
| `REG_MODE` | 40002 | 运行模式（0=自动, 1=手动） |
| `REG_HEARTBEAT` | 40003 | 心跳（每秒 1/0 交替） |
| `REG_HOOK_TYPE` | 40004 | 提钩杆类型（0=低, 1=高） |

**命令值表：**

| 命令 | 值 | 说明 |
|------|----|------|
| `CMD_STOP` | 0 | 停止 |
| `CMD_RESET` | 1 | 复位 |
| `CMD_HOOK` | 3 | 执行流程 |

**状态值表：**

| 状态 | 值 | 说明 |
|------|----|------|
| `STATUS_IDLE` | 0 | 空闲 |
| `STATUS_STANDBY` | 2 | 待机 |
| `STATUS_RUNNING` | 4 | 运行中 |
| `STATUS_HOOK_OK` | 5 | 完成 |
| `STATUS_HOOK_ERR` | 110 | 流程错误 |
| `STATUS_ROBOT_ERR` | 111 | 机器人错误 |
| `STATUS_CAMERA_ERR` | 112 | 相机错误 |

**关键特性：**
- `_internal_write_signatures` 机制：区分"Runtime 内部写 40001"与"PLC 主站写"，避免回调误触发
- 心跳监控：40003 每秒 1/0 交替，超 3 秒无变化告警
- 非法 40004 防护：cmd==3 时若 40004 不在 {0,1}，拒绝启动并写 40001=110
- `write_status_register(status)`：从非事件循环线程同步写 40001（`run_coroutine_threadsafe` + `future.result(timeout=2.0)`）
- pymodbus 版本兼容：try/except 兼容 3.6.4+ 的 API 变化

#### 5.5.2 modbus_utils ([modbus_utils.py](file:///c:/DobotRuntime/dobot_move/communication/modbus_utils.py))

| 函数 | 说明 |
|------|------|
| `float_to_regs(value)` | float → 2 个 16-bit 寄存器（big-endian） |
| `regs_to_float(high, low)` | 反向转换 |

---

### 5.6 配置管理模块 (config)

#### 5.6.1 ConfigManager ([config_manager.py](file:///c:/DobotRuntime/dobot_move/config/config_manager.py))

**职责：** 统一配置管理，~907 行。支持环境变量覆盖、原子写入、缓存、执行快照和自动迁移。

**路径层级：**
- `_MODULE_DIR` = `dobot_move/config/`
- `_PACKAGE_DIR` = `dobot_move/`
- `_PROJECT_ROOT` = 项目根
- `USER_DATA_DIR` = `user_data/`（升级保留）

**环境变量覆盖（优先级：环境变量 > config.json > 代码默认值）：**

| 环境变量 | 覆盖字段 |
|----------|----------|
| `DOBOT_ROBOT_IP` | `robot_ip` |
| `DOBOT_MODBUS_PORT` | `modbus_port` |
| `DOBOT_MODBUS_SLAVE` | `modbus_slave_id` |
| `DOBOT_D435I_MODEL` | `camera.models.D435i` |
| `DOBOT_D405_MODEL` | `camera.models.D405` |
| `DOBOT_REMOTE_API_PORT` | `remote_api.port` |

**关键函数/类：**

| 函数/类 | 说明 |
|---------|------|
| `USER_DATA_DIR` | 用户数据目录（`user_data/`，升级保留） |
| `CONFIG_FILE` / `GRASP_FLOW_FILE` / ... | 数据文件路径常量 |
| `SUPPORTED_CAMERA_TYPES = ("D435i", "D405")` | 支持的相机类型 |
| `load_config()` | 加载配置（执行快照优先→缓存→读文件+备份恢复+环境变量覆盖） |
| `save_config(config)` | 原子写入（uuid 临时文件 + os.replace + 写前备份） |
| `reload_config()` | 使缓存失效并重新加载 |
| `use_config_snapshot(config)` | contextmanager，用 `contextvars` 固定执行上下文配置 |
| `check_config(verbose=True)` | 部署预检：校验 robot_ip/modbus_port/相机模型/标定/拍照位/点位/流程库 |
| `get_performance_config()` / `get_runtime_config()` / `get_remote_api_config()` / `get_visual_servo_config()` | 各段默认值 + 用户覆盖合并 |
| `get_robot_ip()` / `get_modbus_port()` / `get_modbus_slave_id()` / `get_photo_position()` | 各配置项 getter |
| `get_calibration(camera_type)` | 获取手眼标定（含旧格式自动迁移） |
| `get_camera_handeye_matrix(camera_type)` | 获取 4x4 手眼矩阵 |
| `resolve_camera_model_path(camera_type, model_path=None)` | 解析并校验 ONNX 模型路径 |
| `resolve_point(name, visited=None)` | 递归解析相对点位（基准+偏移），检测循环引用 |
| `get_initial_point()` | 解析 initial_point，回退到 photo_position |
| `_migrate_legacy_paths()` | 导入时自动执行，幂等迁移旧路径数据到 `user_data/` |

**ConfigService 类（单例）：** 防抖配置写入服务，500ms 单次触发 QTimer，避免高频编辑连续写盘。点位的增删改强制 flush。

**默认配置字典：**
- `DEFAULT_PERFORMANCE_CONFIG`：轮询间隔、缓存年龄、运动完成判定阈值、视觉伺服参数
- `DEFAULT_RUNTIME_CONFIG`：`ipc_host`/`ipc_port`(8765)/`ipc_command_timeout_s`/`startup_connect_timeout_s`
- `DEFAULT_REMOTE_API_CONFIG`：`host`(0.0.0.0)/`port`(8000)/`token`/`feedback_port`(30004)
- `DEFAULT_VISUAL_SERVO_CONFIG`：servo_period/三段增益/最大步长/YOLO频率/收敛停止开关

#### 5.6.2 AlarmHistory ([alarm_history.py](file:///c:/DobotRuntime/dobot_move/config/alarm_history.py))

**职责：** 线程安全的报警历史记录。

| 方法 | 说明 |
|------|------|
| `AlarmHistory(path, max_records=1000)` | 初始化 |
| `.add(source, code, level, description, solution, raw)` | 添加记录 |
| `.list_records()` | 列出所有记录 |
| `.clear()` | 清空 |

实现要点：`threading.Lock` 保护，JSON 数组存储，`max_records` 滚动截断，损坏文件隔离保留到 `.corrupt.<timestamp>`。

---

### 5.7 用户界面模块 (ui)

#### 5.7.1 DobotMainWindow ([gui_app.py](file:///c:/DobotRuntime/dobot_move/ui/gui_app.py))

**职责：** PySide6 主窗口，~1440 行。5 个 Mixin + 9 个导航页。

**Mixin 组合：**
```python
class DobotMainWindow(RobotControlMixin, VisionMixin, ModbusMixin,
                      PointManagementMixin, GraspFlowMixin, QMainWindow):
```

**9 个导航页：**
1. 生产监控（`ProductionMonitorPage`）
2. 配置中心（`ConfigCenterPage`）
3. 主功能（`MainControlPanel`）
4. 运动编辑（`MotionEditorPage`）
5. 点位管理（`PointManagementPage`）
6. Modbus 通信（`ModbusCommPage`）
7. 报警记录（`AlarmHistoryPage`）
8. 相机测试（`CameraTestPage`）
9. Runtime 调试（`RuntimeDebugPage`）

**关键属性：**
- `self._runtime_status_reader`（`RuntimeHealthReader`，stale_after_s=3.0）
- `self._runtime_ipc_client`（`RuntimeIpcClient`）
- `self._runtime_facade`（`RuntimeFacade`）
- `self._ipc_request_threads`（set，去重）
- `self._runtime_capabilities`（list，能力门控）

**关键方法：**
- `_send_runtime_ipc(command, data, on_success, quiet)`：异步 IPC 发送，命令去重
- `_send_runtime_ipc_stop(command, data, on_success)`：走 Stop 通道（8766），不去重
- `_poll_status()`：1s 轮询 Runtime 健康
- `on_emergency_stop()`：500ms 防抖，走 Stop 通道 `safe_stop`
- `_apply_capability_gating()`：根据 `capabilities` 禁用不支持的按钮

**能力门控（PR-C Task 6）：** `_CAPABILITY_BUTTON_MAP` 映射按钮属性 → IPC 命令名；`capabilities` 为空时全支持（兼容旧版）

#### 5.7.2 RuntimeFacade ([runtime_facade.py](file:///c:/DobotRuntime/dobot_move/ui/runtime_facade.py))

**职责：** 同步外观，封装 GUI 异步 Runtime IPC 调用，每个方法返回 `(success: bool, message: str)`。

**方法分类：**
- 机器人控制：`enable_robot`/`disable_robot`/`clear_alarms`/`connect_robot(ip)`/`set_collision_level`/`safe_stop()`/`clear_recovery`
- 运动：`move_to_point(name, motion_type, speed)`/`move_to_initial_position()`/`get_current_pose()`
- 相机：`connect_camera(cam_type)`/`disconnect_camera`/`camera_test`/`open_realtime_feedback`
- 调试流程：`run_step(flow_id, step_index)`/`run_flow`/`pause_flow`/`resume_flow`/`stop_flow`
- Modbus：`start_modbus`/`stop_modbus`

#### 5.7.3 RuntimeIpcClient ([gui_ipc_client.py](file:///c:/DobotRuntime/dobot_move/ui/gui_ipc_client.py))

**职责：** 同步短生命周期 IPC 客户端。

| 类 | 说明 |
|----|------|
| `RuntimeIpcClient(host, port, stop_port, timeout_s, auth_token, token_path)` | 每请求生成 uuid4，socket 短连接 |
| `.request(command, data)` | 普通通道 |
| `.request_stop(command, data)` | Stop 通道 |
| `RuntimeIpcRequestThread(QThread)` | QThread 异步执行单次 IPC 请求 |

#### 5.7.4 RuntimeHealthReader ([gui_runtime_status.py](file:///c:/DobotRuntime/dobot_move/ui/gui_runtime_status.py))

**职责：** 只读加载 `runtime_health.json`，不打开硬件不阻塞 IPC。

| 类/函数 | 说明 |
|---------|------|
| `translate_runtime_state(state)` | 状态中文化 |
| `runtime_state_color(state)` | 状态颜色（READY=绿/RUNNING=蓝/MAINTENANCE=黄/DEGRADED=红） |
| `RuntimeHealthSnapshot` (frozen dataclass) | `online/timestamp/age_s/runtime_state/robot_connected/...` |
| `RuntimeHealthReader(path, stale_after_s)` | `read()` 返回快照，文件缺失/损坏返回带 `read_error` 的快照 |

#### 5.7.5 qt_compat ([qt_compat.py](file:///c:/DobotRuntime/dobot_move/ui/qt_compat.py))

**职责：** PySide6 兼容层，统一 Qt 5/6 API 差异。将 `Signal`/`Slot`/`Property` 别名为 `pyqtSignal`/`pyqtSlot`/`pyqtProperty`，使代码保持 PyQt 写法。

#### 5.7.6 其他 UI 组件

| 文件 | 类 | 说明 |
|------|-----|------|
| `main_control_panel.py` | `MainControlPanel` | 主控面板（卡片式：连接配置+任务控制+机器人控制） |
| `gui_connection.py` | `ConnectionSignals`/`DaemonConnectionTask` | 守护线程连接器，generation 防竞态 |
| `gui_debug_widgets.py` | `ErrorTrendPlot` | 自定义绘制误差趋势图（deque(maxlen=100)） |
| `ui_theme.py` | - | 14 个颜色 token + ~400 行 QSS + 9 个导航图标 |
| `logging_config.py` | `setup_logging()` | root logger + StreamHandler(stdout) |
| `realtime_feedback_dialog.py` | `RealTimeFeedbackDialog` | 实时反馈对话框（30004 端口，100ms 刷新） |
| `camera_test_worker.py` | `CameraTestWorker(QThread)` | GUI 相机测试（组合 CaptureWorker，帧计数驱动检测频率） |
| `config_center_page.py` | `ConfigCenterPage`/`CalibMatrixDialog` | 配置中心（5类配置）+ 4x4 矩阵输入对话框 |
| `motion_editor_page.py` | `MotionEditorPage` | 运动编辑（8种模块参数面板 + 15列段表） |
| `production_monitor_page.py` | `ProductionMonitorPage` | 生产监控（4张状态卡+生产上下文面板） |
| `runtime_debug_page.py` | `RuntimeDebugPage` | 3 Tab 调试（状态概览+流程调试+视觉诊断） |

#### 5.7.7 Mixins

| Mixin | 职责 |
|-------|------|
| `RobotControlMixin` | 委托硬件命令给 `RuntimeFacade` |
| `VisionMixin` | 相机配置 UI（基于 Runtime 健康快照） |
| `ModbusMixin` | 只读 Modbus 状态（从 Runtime 健康） |
| `PointManagementMixin` | 点位 CRUD + 相对点位解析 |
| `GraspFlowMixin` | 抓取流程编辑（~788 行，最大 Mixin） |
| `StartupConnectionMixin` | 遗留兼容壳 |

---

### 5.8 远程API模块 (remote_api)

#### 5.8.1 RemoteApiServer ([app.py](file:///c:/DobotRuntime/dobot_move/remote_api/app.py))

**职责：** 独立 HTTP 服务，基于标准库 `ThreadingHTTPServer`，零新第三方依赖。

**端点：**

| 端点 | 方法 | 认证 | 说明 |
|------|------|------|------|
| `/api/v1/health` | GET | 免认证 | 服务健康（uptime/请求计数/错误计数/feedback_health） |
| `/api/v1/status` | GET | Bearer Token | 机器人综合状态 |
| `/api/v1/feedback/all` | GET | Bearer Token | 30004 完整反馈（位姿/力/关节/安全） |
| `/api/v1/modbus/registers` | GET | Bearer Token | Modbus 4 个寄存器 |
| `/api/v1/production/status` | GET | Bearer Token | 生产状态（读 runtime_health.json） |

**特性：**
- 旧路径 `/api/status` 等返回 **301 重定向** 到 v1（保留 query string）
- CORS `Access-Control-Allow-Origin: *`，支持 `allowed_ips` IP 白名单
- Token 认证用 `hmac.compare_digest` 防 timing attack，空 token 禁用认证
- `stop()` 通过守护线程调用 `_http_server.shutdown()`，避免与 `serve_forever()` 死锁

#### 5.8.2 其他 remote_api 组件

| 文件 | 类/函数 | 说明 |
|------|---------|------|
| `handlers.py` | `parse_feedback(fb)` | 解析 30004 numpy 结构化数组为 dict |
| | `build_status/build_feedback_all/build_health/build_production_status` | 响应构建器 |
| `feedback_worker.py` | `FeedbackWorker` | 30004 后台连接线程，health 三态：ok/stale/disconnected |
| `modbus_client.py` | `read_registers(host, port, slave_id, timeout)` | 兼容 pymodbus 2.x-3.6+ 多版本 API |
| `config.py` | - | 薄封装，委托给 `config_manager` |

---

### 5.9 Windows服务模块 (windows_service)

**职责：** Windows 服务封装，使用 WinSW 2.12 将 Runtime 和 Watchdog 注册为 Windows 服务。

| 文件 | 类/函数 | 说明 |
|------|---------|------|
| `service_config.py` | `RUNTIME_SERVICE_ID`/`WATCHDOG_SERVICE_ID` | 服务名常量 |
| | `build_runtime_service_xml(...)` | Runtime 服务 XML（`onfailure restart(10s)`，`resetfailure=10min`） |
| | `build_watchdog_service_xml(...)` | Watchdog 服务 XML（`<depend>DobotRuntimeService</depend>`，LocalSystem） |
| | `verify_winsw_binary(path)` | SHA256 校验 WinSW-x64.exe |
| `generate_config.py` | `main()` | CLI 生成 XML 配置 |
| `preflight.py` | `collect_preflight_errors()` | 非硬件预检（config/FlowLibrary/Python依赖/相机模型/端口） |

**服务依赖：** Watchdog 服务通过 `<depend>` 声明对 Runtime 服务的依赖，确保系统启动时 Runtime 先于 Watchdog 启动；Runtime 服务停止时 SCM 也会联动停止 Watchdog。

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
dets = dobot_core.yolo.postprocess_yolov8(outputs, original_size, scale, offset, new_size, num_classes, conf_threshold=0.25, iou_threshold=0.5)
dets = dobot_core.yolo.postprocess_yolo26(outputs, original_size, scale, offset, new_size, num_classes, conf_threshold=0.25)
masks = dobot_core.yolo.process_mask(protos, masks_in, bboxes, shape, scale, offset, new_size, threshold=0.5)

# 深度位置计算
pos = dobot_core.depth.calculate_object_position(depth_image, mask, bbox, fx, fy, cx, cy, depth_scale, min_depth, max_depth)
```

#### C++ 侧结构

| 头文件 | 函数 | 实现要点 |
|--------|------|----------|
| `transforms.h` | `euler2rot`/`pose2matrix`/`transform_point` | Rz·Ry·Rx 旋转顺序（ZYX 内旋），degree 先转弧度 |
| `nms.h` | `nms` | 经典贪心 NMS：按分数 stable_sort 后逐一保留 |
| `yolo.h` | `postprocess_yolov8`/`postprocess_yolo26`/`process_mask` | yolov8: cx,cy,w,h + NMS + 32 系数分割；yolo26: x1y1x2y2 无 NMS；含 `bilinear_resize` |
| `depth_position.h` | `calculate_object_position` | 掩码质心取深度，无效时退回 bbox 中位数；针孔模型反投影 |

**构建配置（CMakeLists.txt）：**
- `cmake_minimum_required(VERSION 3.15)`
- C++17（`CMAKE_CXX_STANDARD_REQUIRED ON`）
- `pybind11_add_module(dobot_core ...)` 包含 5 个源文件
- 输出目录：`LIBRARY_OUTPUT_DIRECTORY` 和 `RUNTIME_OUTPUT_DIRECTORY` 均为 `${CMAKE_CURRENT_SOURCE_DIR}/..`（项目根目录）

**构建脚本（[build_cpp.py](file:///c:/DobotRuntime/build_cpp.py)）：**
1. 路径解析：`project_root` / `cpp_dir` / `build_dir`
2. CMake 参数：`-DPYTHON_EXECUTABLE` + 可选 `-Dpybind11_DIR`
3. 执行 `python -m cmake -S <cpp_dir> -B <build_dir>`（使用 cmake Python 包）
4. 执行 `python -m cmake --build <build_dir> --config Release`
5. 搜索 `dobot_core*` 产物（Release/ 和 build/），复制 `.pyd`/`.so` 到项目根目录

**回退机制：** `dobot_core` 不可用时（未编译/不支持平台），所有函数自动回退到纯 Python 实现（`_euler2rot_py`/`_nms_py`/`_process_mask_py`/`_postprocess_yolov8_py`/`_postprocess_yolo26_py`）。

---

## 6. 关键类与函数索引

### 核心类

| 类名 | 模块 | 职责 |
|------|------|------|
| `DobotController` | `robot.robot_controller` | 机器人控制核心枢纽（~162KB） |
| `DobotApi` | `robot.dobot_api` | TCP 通信基类 |
| `DobotApiDashboard` | `robot.dobot_api` | Dashboard 命令通道 (29999)，130+ 方法 |
| `DobotApiFeedBack` | `robot.dobot_api` | 实时反馈通道 (30004)，1440 字节结构 |
| `VisualServoController` | `robot.visual_servo_controller` | 多线程视觉伺服控制器 |
| `VisionThread` | `robot.visual_servo_controller` | 视觉检测线程（低频 YOLO + 高频复用） |
| `ServoThread` | `robot.visual_servo_controller` | 伺服控制线程（唯一发 ServoP） |
| `TargetCache` | `robot.visual_servo_controller` | 线程安全目标缓存 |
| `TargetObservation` | `robot.visual_servo_controller` | 视觉目标观测数据结构 |
| `ArcMotionController` | `robot.arc_motion_controller` | 圆弧运动控制器 |
| `ArcTrajectoryPlanner` | `robot.arc_trajectory_planner` | 圆弧轨迹规划器 |
| `HandEyeCalibManager` | `robot.hand_eye_calib` | 手眼标定管理器 |
| `RobotPoseBuffer` | `robot.robot_pose_buffer` | 位姿环形缓冲区（时间索引插值） |
| `VisionSystem` | `vision.vision_system` | 视觉系统主类 |
| `FramePacket` | `vision.vision_system` | 线程安全帧数据包 |
| `BYTETracker` | `vision.tracker` | ByteTrack 多目标跟踪器 |
| `STrack` | `vision.tracker` | 单目标跟踪轨迹（含 bbox KF） |
| `KalmanFilter3D` | `vision.kalman_filter_3d` | 6 状态 3D Kalman 滤波器（CV 模型） |
| `DepthProcessor` | `vision.depth_processor` | 4 级深度滤波链 |
| `CaptureWorker` | `vision.capture_worker` | 纯 Python 帧采集线程 |
| `FlowExecutor` | `flow.flow_executor` | 流程执行器（无 Qt） |
| `FlowRunContext` | `flow.flow_executor` | 流程运行上下文 |
| `FlowLibrary` | `flow.flow_library` | 版本化流程库（v3 schema） |
| `FlowResult` | `flow.flow_result` | 结构化流程结果 |
| `FailureKind` | `flow.flow_result` | 失败分类枚举 |
| `FlowReadinessResult` | `flow.flow_readiness` | 就绪性检查结果 |
| `DobotRuntimeAgent` | `runtime.runtime_agent` | 后台运行代理（~147KB） |
| `RobotConnectionSupervisor` | `runtime.runtime_agent` | 机器人连接保活（指数回退） |
| `RuntimeProgramRunner` | `runtime.runtime_agent` | 后台流程执行（动态超时） |
| `RuntimeWatchdog` | `runtime.runtime_watchdog` | 外部看门狗 |
| `WindowsServiceController` | `runtime.runtime_watchdog` | Windows SCM 适配器 |
| `RuntimeStateStore` | `runtime.runtime_resilience` | 运行时状态持久化 |
| `SingleInstanceLock` | `runtime.runtime_resilience` | 跨进程单实例锁 |
| `RestartWindow` | `runtime.runtime_resilience` | 重启熔断窗口 |
| `RuntimeIpcServer` | `runtime.runtime_ipc` | IPC 服务器（双通道） |
| `ProductionState` | `runtime.production_state` | 生产状态机枚举（12 状态） |
| `ProductionTaskContext` | `runtime.production_context` | 生产任务上下文（hook_type latched） |
| `ProductionFlowRouter` | `runtime.production_flow_router` | 流程路由器 |
| `RecoveryPolicy` | `runtime.recovery_policy` | 恢复策略（保守判定） |
| `ResetStrategy` | `runtime.reset_strategy` | 复位策略（状态感知） |
| `RuntimePublicationStore` | `runtime.runtime_publication` | 草稿→批准快照发布 |
| `StartupConnectionState` | `runtime.startup_connection` | 启动设备就绪状态 |
| `DobotModbusServer` | `communication.modbus_server` | Modbus TCP 服务器 |
| `DobotMainWindow` | `ui.gui_app` | PySide6 主窗口（5 Mixin + 9 Pages） |
| `RuntimeFacade` | `ui.runtime_facade` | Runtime 外观模式 |
| `RuntimeIpcClient` | `ui.gui_ipc_client` | IPC 客户端（同步短连接） |
| `RuntimeIpcRequestThread` | `ui.gui_ipc_client` | QThread 异步 IPC |
| `RuntimeHealthReader` | `ui.gui_runtime_status` | Runtime 健康状态读取 |
| `RuntimeHealthSnapshot` | `ui.gui_runtime_status` | 健康快照（frozen dataclass） |
| `ConfigService` | `config.config_manager` | 防抖配置写入服务（单例） |
| `AlarmHistory` | `config.alarm_history` | 报警历史记录 |
| `RemoteApiServer` | `remote_api.app` | HTTP 服务主应用 |
| `APIHandler` | `remote_api.app` | REST 请求处理器 |
| `FeedbackWorker` | `remote_api.feedback_worker` | 30004 反馈后台线程 |

### 核心函数

| 函数 | 模块 | 说明 |
|------|------|------|
| `euler2rot(rx,ry,rz,degree)` | `robot.transform_utils` | 欧拉角 → 旋转矩阵（ZYX，C++优先） |
| `pose2matrix(x,y,z,rx,ry,rz)` | `robot.transform_utils` | 位姿 → 齐次矩阵（C++优先） |
| `validate_absolute_pose()` | `robot.motion_safety` | 绝对位姿安全校验 |
| `validate_relative_delta()` | `robot.motion_safety` | 相对偏移安全校验 |
| `validate_servo_p_params()` | `robot.motion_safety` | ServoP 参数 clamp |
| `atomic_write_json()` | `runtime.runtime_resilience` | 原子写入 JSON |
| `flow_timeout_seconds()` | `runtime.runtime_resilience` | 流程总超时预算 |
| `module_timeout_seconds()` | `runtime.runtime_resilience` | 模块超时预算 |
| `required_camera_types()` | `flow.flow_library` | 分析流程所需相机 |
| `resolve_point()` | `config.config_manager` | 递归解析点位 |
| `check_flow_readiness()` | `flow.flow_readiness` | 流程就绪性检查（无副作用） |
| `validate_grasp_flow_modules()` | `flow.flow_executor` | 执行前校验 |
| `build_force_guard()` | `flow.flow_executor` | 构建力保护配置 |
| `wait_for_flow_delay_or_signal()` | `flow.flow_executor` | 可中断延时 |
| `load_config()` / `save_config()` | `config.config_manager` | 配置加载/原子写入 |
| `use_config_snapshot()` | `config.config_manager` | 配置快照上下文管理器 |
| `check_config()` | `config.config_manager` | 部署预检 |
| `load_ipc_token()` | `runtime.runtime_ipc` | 加载 IPC 认证 token |
| `validate_payload()` | `runtime.runtime_contract` | IPC 命令契约校验 |
| `capture_vision_snapshot()` | `runtime.runtime_vision_debug` | 视觉诊断快照 |
| `read_registers()` | `remote_api.modbus_client` | Modbus 寄存器读取（多版本兼容） |
| `parse_feedback()` | `remote_api.handlers` | 解析 30004 反馈 |

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
    │ (5 Mixins)   │ │_facade   │ └─────┬──────┘
    └──────┬───────┘ │ipc_client│       │
           │         └────┬─────┘       │
           ▼              ▼             ▼
    ┌──────────────────────────────────────────┐
    │           robot/ (机器人控制)              │
    │  DobotController ← DobotApiDashboard     │
    │                 ← DobotApiFeedBack        │
    │                 ← VisualServoController   │
    │                 ← ArcMotionController     │
    │                 ← MotionSafety            │
    │                 ← RobotPoseBuffer         │
    │                 ← HandEyeCalibManager     │
    └──────────┬──────────────────┬────────────┘
               │                  │
               ▼                  ▼
    ┌──────────────────┐  ┌──────────────────┐
    │  vision/ (视觉)   │  │communication/    │
    │  VisionSystem    │  │  ModbusServer    │
    │  +Tracker        │  └──────────────────┘
    │  +KalmanFilter3D │
    │  +DepthProcessor │
    │  +CaptureWorker  │
    └────────┬─────────┘
             │
             ▼
    ┌──────────────────┐     ┌──────────────────┐
    │ config/ (配置)    │     │  flow/ (流程)     │
    │ ConfigManager    │◄────│  FlowExecutor     │
    │ ConfigService    │     │  FlowLibrary      │
    │ AlarmHistory     │     │  FlowResult       │
    └──────────────────┘     │  FlowReadiness    │
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
                             │ ResetStrategy     │
                             │ RuntimePublication│
                             └────────┬─────────┘
                                      │
                                      ▼
                             ┌──────────────────┐
                             │ remote_api/       │
                             │  Server + Handlers│
                             │  + FeedbackWorker │
                             │  + ModbusClient   │
                             └──────────────────┘
```

**关键依赖链：**

1. **GUI → Runtime IPC：** GUI 通过 `RuntimeIpcClient` + `RuntimeFacade` 与后台 Runtime 通信（TCP 127.0.0.1:8765/8766）
2. **GUI 状态读取：** `RuntimeHealthReader` 只读加载 `runtime_health.json`（1s 轮询），无 IPC 开销
3. **FlowExecutor → Robot + Vision：** 流程执行器调用 `DobotController`（运动）和 `VisionSystem`（识别）
4. **VisualServoController → Robot + Vision：** 视觉伺服依赖反馈位姿（`pose_buffer`）和目标检测（`TargetCache`）
5. **RuntimeAgent → Modbus + Robot + Flow：** 后台代理整合 Modbus 协议、机器人控制和流程执行
6. **VisionSystem → dobot_core (可选)：** C++ 加速模块可选，不可用时自动 Python 回退
7. **Remote API → 30004 Feedback + Modbus Client：** 只读查询，不暴露控制命令，不重复开服务
8. **transform_utils → dobot_core (可选)：** 坐标变换 C++ 加速，失败回退纯 numpy

---

## 8. 数据流与控制流

### 8.1 抓取流程数据流

```
拍照位 → D435i 粗识别 → 移动至 D435i 目标上方
→ 视觉伺服逼近 → D405 精细识别（掩码几何中心）
→ 计算目标点 → 移动至目标位置
→ 原生圆弧运动或相对移动（可选） → 抬升 → 放置
```

### 8.2 视觉伺服数据流（三线程时间对齐）

```
FeedbackThread (30004) ──→ latest_pose ──→ RobotPoseBuffer.push()
                                                    │
VisionThread ──→ YOLO检测 ──→ 3D定位 ──→ TargetCache.update_from_detection()
                                        │         │
                                        │    pose_buffer.pose_at(capture_time)
                                        │         │  (按采集时刻插值位姿)
                                        └──→ target_base (预计算)
                                                    │
ServoThread ──→ read target_base + current_pose ──→ 误差计算
                                                    │
                                        ┌───────────┴───────────┐
                                        │ 自适应增益 + 步长钳位  │
                                        │ + 预测门控 + 安全钳位  │
                                        └───────────┬───────────┘
                                                    │
                                        ServoP 下发 → 机器人运动
```

### 8.3 Modbus 控制流

```
外部主站 PC ──→ Modbus TCP 写 40001=3 ──→ DobotModbusServer
                                                    │
                                        _action_callback (区分内部写/主站写)
                                                    │
                                        _on_modbus_command_delegate (入队)
                                                    │
                                        _command_worker_loop (daemon)
                                                    │
                                        _dispatch_command → start_new_task
                                                    │
                                        ProductionFlowRouter.resolve(hook_type)
                                                    │
                                        RuntimeProgramRunner.start_request
                                                    │
                                        FlowExecutor.run() (后台线程)
                                                    │
                                        写 40001=4(运行) / 5(完成) / 110(错误)
```

### 8.4 IPC 控制流（双通道）

```
GUI ──→ RuntimeIpcClient ──→ TCP 127.0.0.1:8765 ──→ RuntimeIpcServer
                                                            │
                                                _command_queue (FIFO)
                                                            │
                                                _command_loop (单 worker 串行)
                                                            │
                                                _handle_ipc_command ──→ RuntimeAgent
                                                            │
                                                response ──→ GUI

GUI(紧急停止) ──→ TCP 127.0.0.1:8766 ──→ Stop通道(旁路队列) ──→ 立即执行
                                                    (safe_stop/stop_current_task/stop_debug_flow)
```

### 8.5 生产状态机转换

```
IDLE/STANDBY ──40001=3──► STARTING ──start_request成功──► RUNNING
                                       │
                                       │ 40001=0 ──► PAUSED ──40001=3──► RUNNING
                                       │ 40001=1 ──► RESETTING ──成功──► STANDBY(2)
                                       │                                              └─失败──► FLOW_ERROR(110)
                                       │ 流程成功
                                       └──► HOLDING_HOOK(5) ──40001=1──► RESETTING ──► STANDBY
                                       │ 流程失败
                                       ├──► ROBOT_ERROR(111, 永不恢复)
                                       ├──► FLOW_ERROR(110) ──可恢复──► ERROR_RECOVERY ──► FLOW_ERROR(110)
                                       └──► CAMERA_ERROR(112) ──可恢复──► ERROR_RECOVERY ──► CAMERA_ERROR(112)

40002 0→1: 任意状态 ──► MANUAL_OFFLINE (停流程+Stop+关机器人+禁重连)
40002=0 + 40001=1: MANUAL_OFFLINE ──► (重连) ──► STANDBY(2)
```

### 8.6 外部看门狗控制流

```
RuntimeWatchdog (独立进程)
    │
    ├─ 周期读 runtime_health.json 的 timestamp (心跳)
    │
    ├─ 心跳新鲜 (now - heartbeat <= stale_after_s) → healthy
    │
    ├─ 僵死 → RestartWindow.allow_and_record
    │           ├─ 允许 → 独立 Dashboard Stop() → 重启 (task/service)
    │           └─ 超限 → 写 lockout.json → locked_out (需人工)
    │
    └─ service 模式: 服务 STOPPED + stop_marker → intentionally_stopped (不重启)
```

---

## 9. 核心算法说明

### 9.1 运动完成判定算法（`wait_for_motion_completion`）

**判定优先级（4 级）：**

1. **力到位保护检查**（force_guard，最高优先级）
   - 计算 `_force_delta_norm`（Fx/Fy/Fz 合力增量 = `norm(current_force[:3] - baseline_force[:3])`）
   - 超过 `threshold_n` 且达到 `debounce_samples` 次连续 → 触发 `Stop()`
   - 调用 `_wait_after_stop_settled` 等待稳定，返回 True（reason=`"force_triggered"`）

2. **官方模式判定**（command_id）
   - 条件：有 command_id 且 30004 反馈新鲜
   - `CurrentCommandId == command_id` 且 `RobotMode == 5`，连续 `stable_samples` 次 → 完成（reason=`"motion_done"`）
   - **仅走此路径**，跳过通用判定

3. **30004 反馈辅助判定**
   - 运动状态守卫：必须先观察到运动（`_has_seen_motion_state`，通过速度或 RunningStatus 判定）
   - 绝对运动：速度归零（`< motion_done_speed_threshold`）+ 位姿到位（`pos_diff < pose_tolerance` 且 `rot_diff < rot_tolerance`）+ 连续 `stable_samples` 次
   - 相对运动：速度归零 + `RunningStatus==0` 或 `RunQueuedCmd==0` + 连续 `stable_samples` 次

4. **Dashboard 兜底**
   - 仅当 30004 反馈不新鲜（`snapshot_health != "ok"`）时
   - `RobotMode==5` 完成；`==9` 自动清错（最多 3 次）；`==7/8` 运行中

**settle_time 守卫：** `_motion_command_sent_time` 后的 settle 时间内跳过判定。

### 9.2 ByteTrack 多目标跟踪算法

```
detections
  ├─ score >= track_thresh (0.5) → dets_high (STrack 列表)
  └─ score <  track_thresh       → dets_low

# 第一阶段：tracked_stracks × dets_high
for t in tracked_stracks: t.predict()   # bbox KF 预测
cost = iou_distance(tracked_stracks, dets_high)  # 1 - IoU
matches, u_track, u_det = linear_assignment(cost, match_thresh=0.8)  # 匈牙利
  → 匹配成功: tracked.update(det), state="tracked"
  → 未匹配 track: state="lost", 移入 lost_stracks
  → 未匹配 det:  作为 new_tracks 候选

# 第二阶段：lost_stracks × dets_low (二次匹配)
cost_low = iou_distance(lost_stracks, stracks_low)
matches_low = linear_assignment(cost_low, match_thresh)
  → 匹配成功: lost.update(det), state="tracked", 移回 tracked_stracks

# 清理
tracked_stracks = [t for t in tracked if state=="tracked"] + new_tracks
_remove_lost(): frame_id - t.frame_id > track_buffer(30) → removed
return [t for t in tracked_stracks if state=="tracked"]
```

- 空 detections 时所有 tracked 直接转 lost
- `STrack` 内部用 `_BBoxKalmanFilter`（8 维 `[x1,y1,x2,y2,vx1,vy1,vx2,vy2]`）做 bbox 预测

### 9.3 3D Kalman 滤波算法

**状态向量：** `[x, y, z, vx, vy, vz]`（6 维，位置+速度）
**模型：** 恒速（Constant-Velocity, CV）

```
update(z, dt=None):
  if not initialized:
      x[:3] = z; initialized=True; miss_count=0; prediction_age=0
      return x[:3]
  # 1. predict (时间更新), 用传入的 dt 重建 F/Q
  predict(dt)
  # 2. Mahalanobis 门控 (基于预测状态)
  y = z - H@x
  S = H@P@H.T + R
  d_sq = y.T @ inv(S) @ y
  if d_sq > gate_threshold²(=9):
      miss_count += 1
      if miss_count >= max_miss_count(=10): reset(); return z   # 重生
      return x[:3]        # 拒收测量, 保留预测
  # 3. 测量更新
  K = P@H.T@inv(S)
  x = x + K@y
  P = (I - K@H)@P
  miss_count=0; prediction_age=0
  return x[:3]
```

- **变 dt 支持：** `predict/update` 均接受 `dt` 参数，由 `VisionSystem._kalman_step_dt` 用 `perf_counter` 计算
- **置信度衰减：** `get_confidence = 1/(1+trace(P[:3,:3]))`，`prediction_age > prediction_gate(0.5s)` 时返回 0

### 9.4 YOLO 推理流程

```
image
  → preprocess_image_yolov8   # letterbox(640×640, pad=114), BGR→RGB, /255, HWC→NCHW
  → session.run(None, {input_name: input_tensor})   # ONNX Runtime, CUDA 优先
  → postprocess_yolov8
       ├─ model_format=="yolo26"  → _postprocess_yolo26_py (端到端, 无 NMS, 输出 [1,300,38])
       └─ model_format=="yolov8"  → _postprocess_yolov8_py (解析 [37,8400], NMS)
            │  (优先 dobot_core.yolo C++ 实现, 失败回退 Python)
            ↓
       detections: [{bbox, score, class_id, class_name, mask}, ...]
  → filter_detections_by_area (面积比 < 0.005 过滤)
```

**模型格式自动识别：** 根据输出张量形状判断 — 第二输出为 `[N,32,H,W]` 时为分割模型；`dim1 < dim2` 为 yolov8 格式，否则为 yolo26 格式。

**掩码生成：** `masks = sigmoid(masks_coeff @ protos_flat)`，resize 到 640×640 → 裁剪 letterbox padding → resize 到原图 → 二值化 → 裁剪到 bbox 内。

### 9.5 深度位置计算算法

```
calculate_object_position(depth_frame, color_frame, target):
  1. 优先 dobot_core.depth.calculate_object_position (C++)
     ├─ 掩码质心取深度
     ├─ 无效时退回 bbox 内有效深度的中位数 (nth_element)
     └─ 针孔模型反投影: X = (u - cx) * depth / fx, 单位 mm
  2. Python 回退: extract_mask_point_cloud_with_median_compensation
     ├─ 掩膜内无效深度用中位数补偿
     └─ 反投影成 3D 点云
  3. _reject_camera_z_over_limit: Z 超过 max_camera_z_mm 则丢弃
     ├─ D405: 800mm
     └─ D435i: 2200mm
```

### 9.6 视觉伺服安全门控链

```
ServoThread._loop:
  1. 读取当前位姿 (get_current_pose_from_feedback)，过期跳过
  2. _resolve_target_base:
     ├─ Gate 1: source=="prediction" 且 prediction_age > 0.5s → 拒绝
     ├─ Gate 2: covariance is not None 且 trace > 100mm² → 拒绝
     └─ Fallback: target_end + current_pose → convert_to_base_coords
  3. 计算误差 error_mm = norm(target_base[:3] - current_pose[:3])
  4. 安全检查: error_mm > 300mm 跳过
  5. 收敛判断: error_mm < converge_threshold → hold + ServoP + 返回 success
  6. 计算指令位姿: cmd_pos = current_pose[:3] + e * gain
  7. _apply_prediction_policy: prediction 时降速/限步长 + 连续预测软停止
  8. _safety_clamp: 距离超 max_step 缩放；Z < z_safety_limit 返回 None
  9. 队列延迟保护: last_servo_ms > servo_period*1000 跳帧
  10. validate_servo_p_params clamp 后下发 ServoP
  11. 连续失败处理 (3 次暂停 1 周期)
  12. 迭代上限检查 (max_iterations)
```

---

## 10. 配置体系

### 10.1 配置文件位置

| 文件 | 位置 | 说明 |
|------|------|------|
| `config.json` | `user_data/config.json` | 现场配置（标定/点位/IP/模型路径） |
| `grasp_flow_modules.json` | `user_data/grasp_flow_modules.json` | 用户编辑的流程库（v3 schema） |
| `alarm_history.json` | `user_data/alarm_history.json` | 运行时报警记录 |
| `runtime_health.json` | `user_data/runtime_health.json` | Runtime 健康状态（schema_version=2） |
| `runtime_state.json` | `user_data/runtime_state.json` | Runtime 诊断状态（不恢复流程） |
| `runtime_publication.json` | `user_data/runtime_publication.json` | Runtime 发布状态（草稿→批准快照） |
| `runtime_ipc.token` | `user_data/runtime_ipc.token` | IPC 认证 token（≥32 字符） |
| `runtime_agent.lock` | `user_data/runtime_agent.lock` | 后台进程单实例锁 |
| `robot_control.lock` | `user_data/robot_control.lock` | GUI 与后台共享的机器人控制租约 |
| `runtime_watchdog_restarts.json` | - | 看门狗最近 10 分钟的重启记录 |
| `runtime_watchdog_lockout.json` | - | 重启次数超限后的人工恢复锁 |
| `config.example.json` | `dobot_move/config/config.example.json` | 配置示例模板 |

### 10.2 核心配置项

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `robot_ip` | string | `"192.168.5.1"` | 机器人 IP 地址 |
| `modbus_port` | int | `502` | Modbus TCP 服务器端口 |
| `modbus_slave_id` | int | `5` | Modbus 从站地址 |
| `photo_position` | float[6] | `[0,0,0,0,0,0]` | 拍照位 [x,y,z,rx,ry,rz]（mm/deg） |
| `target_offset` | float[3] | `[0,0,0]` | 抓取目标偏移 [dx,dy,dz]（mm） |
| `camera.models.D435i` | string | `""` | D435i ONNX 模型绝对路径 |
| `camera.models.D405` | string | `""` | D405 ONNX 模型绝对路径 |
| `calibration.D435i.cam_to_flange_pose` | float[6] | `[0,0,0,0,0,0]` | D435i 相机相对法兰位姿 |
| `calibration.D405.cam_to_flange_pose` | float[6] | `[0,0,0,0,0,0]` | D405 相机相对法兰位姿 |
| `points` | object | `{}` | 点位表（首次运行自动生成三个默认点位） |
| `user_index` / `tool_index` | int | `0` | 用户/工具坐标系索引 |

### 10.3 性能配置（`performance` 块）

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `flow_wait_poll_interval` | 0.05 | 流程等待轮询间隔（s） |
| `robot_mode_dashboard_fallback_interval` | 1.0 | Dashboard 查询冷却间隔（s） |
| `pose_cache_max_age` | 0.3 | 位姿缓存最大年龄（s） |
| `motion_settle_time` | 0.15 | 运动后最小稳定时间（s） |
| `motion_done_speed_threshold` | 1.0 | 线速度归零阈值（mm/s） |
| `motion_done_rotation_speed_threshold` | 1.0 | 角速度归零阈值（°/s） |
| `motion_done_pose_tolerance` | 2.0 | 位姿到位容差（mm） |
| `motion_done_rotation_tolerance` | 2.0 | 旋转到位容差（°） |
| `motion_done_stable_samples` | 3 | 连续稳定采样次数 |
| `motion_done_use_feedback` | true | 是否使用 30004 反馈辅助判定 |
| `feedback_stale_fail_age` | 2.0 | 反馈断流失败判定时间（s） |

### 10.4 Runtime 配置（`runtime` 块）

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `ipc_host` | `127.0.0.1` | IPC 服务器监听地址 |
| `ipc_port` | 8765 | IPC 主通道端口 |
| `ipc_stop_port` | 8766 | IPC Stop 通道端口 |
| `ipc_command_timeout_s` | 5.0 | IPC 命令超时（s） |
| `ipc_token_path` | `user_data/runtime_ipc.token` | IPC 认证 token 路径 |
| `health_path` | `user_data/runtime_health.json` | 健康状态文件路径 |
| `service_stop_marker_path` | `user_data/runtime_service_stopped.json` | 服务停止标记路径 |
| `startup_connect_timeout_s` | 5.0 | 启动连接观察窗口（s） |
| `camera_retry_interval_s` | 10.0 | 相机重连间隔（s） |

### 10.5 Remote API 配置（`remote_api` 块）

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `host` | string | `"0.0.0.0"` | HTTP 监听地址 |
| `port` | int | `8000` | HTTP 监听端口 |
| `token` | string | `""` | Bearer Token，为空禁用认证 |
| `feedback_port` | int | `30004` | 30004 反馈端口 |
| `feedback_reconnect_interval_s` | float | `2.0` | 反馈断流后重连间隔（s） |
| `feedback_stale_ok_s` | float | `0.3` | 反馈新鲜阈值（s） |
| `feedback_stale_fail_s` | float | `2.0` | 反馈失效阈值（s） |
| `modbus_client_timeout_s` | float | `3.0` | Modbus 客户端读取超时（s） |
| `modbus_host` | string | `"127.0.0.1"` | Modbus 客户端目标主机 |
| `allowed_ips` | array | `[]` | IP 白名单（空数组不限制） |

### 10.6 环境变量覆盖

优先级：**环境变量 > config.json > 代码默认值**

| 环境变量 | 覆盖字段 |
|----------|----------|
| `DOBOT_ROBOT_IP` | `robot_ip` |
| `DOBOT_MODBUS_PORT` | `modbus_port` |
| `DOBOT_MODBUS_SLAVE` | `modbus_slave_id` |
| `DOBOT_D435I_MODEL` | `camera.models.D435i` |
| `DOBOT_D405_MODEL` | `camera.models.D405` |
| `DOBOT_REMOTE_API_PORT` | `remote_api.port` |

### 10.7 配置升级迁移

`config_manager._migrate_legacy_paths()` 在导入时自动执行：
- 将旧位置数据（`dobot_move/config.json`、`dobot_move/gui_mixins/grasp_flow_modules.json` 等）迁移到 `user_data/`
- 幂等操作：目标已存在时跳过
- 保留原文件（复制，非移动）
- 旧版双位姿标定格式（`tool_base_calib_pose` + `cam_base_calib_pose`）自动迁移为 `cam_to_flange_pose`

---

## 11. 安全机制

| 机制 | 说明 |
|------|------|
| **运动互斥锁** | `acquire_motion(owner)`/`release_motion(owner)`，可重入，流程和 Modbus 运动互斥执行 |
| **急停独立连接** | 通过独立临时 TCP 连接发送 EmergencyStop，避免主连接锁阻塞 |
| **急停始终优先** | 急停触发时立即设置 stop_event，流程线程马上停止下发；500ms 防抖 |
| **运动安全校验** | `validate_absolute_pose()`/`validate_relative_delta()` 校验工作空间/姿态角/速度范围 |
| **ServoP 参数 clamp** | `validate_servo_p_params()` 确保 t/aheadtime/gain 在安全范围 |
| **视觉伺服安全** | Z 轴安全限位 + 最大误差拒绝(300mm) + 队列延迟保护 + 预测门控(0.5s) + 协方差门控(100mm²) |
| **跨进程控制租约** | `SingleInstanceLock` 保证 GUI 与 Runtime 互斥占用机器人控制权 |
| **IPC 认证** | Token 认证（`secrets.compare_digest` 防 timing attack）+ Stop 通道旁路（独立端口 8766） |
| **配置防抖** | `ConfigService` 500ms 防抖，避免频繁磁盘 I/O |
| **配置原子写** | `save_config` 用 uuid 临时文件 + os.replace + 写前备份 |
| **看门狗** | 流程超时检测 + 反馈断流先停 + 崩溃恢复锁 + 外部看门狗卡死检测 |
| **重启熔断** | `RestartWindow` 限制 600s 窗口期内连续重启 3 次，超限写 lockout.json 需人工 |
| **生产状态机** | 严格状态转换，错误状态分类（FLOW/ROBOT/CAMERA），RESETTING 拒绝除 STOP 外命令 |
| **恢复策略** | `RecoveryPolicy` 保守判定，ROBOT 故障永不恢复，任何机器人健康疑虑即拒绝 |
| **防递归恢复** | `ProductionTaskContext.recovery_started` 标志阻止二次派发恢复 hook |
| **40001 单一所有权** | 生产模式下 40001 仅由生产状态机写；内部写签名区分避免回调误触发 |
| **非法 40004 防护** | cmd==3 时若 40004 不在 {0,1}，拒绝启动并写 40001=110 |
| **服务停止标记** | service 模式下停止写 stop_marker，看门狗据此识别"故意停止"避免误重启 |
| **力到位保护** | 运动中监控 ActualTCPForce，Fx/Fy/Fz 合力增量超阈值即 Stop 并继续下一步 |
| **三点共线校验** | MovC 圆弧运动前校验三点不共线（tolerance=0.5mm） |
| **连接代际机制** | `_connection_generation` 防止并发连接竞态导致旧连接覆盖新连接 |

---

## 12. 依赖清单

### Python 依赖（基于 `requirements_lock.txt`，99 个包）

#### 核心业务依赖

| 包 | 锁定版本 | 用途 |
|----|----------|------|
| `numpy` | 2.4.1 | 数值计算基础（深度图/bbox/掩码） |
| `scipy` | 1.17.0 | 科学计算（匈牙利算法/卡尔曼滤波） |
| `opencv-python` / `opencv-contrib-python` | 4.13.0.90 | 计算机视觉处理 |
| `pillow` | 12.1.0 | 图像 IO |
| `open3d` | 0.19.0 | 3D 点云处理（深度/标定） |
| `transforms3d` | 0.4.2 | 3D 变换（与 C++ transforms 互补） |
| `torch` | 2.11.0 | 深度学习推理后端 |
| `torchvision` | 0.26.0 | 视觉模型（YOLO 预处理） |
| `ultralytics` | 8.4.27 | YOLOv8 训练/推理框架 |
| `onnx` | 1.20.1 | ONNX 模型格式 |
| `onnxruntime` | 1.24.3 | ONNX 推理引擎（CPU） |
| `onnxslim` | 0.1.90 | ONNX 模型精简 |
| `lapx` | 0.9.4 | 线性指派（ByteTrack 多目标跟踪） |

#### 硬件与通信

| 包 | 锁定版本 | 用途 |
|----|----------|------|
| `pyrealsense2` | 2.56.5.9235 | Intel RealSense 深度相机 SDK |
| `pyserial` | 3.5 | 串口通信（夹爪） |
| `python-can` | 4.6.1 | CAN 总线通信 |
| `pymodbus` | 3.12.1 | Modbus 协议（TCP/RTU 服务端与客户端） |
| `minimalmodbus` | 2.1.1 | Modbus RTU 简化客户端（夹爪） |

#### GUI 框架

| 包 | 锁定版本 | 用途 |
|----|----------|------|
| `PySide6` | (wheels/) | **实际代码使用**（`qt_compat.py` 导入） |

> **注：** `requirements_lock.txt` 锁定的是 `PyQt6` 6.11.0，但实际代码 `qt_compat.py` 导入的是 `PySide6`。`wheels/` 目录同时提供 `pyside6-6.11.1` 和 `pyqt6-6.11.0` wheel 包用于离线安装。

#### Web / 远程 API

| 包 | 锁定版本 | 用途 |
|----|----------|------|
| `Flask` | 3.1.2 | 远程 API Web 框架（备选） |
| `Werkzeug` | 3.1.5 | Flask WSGI 工具库 |
| `dash` | 3.4.0 | 数据可视化 Web 应用 |
| `plotly` | 6.5.2 | 交互式图表 |
| `requests` | 2.32.5 | HTTP 客户端 |

#### 构建 / 工具

| 包 | 锁定版本 | 用途 |
|----|----------|------|
| `cmake` | 4.3.2 | C++ 模块构建（被 `build_cpp.py` 调用） |
| `pybind11` | 3.0.4 | Python/C++ 绑定 |
| `pytest` | 9.0.3 | 测试框架 |
| `ConfigArgParse` | 1.7.1 | 配置/命令行参数解析 |
| `PyYAML` | 6.0.3 | YAML 配置解析 |
| `psutil` | 7.2.2 | 进程/系统监控（`get_process_metrics`） |

#### GPU 可选依赖（`wheels/` 目录）

| 包 | 用途 |
|----|------|
| `onnxruntime-gpu` | 1.26.0，GPU YOLO 推理（NVIDIA GPU） |
| `nvidia-cublas-cu12` / `nvidia-cudnn-cu12` / `nvidia-cuda-runtime-cu12` 等 | CUDA 12.x 运行时库 |

### 硬件依赖

| 设备 | 型号 | 用途 |
|------|------|------|
| 机械臂 | Dobot CR20A 系列 | TCP/IP 协议控制，默认 IP `192.168.1.50` |
| 中距相机 | Intel RealSense D435i | 粗定位，深度 0.5-2.2m |
| 近距相机 | Intel RealSense D405 | 精细识别（掩码几何中心），深度 0.07-0.8m |
| 力传感器 | Dobot 内置六轴力传感器 | TCP 力到位保护 |
| GPU（可选） | NVIDIA 计算能力 6.0+（Pascal 及以上） | YOLO 推理加速 |

### 构建依赖（可选）

- CMake 3.15+
- C++17 编译器（Windows: Visual Studio Build Tools; Linux: GCC/Clang）
- NVIDIA 驱动 >= 525.60.13（GPU 推理）

---

## 13. 测试体系

项目包含 **61 个测试文件**，覆盖各核心模块。测试框架使用 `pytest`。

### 测试分类

| 分类 | 数量 | 测试文件 | 覆盖范围 |
|------|------|----------|----------|
| Runtime 核心 | 10 | `test_runtime_agent`/`test_runtime_contract`/`test_runtime_e2e_no_qt`/`test_runtime_facade`/`test_runtime_handlers`/`test_runtime_ipc`/`test_runtime_no_qt_import`/`test_runtime_publication`/`test_runtime_resilience`/`test_runtime_vision_debug` | Agent/IPC/韧性/状态机/无Qt |
| 视觉/感知 | 11 | `test_capture_time_advance`/`test_d435i_z_limit`/`test_flow_camera_detection`/`test_frame_packet_capture_time`/`test_kalman_gate`/`test_kalman_variable_dt`/`test_target_base_semantic`/`test_target_observation`/`test_tracker`/`test_vision_robot_timestamp_align`/`test_visual_servo_params` | 跟踪/滤波/相机模型/时间对齐 |
| 机器人/运动 | 8 | `test_dobot_api_transport`/`test_motion_safety`/`test_point_resolution`/`test_pose_buffer_*`(3)/`test_robot_pose_buffer`/`test_prediction_control_policy` | TCP/IP/安全/位姿缓冲/插值 |
| Flow 流程 | 5 | `test_flow_delay`/`test_flow_executor_callbacks`/`test_flow_library`/`test_flow_readiness`/`test_flow_recovery_policy` | 执行器/库/恢复/就绪性 |
| GUI | 5 | `test_gui_entries`/`test_gui_ipc_stop_client`/`test_gui_runtime_ownership`/`test_gui_runtime_status`/`test_gui_safe_stop_button` | IPC/状态/安全停止 |
| Modbus | 4 | `test_00_modbus_hook_relative`/`test_modbus_callback_ownership`/`test_modbus_deadlock`/`test_modbus_utils` | 服务器/客户端/死锁/回调 |
| 生产状态机 | 4 | `test_production_debug_flow_separation`/`test_production_flow_roles`/`test_production_state_machine`/`test_production_telemetry` | 状态机/角色/遥测 |
| 相机模型 | 2 | `test_camera_model_controls`/`test_camera_model_loading` | 模型加载/控件 |
| Windows 服务 | 2 | `test_windows_service_config`/`test_windows_service_scripts` | 服务配置/脚本 |
| 时钟/时序 | 2 | `test_clock_domain_unified`/`test_measurement_age` | 时钟域/测量年龄 |
| 其他 | 8 | `test_calib_matrix_input`/`test_config_manager`/`test_feedback_cache`/`test_hook_type_register`/`test_maintenance_display`/`test_remote_api_handlers`/`test_startup_connection`/`test_stop_channel` | 标定/配置/反馈/钩子/远程API |

**命名约定：**
- 文件统一以 `test_` 前缀命名
- `test_00_modbus_hook_relative.py` 使用数字前缀 `00_` 确保最先执行
- 多个测试聚焦横切关注点：时间戳对齐（`*_timestamp_align`）、死锁/所有权（`*_deadlock`/`*_ownership`）、回退策略（`*_recovery_policy`）、无 Qt 依赖（`*_no_qt`）

**辅助文件：**
- `conftest.py`：仅做 `sys.path` 注入，使 `dobot_move` 包可导入
- `__init__.py`：空

### 运行测试

```bash
pytest tests/ -v
```

---

## 14. 部署脚本

### 14.1 公共模块 ([windows_service_common.ps1](file:///c:/DobotRuntime/scripts/windows_service_common.ps1))

被所有服务脚本 dot-source。定义：
- 常量：`$script:RuntimeServiceName = "DobotRuntimeService"`、`$script:WatchdogServiceName = "DobotRuntimeWatchdog"`
- 函数：`Assert-Administrator`、`Resolve-DobotProjectRoot`、`Resolve-DobotPython`、`Backup-AndDisableLegacyTasks`、`Restore-LegacyTasks`、`Invoke-WinSW`、`Test-LocalTcpPortAvailable`、`Stop-And-UninstallServiceWrapper`

### 14.2 安装脚本 ([install_windows_services.ps1](file:///c:/DobotRuntime/scripts/install_windows_services.ps1))

**参数：**
- `-ProjectRoot`（默认 `C:\DobotRuntime`）
- `-PythonExe`（默认 `<ProjectRoot>\.venv\Scripts\python.exe`）
- `-ServiceUser`（默认 `.\DobotRuntimeSvc`）
- `-CreateServiceUser`（自动创建本地用户并生成 32 位强密码）
- `-ForceReinstall`（强制重装）
- `-ConfigureFirewall`（创建 "Dobot Modbus" TCP 502 和 "Dobot Remote API" TCP 8000 入站规则）

**执行流程：**
1. 检查管理员权限、Python 导入和 WinSW 哈希
2. 创建或验证 `DobotRuntimeSvc`，自动生成强密码
3. 生成 `runtime_ipc.token`（48 字节随机 Base64）并限制文件权限
4. 备份并禁用旧计划任务
5. 端口检查（IPC 8765/8766/Modbus 502）
6. ACL 授权（项目根只读，user_data/logs 修改权限，token 文件严格权限）
7. 安装并启动 Runtime + Watchdog 服务
8. 调用 `test_windows_services.ps1` 验证

### 14.3 卸载/回滚/测试脚本

| 脚本 | 说明 |
|------|------|
| `uninstall_windows_services.ps1` | 卸载 Watchdog + Runtime 服务（先 Watchdog 后 Runtime），移除防火墙规则，可选 `-RemoveToken` |
| `rollback_windows_services.ps1` | 卸载服务 + 从 `scheduled-task-backup` 恢复旧计划任务（`-StartLegacyTasks`） |
| `test_windows_services.ps1` | 服务健康验证：校验 WinSW 哈希、服务状态、健康文件新鲜度（≤5s）、IPC ping（带 token） |

### 14.4 已废弃脚本

| 脚本 | 说明 |
|------|------|
| `install_runtime_task.ps1` | 用 `Register-ScheduledTask` 注册旧计划任务，已推荐改用 `install_windows_services.ps1` |
| `_diag.ps1` | 空文件 |

---

> 本文档基于项目源码深度分析生成，最后更新：2026-07-15
