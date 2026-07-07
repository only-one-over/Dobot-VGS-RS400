"""Tests for motion safety validation."""
import time
import pytest
from dobot_move.robot.motion_safety import (
    validate_absolute_pose, validate_relative_delta,
    validate_servo_p_params, validate_motion_target,
    MotionValidationResult, MotionSafetyConfig, MotionSafetyState,
    CODE_OK, CODE_NAN_INF, CODE_LENGTH, CODE_WORKSPACE,
    CODE_NOT_CONNECTED, CODE_NOT_ENABLED, CODE_ESTOP, CODE_ALARM,
    CODE_STALE_FEEDBACK, CODE_RELATIVE_DELTA, CODE_UNPROJECTABLE_RELATIVE,
)


class FakeController:
    """Fake controller for testing without hardware."""
    _DEFAULT_POSE = [300.0, 0.0, 200.0, 0.0, 0.0, -90.0]

    def __init__(self, connected=True, enabled=True, estopped=False,
                 error_status=0, robot_mode=5, feedback_age=0.1,
                 latest_pose=_DEFAULT_POSE, user_index=0, tool_index=0):
        self.is_connected = connected
        self.is_enabled = enabled
        self.software_emergency_active = estopped
        self._error_status = error_status
        self._robot_mode = robot_mode
        self._feedback_age = feedback_age
        self.latest_pose = latest_pose
        self._user_index = user_index
        self._tool_index = tool_index

    def get_motion_safety_state(self):
        return MotionSafetyState(
            is_connected=self.is_connected,
            is_enabled=self.is_enabled,
            software_emergency_active=self.software_emergency_active,
            error_status=self._error_status,
            robot_mode=self._robot_mode,
            feedback_age=self._feedback_age,
        )


class TestMotionValidationResult:
    def test_ok_is_truthy(self):
        r = MotionValidationResult(ok=True, code=0, message="OK")
        assert bool(r) is True

    def test_fail_is_falsy(self):
        r = MotionValidationResult(ok=False, code=1, message="bad")
        assert bool(r) is False


class TestValidateAbsolutePose:
    def test_valid_pose(self):
        ctrl = FakeController()
        result = validate_absolute_pose(ctrl, [300, 0, 200, 0, 0, -90])
        assert result.ok is True
        assert result.code == CODE_OK

    def test_nan_rejected(self):
        ctrl = FakeController()
        result = validate_absolute_pose(ctrl, [float('nan'), 0, 200, 0, 0, -90])
        assert result.ok is False
        assert result.code == CODE_NAN_INF

    def test_inf_rejected(self):
        ctrl = FakeController()
        result = validate_absolute_pose(ctrl, [300, 0, 200, 0, 0, float('inf')])
        assert result.ok is False
        assert result.code == CODE_NAN_INF

    def test_length_not_6_rejected(self):
        ctrl = FakeController()
        # Length 5
        result = validate_absolute_pose(ctrl, [300, 0, 200, 0, 0])
        assert result.ok is False
        assert result.code == CODE_LENGTH
        # Length 7
        result = validate_absolute_pose(ctrl, [300, 0, 200, 0, 0, -90, 0])
        assert result.ok is False
        assert result.code == CODE_LENGTH

    def test_none_rejected(self):
        ctrl = FakeController()
        result = validate_absolute_pose(ctrl, None)
        assert result.ok is False
        assert result.code == CODE_LENGTH

    def test_workspace_x_exceeded(self):
        ctrl = FakeController()
        result = validate_absolute_pose(ctrl, [9999, 0, 200, 0, 0, -90])
        assert result.ok is False
        assert result.code == CODE_WORKSPACE

    def test_workspace_z_negative(self):
        ctrl = FakeController()
        result = validate_absolute_pose(ctrl, [300, 0, -100, 0, 0, -90])
        assert result.ok is False
        assert result.code == CODE_WORKSPACE

    def test_not_connected(self):
        ctrl = FakeController(connected=False)
        result = validate_absolute_pose(ctrl, [300, 0, 200, 0, 0, -90])
        assert result.ok is False
        assert result.code == CODE_NOT_CONNECTED

    def test_not_enabled(self):
        ctrl = FakeController(enabled=False)
        result = validate_absolute_pose(ctrl, [300, 0, 200, 0, 0, -90])
        assert result.ok is False
        assert result.code == CODE_NOT_ENABLED

    def test_software_emergency(self):
        ctrl = FakeController(estopped=True)
        result = validate_absolute_pose(ctrl, [300, 0, 200, 0, 0, -90])
        assert result.ok is False
        assert result.code == CODE_ESTOP

    def test_error_status(self):
        ctrl = FakeController(error_status=3)
        result = validate_absolute_pose(ctrl, [300, 0, 200, 0, 0, -90])
        assert result.ok is False
        assert result.code == CODE_ALARM


