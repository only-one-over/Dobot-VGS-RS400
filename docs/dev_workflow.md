# 开发工作流

## 安装依赖

所有依赖统一在 `requirements.txt` 中，用注释分区标注（基础 / GPU可选 / C++可选）。

从仓库根目录：

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

GPU 环境详细部署指南见 [gpu_environment.md](gpu_environment.md)。

RealSense 工作还需要在 Python 之外安装 Intel RealSense SDK 2.0。原生加速需要 CMake、C++17 编译器和 pybind11。

## 启动项目

运行 PyQt 应用：

```powershell
.\.venv\Scripts\activate
python -m dobot_move
```

应用期望运行时配置位于 `user_data/config.json`（首次升级时从 `dobot_move/config.json` 自动迁移）。D435i、D405 可在主控制页分别选择 ONNX 模型，路径保存到 `camera.models`；缺少该配置时使用 `dobot_move/best.onnx`。模型文件不提交到 Git，部署时需单独复制到工控机。

### 启动 Remote REST API（可选）

供外部平板/MES 只读查询的独立 HTTP 服务，与 Runtime 解耦：

```powershell
.\.venv\Scripts\activate
python -m dobot_move.remote_api --host 0.0.0.0 --port 8000
```

配置块见 `user_data/config.json` 的 `remote_api` 段（缺失时使用默认值）。`token` 为空时禁用认证；生产环境应配置非空 token 并限制 `allowed_ips`。架构与端点契约见 [architecture.md](architecture.md#阶段-8-remote-rest-api)。

## 运行测试和检查

当前测试覆盖率有限。使用定向检查：

```powershell
# 语法检查关键模块
python -m py_compile dobot_move\flow\flow_executor.py dobot_move\flow\qt_workers.py dobot_move\flow\camera_test_worker.py dobot_move\runtime\runtime_agent.py

# 运行测试套件（排除依赖硬件的测试）
python -m pytest tests\ --ignore=tests\test_feedback_cache.py -q
```

Runtime 去 Qt 化验证：

```powershell
# 验证 FlowExecutor 回调接口
python -m pytest tests\test_flow_executor_callbacks.py -v

# 验证 runtime_agent 不依赖 Qt（AST 级 + 运行时导入检查）
python -m pytest tests\test_runtime_no_qt_import.py -v
```

Remote REST API 验证：

```powershell
# 语法检查
python -m py_compile dobot_move\remote_api\app.py dobot_move\remote_api\handlers.py dobot_move\remote_api\feedback_worker.py dobot_move\remote_api\modbus_client.py dobot_move\remote_api\config.py

# 单元测试（纯函数 + Token 中间件 + 301 重定向 + 配置默认值合并）
python -m pytest tests\test_remote_api_handlers.py -v

# 冒烟测试：--help 正常退出
python -m dobot_move.remote_api --help

# 冒烟测试：启动后访问 health 端点（免认证）
python -m dobot_move.remote_api --port 8000 &
Invoke-WebRequest http://localhost:8000/api/v1/health
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
