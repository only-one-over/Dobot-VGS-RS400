# 设备移植方案文档

## 1. 概述

本项目是一个基于 Python + PyQt6 的机械臂抓取控制系统，当前绑定越疆 CR 系列机器人。本文档指导开发者将系统适配到其他品牌/型号的机器人设备。

### 1.1 项目架构

```
dobot_move/
├── gui_app.py              # 主 GUI 界面（PyQt6）
├── robot_controller.py     # 机器人控制器（核心适配层）
├── dobot_api.py            # TCP/IP 通信底层（越疆协议）
├── config_manager.py       # 配置文件管理
├── vision_system.py        # 视觉系统（RealSense + YOLOv8）
├── hand_eye_calib.py       # 手眼标定管理
├── transform_utils.py      # 公共坐标变换工具
├── force_arc_controller.py # 力控圆弧控制器
├── force_feedback_monitor.py # 力反馈监控
├── arc_trajectory_planner.py # 圆弧轨迹规划
├── gripper_controller.py   # 夹爪控制（已移除）
├── battery_monitor.py      # 电池监控
├── modbus_server.py         # Modbus TCP 服务器
├── modbus_client.py         # Modbus TCP 客户端
├── modbus_utils.py          # Modbus 工具函数
├── workers.py               # 后台工作线程
├── realtime_feedback_dialog.py # 实时反馈弹窗
├── config.json              # 配置文件
└── best.onnx                # YOLOv8 实例分割模型
```

### 1.2 模块依赖关系

```
gui_app.py
  ├── robot_controller.py → dobot_api.py（TCP/IP 通信）
  ├── vision_system.py → config_manager.py, transform_utils.py
  ├── hand_eye_calib.py → config_manager.py, transform_utils.py
  ├── force_arc_controller.py → dobot_api.py, force_feedback_monitor.py
  ├── config_manager.py → transform_utils.py
  ├── workers.py
  └── gripper_controller.py（已移除）, battery_monitor.py
```

### 1.3 适配优先级

移植时按以下优先级逐层适配：

1. **通信层**（dobot_api.py）— 必须首先适配，是所有机器人指令的基础
2. **控制器层**（robot_controller.py）— 依赖通信层，封装业务逻辑
3. **力控层**（force_arc_controller.py）— 依赖控制器层，需要力传感器接口
4. **视觉层**（vision_system.py）— 相对独立，主要取决于相机硬件
5. **配置层**（config_manager.py, config.json）— 需要根据新设备调整参数

---

## 2. 硬件接口适配

### 2.1 需要适配的核心文件

| 文件 | 适配内容 | 优先级 |
|------|---------|--------|
| `dobot_api.py` | TCP/IP 协议、指令格式、反馈数据结构 | 最高 |
| `robot_controller.py` | 运动指令封装、状态解析、错误处理 | 高 |
| `force_arc_controller.py` | 力控相关指令 | 中 |
| `force_feedback_monitor.py` | 力传感器数据读取 | 中 |

### 2.2 TCP/IP 协议适配

当前系统使用越疆 CR 系列的 TCP/IP 协议，涉及两个端口：

- **端口 29999**：Dashboard 指令端口（运动控制、状态查询、参数设置）
- **端口 30004**：实时反馈端口（位姿、力矩、关节角度等高频数据）

#### 2.2.1 通信类替换

`dobot_api.py` 中定义了三个核心类：

- `DobotApi`：TCP 通信基类，负责 socket 连接、发送指令、接收响应
- `DobotApiDashboard(DobotApi)`：Dashboard 指令封装（MovJ/MovL/MovC/EnableRobot 等）
- `DobotApiFeedBack(DobotApi)`：实时反馈数据解析（使用 numpy 结构体解析二进制流）

**适配步骤：**

1. 创建新文件 `new_robot_api.py`，实现与 `DobotApiDashboard` 相同的公开方法接口
2. 保持方法签名一致，内部替换为新设备的协议格式
3. 如果新设备使用不同的通信方式（如 ROS、串口、EtherCAT），需要重写通信基类

#### 2.2.2 指令格式映射

以下是当前系统使用的越疆指令与新设备需要映射的对照表：

