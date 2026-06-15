# GPU 环境部署指南

本文档说明如何在新 Windows 设备上配置 NVIDIA GPU 环境，使 ONNX Runtime YOLO 推理运行在 CUDA 上。

## 推荐环境

| 项目 | 推荐 |
|------|------|
| 操作系统 | Windows 10/11 x64 |
| Python | 3.12 x64（避免 3.13 兼容性风险） |
| GPU | NVIDIA（计算能力 6.0+，即 Pascal 及以上） |
| NVIDIA 驱动 | >= 525.60.13 |

## CUDA 组件区分

部署时需要区分四个不同层级的 CUDA 组件：

| 组件 | 是否必需 | 说明 |
|------|---------|------|
| **NVIDIA Driver** | 必需 | 显卡驱动，提供 GPU 硬件访问能力。安装后系统即具备 CUDA 基础支持 |
| **CUDA Toolkit** | 非必需 | 完整开发工具包（含 nvcc 编译器、头文件、库）。仅当需要编译 CUDA 代码或使用 nvcc 时才需安装。**本项目不要求安装 CUDA Toolkit** |
| **CUDA Runtime** | 自动随 pip 安装 | onnxruntime-gpu 所需的 CUDA 运行时库。通过 `onnxruntime-gpu[cuda,cudnn]` 的 extras 依赖自动安装到虚拟环境中 |
| **cuDNN** | 自动随 pip 安装 | 深度神经网络加速库。同样通过 `onnxruntime-gpu[cuda,cudnn]` 自动安装到虚拟环境中 |

关键理解：**只需安装 NVIDIA 驱动，CUDA runtime 和 cuDNN 会随 pip 包自动安装到 .venv 中**，无需手动下载 CUDA Toolkit 或 cuDNN 安装包。

## 新设备部署步骤

### 1. 安装 NVIDIA 驱动

从 [NVIDIA 驱动下载页面](https://www.nvidia.com/Download/index.aspx) 下载并安装最新 Game Ready 或 Studio 驱动。

验证驱动安装：

```powershell
nvidia-smi
```

应显示驱动版本和 GPU 信息。驱动版本需 >= 525.60.13。

### 2. 创建虚拟环境

```powershell
# 使用 Python 3.12 x64
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip
```

### 3. 安装依赖

```powershell
# 一键安装（基础 + GPU 推理 + C++ 可选依赖）
pip install -r requirements.txt
```

> GPU 和 C++ 依赖为可选，已包含在 requirements.txt 中。无 NVIDIA GPU 时 onnxruntime-gpu 安装可能失败，不影响 CPU 推理使用。

### 4. 可选：安装 C++ 加速模块

```powershell
pip install -r requirements-cpp.txt
python build_cpp.py
```

## 验证

### 基础依赖验证

```powershell
python -c "import PySide6, numpy, cv2, pyrealsense2, onnxruntime; print('All dependencies OK')"
```

### GPU 真实启用验证

仅检查 `get_available_providers()` 不够——它只说明 onnxruntime 能识别 CUDA provider，不代表实际能创建 CUDA session。正确验证方式是使用项目模型创建 InferenceSession：

```powershell
python -c "import onnxruntime as ort; s = ort.InferenceSession('dobot_move/best.onnx', providers=['CUDAExecutionProvider']); print('Active providers:', s.get_providers())"
```

**通过标准**：输出包含 `CUDAExecutionProvider`。

**未通过**：输出仅剩 `['CPUExecutionProvider']`，说明 CUDA provider 注册但未能激活，需要排查 CUDA/cuDNN DLL 是否缺失。

### C++ 加速模块验证

```powershell
python -c "import dobot_core; print('dobot_core OK:', dir(dobot_core))"
```

## 常见错误排查

### 缺少 cudnn64_9.dll

**错误信息**：
```
Failed to load library cudnn64_9.dll
```

**原因**：cuDNN runtime 未随 pip 正确安装，或版本不匹配。

**解决**：
```powershell
pip install --force-reinstall onnxruntime-gpu[cuda,cudnn]
```

如果仍失败，确认 pip 版本支持 extras 依赖：
```powershell
pip --version  # 应 >= 21.2
```

### CUDA 版本不匹配

**错误信息**：
```
Could not load library cudart64_12.dll
```

**原因**：系统 NVIDIA 驱动版本过低，不支持 CUDA 12.x。

**解决**：更新 NVIDIA 驱动至最新版本。

### onnxruntime 和 onnxruntime-gpu 冲突

**错误信息**：`get_available_providers()` 仅返回 `['CPUExecutionProvider']`

**原因**：同时安装了 `onnxruntime` 和 `onnxruntime-gpu`，CPU 版覆盖了 GPU 版。

**解决**：
```powershell
pip uninstall onnxruntime onnxruntime-gpu -y
pip install -r requirements-gpu-cu12.txt
```

### GPU 驱动正常但 session 仍回退 CPU

**排查步骤**：
1. 确认 `nvidia-smi` 正常显示 GPU
2. 确认虚拟环境中无 `onnxruntime`（CPU 版）：`pip list | findstr onnx`
3. 重新安装 GPU 依赖：`pip install --force-reinstall -r requirements-gpu-cu12.txt`
4. 检查 Python 是否为 x64 版本：`python -c "import struct; print(struct.calcsize('P') * 8)"` 应输出 `64`

## 依赖文件说明

| 文件 | 内容 | 用途 |
|------|------|------|
| `requirements.txt` | 基础依赖 + GPU 推理（可选）+ C++ 构建（可选） | 一键安装 |
