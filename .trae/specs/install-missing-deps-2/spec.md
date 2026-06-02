# 安装缺失依赖 minimalmodbus 和 python-can Spec

## Why
启动 gui_app.py 时夹爪和电池监控初始化失败，报错 `No module named 'minimalmodbus'` 和 `No module named 'can'`。这两个包未包含在 requirements.txt 中也未安装。

## What Changes
- 安装 minimalmodbus 和 python-can 包
- 将这两个包添加到 requirements.txt

## Impact
- Affected code: requirements.txt
- Affected specs: 无

## ADDED Requirements
### Requirement: 夹爪和电池监控依赖完整
系统 SHALL 安装 minimalmodbus 和 python-can 包，确保夹爪控制器和电池监控模块可正常导入。

#### Scenario: minimalmodbus 可导入
- **WHEN** 执行 `import minimalmodbus`
- **THEN** 不再出现 ModuleNotFoundError

#### Scenario: can 可导入
- **WHEN** 执行 `import can`
- **THEN** 不再出现 ModuleNotFoundError

## MODIFIED Requirements
无

## REMOVED Requirements
无