| 越疆指令 | 功能 | 新设备需实现的接口 |
|---------|------|------------------|
| `EnableRobot()` | 使能机器人 | 使能/上电 |
| `DisableRobot()` | 下使能 | 下使能/下电 |
| `ClearError()` | 清除报警 | 清除故障/复位 |
| `SpeedFactor(pct)` | 设置速度比例 | 速度设置 |
| `MovJ(x,y,z,rx,ry,rz,0)` | 关节运动 | 关节运动到目标位姿 |
| `MovL(x,y,z,rx,ry,rz,0)` | 直线运动 | 直线运动到目标位姿 |
| `MovC(...)` | 圆弧运动 | 圆弧运动 |
| `RelJointMovJ(...)` | 关节相对运动 | 关节相对运动 |
| `GetPose()` | 获取当前位姿 | 获取 TCP 位姿 |
| `GetAngle()` | 获取关节角度 | 获取关节角度 |
| `RobotMode()` | 获取机器人模式 | 获取运行状态 |
| `MoveJog(axis)` | 点动运动 | 点动控制 |
| `Pause()` | 暂停 | 暂停运动 |
| `Continue()` | 继续 | 恢复运动 |
| `Stop()` | 停止 | 急停/停止 |
| `SetCollisionLevel(lv)` | 碰撞等级 | 碰撞检测设置 |
| `GetForce(tool)` | 获取力传感器数据 | 力传感器读取 |
| `EnableFTSensor(s)` | 使能力传感器 | 力传感器使能 |
| `SixForceHome()` | 力传感器清零 | 力传感器归零 |
| `FCForceMode(...)` | 力控模式 | 力控制模式设置 |
| `FCSetDeviation(...)` | 力控偏差设置 | 力控参数配置 |
| `FCSetDamping(...)` | 阻尼设置 | 阻尼参数配置 |
| `FCOff()` | 关闭力控 | 退出力控模式 |

#### 2.2.3 反馈数据结构适配

当前系统使用 `MyType` numpy 结构体解析端口 30004 的二进制数据流，包含以下关键字段：

| 字段名 | 类型 | 含义 |
|--------|------|------|
| `RobotMode` | uint64 | 机器人模式（1-11） |
| `QActual` | float64[6] | 实际关节角度 |
| `IActual` | float64[6] | 实际关节电流 |
| `ActualTCPForce` | float64[6] | TCP 力/力矩 |
| `ToolVectorActual` | float64[6] | 实际 TCP 位姿 |
| `SpeedScaling` | float64 | 速度比例 |

**适配步骤：**

1. 查阅新设备的反馈数据协议文档
2. 修改 `MyType` 结构体定义或创建新的解析方式
3. 确保 `robot_controller.py` 中 `get_feed_data()` 返回的数据格式与 GUI 层期望一致
4. 关键字段映射：`ToolVectorActual` → TCP 位姿、`ActualTCPForce` → 力数据、`QActual` → 关节角度

### 2.3 端口配置

当前硬编码的端口：

```python
# dobot_api.py
DobotApi.__init__: self.port == 29999 or self.port == 30004 or self.port == 30005

# robot_controller.py
DobotApiDashboard(self.robot_ip, 29999)
DobotApiFeedBack(self.robot_ip, 30004)
```

**适配步骤：**

1. 将端口号提取到 `config.json` 中
2. 修改 `dobot_api.py` 移除端口硬编码检查
3. 在 `config_manager.py` 中增加端口配置项

---

## 3. 通信协议替换

### 3.1 Modbus TCP 服务器

`modbus_server.py` 实现 Modbus TCP Server，供外部 PLC/上位机读写机器人状态。

**适配要点：**

- Modbus 协议本身与机器人品牌无关，通常不需要修改
- 需要根据新设备调整寄存器映射（状态码含义、坐标数据格式）
- 当前寄存器布局：

| 寄存器地址 | 含义 | 数据类型 |
|-----------|------|---------|
| 0-1 | 机器人状态 | U16 |
| 2-3 | 故障码 | U16 |
| 4-5 | 到位标志 | U16 |
| 6-11 | X/Y/Z 坐标 | Float32×3 |
| 12-13 | 控制命令 | U16 |

