# IP永久保存与运动编辑优化 Spec

## Why
当前修改机器人IP后重启程序会恢复为默认值"192.168.5.1"，用户每次启动都需要重新输入IP；运动编辑中"添加模块"总是追加到列表末尾、"移除模块"总是删除最后一个，无法基于选中位置操作，使用不便。

## What Changes
- 将机器人IP地址持久化到 `config.json`，启动时从配置加载，修改IP时自动保存
- "添加模块"改为插入到当前选中步骤的下一个位置（未选中则追加到末尾）
- "移除模块"改为删除当前选中的步骤（未选中则提示先选择）

## Impact
- Affected code: `gui_app.py`（IP输入初始化、连接方法、add_module、remove_module）, `config_manager.py`（新增 get/set robot_ip）, `config.json`（新增 robot_ip 字段）

## ADDED Requirements

### Requirement: IP地址持久化
系统 SHALL 将机器人IP地址保存到 `config.json` 中，程序启动时从配置加载，用户修改IP并连接成功后自动持久化。

#### Scenario: 首次启动无配置
- **WHEN** `config.json` 中没有 `robot_ip` 字段
- **THEN** 使用默认值 "192.168.5.1"，IP输入框显示默认值

#### Scenario: 有配置时启动
- **WHEN** `config.json` 中存在 `robot_ip` 字段
- **THEN** 程序启动时从配置读取IP，IP输入框显示配置值，控制器使用配置IP

#### Scenario: 修改IP后持久化
- **WHEN** 用户在IP输入框修改IP并点击连接
- **THEN** 新IP自动保存到 `config.json`，下次启动时使用新IP

### Requirement: 添加模块插入到选中位置之后
"添加模块"操作 SHALL 将新模块插入到当前选中步骤的下一个位置。如果没有选中任何步骤，则追加到列表末尾。

#### Scenario: 选中步骤后添加
- **WHEN** 用户选中第3步并点击"添加模块"
- **THEN** 新模块插入为第4步，原第4步及之后的步骤依次后移

#### Scenario: 未选中步骤时添加
- **WHEN** 没有选中任何步骤（selected_step_index == -1）并点击"添加模块"
- **THEN** 新模块追加到列表末尾（与当前行为一致）

### Requirement: 删除选中的模块
"移除模块"操作 SHALL 删除当前选中的步骤。如果没有选中任何步骤，提示用户先选择。

#### Scenario: 选中步骤后删除
- **WHEN** 用户选中某一步骤并点击"移除模块"
- **THEN** 删除选中的步骤，后续步骤前移，选中索引更新

#### Scenario: 未选中步骤时删除
- **WHEN** 没有选中任何步骤并点击"移除模块"
- **THEN** 提示"请先选择要删除的模块"

#### Scenario: 删除后选中索引调整
- **WHEN** 删除选中步骤后
- **THEN** 如果删除的是最后一步，选中索引前移一步；否则选中索引指向原位置的新步骤

## MODIFIED Requirements

### Requirement: config_manager 新增 IP 配置函数
`config_manager.py` SHALL 新增 `get_robot_ip()` 和 `set_robot_ip(ip)` 函数。

### Requirement: gui_app.py 初始化使用配置IP
`DobotGUI.__init__` 中 `self.robot_ip` 和 `self.ip_input` 的初始值 SHALL 从 `config_manager.get_robot_ip()` 获取。

## REMOVED Requirements

### Requirement: IP硬编码默认值
**Reason**: IP应从配置文件读取，不再硬编码
**Migration**: `config_manager.get_robot_ip()` 提供默认值回退

### Requirement: 添加模块总是追加到末尾
**Reason**: 改为插入到选中位置之后
**Migration**: 使用 `list.insert(selected_index + 1, new_module)` 替代 `list.append(new_module)`

### Requirement: 移除模块总是删除最后一个
**Reason**: 改为删除选中的模块
**Migration**: 使用 `list.pop(selected_index)` 替代 `list.pop()`
