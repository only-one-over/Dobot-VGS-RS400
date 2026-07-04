from dobot_move.startup_connection import (
    STATUS_CAMERA_ERR,
    STATUS_ROBOT_ERR,
    StartupConnectionState,
    connection_error_code,
)


def test_robot_failure_has_priority_over_camera_failure():
    assert connection_error_code(False, {"D405"}, {"D405": False}) == STATUS_ROBOT_ERR


def test_camera_failure_is_reported_only_when_required():
    assert connection_error_code(True, {"D405"}, {"D405": False}) == STATUS_CAMERA_ERR
    assert connection_error_code(True, set(), {}) is None


def test_fault_is_latched_only_after_deadline():
    state = StartupConnectionState(timeout_s=5.0)
    state.begin({"D435i"}, now=10.0)
    state.update(robot_connected=True, camera_connected={"D435i": False})
    assert state.latch_if_due(now=14.99) is None
    assert state.latch_if_due(now=15.0) == STATUS_CAMERA_ERR
    assert state.snapshot()["fault_latched"] is True


def test_ready_devices_do_not_latch_fault():
    state = StartupConnectionState(timeout_s=5.0)
    state.begin({"D405", "D435i"}, now=10.0)
    state.update(
        robot_connected=True,
        camera_connected={"D405": True, "D435i": True},
    )
    assert state.latch_if_due(now=15.0) is None
    assert state.snapshot()["missing_devices"] == []


def test_recheck_clears_latched_fault_only_after_devices_are_ready():
    state = StartupConnectionState(timeout_s=5.0)
    state.begin({"D405"}, now=10.0)
    state.update(robot_connected=True, camera_connected={"D405": False})
    assert state.latch_if_due(now=15.0) == STATUS_CAMERA_ERR

    state.update(robot_connected=True, camera_connected={"D405": True})
    assert state.recheck_fault() is None
    assert state.snapshot()["fault_latched"] is False
