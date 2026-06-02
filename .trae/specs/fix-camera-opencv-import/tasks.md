# Tasks

- [x] Task 1: 修复 gui_app.py 中 cv2 未导入的问题
  - [x] SubTask 1.1: 在 `gui_app.py` L38-41 的视觉导入 try 块中增加 `import cv2`，使 cv2 在 gui_app.py 命名空间可用
  - [x] SubTask 1.2: 重写 except 块，逐个检测 pyrealsense2、cv2、onnxruntime 是否可导入，列出具体缺失的库及安装命令

- [x] Task 2: 为 vision_system.py 的 cv2 导入添加容错处理
  - [x] SubTask 2.1: 将 `vision_system.py` L9 的 `import cv2` 改为 try/except 包裹，导入失败时抛出包含 "opencv-python" 关键字的明确 ImportError

- [x] Task 3: 为 depth_processor.py 的 cv2 导入添加容错处理
  - [x] SubTask 3.1: 将 `depth_processor.py` L5 的 `import cv2` 改为 try/except 包裹，与 pyrealsense2 的导入方式保持一致，设置 `HAS_CV2 = True/False` 标志
  - [x] SubTask 3.2: 在 `process_depth_image` 方法中检查 `HAS_CV2`，不可用时给出明确提示而非崩溃

# Task Dependencies
- Task 1 与 Task 2、Task 3 无顺序依赖，可并行执行
- Task 2 和 Task 3 无依赖关系，可并行执行
