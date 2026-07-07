"""Tests for config_manager: atomic write, backup recovery, visual servo config."""
import json
import os
import shutil
import uuid
import pytest

# We test config_manager functions by importing them
from dobot_move.config_manager import (
    load_config, save_config, get_visual_servo_config,
    DEFAULT_VISUAL_SERVO_CONFIG, DEFAULT_CAMERA_MODEL_PATH,
    get_camera_model_path, resolve_camera_model_path, set_camera_model_path,
)


def _make_test_directory(prefix):
    path = os.path.join(os.getcwd(), f".{prefix}_{uuid.uuid4().hex}")
    os.mkdir(path)
    return path


class TestAtomicWrite:
    """Test atomic config writing and backup."""

    def setup_method(self):
        """Create a temp dir for config files."""
        self.tmpdir = _make_test_directory("config_test")
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

    def test_reload_config_invalidates_process_cache(self):
        import dobot_move.config_manager as cm

        original_file = cm.CONFIG_FILE
        try:
            cm.CONFIG_FILE = self.config_file
            cm._cache_valid = False
            cm._config_cache = None
            save_config({"version": 1})
            assert load_config()["version"] == 1
            with open(self.config_file, "w", encoding="utf-8") as handle:
                json.dump({"version": 2}, handle)

            assert load_config()["version"] == 1
            assert cm.reload_config()["version"] == 2
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


class TestCameraModelConfig:
    def setup_method(self):
        import dobot_move.config_manager as cm

        self.tmpdir = _make_test_directory("camera_model_test")
        self.original_config_file = cm.CONFIG_FILE
        cm.CONFIG_FILE = os.path.join(self.tmpdir, "config.json")
        cm._cache_valid = False
        cm._config_cache = None

    def teardown_method(self):
        import dobot_move.config_manager as cm

        cm.CONFIG_FILE = self.original_config_file
        cm._cache_valid = False
        cm._config_cache = None
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_legacy_config_uses_bundled_model_for_both_cameras(self):
        save_config({})

        assert get_camera_model_path("D435i") == DEFAULT_CAMERA_MODEL_PATH
        assert get_camera_model_path("D405") == DEFAULT_CAMERA_MODEL_PATH

    def test_camera_model_paths_are_persisted_independently(self):
        d435i_model = os.path.join(self.tmpdir, "d435i.onnx")
        d405_model = os.path.join(self.tmpdir, "d405.onnx")
        with open(d435i_model, "wb") as model_file:
            model_file.write(b"d435i")
        with open(d405_model, "wb") as model_file:
            model_file.write(b"d405")

        set_camera_model_path("D435i", d435i_model)
        set_camera_model_path("D405", d405_model)

        assert get_camera_model_path("D435i") == os.path.abspath(d435i_model)
        assert get_camera_model_path("D405") == os.path.abspath(d405_model)
        config = load_config()
        assert config["camera"]["models"] == {
            "D435i": os.path.abspath(d435i_model),
            "D405": os.path.abspath(d405_model),
        }

    @pytest.mark.parametrize("camera_type", ["D455", "", None])
    def test_invalid_camera_type_is_rejected(self, camera_type):
        with pytest.raises(ValueError, match="不支持的相机类型"):
            get_camera_model_path(camera_type)

    def test_non_onnx_model_is_rejected(self):
        model = os.path.join(self.tmpdir, "model.pt")
        with open(model, "wb") as model_file:
            model_file.write(b"model")

        with pytest.raises(ValueError, match=r"\.onnx"):
            set_camera_model_path("D435i", model)

    def test_missing_model_is_rejected_without_fallback(self):
        missing_model = os.path.join(self.tmpdir, "missing.onnx")

        with pytest.raises(FileNotFoundError, match="模型文件不存在"):
            resolve_camera_model_path("D405", missing_model)

    def test_explicit_model_path_takes_precedence(self):
        configured_model = os.path.join(self.tmpdir, "configured.onnx")
        explicit_model = os.path.join(self.tmpdir, "explicit.onnx")
        with open(configured_model, "wb") as model_file:
            model_file.write(b"configured")
        with open(explicit_model, "wb") as model_file:
            model_file.write(b"explicit")
        set_camera_model_path("D435i", configured_model)

        assert resolve_camera_model_path("D435i", explicit_model) == os.path.abspath(explicit_model)
