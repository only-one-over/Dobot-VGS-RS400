"""Non-hardware deployment checks for the Windows Service installer."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

from .. import config_manager
from ..flow_library import FlowLibrary


def collect_preflight_errors() -> list[str]:
    errors: list[str] = []
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
            errors.append(f"{camera_type} model is not an ONNX file: {model_path}")
        elif not model_path.is_file():
            errors.append(f"{camera_type} model does not exist: {model_path}")
    return errors


def main() -> int:
    errors = collect_preflight_errors()
    for error in errors:
        print(error)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
