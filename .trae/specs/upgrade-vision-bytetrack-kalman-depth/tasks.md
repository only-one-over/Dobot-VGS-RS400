# Tasks

- [x] Task 1: 创建 3D 卡尔曼滤波器模块 `kalman_filter_3d.py`
  - [x] 1.1: 创建 `c:\Users\ADMIN\Desktop\dobot_move_python\dobot_move\kalman_filter_3d.py`，实现 `KalmanFilter3D` 类

- [x] Task 2: 创建 ByteTrack 跟踪器模块 `tracker.py`
  - [x] 2.1: 实现 `STrack` 类
  - [x] 2.2: 实现 `BYTETracker` 类
  - [x] 2.3: 实现辅助函数 iou_distance 和 linear_assignment

- [x] Task 3: 创建深度处理增强模块 `depth_processor.py`
  - [x] 3.1: 创建 `DepthProcessor` 类
  - [x] 3.2: 实现 RealSense 官方滤波链初始化
  - [x] 3.3: 实现 process_frame() 方法
  - [x] 3.4: 实现 process_depth_image() 方法

- [x] Task 4: 修改 `vision_system.py` 集成三个新模块
  - [x] 4.1: VisionSystem.__init__ 新增参数和初始化
  - [x] 4.2: 修改 capture_frames() 集成深度滤波链
  - [x] 4.3: 新增 run_detection_tracked() 方法
  - [x] 4.4: 新增 _select_target() 方法
  - [x] 4.5: 新增 calculate_object_position_smoothed() 方法
  - [x] 4.6: 新增 reset_tracking() 方法

- [x] Task 5: 修改 `gui_app.py` FlowThread 相机模块
  - [x] 5.1: 修改 FlowThread 中 camera 类型模块的执行逻辑
  - [x] 5.2: 在流程开始前调用 reset_tracking()
  - [x] 5.3: 日志输出增加平滑和置信度信息

- [x] Task 6: 更新 `requirements.txt`
  - [x] 6.1: 新增 lapx 依赖

# Task Dependencies
- Task 1 独立
- Task 2 独立
- Task 3 独立
- Task 4 依赖 Task 1, 2, 3
- Task 5 依赖 Task 4
- Task 6 独立
