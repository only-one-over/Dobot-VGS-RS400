# 修复相机连接失败 - Spec

## Why
用户点击"连接相机"按钮时收到错误"视觉系统不可用，可能是依赖库安装问题"。根因是 `requirements.txt` 缺少视觉系统所需的 3 个核心依赖库（`pyrealsense2`、`opencv-python`、`onnxruntime`），导致 `vision_system.py` 导入失败，`VISION_AVAILABLE` 被设为 `False`，`connect_camera` 直接返回。

## What Changes
- `requirements.txt` — 添加 `pyrealsense2`、`opencv-python`、`onnxruntime` 依赖
- `gui_app.py` — 改进错误提示，明确告知用户需要安装哪些依赖及安装方法

## Impact
- Affected specs: 无
- Affected code: `dobot_move_python/requirements.txt`, `dobot_move/gui_app.py` L28-L41

## MODIFIED Requirements
### Requirement: requirements.txt 包含所有视觉依赖
`requirements.txt` SHALL 包含 `pyrealsense2`、`opencv-python`（或 `opencv-python-headless`）、`onnxruntime` 这三个视觉系统必需的依赖库。

#### Scenario: 安装依赖后连接相机
- **GIVEN** 用户在 `.venv` 虚拟环境中执行 `pip install -r requirements.txt`
- **WHEN** 启动程序并点击"连接相机"
- **THEN** 所有依赖库可用，相机连接成功
