import sys
import types

import numpy as np

if "pyrealsense2" not in sys.modules:
    sys.modules["pyrealsense2"] = types.ModuleType("pyrealsense2")

from dobot_move.vision.tracker import BYTETracker, STrack, iou_distance
from dobot_move.vision.kalman_filter_3d import KalmanFilter3D
import dobot_move.vision.vision_system as vision_module
from dobot_move.vision.vision_system import VisionSystem


def _track(bbox, score=0.9):
    return STrack(bbox, score)


def test_iou_distance_returns_pairwise_shape_for_2x1():
    STrack.reset_id_counter()

    cost = iou_distance(
        [_track([0, 0, 10, 10]), _track([100, 100, 110, 110])],
        [_track([0, 0, 10, 10])],
    )

    assert cost.shape == (2, 1)
    assert cost[0, 0] < 1e-6
    assert cost[1, 0] > 0.99


def test_iou_distance_returns_pairwise_shape_for_1x2():
    STrack.reset_id_counter()

    cost = iou_distance(
        [_track([0, 0, 10, 10])],
        [_track([0, 0, 10, 10]), _track([100, 100, 110, 110])],
    )

    assert cost.shape == (1, 2)
    assert cost[0, 0] < 1e-6
    assert cost[0, 1] > 0.99


def test_iou_distance_returns_pairwise_shape_for_2x3():
    STrack.reset_id_counter()

    cost = iou_distance(
        [_track([0, 0, 10, 10]), _track([50, 50, 60, 60])],
        [
            _track([0, 0, 10, 10]),
            _track([50, 50, 60, 60]),
            _track([100, 100, 110, 110]),
        ],
    )

    assert cost.shape == (2, 3)
    assert cost[0, 0] < 1e-6
    assert cost[1, 1] < 1e-6
    assert cost[0, 2] > 0.99


def test_byte_tracker_two_tracks_then_one_detection_does_not_raise():
    tracker = BYTETracker(track_thresh=0.5, match_thresh=0.8)
    tracker.update(
        [
            {"bbox": [0, 0, 10, 10], "score": 0.9},
            {"bbox": [100, 100, 110, 110], "score": 0.9},
        ],
        (640, 480),
    )

    tracks = tracker.update(
        [{"bbox": [0, 0, 10, 10], "score": 0.9}],
        (640, 480),
    )

    assert isinstance(tracks, list)


def test_run_detection_tracked_falls_back_to_best_detection_on_tracker_error():
    class FailingTracker:
        def __init__(self):
            self.reset_called = False

        def update(self, det_list, img_size):
            raise IndexError("list index out of range")

        def reset(self):
            self.reset_called = True

    tracker = FailingTracker()
    vision = object.__new__(VisionSystem)
    vision.tracker = tracker

    def run_detection(color_image):
        return [
            {"bbox": [0, 0, 10, 10], "score": 0.2, "mask": np.ones((4, 4), dtype=np.uint8)},
            {"bbox": [1, 1, 11, 11], "score": 0.9, "mask": np.ones((4, 4), dtype=np.uint8)},
        ]

    vision.run_detection = run_detection

    target = VisionSystem.run_detection_tracked(
        vision,
        np.zeros((4, 4, 3), dtype=np.uint8),
    )

    assert target["score"] == 0.9
    assert tracker.reset_called is True


def test_smoothed_position_keeps_model_score_as_confidence():
    vision = object.__new__(VisionSystem)
    vision.kalman_3d = KalmanFilter3D()

    def calculate_object_position(depth_frame, color_frame, detections):
        return {"camera_coords": [1.0, 2.0, 3.0]}

    vision.calculate_object_position = calculate_object_position

    result = VisionSystem.calculate_object_position_smoothed(
        vision,
        np.ones((4, 4), dtype=np.uint16),
        np.zeros((4, 4, 3), dtype=np.uint8),
        {
            "bbox": (0, 0, 3, 3),
            "score": 0.87,
            "mask": np.ones((4, 4), dtype=np.uint8) * 255,
            "class_id": 0,
        },
    )

    assert result["confidence"] == 0.87
    assert result["detection_score"] == 0.87
    assert result["tracking_confidence"] < 0.01
    assert result["source"] == "kalman_smoothed"


