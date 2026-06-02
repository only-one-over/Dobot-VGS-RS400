# Tasks

- [x] Task 1: 创建RealTimeFeedbackDialog独立弹窗页面
  - [x] 创建dobot_move/realtime_feedback_dialog.py文件
  - [x] 弹窗包含连接/断开按钮
  - [x] 显示所有实时反馈数据：
    - 机器人模式、运行时间、速度比例
    - 实际关节位置(QActual) 6个关节
    - 实际关节速度(QDActual) 6个关节
    - TCP实际坐标(X,Y,Z,Rx,Ry,Rz)
    - TCP实际速度
    - TCP受力(Fx,Fy,Fz,Mx,My,Mz)
    - 关节温度 6个关节
    - 当前用户坐标系、工具坐标系、速度比例、加速度比例
  - [x] 使用定时器每100ms更新显示
  - [x] 弹窗关闭时自动停止RealTimeFeedback连接

- [x] Task 2: 在主GUI中添加实时反馈按钮
  - [x] 在主GUI状态区域添加"实时反馈"按钮
  - [x] 点击按钮打开RealTimeFeedbackDialog弹窗

# Task Dependencies
- Task 2 depends on Task 1
