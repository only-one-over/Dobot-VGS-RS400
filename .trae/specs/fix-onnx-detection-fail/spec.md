# 修复 ONNX 物体检测失败 - Spec

## Why
机器人移动到拍照位置后，相机无法识别物体。根因是 `best.onnx` 模型路径使用相对路径，运行时工作目录不匹配导致模型加载失败（`session=None`），所有检测静默返回 `None`。同时模型输出格式假设硬编码为 seg 格式，如果实际是 detect 模型则永远返回空列表。

## What Changes
- `vision_system.py` — 模型路径改为基于 `__file__` 的绝对路径
- `vision_system.py` — 模型加载失败时抛出 `RuntimeError`，不再静默设置 `session=None`
- `vision_system.py` — 后处理支持 detect 模型（1个输出）和 seg 模型（2个输出）
- `vision_system.py` — 从模型输出形状动态推断 `num_classes`

## Impact
- Affected specs: 无
- Affected code: `dobot_move/vision_system.py` L122, L136-L144, L424-L535, L60-L61

## MODIFIED Requirements
### Requirement: 模型路径使用绝对路径
`VisionSystem.__init__` SHALL 使用 `os.path.dirname(os.path.abspath(__file__))` 构建 `best.onnx` 的绝对路径。

#### Scenario: 从不同工作目录启动
- **GIVEN** 程序从 `dobot_move_python/` 目录运行 `python dobot_move/gui_app.py`
- **WHEN** `VisionSystem` 加载模型
- **THEN** 模型路径解析为 `dobot_move_python/dobot_move/best.onnx`，文件可被正确找到

### Requirement: 模型加载失败必须报错
`VisionSystem.__init__` SHALL 在 ONNX 模型加载失败时抛出 `RuntimeError`，而非静默设置 `session=None`。

#### Scenario: 模型文件不存在或格式错误
- **GIVEN** `best.onnx` 文件不存在或损坏
- **WHEN** 构造 `VisionSystem()` 实例
- **THEN** 抛出 `RuntimeError("ONNX模型加载失败: ...")`

### Requirement: 后处理兼容 detect 和 seg 模型
`_postprocess_yolov8_py` SHALL 同时支持 1 个输出（detect）和 2 个输出（seg）的模型格式。当只有 1 个输出时，跳过掩码处理，仅返回 bbox 检测结果。

#### Scenario: 使用 detect 模型
- **GIVEN** 模型输出只有 1 个张量（detect 格式）
- **WHEN** 调用 `_postprocess_yolov8_py`
- **THEN** 正常返回 bbox 检测结果，mask 字段为 None

### Requirement: 动态推断 num_classes
`VisionSystem.__init__` SHALL 从模型输出形状动态推断 `num_classes`，而非硬编码为 1。

#### Scenario: 模型类别数变化
- **GIVEN** 模型输出形状为 `(1, 37, 8400)`
- **WHEN** 加载模型后推断 `num_classes`
- **THEN** `num_classes = 37 - 4 - 32 = 1`（seg 模型）或 `num_classes = 37 - 4 = 33`（detect 模型无掩码系数）
