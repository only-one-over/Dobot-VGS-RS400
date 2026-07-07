import sys
import time
import types
import inspect

import numpy as np

if "pyrealsense2" not in sys.modules:
    sys.modules["pyrealsense2"] = types.ModuleType("pyrealsense2")
pymodbus = sys.modules.setdefault("pymodbus", types.ModuleType("pymodbus"))


class ModbusDeviceIdentification:
    pass


pymodbus.ModbusDeviceIdentification = getattr(
    pymodbus,
    "ModbusDeviceIdentification",
    ModbusDeviceIdentification,
)

server = sys.modules.setdefault("pymodbus.server", types.ModuleType("pymodbus.server"))


class ModbusTcpServer:
    pass


server.ModbusTcpServer = getattr(server, "ModbusTcpServer", ModbusTcpServer)

simulator = sys.modules.setdefault(
    "pymodbus.simulator",
    types.ModuleType("pymodbus.simulator"),
)


class SimData:
    pass


class SimDevice:
    pass


class DataType:
    REGISTERS = "registers"


simulator.SimData = getattr(simulator, "SimData", SimData)
simulator.SimDevice = getattr(simulator, "SimDevice", SimDevice)
simulator.DataType = getattr(simulator, "DataType", DataType)

from dobot_move.vision_system import FramePacket
from dobot_move.workers import (
    FlowRunContext,
    FlowThread,
    coerce_float_vector,
    validate_grasp_flow_modules,
)
from dobot_move.gui_mixins.grasp_flow_mixin import GraspFlowMixin


def test_relative_path_new_module_defaults_to_empty_segments():
    source = inspect.getsource(GraspFlowMixin.add_module)

    assert '"segments": []' in source
    assert '"X+200"' not in source
    assert '"x": 200' not in source


def test_empty_path_template_still_adds_zero_editable_segment():
    source = inspect.getsource(GraspFlowMixin._add_path_template)

    assert 'template == "x200"' in source
    assert 'values = [0, 0, 0, 0, 0, 0]' in source


class FakeCaptureThread:
    def __init__(self, vision):
        self.vision = vision
        self.started = False
        self.stopped = False
        self.joined = False
        self.index = 0

    def start(self):
        self.started = True
        self.vision.capture_thread = self

    def get_latest(self):
        if self.index >= len(self.vision.packets):
            return self.vision.packets[-1], 0.0
        packet = self.vision.packets[self.index]
        self.index += 1
        return packet, 1.25

    def stop(self):
        self.stopped = True

    def join(self, timeout=None):
        self.joined = True
        self.join_timeout = timeout


class FakeVision:
    def __init__(self, object_position):
        self.object_position = object_position
        self.reset_called = False
        self.detect_images = []
        self.position_inputs = []
        self.capture_thread = None
        self.packets = [
            FramePacket(
                seq=1,
                timestamp=1.0,
                color_image=np.zeros((4, 4, 3), dtype=np.uint8),
                depth_image=np.ones((4, 4), dtype=np.uint16),
            )
        ]

    def reset_tracking(self):
        self.reset_called = True

    def run_detection_tracked(self, color_image):
        self.detect_images.append(color_image)
        return {"bbox": (0, 0, 2, 2), "score": 0.91, "mask": np.ones((4, 4), dtype=np.uint8)}

    def calculate_object_position_smoothed(self, depth_image, color_image, target):
        self.position_inputs.append((depth_image, color_image, target))
        return self.object_position


class NoDetectionVision(FakeVision):
    def __init__(self, packet_count=2):
        super().__init__(None)
        self.packets = [
            FramePacket(
                seq=i + 1,
                timestamp=float(i + 1),
                color_image=np.zeros((4, 4, 3), dtype=np.uint8),
                depth_image=np.ones((4, 4), dtype=np.uint16),
            )
            for i in range(packet_count)
        ]

    def run_detection_tracked(self, color_image):
        self.detect_images.append(color_image)
        return None


def _make_flow_thread():
    return FlowThread(
        controller=object(),
        vision_d435i=None,
        vision_d405=None,
        grasp_flow_modules=[],
        is_paused_ref=[False],
    )


def test_flow_camera_detection_uses_capture_thread_numpy_packets(monkeypatch):
    import dobot_move.workers as workers

    monkeypatch.setattr(workers, "CaptureThread", FakeCaptureThread)
    thread = _make_flow_thread()
    ctx = FlowRunContext(run_id="test", start_time=0.0)
    vision = FakeVision({
        "camera_coords": [1.0, 2.0, 3.0],
        "confidence": 0.92,
        "source": "unit",
    })

    result = thread._detect_camera_object_for_flow(
        vision,
        "D435i",
        ctx,
        max_frames=1,
        early_confidence=0.85,
    )

    assert result["object_position"]["camera_coords"] == [1.0, 2.0, 3.0]
    assert result["confidence"] == 0.92
    assert vision.reset_called is True
    assert vision.detect_images[0] is vision.packets[0].color_image
    assert vision.position_inputs[0][0] is vision.packets[0].depth_image
    assert vision.capture_thread.stopped is True
    assert vision.capture_thread.joined is True