- `modbus_utils.py` 提供浮点数与 Modbus 寄存器的转换（大端 IEEE 754）

### 3.2 Modbus TCP 客户端

`modbus_client.py` 实现 Modbus TCP Client，连接小车控制器。

**适配要点：**

- 如果新场景不使用小车，可以移除此模块
- 如果使用不同协议的小车，需要重写客户端

---

## 4. 视觉系统配置

### 4.1 相机选型

当前系统支持 Intel RealSense D435i 和 D405 双相机：

| 参数 | D435i | D405 |
|------|-------|------|
| 深度范围 | 0.5-2.2m | 0.07-0.8m |
| 用途 | 粗识别（目标中心点） | 精识别（铁钩两端） |
| 分辨率 | 640×480 | 640×480 |
| 帧率 | 30fps | 30fps |

**适配步骤：**

1. 如果使用其他品牌深度相机（如 Orbbec、Zivid），需要替换 `pyrealsense2` 依赖
2. 修改 `vision_system.py` 中的相机初始化代码：
   - 替换 `rs.pipeline()` 为新相机的 SDK 接口
   - 替换 `rs.config().enable_device(serial)` 为新相机的多设备区分方式
   - 调整深度范围参数 `min_depth`/`max_depth`
3. 确保新相机提供：对齐的深度帧+彩色帧、相机内参（fx, fy, cx, cy）

### 4.2 模型推理

当前使用 YOLOv8 实例分割 ONNX 模型（`best.onnx`），通过 `onnxruntime` 推理。

**适配要点：**

- ONNX Runtime 与硬件无关，无需修改
- 如果更换检测目标，需要训练新模型并替换 `best.onnx`
- 如果更换模型框架（如 TensorRT、OpenVINO），修改 `vision_system.py` 中的推理代码

### 4.3 坐标转换流程

```
像素坐标 → 相机3D坐标 → 末端坐标 → 基座坐标
           (相机内参)    (手眼矩阵)   (机器人位姿)
```

此流程与机器人品牌无关，只需确保手眼标定矩阵正确。

---

## 5. 手眼标定

### 5.1 标定矩阵格式

系统使用 4×4 齐次变换矩阵 `T_cam2gripper`（相机到末端的变换），存储在 `config.json` 的 `calibration` 字段中。

计算公式：
```
T_cam2gripper = inv(T_tool2base) @ T_cam2base
```

其中：
- `T_tool2base`：标定板上工具点相对于基座的位姿（6自由度：x, y, z, rx, ry, rz）
- `T_cam2base`：相机原点相对于基座的位姿

### 5.2 适配步骤

1. **标定数据采集**：使用新机器人的示教器记录标定板上工具点的位姿
2. **计算标定矩阵**：使用 `config_manager.get_camera_handeye_matrix()` 或 `hand_eye_calib.py` 中的 `HandEyeCalibManager`
3. **写入配置**：通过 GUI 的"手眼标定"选项卡输入矩阵，或直接编辑 `config.json`
4. **验证**：将标定后的坐标与实际位置对比，误差应 < 5mm

### 5.3 注意事项

- 不同机器人的欧拉角约定可能不同（ZYX/ZXY/XYZ 等），需确认新设备的旋转顺序
- `transform_utils.py` 中的 `euler2rot` 使用 ZYX 旋转顺序（`R = Rz @ Ry @ Rx`），如果新设备使用不同约定需要修改
- 角度单位：当前系统使用度（degree），部分机器人使用弧度

---

## 6. 点位管理系统

### 6.1 数据格式

点位存储在 `config.json` 的 `points` 字段中，每个点位包含：

```json
{
  "coords": [x, y, z, rx, ry, rz],
  "is_relative": false,
  "relative_to": null,
  "offset": [0, 0, 0, 0, 0, 0],
  "is_default": true
}
```

| 字段 | 类型 | 含义 |
|------|------|------|
| `coords` | float[6] | 绝对坐标（mm, deg） |
| `is_relative` | bool | 是否为相对点位 |
| `relative_to` | string/null | 基准点位名称 |
| `offset` | float[6] | 相对偏移量 |
| `is_default` | bool | 是否为系统默认点位（不可删除） |

### 6.2 默认点位

系统预置两个默认点位，由相机识别后自动更新：

