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

```bash
git clone https://github.com/only-one-over/Dobot-VGS-RS400.git
cd Dobot-VGS-RS400
python -m venv .venv && .venv\Scripts\activate      # Windows
pip install -r requirements.txt
python run.py                                          # 启动 GUI
```

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