def test_flow_camera_detection_reports_depth_position_failure(monkeypatch):
    import dobot_move.workers as workers

    monkeypatch.setattr(workers, "CaptureThread", FakeCaptureThread)
    thread = _make_flow_thread()
    ctx = FlowRunContext(run_id="test", start_time=0.0)
    vision = FakeVision(None)

    result = thread._detect_camera_object_for_flow(
        vision,
        "D405",
        ctx,
        max_frames=1,
        early_confidence=0.85,
    )

    assert result["object_position"] is None
    assert "坐标计算失败" in result["failure_reason"]


def test_flow_camera_detection_reports_no_object(monkeypatch):
    import dobot_move.workers as workers

    monkeypatch.setattr(workers, "CaptureThread", FakeCaptureThread)
    thread = _make_flow_thread()
    ctx = FlowRunContext(run_id="test", start_time=0.0)
    vision = NoDetectionVision(packet_count=2)

    result = thread._detect_camera_object_for_flow(
        vision,
        "D435i",
        ctx,
        max_frames=2,
        early_confidence=0.85,
    )

    assert result["object_position"] is None
    assert result["processed_frames"] == 2
    assert "未检测" in result["failure_reason"]
    assert len(vision.detect_images) == 2
    assert vision.position_inputs == []


class FakeCameraTestWorker:
    cam_type = "D435i"
    running = True

    def __init__(self, snapshots):
        self.snapshots = snapshots
        self.calls = 0
        self.flow_active_changes = []
        self.flow_detection_changes = []
        self.flow_detection_enabled = True

    def isRunning(self):
        return True

    def set_flow_active(self, active):
        self.flow_active_changes.append(bool(active))
        self.flow_detection_enabled = not bool(active)

    def set_flow_detection_enabled(self, enabled):
        self.flow_detection_changes.append(bool(enabled))
        self.flow_detection_enabled = bool(enabled)

    def get_flow_detection_snapshot(self):
        if not self.flow_detection_enabled:
            return None
        if not self.snapshots:
            return None
        index = min(self.calls, len(self.snapshots) - 1)
        self.calls += 1
        return self.snapshots[index]


def test_flow_camera_detection_reuses_running_camera_test_worker(monkeypatch):
    import dobot_move.workers as workers

    class ForbiddenCaptureThread:
        def __init__(self, vision):
            raise AssertionError("flow should reuse camera-test snapshots")

    monkeypatch.setattr(workers, "CaptureThread", ForbiddenCaptureThread)
    object_position = {
        "camera_coords": [1.0, 2.0, 3.0],
        "confidence": 0.93,
        "source": "camera_test",
    }
    worker = FakeCameraTestWorker([
        {"seq": 0},
        {
            "seq": 1,
            "target": {"bbox": (0, 0, 2, 2), "score": 0.93},
            "object_position": object_position,
            "confidence": 0.93,
        },
    ])
    thread = FlowThread(
        controller=object(),
        vision_d435i=None,
        vision_d405=None,
        grasp_flow_modules=[],
        is_paused_ref=[False],
        camera_test_workers={"D435i": worker},
    )
    ctx = FlowRunContext(run_id="test", start_time=0.0)
    vision = FakeVision(None)

    result = thread._detect_camera_object_for_flow(
        vision,
        "D435i",
        ctx,
        max_frames=1,
        early_confidence=0.85,
    )

    assert result["object_position"] is object_position
    assert vision.reset_called is False
    assert worker.flow_detection_changes == [True, False]
    assert worker.calls >= 2


def test_flow_run_pauses_camera_test_detection_outside_camera_module():
    class Controller:
        def __init__(self):
            self.released = False
            self._active_flow_thread = None

        def acquire_motion(self, owner):
            return True

        def release_motion(self, owner):
            self.released = True

    worker = FakeCameraTestWorker([])
    thread = FlowThread(
        controller=Controller(),
        vision_d435i=None,
        vision_d405=None,
        grasp_flow_modules=[],
        is_paused_ref=[False],
        camera_test_workers={"D435i": worker},
    )

    thread.run()

    assert worker.flow_active_changes == [True, False]
    assert worker.flow_detection_enabled is True