def _minimal_vision():
    vision = object.__new__(VisionSystem)
    vision.fx = 1.0
    vision.fy = 1.0
    vision.cx = 1.0
    vision.cy = 1.0
    vision.depth_scale = 0.001
    vision.min_depth = 0.0
    vision.max_depth = 2.0
    vision.max_camera_z_mm = 500.0
    vision.kalman_3d = None
    vision._record_performance = lambda *args, **kwargs: None
    return vision


def _mask_detection():
    return [{
        "bbox": (0, 0, 3, 3),
        "score": 0.9,
        "mask": np.ones((3, 3), dtype=np.uint8) * 255,
        "class_id": 0,
    }]


def test_camera_z_500_is_kept_python_depth(monkeypatch):
    monkeypatch.setattr(vision_module, "DOBOT_CORE_AVAILABLE", False)
    vision = _minimal_vision()

    result = VisionSystem.calculate_object_position(
        vision,
        np.full((3, 3), 500, dtype=np.uint16),
        np.zeros((3, 3, 3), dtype=np.uint8),
        _mask_detection(),
    )

    assert result is not None
    assert result["camera_coords"][2] == 500.0


def test_camera_z_over_500_is_filtered_python_depth(monkeypatch):
    monkeypatch.setattr(vision_module, "DOBOT_CORE_AVAILABLE", False)
    vision = _minimal_vision()

    result = VisionSystem.calculate_object_position(
        vision,
        np.full((3, 3), 501, dtype=np.uint16),
        np.zeros((3, 3, 3), dtype=np.uint8),
        _mask_detection(),
    )

    assert result is None


def test_camera_z_over_500_is_filtered_cpp_depth(monkeypatch):
    class FakeDepth:
        @staticmethod
        def calculate_object_position(*args, **kwargs):
            return {"camera_coords": [1.0, 2.0, 500.1]}

    fake_core = types.SimpleNamespace(depth=FakeDepth())
    monkeypatch.setattr(vision_module, "DOBOT_CORE_AVAILABLE", True)
    monkeypatch.setattr(vision_module, "dobot_core", fake_core, raising=False)
    vision = _minimal_vision()

    result = VisionSystem.calculate_object_position(
        vision,
        np.full((3, 3), 400, dtype=np.uint16),
        np.zeros((3, 3, 3), dtype=np.uint8),
        _mask_detection(),
    )

    assert result is None


def test_camera_z_over_500_is_filtered_kalman_smoothed():
    class FakeKalman:
        initialized = True

        def update(self, observed, dt=None):
            return np.array([1.0, 2.0, 500.1])

        def get_confidence(self):
            return 0.9

    vision = _minimal_vision()
    vision.kalman_3d = FakeKalman()
    vision.calculate_object_position = lambda *args, **kwargs: {"camera_coords": [1.0, 2.0, 400.0]}

    result = VisionSystem.calculate_object_position_smoothed(
        vision,
        np.ones((3, 3), dtype=np.uint16),
        np.zeros((3, 3, 3), dtype=np.uint8),
        {"bbox": (0, 0, 3, 3), "score": 0.9, "mask": np.ones((3, 3), dtype=np.uint8) * 255},
    )

    assert result is None


def test_camera_z_over_500_is_filtered_kalman_prediction():
    vision = _minimal_vision()

    result = VisionSystem.calculate_object_position_smoothed(
        vision,
        np.ones((3, 3), dtype=np.uint16),
        np.zeros((3, 3, 3), dtype=np.uint8),
        {"predicted": True, "camera_coords": [1.0, 2.0, 500.1], "confidence": 0.8},
    )

    assert result is None
