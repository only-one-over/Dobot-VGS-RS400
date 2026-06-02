# 项目精简优化与文件夹重组 Spec

## Why
项目经过多轮迭代后，存在文件散落、重复配置、模块职责不清、缺少包结构等问题，导致维护成本高、新人上手困难、打包配置混乱。需要系统性地精简项目逻辑并规范文件夹排布。

## What Changes
- 清理根目录散落的配置文件（`config.json`、`grasp_flow_modules.json`），统一到 `dobot_move/` 包内
- 删除 `TCP-IP-Python-V4-main/` 官方参考目录（非项目运行依赖）
- 删除根目录 `CODE_WIKI.md`（文档应随项目源码走）
- 将 `files/alarmController.py` 和 `files/alarmServo.py` 纯数据文件转为仅保留 JSON 版本
- 提取 `modbus_server.py` 和 `modbus_client.py` 中重复的浮点编解码工具函数到公共模块
- 为 `dobot_move` 包添加 `__init__.py`，导出核心类
- 修复 `config_manager.py` 使用相对路径导致 CWD 敏感的问题
- 添加 `.gitignore` 忽略 `__pycache__/`、`build/`、`dist/`、`*.pyc`
- 将视觉系统硬编码的标定参数迁移到 `config.json`
- 精简 `gui_app.py` 中的内联线程类，提取到独立模块 `workers.py`

## Impact
- Affected specs: 所有依赖 `dobot_move` 包的模块
- Affected code: `config_manager.py`, `modbus_server.py`, `modbus_client.py`, `vision_system.py`, `gui_app.py`, `dobot_api.py`, 项目根目录文件

## ADDED Requirements

### Requirement: 统一配置文件位置
系统 SHALL 将所有运行时配置文件（`config.json`、`grasp_flow_modules.json`）统一存放在 `dobot_move/` 包目录内，根目录不再散落配置文件。

#### Scenario: 配置文件路径一致
- **WHEN** 程序启动时
- **THEN** `config_manager.py` 基于模块文件所在目录解析配置路径，不依赖 CWD

### Requirement: 清理非必要目录和文件
系统 SHALL 移除以下非项目运行依赖的内容：
- 根目录 `TCP-IP-Python-V4-main/`（官方参考实现，非运行依赖）
- 根目录 `CODE_WIKI.md`（文档应随源码走）
- 根目录 `config.json` 和 `grasp_flow_modules.json`（与包内重复）
- `files/alarmController.py` 和 `files/alarmServo.py`（纯数据文件，仅保留 JSON 版本）

#### Scenario: 根目录整洁
- **WHEN** 查看项目根目录
- **THEN** 仅包含 `dobot_move_python/` 目录和 `.gitignore`

### Requirement: 公共工具函数去重
系统 SHALL 将 `modbus_server.py` 和 `modbus_client.py` 中重复的 `_float_to_regs` / `_regs_to_float` 函数提取到 `dobot_move/modbus_utils.py` 公共模块。

#### Scenario: Modbus 浮点编解码复用
- **WHEN** 任何模块需要 Modbus 浮点编解码
- **THEN** 从 `modbus_utils.py` 导入，无重复实现

### Requirement: 包结构规范化
系统 SHALL 为 `dobot_move` 包提供 `__init__.py`，导出核心类 `DobotController`、`VisionSystem`、`DobotModbusServer`、`DobotModbusClient`。

#### Scenario: 包导入可用
- **WHEN** 外部代码执行 `from dobot_move import DobotController`
- **THEN** 成功导入，无需手动 `sys.path.insert`

### Requirement: 配置路径 CWD 无关
`config_manager.py` SHALL 使用 `os.path.dirname(__file__)` 定位配置文件，而非依赖当前工作目录。

#### Scenario: 任意 CWD 启动
- **WHEN** 从不同工作目录启动程序
- **THEN** 配置文件仍能正确加载

### Requirement: 视觉标定参数可配置
视觉系统的手眼标定参数 SHALL 从 `config.json` 读取，而非硬编码在 `vision_system.py` 中。

#### Scenario: 标定参数修改
- **WHEN** 用户修改 `config.json` 中的标定参数
- **THEN** 重启后视觉系统使用新参数，无需改代码

### Requirement: GUI 线程类独立模块
`gui_app.py` 中的 `DeviceInitThread`、`StatusUpdateThread`、`MonitorThread`、`RobotCmdThread` SHALL 提取到 `dobot_move/workers.py` 独立模块。

#### Scenario: GUI 代码精简
- **WHEN** 查看 `gui_app.py`
- **THEN** 仅包含 UI 布局和事件处理逻辑，线程类从 `workers.py` 导入

### Requirement: Git 忽略规则
项目 SHALL 包含 `.gitignore`，忽略 `__pycache__/`、`*.pyc`、`build/`、`dist/`、`*.spec.bak`、`.vscode/`、`.idea/`。

#### Scenario: 构建产物不被追踪
- **WHEN** 执行 `git status`
- **THEN** `__pycache__/`、`build/`、`dist/` 不出现在未追踪文件列表

## MODIFIED Requirements

### Requirement: 项目目录结构
项目目标目录结构如下：

```
dobotm/
├── .gitignore
├── dobot_move_python/
│   ├── dobot_move/                    # 核心 Python 包
│   │   ├── __init__.py               # 包导出
│   │   ├── dobot_api.py              # 底层 TCP 通信
│   │   ├── robot_controller.py       # 机器人控制器
│   │   ├── gui_app.py                # GUI 主窗口（仅 UI 逻辑）
│   │   ├── workers.py                # GUI 线程类
│   │   ├── vision_system.py          # 视觉系统
│   │   ├── modbus_server.py          # Modbus 服务端
│   │   ├── modbus_client.py          # Modbus 客户端
│   │   ├── modbus_utils.py           # Modbus 公共工具
│   │   ├── gripper_controller.py     # 夹爪控制
│   │   ├── battery_monitor.py        # 电池监控
│   │   ├── config_manager.py         # 配置管理（CWD 无关）
│   │   ├── realtime_feedback_dialog.py
│   │   ├── config.json               # 运行时配置（含标定参数）
│   │   ├── grasp_flow_modules.json   # 抓取流程配置
│   │   ├── best.onnx                 # 视觉模型
│   │   └── files/
│   │       ├── alarmController.json  # 控制器报警（仅 JSON）
│   │       └── alarmServo.json       # 伺服报警（仅 JSON）
│   ├── requirements.txt
│   ├── build.bat
│   └── DobotControl.spec
```

## REMOVED Requirements

### Requirement: 根目录散落配置文件
**Reason**: 与包内配置重复，且路径依赖 CWD
**Migration**: 删除根目录 `config.json` 和 `grasp_flow_modules.json`，统一使用包内版本

### Requirement: files/ 目录下的 .py 报警数据文件
**Reason**: `alarmController.py` 和 `alarmServo.py` 是纯数据列表，JSON 版本已存在且更标准
**Migration**: 删除 `.py` 版本，`dobot_api.py` 中改为加载 `.json` 版本
