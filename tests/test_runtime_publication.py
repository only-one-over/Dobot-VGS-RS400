import json
import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest

import dobot_move.config.config_manager as config_manager
from dobot_move.config.config_manager import load_config, use_config_snapshot
from dobot_move.runtime.runtime_publication import PublicationError, RuntimePublicationStore


@contextmanager
def _workspace_temp():
    path = Path.cwd() / f"_runtime_publication_test_{uuid.uuid4().hex}"
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _write_drafts(tmp_path):
    config_path = tmp_path / "config.json"
    flow_path = tmp_path / "flows.json"
    config_path.write_text(
        json.dumps({"robot_ip": "192.168.1.6", "modbus_port": 502}),
        encoding="utf-8",
    )
    flow_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "main_flow_id": "flow-a",
                "last_edited_flow_id": "flow-a",
                "flows": [
                    {"id": "flow-a", "name": "Flow A", "modules": []}
                ],
            }
        ),
        encoding="utf-8",
    )
    return config_path, flow_path


def test_publication_separates_draft_and_active_snapshot():
    with _workspace_temp() as tmp_path:
        config_path, flow_path = _write_drafts(tmp_path)
        store = RuntimePublicationStore(
            tmp_path / "published.json",
            config_path=config_path,
            flow_path=flow_path,
        )
        assert store.status()["revision"] == "legacy-draft"

        first = store.publish_drafts()
        config_path.write_text(
            json.dumps({"robot_ip": "10.0.0.8", "modbus_port": 502}),
            encoding="utf-8",
        )

        assert store.snapshot()["config"]["robot_ip"] == "192.168.1.6"
        second = store.publish_drafts()
        assert second["revision"] != first["revision"]
        assert second["config"]["robot_ip"] == "10.0.0.8"


def test_publication_validation_does_not_replace_active_snapshot():
    with _workspace_temp() as tmp_path:
        config_path, flow_path = _write_drafts(tmp_path)
        store = RuntimePublicationStore(
            tmp_path / "published.json",
            config_path=config_path,
            flow_path=flow_path,
        )
        active = store.publish_drafts()

        with pytest.raises(PublicationError):
            store.publish_drafts(lambda _config, _library: ["bad draft"])

        assert store.snapshot()["revision"] == active["revision"]


def test_execution_config_snapshot_is_context_local():
    with use_config_snapshot({"robot_ip": "snapshot"}):
        assert load_config()["robot_ip"] == "snapshot"


def test_execution_snapshot_write_does_not_touch_gui_draft(monkeypatch):
    with _workspace_temp() as path:
        draft = path / "config.json"
        draft.write_text(json.dumps({"value": "draft"}), encoding="utf-8")
        monkeypatch.setattr(config_manager, "CONFIG_FILE", str(draft))

        with use_config_snapshot({"value": "published"}):
            assert config_manager.save_config({"value": "task-local"}) is True
            assert load_config()["value"] == "task-local"

        assert json.loads(draft.read_text(encoding="utf-8"))["value"] == "draft"
