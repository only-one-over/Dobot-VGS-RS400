# IP 地址持久化保存 Spec

## Why
当前机器人 IP 仅在点击"连接机器人"时才保存到配置文件，小车 IP 和 Modbus 端口完全硬编码不持久化。用户修改 IP 后如果不点击连接，下次启动仍显示旧 IP，体验不佳。

## What Changes
- 机器人 IP：在输入框编辑完成时（`editingFinished`）立即保存到配置，而非仅连接时保存
- 小车 IP：从配置文件读取初始值，连接和编辑完成时保存
- Modbus 端口：从配置文件读取初始值，编辑完成时保存
- 小车端口：从配置文件读取初始值，编辑完成时保存

## Impact
- Affected code: `gui_app.py`（IP 输入框初始化和事件绑定）、`config_manager.py`（新增 cart_ip、cart_port、modbus_port 配置项）
- Affected specs: 无

## ADDED Requirements
### Requirement: IP 地址输入即时持久化
所有 IP 地址和端口输入 SHALL 在用户编辑完成时立即保存到配置文件，确保下次启动时自动恢复。

#### Scenario: 机器人 IP 编辑后持久化
- **WHEN** 用户在机器人 IP 输入框中修改 IP 并按回车或移开焦点
- **THEN** IP 地址立即保存到 config.json，下次启动时自动填入

#### Scenario: 小车 IP 持久化
- **WHEN** 用户修改小车 IP 输入框并按回车或移开焦点
- **THEN** 小车 IP 保存到 config.json，下次启动时自动填入

#### Scenario: Modbus 端口持久化
- **WHEN** 用户修改 Modbus 服务器端口并按回车或移开焦点
- **THEN** 端口保存到 config.json，下次启动时自动填入

#### Scenario: 小车端口持久化
- **WHEN** 用户修改小车端口并按回车或移开焦点
- **THEN** 端口保存到 config.json，下次启动时自动填入

## MODIFIED Requirements
无

## REMOVED Requirements
无
