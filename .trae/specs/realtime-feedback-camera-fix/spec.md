# 实时状态反馈与相机异常处理 Spec

## Why
1. 机器人30004端口每8ms提供一次实时状态反馈（1440字节），包含关节位置、TCP坐标、力控、温度等关键信息，当前项目未充分利用这些数据。
2. 相机连接失败时vision_system.py会回退到模拟数据，导致用户误以为相机正常工作，实际上使用的是虚拟帧，影响抓取成功率。

## What Changes
- 创建RealTimeFeedback类完整解析30004端口的1440字节实时反馈数据。
- 修改vision_system.py：相机连接失败时直接报错，不使用模拟数据。
- 在GUI中添加实时状态显示面板。

## Impact
- 受影响的代码：
  - `dobot_move/realtime_feedback.py` - 新文件
  - `dobot_move/vision_system.py` - 移除模拟数据回退
  - `dobot_move/gui_app.py` - 添加实时状态显示

## ADDED Requirements

### Requirement: 实时状态反馈解析
根据TCP文档解析30004端口的1440字节实时反馈数据。

#### Scenario: 接收实时数据
- **WHEN** 连接到30004端口
- **THEN** 每8ms解析一次1440字节数据，包含：
  - RobotMode（字节24-31）
  - RunTime（字节40-47）
  - QActual实际关节位置（字节432-479）
  - ToolVectorActual TCP实际坐标（字节624-671）
  - MotorTemperatures关节温度（字节864-911）

### Requirement: 相机失败时不使用模拟数据
相机连接失败时直接报错，不创建模拟帧。

#### Scenario: 相机连接失败
- **WHEN** 相机初始化失败
- **THEN** camera_available=False，capture_frames()返回None, None，不创建模拟数据。