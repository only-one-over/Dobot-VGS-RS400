# Tasks

- [x] Task 1: 创建设备移植方案文档 PORTING_GUIDE.md
  - [x] 1.1: 在 `c:\Users\ADMIN\Desktop\dobot_move_python\` 下创建 `PORTING_GUIDE.md`，包含以下章节：
    - 概述：项目架构和模块依赖关系
    - 硬件接口适配：替换机器人控制器（TCP/IP 协议适配、端口配置、指令格式映射）
    - 通信协议替换：Modbus TCP Server/Client 适配新设备
    - 视觉系统配置：RealSense 相机选型、深度范围、分辨率、标定流程
    - 手眼标定：标定流程、矩阵格式、如何为新设备计算标定矩阵
    - 点位管理系统：点位数据格式、相对点位解析、如何迁移已有点位
    - 力控圆弧：力反馈接口适配、力控参数调整
    - 配置文件：config.json 格式说明、需要修改的配置项
    - 移植检查清单：逐步验证清单

# Task Dependencies
- Task 1 独立
