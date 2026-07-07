"""Unit tests for ``RuntimeFacade``.

The façade wraps the GUI's async IPC sender and returns synchronous
``(success, message)`` tuples. These tests verify the offline guard, the
happy path, exception handling, the ``move_to_point`` payload shape, and
that ``safe_stop`` routes through the dedicated Stop channel.
"""
from __future__ import annotations

from unittest.mock import Mock

from dobot_move.ui.runtime_facade import RuntimeFacade


def _make_facade(online=True, send_raises=False, with_stop=True):
    """Build a façade wired to Mock callables.

    Returns ``(facade, send_ipc, is_online, send_stop)``.
    """
    send_ipc = Mock(side_effect=Exception("ipc boom") if send_raises else None)
    is_online = Mock(return_value=online)
    send_stop = Mock() if with_stop else None
    facade = RuntimeFacade(
        ipc_client=Mock(),
        send_ipc_func=send_ipc,
        is_online_func=is_online,
        send_stop_func=send_stop,
    )
    return facade, send_ipc, is_online, send_stop


def test_offline_returns_failure_without_sending():
    facade, send_ipc, _is_online, _send_stop = _make_facade(online=False)

    # Spot-check no-arg methods from each category.
    no_arg_cases = [
        facade.enable_robot,
        facade.disable_robot,
        facade.clear_alarms,
        facade.connect_robot,
        facade.set_collision_level,
        facade.safe_stop,
        facade.move_to_initial_position,
        facade.get_current_pose,
        facade.get_point,
        facade.open_realtime_feedback,
        facade.run_flow,
        facade.pause_flow,
        facade.resume_flow,
        facade.stop_flow,
        facade.clear_alarm_history,
        facade.start_modbus,
        facade.stop_modbus,
    ]
    for method in no_arg_cases:
        success, msg = method()
        assert success is False
        assert "Runtime 离线" in msg

    # Methods that require arguments must also respect the offline guard.
    for method, args in (
        (facade.move_to_point, ("p1",)),
        (facade.connect_camera, ("D435i",)),
        (facade.disconnect_camera, ("D405",)),
        (facade.camera_test, ("D435i",)),
        (facade.run_step, ({"type": "move"},)),
    ):
        success, msg = method(*args)
        assert success is False
        assert "Runtime 离线" in msg

    # No IPC should be dispatched while offline.
    assert send_ipc.call_count == 0


def test_online_enable_robot_sends_ipc_and_returns_success():
    facade, send_ipc, _is_online, _send_stop = _make_facade(online=True)

    success, msg = facade.enable_robot()

    assert success is True
    assert "已发送" in msg
    send_ipc.assert_called_once_with("enable_robot", None)


def test_send_ipc_exception_returns_failure_without_raising():
    facade, _send_ipc, _is_online, _send_stop = _make_facade(
        online=True, send_raises=True
    )

    success, msg = facade.enable_robot()

    assert success is False
    assert "失败" in msg
    assert "ipc boom" in msg


def test_move_to_point_payload_shape():
    facade, send_ipc, _is_online, _send_stop = _make_facade(online=True)

    success, _msg = facade.move_to_point("p1", "MovJ", 10)

    assert success is True
    send_ipc.assert_called_once_with(
        "move_to_point",
        {"point_name": "p1", "motion_type": "MovJ", "speed": 10.0},
    )


def test_safe_stop_uses_stop_channel_not_normal_channel():
    facade, send_ipc, _is_online, send_stop = _make_facade(online=True)

    success, _msg = facade.safe_stop()

    assert success is True
    # Stop channel receives the command.
    send_stop.assert_called_once_with("safe_stop")
    # Normal IPC channel is bypassed entirely.
    send_ipc.assert_not_called()


def test_safe_stop_falls_back_to_normal_channel_without_stop_func():
    facade, send_ipc, _is_online, _send_stop = _make_facade(
        online=True, with_stop=False
    )

    success, _msg = facade.safe_stop()

    assert success is True
    send_ipc.assert_called_once_with("safe_stop")
