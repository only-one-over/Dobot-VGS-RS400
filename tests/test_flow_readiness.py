from dobot_move.flow_readiness import check_flow_readiness


class _Controller:
    def __init__(self, connected=True, feedback="ok"):
        self.is_connected = connected
        self.dashboard = object() if connected else None
        self.feedback = feedback
        self.feedback_calls = 0

    def get_feedback_health(self, max_age=0.5):
        self.feedback_calls += 1
        return {"health": self.feedback, "max_age": max_age}


class _Vision:
    def __init__(self, available=True):
        self.is_available = available


def test_no_camera_flow_checks_robot_only():
    controller = _Controller()

    result = check_flow_readiness(controller, None, None, [{"type": "delay"}])

    assert result.ok is True
    assert result.missing_devices == ()
    assert controller.feedback_calls == 1


def test_only_cameras_referenced_by_flow_are_required():
    controller = _Controller()
    modules = [{"type": "camera", "params": {"camera_type": "D405"}}]

    result = check_flow_readiness(controller, None, _Vision(), modules)

    assert result.ok is True


def test_missing_camera_is_reported_without_capture():
    controller = _Controller()
    modules = [{"type": "camera", "params": {"camera_type": "D435i"}}]

    result = check_flow_readiness(controller, None, _Vision(), modules)

    assert result.ok is False
    assert result.missing_devices == ("D435i",)
    assert "D435i 未连接" in result.message


def test_stale_feedback_marks_robot_unready():
    controller = _Controller(feedback="stale")

    result = check_flow_readiness(controller, None, None, [])

    assert result.ok is False
    assert result.missing_devices == ("robot",)
    assert "stale" in result.message


def test_unavailable_camera_is_reported():
    controller = _Controller()
    modules = [{"type": "visual_servo", "params": {}}]

    result = check_flow_readiness(
        controller,
        _Vision(),
        _Vision(available=False),
        modules,
    )

    assert result.ok is False
    assert result.missing_devices == ("D405",)
