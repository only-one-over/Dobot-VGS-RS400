"""Tests for point resolution: parsing, circular refs, missing points."""
import pytest
from dobot_move.config_manager import resolve_point, get_points, set_points


class TestResolvePoint:
    """Test point resolution logic."""

    def setup_method(self):
        """Reset config cache."""
        import dobot_move.config_manager as cm
        cm._cache_valid = False
        cm._config_cache = None

    def test_resolve_absolute_point(self):
        """Absolute point should return its coords directly."""
        points = get_points()
        if "test_abs" in points:
            del points["test_abs"]
            set_points(points)
        points = get_points()
        points["test_abs"] = {
            "coords": [100, 200, 300, 0, 0, 0],
            "is_relative": False,
            "relative_to": None,
            "offset": [0, 0, 0, 0, 0, 0],
            "is_default": False,
        }
        set_points(points)
        result = resolve_point("test_abs")
        assert result == [100, 200, 300, 0, 0, 0]
        # Cleanup
        del points["test_abs"]
        set_points(points)

    def test_resolve_missing_point(self):
        """Missing point should return None."""
        result = resolve_point("nonexistent_point_xyz")
        assert result is None

    def test_resolve_circular_reference(self):
        """Circular reference should return None."""
        points = get_points()
        points["test_circ_a"] = {
            "coords": [0, 0, 0, 0, 0, 0],
            "is_relative": True,
            "relative_to": "test_circ_b",
            "offset": [0, 0, 0, 0, 0, 0],
            "is_default": False,
        }
        points["test_circ_b"] = {
            "coords": [0, 0, 0, 0, 0, 0],
            "is_relative": True,
            "relative_to": "test_circ_a",
            "offset": [0, 0, 0, 0, 0, 0],
            "is_default": False,
        }
        set_points(points)
        result = resolve_point("test_circ_a")
        assert result is None
        # Cleanup
        del points["test_circ_a"]
        del points["test_circ_b"]
        set_points(points)
