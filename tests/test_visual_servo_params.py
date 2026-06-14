"""Tests for visual servo parameter computation."""
import pytest
from dobot_move.visual_servo_controller import ServoThread


class TestAdaptiveMaxStep:
    """Test _adaptive_max_step with configurable parameters."""

    def _make_thread(self, **kwargs):
        """Create a ServoThread with fake dependencies."""
        defaults = dict(
            servo_period=0.06,
            gain_far=0.8, gain_mid=0.5, gain_near=0.2,
            threshold_far=50.0, threshold_mid=10.0,
            converge_threshold=3.0,
            max_step_far=35.0, max_step_mid=18.0,
            max_step_near=6.0, max_step_fine=2.0,
            max_error_mm=300.0,
            z_safety_limit=0.0,
            servo_p_t=0.06,
            servo_p_aheadtime=50,
            servo_p_gain=500,
            yolo_every_n=3,
            max_target_age=0.3,
            max_pose_age=0.1,
        )
        defaults.update(kwargs)
        # Create with minimal args - we only test _adaptive_max_step
        thread = object.__new__(ServoThread)
        for key, value in defaults.items():
            setattr(thread, key, value)
        return thread

    def test_far_distance(self):
        thread = self._make_thread()
        assert thread._adaptive_max_step(80.0) == 35.0

    def test_mid_distance(self):
        thread = self._make_thread()
        assert thread._adaptive_max_step(25.0) == 18.0

    def test_near_distance(self):
        thread = self._make_thread()
        assert thread._adaptive_max_step(5.0) == 6.0

    def test_fine_distance(self):
        thread = self._make_thread()
        assert thread._adaptive_max_step(1.0) == 2.0

    def test_custom_thresholds(self):
        thread = self._make_thread(
            threshold_far=100.0, threshold_mid=20.0,
            max_step_far=50.0, max_step_mid=25.0,
            max_step_near=10.0, max_step_fine=3.0,
        )
        assert thread._adaptive_max_step(150.0) == 50.0
        assert thread._adaptive_max_step(50.0) == 25.0
        assert thread._adaptive_max_step(10.0) == 10.0
        assert thread._adaptive_max_step(1.0) == 3.0

    def test_boundary_far(self):
        thread = self._make_thread()
        assert thread._adaptive_max_step(50.0) == 18.0  # exactly at threshold_far → mid

    def test_boundary_mid(self):
        thread = self._make_thread()
        assert thread._adaptive_max_step(10.0) == 6.0  # exactly at threshold_mid → near

    def test_boundary_converge(self):
        thread = self._make_thread(converge_threshold=3.0)
        assert thread._adaptive_max_step(3.0) == 2.0  # exactly at converge → fine
