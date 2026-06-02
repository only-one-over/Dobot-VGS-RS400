# 打包项目为独立应用程序 Spec

## Why
需要将项目打包为独立的应用程序文件夹，使其可以在未安装 Python 环境的其他 Windows 设备上直接运行。

## What Changes
- 生成 `requirements.txt` 依赖清单
- 编写 PyInstaller `.spec` 配置文件
- 使用 PyInstaller 将 `gui_app.py` 打包为独立文件夹（`dist/DobotControl/`）
- 打包时自动包含数据文件：`config.json`、`best.onnx`、`files/` 目录、`grasp_flow_modules.json`
- 清理无用的 `__pycache__` 目录
- 清理无用的辅助文件（`dobot.txt`、`user_manual.md`）
- -- 输出到 `dist/DobotControl/` 文件夹，包含 .exe 和所有依赖

## Impact
- Affected code: 新增 `DobotControl.spec` 和 `requirements.txt`
- 新增目录: `dist/`（打包输出，.gitignore 建议加入）

## ADDED Requirements

### Requirement: 生成 requirements.txt
系统 SHALL 生成 `requirements.txt` 文件，列出所有运行时依赖：
- PyQt6 >= 6.0
- numpy
- requests
- pymodbus >= 3.0
- opencv-python
- onnxruntime

#### Scenario: 依赖安装
- **WHEN** 用户执行 `pip install -r requirements.txt`
- **THEN** 所有依赖成功安装，程序可正常运行

### Requirement: PyInstaller 打包配置
系统 SHALL 创建 `DobotControl.spec` 文件，指定：
- 入口脚本：`dobot_move/gui_app.py`
- 应用名称：`DobotControl`
- 打包模式：`onedir`（文件夹模式，含 .exe 和所有依赖）
- 隐藏导入：确保 PyQt6、numpy、pymodbus 等被包含
- 数据文件：`config.json`、`best.onnx`、`files/`、`grasp_flow_modules.json`

#### Scenario: 打包成功
- **WHEN** 用户执行 `pyinstaller DobotControl.spec`
- **THEN** 在 `dist/DobotControl/` 下生成可独立运行的文件夹，含 `DobotControl.exe`

#### Scenario: 快速打包
- **WHEN** 用户执行一键打包脚本
- **THEN** 自动完成清理、打包、验证流程

### Requirement: 清理冗余文件
打包前 SHALL 清理项目中的冗余内容：
- 删除所有 `__pycache__/` 目录
- 删除 `dobot.txt`（未使用的辅助文件）
- 删除 `user_manual.md`（未使用的文档文件）

#### Scenario: 项目精简
- **WHEN** 执行清理操作
- **THEN** 项目根目录仅保留源代码和必要配置文件

### Requirement: 一键打包脚本
系统 SHALL 提供一键打包脚本 `build.bat`：
- 自动检查/安装 pyinstaller
- 清理旧的 dist 目录
- 执行打包
- 验证输出文件存在

#### Scenario: 一键打包
- **WHEN** 用户双击 `build.bat`
- **THEN** 自动完成打包，输出到 `dist/DobotControl/`
