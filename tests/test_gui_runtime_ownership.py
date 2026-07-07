import inspect

import dobot_move.ui.gui_app as gui_app_module
from dobot_move.ui.mixins.grasp_flow_mixin import GraspFlowMixin
from dobot_move.ui.mixins.modbus_mixin import ModbusMixin
from dobot_move.ui.mixins.point_management_mixin import PointManagementMixin
from dobot_move.ui.mixins.robot_control_mixin import RobotControlMixin
from dobot_move.ui.mixins.vision_mixin import VisionMixin


# Modbus server is now exclusively Runtime-owned; the GUI only sends IPC via
# ``_runtime_facade.start_modbus()``, so the ``.start_modbus(`` substring is a
# legitimate facade delegation and no longer a direct-hardware red flag.
FORBIDDEN_GUI_TOKENS = (
    "DobotController(",
    "DobotApiDashboard(",
    "DobotApiFeedBack(",
    "VisionSystem(",
    "pipeline.start(",
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


class _StubStatusBar:
    def __init__(self):
        self.messages = []

    def showMessage(self, message, timeout=0):
        self.messages.append((message, timeout))


class _FacadeStub:
    """Records every method call and returns a ``(False, msg)`` tuple."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def _method(*args, **kwargs):
            self.calls.append(name)
            return (False, f"{name} 模拟失败")
        return _method


class _FacadeWindow(
    RobotControlMixin,
    VisionMixin,
    ModbusMixin,
    PointManagementMixin,
    GraspFlowMixin,
):
    def __init__(self):
        self._runtime_facade = _FacadeStub()
        self._status_bar = _StubStatusBar()

    def statusBar(self):
        return self._status_bar


def test_hardware_slots_delegate_to_facade_and_return_false():
    window = _FacadeWindow()

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
    # 11 distinct facade calls recorded
    assert len(window._runtime_facade.calls) == 11
    # Each slot also surfaced a status-bar message
    assert len(window._status_bar.messages) == 11


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
