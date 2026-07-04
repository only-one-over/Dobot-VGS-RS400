# 架构

## 项目概述

本项目是一个 Dobot 视觉引导机器人控制应用。它提供 PyQt6 桌面 UI，用于连接 Dobot 机器人、操作双 RealSense 相机、使用 YOLO/ONNX Runtime 检测目标、将相机检测结果转换为机器人坐标、编辑抓取流程模块，以及执行运动、原生圆弧、相对移动和视觉伺服工作流。

该仓库还包含一个可选的 C++/pybind11 模块 `dobot_core`，用于加速视觉热路径，如 YOLO 后处理、深度定位计算、非极大值抑制和坐标变换。当原生模块未构建时，Python 应用应继续正常工作。

## 目录结构

```text
.
├── dobot_move/                  # 主 Python 包和 PyQt6 应用
│   ├── gui_app.py               # 主窗口、标签页、生命周期、Worker 连接
│   ├── main_control_panel.py    # 提取的主控制面板控件
│   ├── gui_mixins/              # 按功能区域划分的 UI 行为 mixin
│   ├── workers.py               # 用于初始化、监控、流程和相机测试的 QThread Worker
│   ├── robot_controller.py      # Dobot 运动/状态编排
│   ├── dobot_api.py             # Dobot Dashboard/Feedback Socket API 封装
│   ├── vision_system.py         # RealSense、ONNX 推理、跟踪、3D 定位
│   ├── config_manager.py        # 运行时 JSON 配置服务和点位/标定访问
│   ├── runtime_agent.py         # 无界面生产后台
│   ├── runtime_watchdog.py      # 进程外健康看门狗
│   ├── runtime_resilience.py    # 后台状态、锁和恢复基础设施
│   ├── ui_theme.py              # 共享的 PyQt 调色板和样式表辅助工具
│   └── config.json              # 运行时配置、标定、点位、性能参数
├── cpp_core/                    # 可选的 C++17 pybind11 加速模块
├── docs/                        # 项目文档
├── build_cpp.py                 # 原生扩展构建辅助脚本
├── requirements.txt             # Python 依赖
├── test_yolo26_bbox.py          # 当前根目录下的视觉回归测试/脚本
└── DobotControl.spec            # PyInstaller 打包规范
```

## 模块职责

- `gui_app.py`：拥有 `QApplication` 入口、`DobotMainWindow`、标签页组合、UI 生命周期、状态刷新和信号连接。
- `main_control_panel.py`：提供机器人连接、相机连接、抓取执行、碰撞等级、暂停/恢复和错误清除的主控制控件。
- `gui_mixins/`：按功能分离的行为 mixin，包括机器人控制、视觉、Modbus 从站服务、点位管理、多流程编辑和启动连接协调。
- `workers.py`：在 UI 线程之外运行慢速或重复工作，包括流程执行、相机测试显示、机器人命令 Worker 和 D435i 低帧率识别。
- `robot_controller.py`：协调 Dobot Dashboard/Feedback API、运动命令、安全状态、Modbus 从站集成、运动所有权、安全状态和位姿解析。
- `vision_system.py`：拥有相机启动、RealSense 帧捕获、ONNX 模型加载、YOLO 后处理、跟踪、深度处理、平滑和坐标转换。
- `config_manager.py`：集中管理 `dobot_move/config.json` 的读写，包括机器人 IP、Modbus 从站端口、标定、点位和手眼矩阵。
- `runtime_agent.py`：生产环境无界面入口，负责设备监督、流程执行、健康状态和崩溃恢复锁。
- `runtime_watchdog.py`：独立进程外看门狗，检测后台卡死，必要时先独立 Stop 再重启任务。
- `runtime_resilience.py`：运行状态持久化、单实例锁、重启窗口、资源指标和动态超时预算。
- 根目录 `runtime_agent.py`、`runtime_watchdog.py`：仅为旧启动命令保留的薄兼容入口，不包含业务实现。
- `cpp_core/`：在原生代码中镜像部分 Python 视觉数学运算以提升性能。必须保留 `vision_system.py` 使用的输入/输出契约。

## 数据流

1. 用户在 `DobotMainWindow` 中操作 PyQt6 UI。
2. UI 事件调用功能 mixin 或 `MainControlPanel` 信号。
3. 机器人操作通过 `DobotController` 流转，然后进入 `DobotApiDashboard` 和 `DobotApiFeedBack`。
4. 相机操作为 D435i 和/或 D405 创建 `VisionSystem` 实例，并从 `camera.models` 读取该相机的模型路径。
5. `VisionSystem` 先校验并加载对应 ONNX 模型，再打开 RealSense 管线、捕获帧、运行推理、跟踪目标、估算深度，并通过手眼标定转换相机坐标。
6. 检测到的基座坐标通过 `config_manager.py` 更新默认点位，如 `d435i` 和 `d405`。
7. `FlowLibrary` 管理 `schema_version=2` 的流程集合、当前编辑流程和主流程；`FlowThread` 接收流程快照，解析点位并协调机器人运动、视觉检测、视觉伺服、相对移动和原生圆弧操作。
8. UI 更新通过 Qt 信号返回，保持主线程响应。

