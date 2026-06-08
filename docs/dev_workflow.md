# 开发工作流

## 安装依赖

从仓库根目录：

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

RealSense 工作还需要在 Python 之外安装 Intel RealSense SDK 2.0。原生加速需要 CMake、C++17 编译器和 pybind11。

## 启动项目

运行 PyQt 应用：

```powershell
.\.venv\Scripts\activate
python dobot_move\gui_app.py
```

应用期望运行时配置位于 `dobot_move/config.json`。相机启动期望已连接 RealSense 硬件且 ONNX 模型位于 `dobot_move/best.onnx`。

## 运行测试和检查

当前测试覆盖率有限。使用定向检查：

```powershell
python -m py_compile dobot_move\gui_app.py dobot_move\workers.py dobot_move\vision_system.py
python test_yolo26_bbox.py
```

仅在确认所需模型/输入假设后使用 `test_yolo26_bbox.py`。TODO：将测试脚本移至 `tests/` 并记录测试夹具。

## 构建原生加速模块

推荐的辅助脚本：

```powershell
pip install pybind11 cmake
python build_cpp.py
```

替代 CMake 路径：

```powershell
cmake -S cpp_core -B cpp_core/build
cmake --build cpp_core/build --config Release
```

验证：

```powershell
python -c "import dobot_core; print('C++ module OK:', dir(dobot_core))"
```

## 构建或打包

仓库包含 `DobotControl.spec`，表明支持 PyInstaller 打包。

TODO：在依赖打包输出之前，确认当前打包命令、所需数据文件、模型文件、RealSense DLL 和 C++ 扩展放置位置。

## 提交代码

推荐的本地流程：

```powershell
git status
python -m py_compile <touched-python-files>
git diff
git add <intended-files>
git commit -m "<short change summary>"
```

不要包含生成的构建目录、本地虚拟环境或意外的运行时配置变更，除非它们是有意变更的一部分。

## 常见问题排查

- 缺少 `pyrealsense2`：先安装 Intel RealSense SDK，然后安装与本地 Python/SDK 环境匹配的 Python 包。
- `ModuleNotFoundError: dobot_core`：构建原生扩展或依赖 Python 回退。
- C++ 导入 ABI 错误：使用运行应用的相同 Python 版本重新构建。
- 相机连接失败：检查 USB 连接、RealSense SDK 安装、序列号选择和 RealSense Viewer 中的相机可用性。
- 机器人连接失败：检查机器人电源、网段、`config.json` 中配置的 IP、Dashboard 端口和 TCP/IP 模式。
- ONNX Runtime provider 失败：CUDA provider 可能失败并回退到 CPU provider；在假设模型失败之前检查日志。
- Modbus 失败：检查端口 `502`、防火墙、是否有其他进程已占用该端口以及小车/服务器 IP 设置。
- 中文乱码：保持 UTF-8，避免使用 GBK 等编辑器编码，除非有意恢复现有文本。

## 建议的项目目录

为未来规范性创建/建议：

- `tests/`：在明确测试夹具假设后，将定向回归测试移至此处。
- `scripts/`：将可重复的维护/构建/检查脚本放置在此处。
- `README.md`：保持设置和操作员快速入门最新；将更深入的工程细节移至 `docs/`。
