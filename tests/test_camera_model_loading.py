import sys
import types

import pytest


if "pyrealsense2" not in sys.modules:
    sys.modules["pyrealsense2"] = types.ModuleType("pyrealsense2")

import dobot_move.vision_system as vision_module
from dobot_move.vision_system import VisionSystem


class _ModelInfo:
    def __init__(self, name, shape):
        self.name = name
        self.shape = shape


class _FakeSession:
    def __init__(
        self,
        output_shape=(1, 300, 38),
        output_count=2,
        mask_shape=(1, 32, 160, 160),
    ):
        self._outputs = [_ModelInfo("output0", list(output_shape))]
        if output_count > 1:
            self._outputs.append(_ModelInfo("output1", list(mask_shape)))

    def get_inputs(self):
        return [_ModelInfo("images", [1, 3, 640, 640])]

    def get_outputs(self):
        return self._outputs

    def get_providers(self):
        return ["CPUExecutionProvider"]

    def run(self, output_names, inputs):
        return []


def _vision_shell(model_path="model.onnx"):
    vision = object.__new__(VisionSystem)
    vision.camera_type = "D435i"
    vision.model_path = model_path
    vision.session = None
    vision.inference_provider = "未检测"
    vision.input_name = None
    vision.input_shape = None
    vision.num_classes = 1
    vision.is_seg_model = True
    return vision


def _fake_onnxruntime(session):
    return types.SimpleNamespace(
        get_available_providers=lambda: ["CPUExecutionProvider"],
        InferenceSession=lambda model_path, providers: session,
    )


def test_compatible_segmentation_model_metadata_is_accepted(monkeypatch):
    session = _FakeSession()
    monkeypatch.setitem(sys.modules, "onnxruntime", _fake_onnxruntime(session))
    vision = _vision_shell()

    vision._initialize_onnx_model()

    assert vision.session is session
    assert vision.input_name == "images"
    assert vision.input_shape == [1, 3, 640, 640]
    assert vision.is_seg_model is True
    assert vision.model_format == "yolo26"


def test_incompatible_model_clears_session(monkeypatch):
    session = _FakeSession(output_shape=(1, 38), output_count=1)
    monkeypatch.setitem(sys.modules, "onnxruntime", _fake_onnxruntime(session))
    vision = _vision_shell("invalid.onnx")

    with pytest.raises(RuntimeError, match="模型主输出必须是三维"):
        vision._initialize_onnx_model()

    assert vision.session is None


def test_incompatible_mask_output_clears_session(monkeypatch):
    session = _FakeSession(mask_shape=(1, 16, 160, 160))
    monkeypatch.setitem(sys.modules, "onnxruntime", _fake_onnxruntime(session))
    vision = _vision_shell("invalid-mask.onnx")

    with pytest.raises(RuntimeError, match="掩码输出必须是"):
        vision._initialize_onnx_model()

    assert vision.session is None


def test_model_initialization_failure_happens_before_camera_pipeline(monkeypatch):
    pipeline_calls = []
    monkeypatch.setattr(
        vision_module,
        "get_calibration",
        lambda camera_type: {"tool_base_calib_pose": [0] * 6},
    )
    monkeypatch.setattr(
        vision_module,
        "get_camera_handeye_matrix",
        lambda camera_type: [[1, 0, 0, 0]] * 4,
    )
    monkeypatch.setattr(
        vision_module,
        "resolve_camera_model_path",
        lambda camera_type, model_path: "invalid.onnx",
    )
    monkeypatch.setattr(
        VisionSystem,
        "_initialize_onnx_model",
        lambda self: (_ for _ in ()).throw(RuntimeError("invalid model")),
    )
    monkeypatch.setattr(
        vision_module.rs,
        "pipeline",
        lambda: pipeline_calls.append(True),
        raising=False,
    )

    with pytest.raises(RuntimeError, match="invalid model"):
        VisionSystem(camera_type="D435i")

    assert pipeline_calls == []