| 点位名 | 含义 | 更新来源 |
|--------|------|---------|
| `d435i` | D435i 识别到的目标点位 | D435i 相机识别 |
| `d405` | D405 识别到的目标点位 | D405 相机识别 |

### 6.3 迁移步骤

1. **坐标系转换**：如果新机器人使用不同的坐标系定义（如 Z 轴方向不同），需要转换所有点位坐标
2. **角度约定**：确认欧拉角约定是否一致
3. **重新标定**：建议在新设备上重新执行视觉识别流程，让系统自动更新默认点位
4. **自定义点位**：手动记录的点位需要重新示教

---

## 7. 力控圆弧

### 7.1 依赖的机器人接口

力控圆弧功能依赖以下越疆专有指令：

| 指令 | 功能 | 必要性 |
|------|------|--------|
| `EnableFTSensor(1)` | 使能力传感器 | 必须 |
| `SixForceHome()` | 力传感器清零 | 必须 |
| `FCForceMode(...)` | 进入力控模式 | 必须 |
| `FCSetDeviation(...)` | 设置力控偏差阈值 | 必须 |
| `FCSetForceLimit(...)` | 设置力限制 | 必须 |
| `FCSetDamping(...)` | 设置阻尼 | 必须 |
| `FCSetStiffness(...)` | 设置刚度 | 必须 |
| `FCSetMass(...)` | 设置质量 | 必须 |
| `FCSetForceSpeedLimit(...)` | 设置力控速度限制 | 必须 |
| `FCSetForce(...)` | 设置目标力 | 必须 |
| `FCOff()` | 退出力控模式 | 必须 |

### 7.2 适配步骤

1. **确认新设备支持力控功能**：需要 6 轴力传感器和力控模式 API
2. **替换力控指令**：在 `force_arc_controller.py` 中将越疆力控指令替换为新设备的等价接口
3. **调整力反馈监控**：`force_feedback_monitor.py` 通过 `GetForce()` 读取力数据，需替换为新设备的力传感器读取接口
4. **参数调整**：不同机器人的力控参数（偏差阈值、阻尼、刚度）范围可能不同，需要根据新设备规格调整

### 7.3 圆弧轨迹规划

`arc_trajectory_planner.py` 生成圆弧路点，与机器人品牌无关，无需修改。

---

## 8. 配置文件

### 8.1 config.json 格式

```json
{
  "photo_position": [x, y, z, rx, ry, rz],
  "calibration": {
    "D435i": {
      "tool_base_calib_pose": [x, y, z, rx, ry, rz],
      "cam_base_calib_pose": [x, y, z, rx, ry, rz]
    },
    "D405": {
      "tool_base_calib_pose": [x, y, z, rx, ry, rz],
      "cam_base_calib_pose": [x, y, z, rx, ry, rz]
    }
  },
  "points": {
    "point_name": {
      "coords": [x, y, z, rx, ry, rz],
      "is_relative": false,
      "relative_to": null,
      "offset": [0, 0, 0, 0, 0, 0],
      "is_default": false
    }
  },
  "robot_ip": "192.168.5.1",
  "cart_ip": "192.168.5.2",
  "cart_port": 502,
  "modbus_port": 502
}
```

### 8.2 需要修改的配置项

| 配置项 | 说明 | 移植时操作 |
|--------|------|-----------|
| `robot_ip` | 机器人 IP 地址 | 改为新设备 IP |
| `photo_position` | 拍照位置 | 重新示教 |
| `calibration.*` | 手眼标定数据 | 重新标定 |
| `points.*` | 所有点位 | 重新示教或坐标转换 |
| `cart_ip/port` | 小车 Modbus 地址 | 根据实际情况修改 |
| `modbus_port` | Modbus 服务端口 | 根据实际情况修改 |

---

## 9. 移植检查清单

### 9.1 通信层验证

- [ ] 新设备 TCP/IP 连接正常（或替代通信方式）
- [ ] Dashboard 指令端口可连接
- [ ] 实时反馈端口可连接（如适用）
- [ ] `EnableRobot` / `DisableRobot` 正常工作
- [ ] `ClearError` 正常工作
- [ ] `SpeedFactor` 速度设置生效

