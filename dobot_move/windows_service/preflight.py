"""Non-hardware deployment checks for the Windows Service installer.

Checks are split into errors (block installation) and warnings (allow
installation to proceed, surfaced for user awareness).
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

from ..config import config_manager
from ..flow.flow_library import FlowLibrary


def collect_preflight_errors() -> tuple[list[str], list[str]]:
    """Return (errors, warnings). Errors block installation; warnings do not."""
    errors: list[str] = []
    warnings: list[str] = []

    try:
        config = json.loads(
            Path(config_manager.CONFIG_FILE).read_text(encoding="utf-8")
        )
        if not isinstance(config, dict):
            errors.append("config.json root must be an object")
    except Exception as exc:
        config = {}
        errors.append(f"config.json cannot be read: {exc}")

    try:
        FlowLibrary.load(config_manager.get_grasp_flow_file(), migrate=False)
    except Exception as exc:
        errors.append(f"flow library cannot be read: {exc}")

    for module_name in ("pyrealsense2", "onnxruntime", "cv2", "numpy"):
        try:
            importlib.import_module(module_name)
        except Exception as exc:
            errors.append(f"Python dependency unavailable: {module_name}: {exc}")

    camera_config = config.get("camera", {})
    models = (
        camera_config.get("models", {})
        if isinstance(camera_config, dict)
        else {}
    )
    for camera_type in ("D405", "D435i"):
        configured = models.get(camera_type) if isinstance(models, dict) else None
        model_path = Path(
            configured or config_manager.DEFAULT_CAMERA_MODEL_PATH
        )
        if model_path.suffix.lower() != ".onnx":
            warnings.append(
                f"{camera_type} model is not an ONNX file: {model_path}"
            )
        elif not model_path.is_file():
            # 模型文件可在部署后通过 GUI 或 config 提供，仅警告不阻塞安装
            warnings.append(
                f"{camera_type} model does not exist: {model_path} "
                "(部署后请通过 camera.models 配置或放置模型文件)"
            )

    # runtime 配置段检查
    runtime_config = config.get("runtime", {})
    if not isinstance(runtime_config, dict):
        warnings.append("config.json 的 runtime 段不是对象，将使用默认值")
        runtime_config = {}
    else:
        if not runtime_config:
            warnings.append(
                "config.json 未配置 runtime 段，将使用默认值 "
                "(ipc_port=8765, ipc_stop_port=8766)"
            )

    # 端口可用性检查（warning 级，不阻塞安装）
    import socket
    default_ports = {
        "IPC": ("127.0.0.1", runtime_config.get("ipc_port", 8765)),
        "Stop": ("127.0.0.1", runtime_config.get("ipc_stop_port", 8766)),
        "Modbus": ("0.0.0.0", config.get("modbus_port", 502)),
    }
    for name, (addr, port) in default_ports.items():
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((addr, int(port)))
            sock.close()
        except OSError:
            warnings.append(
                f"{name} 端口 {addr}:{port} 被占用，安装后服务可能启动失败"
            )
    return errors, warnings


def main() -> int:
    errors, warnings = collect_preflight_errors()
    for warning in warnings:
        print(f"[WARNING] {warning}")
    for error in errors:
        print(f"[ERROR] {error}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
