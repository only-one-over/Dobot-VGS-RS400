# Tasks

- [x] Task 1: 添加 `.gitignore` 并清理构建产物
  - [x] SubTask 1.1: 在 `dobotm/` 根目录创建 `.gitignore`，忽略 `__pycache__/`、`*.pyc`、`build/`、`dist/`、`*.spec.bak`、`.vscode/`、`.idea/`
  - [x] SubTask 1.2: 删除所有 `__pycache__/` 目录
  - [x] SubTask 1.3: 确认 `build/` 和 `dist/` 已被忽略

- [x] Task 2: 清理根目录散落文件
  - [x] SubTask 2.1: 删除根目录 `config.json`（与 `dobot_move_python/dobot_move/config.json` 重复）
  - [x] SubTask 2.2: 删除根目录 `grasp_flow_modules.json`（与 `dobot_move_python/grasp_flow_modules.json` 重复）
  - [x] SubTask 2.3: 删除根目录 `CODE_WIKI.md`
  - [x] SubTask 2.4: 删除 `TCP-IP-Python-V4-main/` 目录（官方参考实现，非运行依赖）

- [x] Task 3: 修复 `config_manager.py` 路径依赖
  - [x] SubTask 3.1: 将 `CONFIG_FILE` 改为基于 `__file__` 的绝对路径
  - [x] SubTask 3.2: 验证从不同 CWD 启动时配置仍能正确加载

- [x] Task 4: 统一配置文件到 `dobot_move/` 包内
  - [x] SubTask 4.1: 删除 `dobot_move_python/config.json`（保留 `dobot_move_python/dobot_move/config.json`）
  - [x] SubTask 4.2: 删除 `dobot_move_python/grasp_flow_modules.json`（保留 `dobot_move_python/dobot_move/grasp_flow_modules.json`）
  - [x] SubTask 4.3: 更新 `DobotControl.spec` 中配置文件的打包路径

- [x] Task 5: 提取 Modbus 公共工具函数
  - [x] SubTask 5.1: 创建 `dobot_move/modbus_utils.py`，包含 `float_to_regs` 和 `regs_to_float`
  - [x] SubTask 5.2: 修改 `modbus_server.py`，从 `modbus_utils` 导入
  - [x] SubTask 5.3: 修改 `modbus_client.py`，从 `modbus_utils` 导入

- [x] Task 6: 添加 `dobot_move/__init__.py`
  - [x] SubTask 6.1: 创建 `__init__.py`，导出 `DobotController`、`VisionSystem`、`DobotModbusServer`、`DobotModbusClient`

- [x] Task 7: 视觉标定参数迁移到配置文件
  - [x] SubTask 7.1: 在 `config.json` 中添加 `calibration` 字段（`tool_base_calib_pose`、`cam_base_calib_pose`）
  - [x] SubTask 7.2: 修改 `vision_system.py` 从 `config_manager` 读取标定参数，保留硬编码值作为默认回退

- [x] Task 8: 提取 GUI 线程类到 `workers.py`
  - [x] SubTask 8.1: 创建 `dobot_move/workers.py`，包含 `DeviceInitThread`、`StatusUpdateThread`、`MonitorThread`、`RobotCmdThread`
  - [x] SubTask 8.2: 修改 `gui_app.py`，从 `workers.py` 导入线程类
  - [x] SubTask 8.3: 确认 GUI 功能不受影响

- [x] Task 9: 清理 `files/` 目录报警数据文件
  - [x] SubTask 9.1: 删除 `files/alarmController.py`（仅保留 `alarmController.json`）
  - [x] SubTask 9.2: 删除 `files/alarmServo.py`（仅保留 `alarmServo.json`）
  - [x] SubTask 9.3: 修改 `dobot_api.py` 中报警文件引用，从 `.py` 改为 `.json`（已确认无需修改，原本就是 .json）

- [x] Task 10: 验证整体功能
  - [x] SubTask 10.1: 确认程序可从 `dobot_move_python/` 目录正常启动
  - [x] SubTask 10.2: 确认所有 import 路径正确
  - [x] SubTask 10.3: 确认打包脚本 `build.bat` 仍可正常工作

# Task Dependencies
- [Task 3] depends on [Task 4] (配置路径修复需先确认配置文件最终位置)
- [Task 7] depends on [Task 3] (标定参数迁移依赖配置管理路径修复)
- [Task 8] depends on [Task 6] (workers 导入依赖包结构)
- [Task 10] depends on [Task 1-9] (最终验证依赖所有任务完成)
- [Task 1, 2, 5, 6, 9] 可并行执行
