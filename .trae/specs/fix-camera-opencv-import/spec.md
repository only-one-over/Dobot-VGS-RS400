# 修复相机功能 OpenCV 缺失报错 Spec

## Why
用户使用相机功能时报错"没有发现 opencv"。根因有两个：(1) `gui_app.py` 的 `CameraTestWorker` 直接使用 `cv2` 但从未在文件顶部导入 `cv2`，即使 opencv 已安装也会触发 `NameError: name 'cv2' is not defined`；(2) 当 opencv 未安装时，`vision_system.py` 的 `import cv2` 硬依赖导致整个视觉模块导入失败，错误信息不明确，用户无法得知具体缺少哪个依赖。

## What Changes
- `gui_app.py` — 在视觉导入 try 块中增加 `import cv2`，确保 `cv2` 在 `gui_app.py` 命名空间可用；当导入失败时，逐个检测缺失的依赖并给出精确提示
- `vision_system.py` — 将 `import cv2` 改为 try/except 包裹，捕获 `ImportError` 时给出明确错误信息
- `depth_processor.py` — 将 `import cv2` 改为 try/except 包裹，与 `pyrealsense2` 的导入方式保持一致

## Impact
- Affected specs: `add-missing-vision-deps`（之前只改了 requirements.txt 和提示文字，未修复 cv2 未导入到 gui_app.py 的问题）
- Affected code: `dobot_move/gui_app.py` L38-56, `dobot_move/vision_system.py` L9, `dobot_move/depth_processor.py` L5

## ADDED Requirements

### Requirement: gui_app.py 必须显式导入 cv2
`gui_app.py` SHALL 在视觉导入 try 块中显式 `import cv2`，确保 `CameraTestWorker` 中对 `cv2.rectangle()`、`cv2.findContours()`、`cv2.drawContours()`、`cv2.cvtColor()` 的调用不会因 `NameError` 而崩溃。

#### Scenario: opencv 已安装时相机测试正常运行
- **GIVEN** opencv-python 已安装在当前 Python 环境中
- **WHEN** 用户点击"连接相机"并启动相机测试
- **THEN** `CameraTestWorker` 中的 `cv2` 调用正常执行，不出现 `NameError`

### Requirement: 视觉依赖缺失时提供精确错误信息
当视觉相关依赖（pyrealsense2、opencv-python、onnxruntime）中任一缺失时，系统 SHALL 逐个检测并告知用户具体缺失哪个库，而非笼统的"视觉系统不可用"。

#### Scenario: 仅 opencv 缺失
- **GIVEN** pyrealsense2 和 onnxruntime 已安装，但 opencv-python 未安装
- **WHEN** 启动程序
- **THEN** 控制台打印精确提示"缺少依赖: opencv-python"，并给出安装命令

#### Scenario: 多个依赖缺失
- **GIVEN** pyrealsense2 和 opencv-python 均未安装
- **WHEN** 启动程序
- **THEN** 控制台列出所有缺失的依赖及对应安装命令

### Requirement: vision_system.py 和 depth_processor.py 对 cv2 导入做容错处理
`vision_system.py` 和 `depth_processor.py` SHALL 使用 try/except 包裹 `import cv2`，在导入失败时抛出明确错误信息，而非让 Python 抛出原始 `ModuleNotFoundError`。

#### Scenario: cv2 导入失败时 vision_system.py 给出明确提示
- **GIVEN** opencv-python 未安装
- **WHEN** 尝试 `from vision_system import VisionSystem`
- **THEN** 抛出 `ImportError` 且错误信息包含 "opencv-python" 关键字

## MODIFIED Requirements

### Requirement: gui_app.py 视觉导入失败提示
`gui_app.py` L38-56 的视觉导入 try/except 块 SHALL 逐个尝试导入 `pyrealsense2`、`cv2`、`onnxruntime`，在 except 中列出具体缺失的库及安装命令，而非仅打印笼统的安装提示。
