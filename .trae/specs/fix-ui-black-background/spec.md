# 修复界面空白区域黑色背景 Spec

## Why
GUI 界面中多处空白区域显示为黑色，与蓝色主题不协调，影响美观。原因是 `set_blue_theme` 的全局样式表未覆盖 `QWidget`（容器）、`QScrollArea`、`QLineEdit`、`QTableWidget`、`QScrollBar` 等控件的背景色，这些控件使用了系统默认的深色/黑色背景。

## What Changes
- 在 `set_blue_theme` 的全局样式表中补充 `QWidget`、`QScrollArea`、`QLineEdit`、`QTableWidget`、`QScrollBar` 等控件的背景色样式
- 确保所有空白区域使用与蓝色主题一致的浅色背景

## Impact
- Affected code: `gui_app.py` 第 341-459 行 `set_blue_theme` 方法的样式表

## ADDED Requirements
### Requirement: 界面空白区域背景色统一
所有界面空白区域 SHALL 使用与蓝色主题一致的浅色背景，不出现黑色区域。

#### Scenario: QWidget 容器背景
- **WHEN** 创建 QWidget 作为选项卡内容容器
- **THEN** 背景色为浅蓝色 (#f0f8ff)，非黑色

#### Scenario: QScrollArea 背景
- **WHEN** 选项卡内容通过 QScrollArea 包裹
- **THEN** 滚动区域背景为浅蓝色 (#f0f8ff)，非黑色

#### Scenario: QLineEdit 背景
- **WHEN** 显示 IP 地址输入框等 QLineEdit 控件
- **THEN** 背景色为白色，边框与主题一致

#### Scenario: QTableWidget 背景
- **WHEN** 显示 Modbus 寄存器表格
- **THEN** 表格背景为白色，交替行颜色为浅蓝色

#### Scenario: QScrollBar 样式
- **WHEN** 内容超出视口需要滚动
- **THEN** 滚动条使用蓝色主题风格

## MODIFIED Requirements
无

## REMOVED Requirements
无
