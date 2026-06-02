# Tasks

- [x] Task 1: `VisionSystem.__init__` — 相机初始化失败时抛出 RuntimeError
  - 修改 `vision_system.py` L115-L118，`except` 分支中改为 `raise RuntimeError(...)`
  - 同时在 `capture_frames` 中移除 `if not self.camera_available` 的冗余检查

- [x] Task 2: `convert_to_end_coords` — T_cam2gripper 为 None 时抛异常
  - 修改 `vision_system.py` L232-L233，将 `return np.array([0,0,0])` 改为 `raise ValueError`

# Task Dependencies
- Task 1 与 Task 2 无顺序依赖，可并行执行