GUI 和后台启动时均先启动 Modbus，再并发连接机器人及主流程引用的 D435i/D405。设备连接由后台线程执行，5 秒截止只负责发布启动故障，不强制终止仍在执行的连接任务；迟到成功可更新设备状态，但不会自动清除 `111/112` 或运行流程。

## 30004 反馈缓存

`_feed_loop()` 持续接收 30004 端口反馈数据并缓存以下字段：

| 缓存字段 | 30004 字段 | 类型 | 描述 |
|---------|-----------|------|------|
| `latest_pose` | ToolVectorActual | float[6] | 当前 TCP 位姿 (x,y,z,rx,ry,rz) |
| `latest_tcp_speed` | TCPSpeedActual | float[6] | 当前 TCP 速度 (vx,vy,vz,wx,wy,wz) |
| `latest_robot_mode` | RobotMode | int | 机器人模式 |
| `latest_running_status` | RunningStatus | int | 运行状态（0=空闲） |
| `latest_run_queued_cmd` | RunQueuedCmd | int | 队列命令数 |
| `latest_current_command_id` | CurrentCommandId | int | 当前执行指令 ID |
| `latest_tool_vector_target` | ToolVectorTarget | float[6] | 目标 TCP 位姿 |
| `latest_q_actual` | QActual | float[6] | 实际关节角度 |
| `latest_q_target` | QTarget | float[6] | 目标关节角度 |

所有字段在 `feed_lock` 内更新，通过 `get_motion_feedback_snapshot(max_age)` 统一读取。

反馈包校验：`TestValue == 0x123456789abcdef`，校验失败时不更新缓存，递增 `_feed_packet_drops` 计数器。

## FlowRunContext

`FlowRunContext` 是单次流程执行的上下文数据类：

| 字段 | 类型 | 描述 |
|------|------|------|
| `run_id` | str | 唯一标识 |
| `start_time` | float | 流程开始时间 |
| `current_module_index` | int | 当前模块索引 |
| `stop_event` | threading.Event | 停止事件 |
| `module_timings` | list | 每步耗时记录 |
| `motion_generation` | int | 运动代数（每次运动+1，用于相机缓存失效） |
| `_flow_detection_cache` | dict | 相机识别结果缓存 |

FlowThread 在 `run()` 开始时注册为 `controller._active_flow_thread`，在 `finally` 中释放。

## 运动互斥锁

`acquire_motion(owner)` / `release_motion(owner)` 确保流程和 Modbus 运动互斥执行：

- 流程执行时持有 `"flow"` 锁
- Modbus 运动持有 `"modbus"` 锁
- 急停始终优先，不受锁限制
- `wait_for_motion_completion()` 接受 `stop_checker` 参数，每轮轮询检查停止信号

## 运动完成判定

`wait_for_motion_completion()` 采用命令 ID 优先短路机制：

- **有 command_id 且 30004 新鲜时**：仅走官方模式判定（`CurrentCommandId == command_id && RobotMode == 5`），判定完成后直接返回 True，跳过通用速度/状态判定
- **无 command_id 或 30004 失效时**：走 30004 反馈状态机兜底（速度归零+位姿到位/运行状态完成+连续稳定）
- **30004 反馈断流时**：走 Dashboard RobotMode 兜底

## send_relative_command 统一封装

`send_relative_command()` 封装了所有相对移动命令的发送、响应解析和 command_id 追踪：

- 支持 `wait=True`（发送+等待完成）和 `wait=False`（仅发送，返回 response_code 和 command_id）
- queued 模式通过 `wait=False` 批量下发，最后统一等待
- 统一传入 `user_index`/`tool_index` 坐标系参数
- 统一日志、响应码校验、r/cp 互斥处理

## ServoP 队列保护

视觉伺服控制器内置 ServoP 队列延迟保护：

- 当 `last_servo_ms > servo_period * 1000`（TCP 往返超过伺服周期）时跳过当前帧，避免队列堆积
- 连续 3 次 ServoP 失败时暂停 1 个伺服周期后重试
- 成功时重置连续失败计数器

## user/tool 统一参数

所有应用层运动命令（MovJ、MovL、MovC、Arc、RelMovLUser/Tool、RelMovJUser/Tool）统一从 `config.json` 读取 `user_index` 和 `tool_index` 并传入对应 API 参数：

- 配置默认值：`user_index=0`, `tool_index=0`
- `RelJointMovJ` 不支持 user/tool 参数（官方 API 签名无此参数）

应用层点动页面、控制器方法和监控定时器已移除；`dobot_api.py` 仍保留通用 `MoveJog` SDK 封装，供底层兼容使用。

## 急停独立连接

`_emergency_stop_direct(mode)` 通过独立临时 TCP 连接（端口 29999）发送 `EmergencyStop`：

