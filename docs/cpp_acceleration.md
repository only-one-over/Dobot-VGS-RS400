# C++ 加速指南

本项目可以使用 `dobot_core` pybind11 模块加速最热的视觉路径：

- YOLO 分割后处理：bbox 解析、NMS、掩码生成。
- 深度定位计算：掩码质心、深度回退、相机坐标。
- 坐标变换：`dobot_core` 已暴露的欧拉角/矩阵辅助函数。

如果无法导入 `dobot_core`，将自动使用 Python 实现。应用应继续正常工作，但视觉延迟会更高。

## 构建要求

- CMake 3.15 或更新版本
- C++17 编译器
- 与运行应用的 Python 匹配的 Python 开发头文件
- `pybind11`

在 Windows 上，尽可能使用运行 GUI 的相同 Python 环境。

## 构建命令

从仓库根目录：

```powershell
cmake -S cpp_core -B cpp_core/build
cmake --build cpp_core/build --config Release
```

构建的扩展由 `cpp_core/CMakeLists.txt` 写入仓库根目录。构建后，根目录应包含平台特定的扩展文件，如 `dobot_core.pyd`。

## 验证 C++ 加速是否启用

使用应用的 Python 从仓库根目录运行：

```powershell
python - <<'PY'
import dobot_core
print("dobot_core loaded:", dobot_core.__doc__)
print("has yolo:", hasattr(dobot_core, "yolo"))
print("has depth:", hasattr(dobot_core, "depth"))
print("has transforms:", hasattr(dobot_core, "transforms"))
PY
```

GUI 在 `dobot_move/vision_system.py` 中导入 `dobot_core`。当导入成功时，会优先尝试以下路径：

- `dobot_core.yolo.postprocess_yolov8`
- `dobot_core.yolo.postprocess_yolo26`
- `dobot_core.yolo.process_mask`
- `dobot_core.depth.calculate_object_position`

如果 C++ 调用抛出异常，代码会记录调试回退消息并使用该操作的 Python 实现。

## 深度定位接口契约

`dobot_core.depth.calculate_object_position(...)` 期望：

```python
calculate_object_position(
    depth_image,   # uint16 HxW RealSense 深度图
    mask,          # uint8 HxW 分割掩码，有效像素 > 127
    bbox,          # (x1, y1, x2, y2) 或 None
    fx, fy, cx, cy,
    depth_scale,
    min_depth,
    max_depth,
)
```

返回 `None` 或：

```python
{
    "center_x": int,
    "center_y": int,
    "depth": float,                 # 米
    "camera_coords": (x, y, z),      # 毫米
}
```

中心点是分割掩码的质心，而非 bbox 中心。如果中心深度无效，C++ 路径会计算 bbox 限定掩码区域内的中位数有效深度。

## 性能验证

运行相机识别并检查以下日志：

- `performance[detection]`
- `performance[depth_position]`
- `performance[camera_test_worker]`
- `performance[d435i_low_fps_worker]`

预期改进应主要出现在：

- `performance[detection]` 中的 `postprocess` 时间
- `performance[depth_position]` 中的 `total` 时间
- 存在检测时的 Worker `total` 时间

## 回退测试

要确认 Python 回退仍然有效，临时将构建的扩展重命名到应用进程之外，例如：

```powershell
Rename-Item .\dobot_core*.pyd dobot_core.disabled.pyd
```

然后启动应用。它应该仍然运行，但 C++ 加速路径将不可用。测试完成后将文件重命名回来。

## 问题排查

- `ModuleNotFoundError: dobot_core`：构建输出缺失或不在仓库根目录/Python 路径中。
- 关于 Python DLL 或 ABI 的 `ImportError`：使用运行 GUI 的相同 Python 重新构建。
- 找不到 `pybind11_DIR`：在当前 Python 环境中安装 `pybind11` 或显式传递其 CMake 目录。
- C++ 调用在 info 级别静默回退：启用调试日志以查看具体的回退原因。
