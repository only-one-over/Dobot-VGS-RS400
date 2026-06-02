# 识别部分代码逻辑审查 - Spec

## Why
对 `vision_system.py` 及 `gui_app.py` 中的视觉识别链路进行全面审查，确保坐标转换、深度获取、物体检测等逻辑正确，发现并修复潜在缺陷。

## 审查结论

### 正确的部分 ✅
- 手眼标定公式 `inv(T_tool2base) @ T_cam2base` — 标准 eye-in-hand 公式
- 针孔相机模型 `X = (u-cx)*Z/fx` — 实现正确
- 深度单位链 `raw(uint16) × scale → 米 × 1000 → 毫米` — 全程一致
- 坐标转换链 `相机 → 末端 → 基座` — 公式推导无误
- 欧拉角 ZYX 旋转顺序 — 匹配越疆机器人 SDK
- 帧对齐 `rs.align(rs.stream.color)` — 深度图与彩色图像素一致

### 需要修复的问题 ⚠️
1. **相机初始化失败静默成功**：`VisionSystem.__init__` 中相机连接失败时仅设 `camera_available=False`，不抛异常，用户点击"连接相机"后无错误提示
2. **`convert_to_end_coords` 中 `T_cam2gripper` 为 None 时返回 `[0,0,0]`**：静默返回基座原点附近坐标，机器人可能移动到错误位置

## What Changes
- `vision_system.py` `__init__` — 相机初始化失败时抛出异常，让上层感知
- `vision_system.py` `convert_to_end_coords` — `T_cam2gripper` 为 None 时抛异常而非返回 `[0,0,0]`
- `gui_app.py` `connect_camera` — 捕获相机初始化异常并弹窗报错

## Impact
- Affected specs: 无
- Affected code: `dobot_move/vision_system.py` L48-L146, L229-L246; `dobot_move/gui_app.py` connect_camera

## MODIFIED Requirements
### Requirement: 相机初始化失败必须报错
`VisionSystem.__init__` SHALL 在相机不可用时抛出 `RuntimeError`，而非静默设置标志位。

#### Scenario: 相机未连接或启动失败
- **GIVEN** RealSense 相机未插入或驱动未加载
- **WHEN** 构造 `VisionSystem()` 实例
- **THEN** 抛出 `RuntimeError("相机初始化失败: ...")`
- **AND** GUI 弹出错误提示，明确告知用户检查相机连接

### Requirement: T_cam2gripper 为 None 时必须报错
`convert_to_end_coords` SHALL 在 `self.T_cam2gripper` 为 None 时抛出 `ValueError`，而非静默返回零向量。

#### Scenario: 标定矩阵未初始化
- **GIVEN** `T_cam2gripper` 为 None
- **WHEN** 调用 `convert_to_end_coords`
- **THEN** 抛出 `ValueError("手眼标定矩阵未初始化")`
