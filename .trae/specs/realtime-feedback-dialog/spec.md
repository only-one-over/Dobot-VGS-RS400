# 实时反馈独立页面弹窗 Spec

## Why
当前GUI中实时状态反馈区域没有数字显示，用户希望将其做成一个独立的页面/弹窗，用户点击按钮后才开启端口进行实时反馈，方便查看机器人的实时状态数据。

## What Changes
- 创建RealTimeFeedbackDialog独立弹窗页面
- 在主GUI中添加"实时反馈"按钮，点击打开弹窗
- 弹窗中连接30004端口并实时显示所有解析后的数据
- 弹窗关闭时停止实时反馈连接

## Impact
- 受影响的代码：
  - `dobot_move/realtime_feedback_dialog.py` - 新文件，独立弹窗页面
  - `dobot_move/gui_app.py` - 添加打开弹窗的按钮

## ADDED Requirements

### Requirement: 实时反馈独立弹窗
用户点击按钮后打开独立弹窗，弹窗连接30004端口并显示实时数据。

#### Scenario: 打开实时反馈页面
- **WHEN** 用户点击"实时反馈"按钮
- **THEN** 弹窗打开，连接30004端口，开始显示实时数据

### Requirement: 弹窗关闭时停止连接
弹窗关闭时自动停止实时反馈连接，释放端口。

#### Scenario: 关闭弹窗
- **WHEN** 用户关闭弹窗
- **THEN** 停止RealTimeFeedback连接，释放30004端口
