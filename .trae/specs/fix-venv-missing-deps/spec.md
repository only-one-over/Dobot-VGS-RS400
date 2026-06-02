# 修复虚拟环境依赖 Spec

## Why
虚拟环境从其他目录复制而来，pip 启动器路径损坏，且大量依赖包未安装，导致应用启动时出现 `ModuleNotFoundError: No module named 'pymodbus'`。

## What Changes
- 修复 pip 启动器路径问题（通过 `python.exe -m pip` 绕过）
- 安装 requirements.txt 中所有缺失的依赖包：pymodbus、requests、opencv-python、onnxruntime、pyrealsense2
- 验证所有包可正常导入

## Impact
- Affected code: 无代码变更，仅环境修复
- Affected specs: 无

## ADDED Requirements
### Requirement: 虚拟环境依赖完整性
系统 SHALL 在虚拟环境中安装 requirements.txt 列出的所有依赖包，确保 `gui_app.py` 可正常启动。

#### Scenario: 安装缺失依赖
- **WHEN** 执行 `python.exe -m pip install -r requirements.txt`
- **THEN** 所有依赖包安装成功，无报错

#### Scenario: 验证 pymodbus 可导入
- **WHEN** 在虚拟环境中执行 `import pymodbus`
- **THEN** 不再出现 ModuleNotFoundError

#### Scenario: 验证所有依赖可导入
- **WHEN** 在虚拟环境中依次导入 pymodbus、requests、cv2、onnxruntime
- **THEN** 所有导入均成功

## MODIFIED Requirements
无

## REMOVED Requirements
无
