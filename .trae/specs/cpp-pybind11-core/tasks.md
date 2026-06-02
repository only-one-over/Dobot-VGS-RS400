# Tasks

- [x] Task 1: 搭建 C++ 构建基础设施
  - [x] SubTask 1.1: 创建 `cpp_core/` 目录结构（`src/`、`include/dobot_core/`）
  - [x] SubTask 1.2: 编写 `cpp_core/CMakeLists.txt`，配置 Pybind11 和编译目标 `dobot_core`
  - [x] SubTask 1.3: 编写 `cpp_core/include/dobot_core/transforms.h` 声明坐标变换接口
  - [x] SubTask 1.4: 编写 `cpp_core/include/dobot_core/nms.h` 声明 NMS 接口
  - [x] SubTask 1.5: 编写 `cpp_core/include/dobot_core/yolo.h` 声明 YOLOv8 后处理接口
  - [x] SubTask 1.6: 编写 `cpp_core/src/pybind_module.cpp` Pybind11 模块绑定入口
  - [x] SubTask 1.7: 编写 `build_cpp.py` 一键构建脚本

- [x] Task 2: 实现 C++ 坐标变换模块
  - [x] SubTask 2.1: 实现 `cpp_core/src/transforms.cpp`（euler2rot、pose2matrix、transform_point）
  - [x] SubTask 2.2: 在 `pybind_module.cpp` 中绑定 `dobot_core.transforms` 子模块

- [x] Task 3: 实现 C++ NMS 模块
  - [x] SubTask 3.1: 实现 `cpp_core/src/nms.cpp`（nms 函数）
  - [x] SubTask 3.2: 在 `pybind_module.cpp` 中绑定 `dobot_core.nms` 子模块

- [x] Task 4: 实现 C++ YOLOv8 后处理模块
  - [x] SubTask 4.1: 实现 `cpp_core/src/yolo.cpp`（postprocess_yolov8、process_mask）
  - [x] SubTask 4.2: 在 `pybind_module.cpp` 中绑定 `dobot_core.yolo` 子模块

- [x] Task 5: 修改 `vision_system.py` 集成 C++ 模块
  - [x] SubTask 5.1: 添加 `dobot_core` 导入和回退机制
  - [x] SubTask 5.2: 替换 `nms` 方法为 C++ 版本（带回退）
  - [x] SubTask 5.3: 替换 `process_mask` 和 `postprocess_yolov8` 为 C++ 版本（带回退）

- [x] Task 6: 修改 `transform_utils.py` 集成 C++ 模块
  - [x] SubTask 6.1: 添加 `dobot_core` 导入和回退机制
  - [x] SubTask 6.2: 替换 `euler2rot` / `pose2matrix` 为 C++ 版本（带回退）

- [x] Task 7: 构建验证
  - [x] SubTask 7.1: 所有 C++ 源文件和头文件已创建，CMakeLists.txt 配置正确
  - [x] SubTask 7.2: pybind_module.cpp 正确绑定3个子模块
  - [x] SubTask 7.3: 回退机制已验证（vision_system.py 和 transform_utils.py 均有回退标志）

# Task Dependencies
- [Task 2] depends on [Task 1] (需要构建基础设施和头文件)
- [Task 3] depends on [Task 1]
- [Task 4] depends on [Task 1]
- [Task 5] depends on [Task 2, Task 3, Task 4] (需要 C++ 模块实现完成)
- [Task 6] depends on [Task 2]
- [Task 7] depends on [Task 5, Task 6]
- [Task 2, 3, 4] 可并行执行
