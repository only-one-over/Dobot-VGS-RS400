import inspect

import dobot_move.gui_app as gui_app_module
from dobot_move.gui_mixins.grasp_flow_mixin import GraspFlowMixin
from dobot_move.gui_mixins.modbus_mixin import ModbusMixin
from dobot_move.gui_mixins.point_management_mixin import PointManagementMixin
from dobot_move.gui_mixins.robot_control_mixin import RobotControlMixin
from dobot_move.gui_mixins.vision_mixin import VisionMixin


FORBIDDEN_GUI_TOKENS = (
    "DobotController(",
    "DobotApiDashboard(",
    "DobotApiFeedBack(",
    "VisionSystem(",
    "pipeline.start(",
    ".start_modbus(",
    ".MovJ(",
    ".MovL(",
    ".ServoP(",
    ".Arc(",
)


def test_gui_sources_do_not_acquire_runtime_hardware():
    sources = [
        inspect.getsource(gui_app_module),
        inspect.getsource(RobotControlMixin),
        inspect.getsource(VisionMixin),
        inspect.getsource(ModbusMixin),
        inspect.getsource(PointManagementMixin),
        inspect.getsource(GraspFlowMixin),
    ]
    combined = "\n".join(sources)

    for token in FORBIDDEN_GUI_TOKENS:
        assert token not in combined


class _RejectedActionWindow(
    RobotControlMixin,
    VisionMixin,
    ModbusMixin,
    PointManagementMixin,
    GraspFlowMixin,
):
    def __init__(self):
        self.actions = []

    def _show_runtime_ipc_required(self, action):
        self.actions.append(action)
        return False


def test_hardware_slots_reject_without_controller():
    window = _RejectedActionWindow()

    assert window.connect_robot() is False
    assert window.enable_robot() is False
    assert window.get_current_position() is False
    assert window.connect_d405() is False
    assert window.connect_d435i() is False
    assert window.open_realtime_feedback() is False
    assert window.start_modbus_server() is False
    assert window.stop_modbus_server() is False
    assert window.run_grasp_flow() is False
    assert window._on_read_current_for_selected_point() is False
    assert window._on_read_current_for_linear() is False
    assert len(window.actions) == 11


def test_gui_close_only_stops_gui_timers(monkeypatch):
    stopped = []
    flushed = []

    class Timer:
        def stop(self):
            stopped.append(True)

    class ConfigServiceInstance:
        def flush(self):
            flushed.append(True)

    class ConfigService:
        @staticmethod
        def instance():
            return ConfigServiceInstance()

    class Window:
        _status_timer = Timer()
        _modbus_refresh_timer = Timer()

    class Event:
        accepted = False

        def accept(self):
            self.accepted = True

    monkeypatch.setattr(gui_app_module, "ConfigService", ConfigService)
    event = Event()

    gui_app_module.DobotMainWindow.closeEvent(Window(), event)

    assert len(stopped) == 2
    assert flushed == [True]
    assert event.accepted is True
