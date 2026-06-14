"""Tests for config_manager: atomic write, backup recovery, visual servo config."""
import json
import os
import tempfile
import shutil
import pytest

# We test config_manager functions by importing them
from dobot_move.config_manager import (
    load_config, save_config, get_visual_servo_config,
    DEFAULT_VISUAL_SERVO_CONFIG,
)


class TestAtomicWrite:
    """Test atomic config writing and backup."""

    def setup_method(self):
        """Create a temp dir for config files."""
        self.tmpdir = tempfile.mkdtemp()
        self.config_file = os.path.join(self.tmpdir, "test_config.json")
        self.bak_file = self.config_file + ".bak"

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_save_creates_file(self):
        """save_config should create the config file."""
        import dobot_move.config_manager as cm
        original_file = cm.CONFIG_FILE
        try:
            cm.CONFIG_FILE = self.config_file
            cm._cache_valid = False
            cm._config_cache = None
            result = save_config({"test": True})
            assert result is True
            assert os.path.exists(self.config_file)
            with open(self.config_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            assert data["test"] is True
        finally:
            cm.CONFIG_FILE = original_file
            cm._cache_valid = False
            cm._config_cache = None

    def test_save_creates_backup(self):
        """save_config should create .bak before overwriting."""
        import dobot_move.config_manager as cm
        original_file = cm.CONFIG_FILE
        try:
            cm.CONFIG_FILE = self.config_file
            cm._cache_valid = False
            cm._config_cache = None
            # First save
            save_config({"version": 1})
            # Second save should create backup
            save_config({"version": 2})
            assert os.path.exists(self.bak_file)
            with open(self.bak_file, 'r', encoding='utf-8') as f:
                bak_data = json.load(f)
            assert bak_data["version"] == 1
        finally:
            cm.CONFIG_FILE = original_file
            cm._cache_valid = False
            cm._config_cache = None

    def test_load_recovers_from_corrupt(self):
        """load_config should recover from .bak when main file is corrupt."""
        import dobot_move.config_manager as cm
        original_file = cm.CONFIG_FILE
        try:
            cm.CONFIG_FILE = self.config_file
            cm._cache_valid = False
            cm._config_cache = None
            # Save valid config twice so a .bak is created
            # (save_config only backs up when overwriting an existing file)
            save_config({"version": 1})
            save_config({"version": 1})
            # Corrupt the main file
            with open(self.config_file, 'w') as f:
                f.write("{invalid json!!!")
            # Load should recover from backup
            cm._cache_valid = False
            cm._config_cache = None
            data = load_config()
            assert data.get("version") == 1
        finally:
            cm.CONFIG_FILE = original_file
            cm._cache_valid = False
            cm._config_cache = None


class TestVisualServoConfig:
    """Test visual servo config retrieval."""

    def test_default_values(self):
        """get_visual_servo_config should return defaults when no config."""
        config = get_visual_servo_config()
        assert config["servo_period"] == 0.06
        assert config["gain_far"] == 0.8
        assert config["gain_mid"] == 0.5
        assert config["gain_near"] == 0.2
        assert config["max_step_far"] == 35.0
        assert config["max_step_fine"] == 2.0
        assert config["yolo_every_n"] == 3
        assert config["stop_on_converge"] is False

    def test_default_config_matches_constant(self):
        """get_visual_servo_config should match DEFAULT_VISUAL_SERVO_CONFIG."""
        config = get_visual_servo_config()
        for key, value in DEFAULT_VISUAL_SERVO_CONFIG.items():
            assert config[key] == value, f"Mismatch for {key}: {config[key]} != {value}"
