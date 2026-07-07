from types import SimpleNamespace

import numpy as np

from dobot_move.runtime.runtime_vision_debug import capture_vision_snapshot


class _Vision:
    depth_scale = 0.001
    inference_provider = "CPUExecutionProvider"
    model_path = "model.onnx"
    T_cam2gripper = np.eye(4)
    _perf_stats = {}

    def capture_numpy_packet(self, seq):
        return SimpleNamespace(
            seq=seq,
            timestamp=1.0,
            color_image=np.zeros((24, 32, 3), dtype=np.uint8),
            depth_image=np.full((24, 32), 100, dtype=np.uint16),
        )

    def run_detection_tracked(self, image):
        return {
            "bbox": (2, 3, 12, 15),
            "track_id": 7,
            "score": 0.9,
            "class_id": 0,
            "mask": np.ones(image.shape[:2], dtype=np.uint8),
        }

    def calculate_object_position_smoothed(self, depth, color, target):
        return {
            "camera_coords": [1.0, 2.0, 3.0],
            "raw_coords": [0.5, 1.5, 2.5],
            "source": "kalman_smoothed",
            "confidence": target["score"],
        }

    def convert_to_end_coords(self, coords):
        return np.asarray(coords) + 1.0

    def convert_to_base_coords(self, coords, pose):
        return np.asarray(coords) + np.asarray(pose[:3])


class _Controller:
    def get_current_pose_fast(self, max_age=1.0, fallback=False):
        return [10.0, 20.0, 30.0, 0.0, 0.0, 0.0]


def test_capture_vision_snapshot_contains_images_coordinates_and_timings():
    result = capture_vision_snapshot(
        _Vision(),
        _Controller(),
        camera_type="D405",
        include_color=True,
        include_depth=True,
        include_mask=True,
    )

    assert result["detection"]["track_id"] == 7
    assert result["coordinates"]["camera_mm"] == [1.0, 2.0, 3.0]
    assert result["coordinates"]["base_mm"] == [12.0, 23.0, 34.0]
    assert result["color_jpeg_base64"]
    assert result["depth_png_base64"]
    assert result["depth_preview_jpeg_base64"]
    assert result["mask_png_base64"]
    assert result["timings_ms"]["total"] >= 0