def test_flow_camera_module_does_not_reuse_cached_result(monkeypatch):
    import dobot_move.workers as workers

    class CachedFlowContext:
        def __init__(self, run_id, start_time):
            self.run_id = run_id
            self.start_time = start_time
            self.current_module_index = -1
            self.stop_event = workers.threading.Event()
            self.module_timings = []
            self.motion_generation = 0
            self._flow_detection_cache = {
                "D435i": {
                    "time": time.perf_counter(),
                    "result": {
                        "camera_coords": [9.0, 9.0, 9.0],
                        "confidence": 0.99,
                    },
                    "confidence": 0.99,
                    "motion_generation": 0,
                }
            }

        def increment_motion_generation(self):
            self.motion_generation += 1

        def is_cache_valid(self, camera_type):
            return True

    class Controller:
        def __init__(self):
            self._active_flow_thread = None
            self.is_enabled = True
            self.released = False

        def acquire_motion(self, owner):
            return True

        def release_motion(self, owner):
            self.released = True

    failures = []
    detector_calls = []

    def fake_detect(self, vision, camera_type, ctx, max_frames, early_confidence):
        detector_calls.append(camera_type)
        return {
            "object_position": None,
            "confidence": 0.0,
            "failure_reason": "no object",
        }

    def fake_fail(self, ctx, module_index, module_name, reason):
        failures.append(reason)

    monkeypatch.setattr(workers, "FlowRunContext", CachedFlowContext)
    monkeypatch.setattr(FlowThread, "_detect_camera_object_for_flow", fake_detect)
    monkeypatch.setattr(FlowThread, "_fail_module", fake_fail)

    controller = Controller()
    thread = FlowThread(
        controller=controller,
        vision_d435i=FakeVision({"camera_coords": [1.0, 2.0, 3.0], "confidence": 0.9}),
        vision_d405=None,
        grasp_flow_modules=[
            {
                "type": "camera",
                "name": "camera detect",
                "params": {"camera_type": "D435i"},
            }
        ],
        is_paused_ref=[False],
    )
    thread.performance_config = {
        "flow_camera_frames": 1,
        "flow_camera_early_confidence": 0.85,
        "flow_camera_min_confidence": 0.3,
    }

    thread.run()

    assert detector_calls == ["D435i"]
    assert failures and failures[0].endswith("no object")
    assert controller.released is True


def test_camera_coords_short_vector_reports_clear_error():
    try:
        coerce_float_vector([], 3, "camera coords")
    except ValueError as exc:
        assert "camera coords" in str(exc)
    else:
        raise AssertionError("short camera coords should fail")


def test_end_coords_short_vector_reports_clear_error():
    try:
        coerce_float_vector([1.0, 2.0], 3, "end coords")
    except ValueError as exc:
        assert "end coords" in str(exc)
    else:
        raise AssertionError("short end coords should fail")


def test_base_coords_short_vector_reports_clear_error():
    try:
        coerce_float_vector(np.array([1.0]), 3, "base coords")
    except ValueError as exc:
        assert "base coords" in str(exc)
    else:
        raise AssertionError("short base coords should fail")


def test_current_pose_short_vector_reports_clear_error():
    try:
        coerce_float_vector([1.0, 2.0, 3.0], 6, "current pose")
    except ValueError as exc:
        assert "current pose" in str(exc)
    else:
        raise AssertionError("short current pose should fail")


def test_valid_numpy_vector_converts_to_float_list():
    result = coerce_float_vector(np.array([[1, 2, 3]]), 3, "鍩哄骇鍧愭爣")

    assert result == [1.0, 2.0, 3.0]


class FakeStatusBar:
    def __init__(self):
        self.messages = []

    def showMessage(self, message):
        self.messages.append(message)


class FakeFlowWindow(GraspFlowMixin):
    def __init__(self):
        self.cam_test_worker = FakeCameraTestWorker([])
        self.stop_called = False
        self.status = FakeStatusBar()

    def _stop_camera_test(self):
        self.stop_called = True
        self.cam_test_worker = None

    def statusBar(self):
        return self.status


def test_gui_flow_does_not_reuse_local_camera_test_worker():
    window = FakeFlowWindow()

    assert window._stop_camera_test_before_flow() is False

    assert window.stop_called is False
    assert window.cam_test_worker is not None
    assert window.status.messages == []


def test_camera_detected_point_must_match_previous_camera_type():
    modules = [
        {
            "type": "camera",
            "name": "camera detect",
            "params": {"camera_type": "D405"},
        },
        {
            "type": "move",
            "name": "move",
            "params": {
                "target": "camera_detected",
                "motion_type": "MovL",
                "point_name": "d435i",
            },
        },
    ]

    errors = validate_grasp_flow_modules(modules)

    assert errors
