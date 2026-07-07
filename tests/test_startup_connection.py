import time

from dobot_move.runtime.startup_connection import StartupConnectionState


def test_ready_devices_have_no_missing_entries():
    state = StartupConnectionState(timeout_s=5.0)
    state.begin({"D405", "D435i"}, now=10.0)
    state.update(
        robot_connected=True,
        camera_connected={"D405": True, "D435i": True},
    )
    assert state.snapshot()["missing_devices"] == []


def test_expired_startup_window_does_not_latch_missing_devices():
    state = StartupConnectionState(timeout_s=5.0)
    state.begin({"D405"}, now=time.monotonic() - 6.0)
    state.update(robot_connected=False, camera_connected={"D405": False})

    snapshot = state.snapshot()

    assert snapshot["deadline_elapsed"] is True
    assert snapshot["missing_devices"] == ["robot", "D405"]
    assert snapshot["fault_latched"] is False
    assert snapshot["fault_code"] is None
