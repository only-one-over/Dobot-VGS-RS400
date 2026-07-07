import json
import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path

from dobot_move.gui_runtime_status import RuntimeHealthReader


@contextmanager
def _workspace_temp_dir():
    path = Path.cwd() / f"_gui_runtime_status_test_{uuid.uuid4().hex}"
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def test_runtime_health_reader_parses_current_schema():
    with _workspace_temp_dir() as tmp_path:
        health_path = tmp_path / "runtime_health.json"
        health_path.write_text(
            json.dumps(
                {
                    "timestamp": 100.0,
                    "runtime": {"state": "READY", "last_error": ""},
                    "robot": {"connected": True, "enabled": True},
                    "modbus": {"is_running": True, "port": 1502},
                    "flow": {
                        "running": False,
                        "main_flow_name": "流程 1",
                        "module_name": None,
                        "module_index": 0,
                        "cameras": {"D405": True, "D435i": False},
                    },
                }
            ),
            encoding="utf-8",
        )

        snapshot = RuntimeHealthReader(health_path).read(now=102.0)

    assert snapshot.online is True
    assert snapshot.runtime_state == "READY"
    assert snapshot.robot_connected is True
    assert snapshot.robot_enabled is True
    assert snapshot.d405_connected is True
    assert snapshot.d435i_connected is False
    assert snapshot.modbus_running is True
    assert snapshot.modbus_port == 1502
    assert snapshot.current_flow == "流程 1"
    assert snapshot.current_step == "0"


def test_runtime_health_reader_marks_stale_file_offline():
    with _workspace_temp_dir() as tmp_path:
        health_path = tmp_path / "runtime_health.json"
        health_path.write_text(
            json.dumps(
                {
                    "timestamp": 100.0,
                    "runtime": {"state": "RUNNING"},
                    "robot": {"connected": True},
                    "modbus": {"is_running": True},
                    "flow": {"cameras": {"D405": True, "D435i": True}},
                }
            ),
            encoding="utf-8",
        )

        snapshot = RuntimeHealthReader(
            health_path, stale_after_s=3.0
        ).read(now=104.0)

    assert snapshot.online is False
    assert snapshot.runtime_state == "OFFLINE"
    assert snapshot.robot_connected is False
    assert snapshot.d405_connected is False
    assert snapshot.modbus_running is False


def test_runtime_health_reader_handles_missing_file():
    with _workspace_temp_dir() as tmp_path:
        snapshot = RuntimeHealthReader(tmp_path / "missing.json").read(now=100.0)

    assert snapshot.online is False
    assert snapshot.runtime_state == "OFFLINE"
    assert snapshot.read_error


def test_runtime_health_reader_handles_invalid_json():
    with _workspace_temp_dir() as tmp_path:
        health_path = tmp_path / "runtime_health.json"
        health_path.write_text("{invalid", encoding="utf-8")

        snapshot = RuntimeHealthReader(health_path).read(now=100.0)

    assert snapshot.online is False
    assert snapshot.read_error


def test_runtime_health_reader_tolerates_missing_fields():
    with _workspace_temp_dir() as tmp_path:
        health_path = tmp_path / "runtime_health.json"
        health_path.write_text('{"timestamp": 100}', encoding="utf-8")

        snapshot = RuntimeHealthReader(health_path).read(now=100.0)

    assert snapshot.online is True
    assert snapshot.runtime_state == "UNKNOWN"
    assert snapshot.modbus_port == 502
