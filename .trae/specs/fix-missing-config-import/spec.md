# 修复 config_manager 缺失导入 Spec

## Why
`gui_app.py` 使用了 `config_manager` 中的 `get_robot_ip` 和 `set_robot_ip` 函数，但未在 import 语句中导入，导致启动时 `NameError: name 'get_robot_ip' is not defined`。

## What Changes
- 在 `gui_app.py` 的 import 语句中添加 `get_robot_ip` 和 `set_robot_ip as config_set_robot_ip`

## Impact
- Affected code: `gui_app.py` 第 26 行 import 语句

## ADDED Requirements
### Requirement: config_manager 函数完整导入
`gui_app.py` SHALL 从 `config_manager` 导入所有实际使用的函数，确保运行时无 NameError。

#### Scenario: 启动时获取机器人IP
- **WHEN** `DobotGUI.__init__` 调用 `get_robot_ip()`
- **THEN** 函数正常执行，返回配置中的 IP 地址或默认值 "192.168.5.1"

#### Scenario: 连接时保存机器人IP
- **WHEN** 用户输入 IP 并点击连接，调用 `config_set_robot_ip(ip)`
- **THEN** IP 地址被正确保存到配置文件

## MODIFIED Requirements
无

## REMOVED Requirements
无