### 9.2 运动控制验证

- [ ] `MovJ` 关节运动到目标位姿正常
- [ ] `MovL` 直线运动到目标位姿正常
- [ ] `MovC` 圆弧运动正常（如需要）
- [ ] `RelJointMovJ` 关节相对运动正常
- [ ] `MoveJog` 点动控制正常
- [ ] `GetPose` 返回正确的 TCP 位姿
- [ ] `GetAngle` 返回正确的关节角度
- [ ] `RobotMode` 状态查询正常
- [ ] `Pause` / `Continue` / `Stop` 正常工作

### 9.3 视觉系统验证

- [ ] 相机连接正常
- [ ] 深度帧和彩色帧对齐正确
- [ ] 相机内参获取正确
- [ ] 物体检测模型推理正常
- [ ] 像素到 3D 坐标转换正确
- [ ] 手眼标定矩阵计算正确
- [ ] 相机坐标→末端坐标→基座坐标转换正确

### 9.4 点位管理验证

- [ ] 默认点位（d435i, d405）由相机正确更新
- [ ] 自定义点位添加/删除/修改正常
- [ ] 相对点位解析正确（递归解析无循环引用）
- [ ] 点位在流程中正确使用

### 9.5 力控圆弧验证

- [ ] 力传感器使能和清零正常
- [ ] 力控模式进入/退出正常
- [ ] 力控参数设置生效
- [ ] 圆弧轨迹生成正确
- [ ] 力反馈监控数据正确
- [ ] 力控修正量计算合理

### 9.6 Modbus 通信验证

- [ ] Modbus TCP Server 启动正常
- [ ] 外部设备可读写寄存器
- [ ] 寄存器数据与机器人状态同步
- [ ] Modbus TCP Client 连接小车正常（如适用）

### 9.7 GUI 验证

- [ ] 主界面状态显示正确
- [ ] 机器人连接/使能/下使能操作正常
- [ ] 相机连接/断开操作正常
- [ ] 抓取流程执行正常
- [ ] 点动控制正常
- [ ] 手眼标定界面正常
- [ ] Modbus 通信界面正常

---

## 附录 A：常见机器人品牌适配参考

| 品牌 | 通信方式 | 力控支持 | 适配难度 |
|------|---------|---------|---------|
| 越疆 CR 系列 | TCP/IP (29999/30004) | 原生支持 | — (当前) |
| UR (e-Series) | URScript (30004) | 力控模式 | 中 |
| 遨博 (AUBO) | TCP/IP (8899) | 力控模式 | 中 |
| 艾利特 (ELITE) | TCP/IP (8080) | 部分支持 | 中-高 |
| KUKA | KRL/EKI | 需外部传感器 | 高 |
| FANUC | Socket/FOCUS | 需外部传感器 | 高 |
| ABB | RAPID/PC SDK | 需外部传感器 | 高 |

## 附录 B：关键文件修改清单

移植到新设备时，按以下顺序修改文件：

1. `dobot_api.py` → 替换为新设备的通信协议实现
2. `robot_controller.py` → 适配运动指令和状态解析
3. `force_arc_controller.py` → 适配力控指令（如新设备支持）
4. `force_feedback_monitor.py` → 适配力传感器数据读取
5. `vision_system.py` → 适配新相机（如更换品牌）
6. `config.json` → 更新 IP、标定数据、点位
7. `gui_app.py` → 通常不需要修改（除非新设备有特殊 UI 需求）

## 10. C++ 核心加速模块移植

### 10.1 模块概述

`dobot_core` 是通过 Pybind11 暴露给 Python 的 C++ 加速模块，用于替代视觉后处理和坐标变换中的计算密集型 Python 代码。当 `dobot_core` 不可用时，程序自动回退到纯 Python 实现。

### 10.2 模块结构

```
cpp_core/
├── CMakeLists.txt              # CMake 构建配置
├── include/dobot_core/
│   ├── transforms.h            # 坐标变换接口
│   ├── nms.h                   # NMS 接口
│   └── yolo.h                  # YOLOv8 后处理接口
└── src/
    ├── pybind_module.cpp       # Pybind11 模块绑定入口
    ├── transforms.cpp          # euler2rot / pose2matrix / transform_point
    ├── nms.cpp                 # 非极大值抑制
    └── yolo.cpp                # YOLOv8 后处理 + process_mask
```

