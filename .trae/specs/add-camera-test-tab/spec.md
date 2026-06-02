# 相机实时测试选项卡 Spec

## Why
当前系统连接相机后无法直观验证识别效果和坐标输出，需要在 GUI 中新增一个独立的"相机测试"选项卡，实时显示相机画面、检测结果和 3D 坐标，方便调试和验证。

## What Changes
- 修改 `gui_app.py`：新增"相机测试"选项卡，包含相机选择、实时画面显示、检测结果标注、3D 坐标实时输出、置信度显示

## Impact
- Affected code: `gui_app.py`（新增选项卡 + QTimer 定时刷新）

## ADDED Requirements

### Requirement: 相机测试选项卡
系统 SHALL 提供独立的"相机测试"选项卡，连接相机后实时显示识别结果和坐标。

#### Scenario: 启动实时测试
- **WHEN** 用户在"相机测试"选项卡选择相机类型（D435i/D405）并点击"开始测试"
- **THEN** 系统以 QTimer 定时（约 200ms 间隔）调用相机拍照→检测→3D定位，实时更新画面和坐标

#### Scenario: 显示检测结果
- **WHEN** 检测到物体
- **THEN** 画面上绘制 bbox 和掩码轮廓，坐标区域显示相机坐标、末端坐标、基座坐标和置信度

#### Scenario: 未检测到物体
- **WHEN** 未检测到物体
- **THEN** 画面显示原始图像，坐标区域显示"未检测到物体"

#### Scenario: 停止测试
- **WHEN** 用户点击"停止测试"
- **THEN** 停止定时器，画面和坐标冻结

#### Scenario: 相机未连接
- **WHEN** 用户选择未连接的相机并点击"开始测试"
- **THEN** 提示"相机未连接"

### Requirement: 坐标显示
系统 SHALL 在测试选项卡中显示以下坐标信息：
- 相机坐标 (X, Y, Z) mm
- 末端坐标 (X, Y, Z) mm（需机器人已连接）
- 基座坐标 (X, Y, Z) mm（需机器人已连接）
- 置信度（0-1）
- D405 额外显示：柄端坐标、钩尖坐标、铁钩长度

## MODIFIED Requirements
无。

## REMOVED Requirements
无。
