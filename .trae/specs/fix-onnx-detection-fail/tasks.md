# Tasks

- [x] Task 1: 修复模型路径为绝对路径 + 模型加载失败抛异常
  - 修改 `vision_system.py` L123，将 `self.model_path = "best.onnx"` 改为 `os.path.join(os.path.dirname(os.path.abspath(__file__)), "best.onnx")`
  - 修改 `vision_system.py` L151-L158，模型加载失败时 `raise RuntimeError` 而非 `self.session = None`
  - 添加调试日志：打印模型绝对路径和文件是否存在

- [x] Task 2: 后处理兼容 detect 和 seg 模型 + 动态推断 num_classes
  - 修改 `vision_system.py` L60-L62，新增 `is_seg_model` 标志
  - 修改 `vision_system.py` L137-L149，从模型输出形状动态推断 `num_classes`
  - 修改 `vision_system.py` L442-L445，当 `len(outputs) < 2` 时按 detect 模型处理
  - seg 模型时：`num_classes = num_channels - 4 - 32`
  - detect 模型时：`num_classes = num_channels - 4`，无掩码系数

# Task Dependencies
- Task 1 与 Task 2 无顺序依赖，可并行执行