### 10.3 编译依赖

| 依赖 | 最低版本 | 说明 |
|------|---------|------|
| CMake | 3.15 | 构建系统 |
| C++ 编译器 | C++17 | MSVC 2019+ / GCC 9+ / Clang 10+ |
| pybind11 | 2.10 | Python/C++ 绑定库 |
| Python | 3.10 | 目标 Python 版本 |

### 10.4 API 接口

`dobot_core` 暴露 3 个子模块：

#### dobot_core.transforms

| 函数 | 签名 | 说明 |
|------|------|------|
| `euler2rot` | `(rx, ry, rz, degree=True) → ndarray(3,3)` | 欧拉角→旋转矩阵，ZYX 顺序 |
| `pose2matrix` | `(x, y, z, rx, ry, rz) → ndarray(4,4)` | 位姿→齐次变换矩阵 |
| `transform_point` | `(matrix, point) → ndarray(3)` | 齐次矩阵变换点坐标 |

#### dobot_core.nms

| 函数 | 签名 | 说明 |
|------|------|------|
| `nms` | `(boxes, scores, iou_threshold=0.5) → list[int]` | 非极大值抑制 |

#### dobot_core.yolo

| 函数 | 签名 | 说明 |
|------|------|------|
| `postprocess_yolov8` | `(outputs, original_size, scale, offset, new_size, num_classes, conf_threshold=0.25, iou_threshold=0.5) → list[dict]` | YOLOv8 检测后处理 |
| `process_mask` | `(protos, masks_in, bboxes, shape, scale, offset, new_size, threshold=0.5) → list[ndarray]` | 掩码生成 |

### 10.5 Python 集成方式

Python 端通过 `try/except` 导入 `dobot_core`，设置模块级标志位：

```python
try:
    import dobot_core
    DOBOT_CORE_AVAILABLE = True
except ImportError:
    DOBOT_CORE_AVAILABLE = False
```

调用时优先使用 C++ 实现，失败时静默回退：

```python
def euler2rot(rx, ry, rz, degree=True):
    if DOBOT_CORE_AVAILABLE:
        try:
            return dobot_core.transforms.euler2rot(rx, ry, rz, degree)
        except Exception:
            pass
    return _euler2rot_py(rx, ry, rz, degree)
```

### 10.6 跨平台编译

#### Windows (MSVC)

```bash
pip install pybind11 cmake
python build_cpp.py
```

#### Linux (GCC)

```bash
sudo apt install build-essential cmake
pip install pybind11 cmake
python build_cpp.py
```

编译产物：
- Windows: `dobot_core.cp3XX-win_amd64.pyd`
- Linux: `dobot_core.cpython-3XX-linux-x86_64.so`

### 10.7 移植注意事项

1. **无外部依赖**：C++ 代码仅依赖 pybind11 和标准库，不使用 OpenCV 或 Eigen
2. **双线性插值**：`yolo.cpp` 中自实现了 `bilinear_resize` 函数替代 `cv2.resize`
3. **数值精度**：C++ 实现与 Python numpy 结果在 1e-6 浮点精度内一致
4. **NMS 排序**：使用 `std::stable_sort` 降序排列，与 numpy argsort 行为一致
5. **MSVC 兼容**：`transforms.cpp` 需 `#define _USE_MATH_DEFINES` 以启用 `M_PI`
6. **数组转置**：`postprocess_yolov8` 中 3D 输入需先 reshape 再转置（与 Python `dets[0].T` 等价）

### 10.8 移植检查清单

- [ ] CMake 配置正确，`find_package(pybind11)` 可找到 pybind11
- [ ] 编译成功生成 `.pyd` 或 `.so` 文件
- [ ] `import dobot_core` 无报错
- [ ] `dobot_core.transforms.euler2rot` 与 Python 版本精度差 < 1e-6
- [ ] `dobot_core.nms.nms` 返回结果与 Python 版本一致
- [ ] `dobot_core.yolo.process_mask` 掩码 IoU > 0.95
- [ ] 删除 `.pyd`/`.so` 后程序正常运行（回退机制）