class TestValidateRelativeDelta:
    def test_small_offset_passes(self):
        """合法小偏移应通过"""
        ctrl = FakeController(latest_pose=[300, 0, 200, 0, 0, -90])
        result = validate_relative_delta(ctrl, [0, 0, -10, 0, 0, 0])
        assert result.ok is True

    def test_large_xyz_offset_rejected(self):
        """XYZ 单段偏移超 300mm 应被拒绝"""
        ctrl = FakeController(latest_pose=[300, 0, 200, 0, 0, -90])
        result = validate_relative_delta(ctrl, [500, 0, 0, 0, 0, 0])
        assert result.ok is False
        assert result.code == CODE_RELATIVE_DELTA

    def test_large_rot_offset_rejected(self):
        """姿态单段偏移超 45deg 应被拒绝"""
        ctrl = FakeController(latest_pose=[300, 0, 200, 0, 0, -90])
        result = validate_relative_delta(ctrl, [0, 0, 0, 0, 0, 60])
        assert result.ok is False
        assert result.code == CODE_RELATIVE_DELTA

    def test_stale_feedback_rejected(self):
        """反馈过期应被拒绝"""
        ctrl = FakeController(feedback_age=1.0, latest_pose=[300, 0, 200, 0, 0, -90])
        result = validate_relative_delta(ctrl, [0, 0, -10, 0, 0, 0])
        assert result.ok is False
        assert result.code == CODE_STALE_FEEDBACK

    def test_projected_endpoint_out_of_workspace(self):
        """投影终点超出工作空间应被拒绝"""
        ctrl = FakeController(latest_pose=[800, 0, 200, 0, 0, -90])
        result = validate_relative_delta(ctrl, [200, 0, 0, 0, 0, 0])
        # projected X = 1000, which is > 900
        assert result.ok is False
        assert result.code == CODE_WORKSPACE

    def test_no_current_pose_rejected(self):
        """无法读取当前位姿应被拒绝"""
        ctrl = FakeController(latest_pose=None)
        result = validate_relative_delta(ctrl, [0, 0, -10, 0, 0, 0])
        assert result.ok is False
        assert result.code == CODE_UNPROJECTABLE_RELATIVE

    def test_nonzero_user_tool_rejected(self):
        """非零 user/tool 坐标系应被拒绝"""
        ctrl = FakeController(latest_pose=[300, 0, 200, 0, 0, -90], user_index=1)
        result = validate_relative_delta(ctrl, [0, 0, -10, 0, 0, 0])
        assert result.ok is False
        assert result.code == CODE_UNPROJECTABLE_RELATIVE

    def test_not_connected(self):
        ctrl = FakeController(connected=False, feedback_age=0.1)
        result = validate_relative_delta(ctrl, [0, 0, -10, 0, 0, 0])
        assert result.ok is False
        assert result.code == CODE_NOT_CONNECTED

    def test_nan_offset_rejected(self):
        ctrl = FakeController()
        result = validate_relative_delta(ctrl, [float('nan'), 0, 0, 0, 0, 0])
        assert result.ok is False
        assert result.code == CODE_NAN_INF

    def test_length_not_6_rejected(self):
        ctrl = FakeController()
        result = validate_relative_delta(ctrl, [0, 0, -10, 0, 0])
        assert result.ok is False
        assert result.code == CODE_LENGTH


class TestValidateServoPParams:
    def test_normal_params(self):
        t, aheadtime, gain = validate_servo_p_params(0.06, 50, 500, 0.06)
        assert t == 0.06
        assert aheadtime == 50
        assert gain == 500

    def test_t_below_servo_period(self):
        t, _, _ = validate_servo_p_params(0.01, 50, 500, 0.06)
        assert t == 0.06

    def test_aheadtime_clamped_low(self):
        _, aheadtime, _ = validate_servo_p_params(0.06, 10, 500, 0.06)
        assert aheadtime == 20

    def test_aheadtime_clamped_high(self):
        _, aheadtime, _ = validate_servo_p_params(0.06, 200, 500, 0.06)
        assert aheadtime == 100

    def test_gain_clamped_low(self):
        _, _, gain = validate_servo_p_params(0.06, 50, 100, 0.06)
        assert gain == 200

    def test_gain_clamped_high(self):
        _, _, gain = validate_servo_p_params(0.06, 50, 2000, 0.06)
        assert gain == 1000


class TestDeprecatedRoute:
    """validate_motion_target should still work as deprecated path."""
    def test_delegates_to_absolute(self):
        ctrl = FakeController()
        result = validate_motion_target(ctrl, [300, 0, 200, 0, 0, -90])
        assert result.ok is True