- 优先使用独立连接，避免主 Dashboard 连接 `__globalLock` 阻塞
- 响应码校验：code==0 返回成功；code!=0 返回失败走主连接兜底；空响应（超时）返回成功但记录"已发送未确认"
- 主连接作为备份，同样校验响应码
- 急停触发时立即设置 `software_emergency_active = True`，不等待响应确认
- 同时设置 `stop_event`，流程线程马上停止下发
- 急停按钮始终可点击，内部 500ms 时间戳防抖，不受命令执行状态禁用

## Modbus 异步执行

`_modbus_dispatch_motion(func, name)` 将 Modbus 运动命令投递到独立线程：

- `40001=1` 在非流程运行时投递回初始点复位，完成后写 `2`
- `40001=3` 在非流程运行时请求执行保存的运动流程
- `40001=0` 始终直接停止当前流程/运动，不排队
- 流程普通运行时忽略 `1/3`；信号延时阶段的 `1` 只用于放行下一步
- `_modbus_exec_lock` 确保同一时间只有一个 Modbus 运动在执行
- Modbus 状态刷新不被长时间运动阻塞

## 7×24 后台韧性

后台采用两层监督：

1. `DobotRuntimeAgent` 进程内监督机器人反馈、Modbus、相机和流程模块。
2. `DobotRuntimeWatchdog` 进程外检查 `runtime_health.json`，处理主进程卡死。

`runtime_state.json` 只保存诊断检查点。若上次退出不干净，后台进入 `RECOVERY_REQUIRED` 并保持 `40001=110`，不会恢复或重放运动；PLC 必须重新执行 `0→1→2→3`。

GUI 和后台通过 `robot_control.lock` 竞争控制租约，后台自身另用 `runtime_agent.lock` 防止重复实例。反馈断流且流程正在运动时，顺序固定为：设置流程停止事件、发送 Dashboard `Stop()`、写机器人故障状态、关闭连接并退避重连。

流程看门狗按模块类型计算截止时间。延时模块使用配置时长加余量，相机和视觉伺服按采集/迭代预算，运动模块使用保守上限；超时后停止流程并写 `40001=110`。

## 依赖

- 运行时 Python 依赖列在 `requirements.txt` 中。
- RealSense 操作需要 Intel RealSense SDK 和兼容的 D435i/D405 设备。
- D435i 和 D405 可通过 `camera.models.D435i`、`camera.models.D405` 配置独立 ONNX 模型；未配置时回退到 `dobot_move/best.onnx`。
- 模型必须具有固定正整数尺寸的 NCHW 输入，并输出当前后处理支持的三维 YOLO 检测张量；实例分割模型还需提供掩码输出。
- GUI、流程线程和后台代理都通过 `VisionSystem(camera_type=...)` 使用同一份相机级配置。配置模型缺失或不兼容时初始化失败，不切换到其他相机模型。
- 机器人控制期望可达的 Dobot Dashboard 和 Feedback 端口；文档中的默认值提及 Dashboard `29999` 和 Feedback `30004`。
- Modbus 默认值存储在 `config.json` 中，典型 TCP 端口为 `502`。
- C++ 加速依赖 CMake、C++17 编译器、pybind11 和 Python ABI 兼容性。

## 扩展点

- 在 `workers.FlowThread` 中添加新的抓取流程模块类型，并在抓取流程 mixin 中添加相应的 UI 编辑行为。
- 通过 `config_manager.py` 添加新的点位/配置字段，并处理迁移/默认值。
- 通过扩展 `VisionSystem` 添加特定相机的检测行为，同时保留 D435i/D405 角色分离。
- 通过暴露兼容的 pybind11 函数并使用 Python 回退行为保护调用来添加 C++ 加速。
- 将更多 UI 面板从 `gui_app.py` 提取为 `dobot_move/` 或未来 UI 目录下的专用控件。

## 风险点

- 机器人运动是安全关键的。错误的坐标转换、标定、单位或点位解析可能导致不安全的运动。
- 多个文件中的现有中文文本出现乱码损坏。编辑这些文件时如果不谨慎处理编码，可能使恢复更加困难。
- `gui_app.py` 仍然很大，仍然混合了 UI 组合、生命周期、状态和部分功能连接。
- `config.json` 既是运行时状态又是持久化配置；来自 UI/Worker 路径的并发写入可能导致过期或丢失更新。
- RealSense、ONNX Runtime、CUDA provider 可用性、Dobot 网络状态和 C++ 扩展 ABI 都对环境敏感。
- 根目录下的生成/构建产物（如 `build/`、`Release/` 和 `.pyd` 文件）可能掩盖纯源代码变更。

## 重构建议

- 将剩余的标签页构建从 `gui_app.py` 移至专用控件，保持 `DobotMainWindow` 作为组装器。
- 将流程执行逻辑从 `workers.FlowThread` 移至具有可测试模块处理器的服务。
- 添加配置写入防抖或单一保存服务，避免多个 UI 路径直接写入。
- 在确认预期的测试夹具和硬件/模型假设后，将根目录下的 `test_yolo26_bbox.py` 移至 `tests/`。
- 添加 PyInstaller 和原生扩展兼容性的打包/构建文档。
- TODO：为 `config.json` 定义稳定的模式版本和迁移规则。
