"""Comprehensive pytest unit tests for the dobot_move.remote_api subpackage.

Covers four areas per the remote_api test spec:
  - SubTask 8.1: pure response builder functions (handlers.py)
  - SubTask 8.2: APIHandler token middleware (_check_token)
  - SubTask 8.3: 301 legacy path redirects (_send_redirect + do_GET routing)
  - SubTask 8.4: remote_api config default merging (get_remote_api_config)
"""
from __future__ import annotations

import json
import sys
import time

import numpy as np
import pytest
from unittest.mock import MagicMock, patch

# Defensive: several test modules (test_flow_recovery_policy, test_runtime_contract,
# test_production_state_machine, ...) replace sys.modules["dobot_move.communication.
# modbus_server"] with a stub that lacks REGISTER_NAME/REGISTER_VALUE_DESC/
# REG_HEARTBEAT/REG_HOOK_TYPE. remote_api.modbus_client imports those constants
# at module load time. If a stub is detected, pop it so Python re-imports the
# real modbus_server module with the full set of constants.
_existing_modbus_server = sys.modules.get("dobot_move.communication.modbus_server")
if _existing_modbus_server is not None and not hasattr(_existing_modbus_server, "REGISTER_NAME"):
    del sys.modules["dobot_move.communication.modbus_server"]

from dobot_move.config import config_manager
from dobot_move.remote_api.config import (
    DEFAULT_REMOTE_API_CONFIG,
    get_remote_api_config,
)
from dobot_move.remote_api.handlers import (
    build_feedback_all,
    build_health,
    build_production_status,
    build_status,
)
from dobot_move.remote_api.app import APIHandler


# ============================ helpers ============================
class FakeFeedback:
    """Mimics a numpy structured feedback array.

    ``fb["FieldName"][0]`` returns the stored scalar or vector value,
    matching the access pattern used by parse_feedback().
    """

    def __init__(self, **fields):
        self._fields = fields

    def __getitem__(self, key):
        return [self._fields[key]]


def _make_feedback(
    robot_mode=5,
    enable_status=1,
    running_status=1,
    error_status=0,
    current_command_id=42,
    speed_scaling=0.5,
):
    """Build a FakeFeedback with sensible defaults and 6-element vectors."""
    return FakeFeedback(
        RobotMode=robot_mode,
        EnableStatus=enable_status,
        RunningStatus=running_status,
        ErrorStatus=error_status,
        CurrentCommandId=current_command_id,
        SpeedScaling=speed_scaling,
        ToolVectorActual=np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0]),
        QActual=np.array([0.1, 0.2, 0.3, 0.4, 0.5, 0.6]),
        QTarget=np.array([0.1, 0.2, 0.3, 0.4, 0.5, 0.6]),
        TCPSpeedActual=np.array([10.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
        ToolVectorTarget=np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0]),
        ActualTCPForce=np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0]),
    )


# ============================ SubTask 8.1: pure function tests ============================

def test_build_status_with_none():
    """build_status(fb=None) reports robot unavailable and disconnected."""
    result = build_status(None, "disconnected", 999.0, "", "192.168.5.1")
    assert result["dobot_available"] is False
    assert result["controller_created"] is False
    assert result["is_connected"] is False
    assert result["is_enabled"] is False
    assert result["motion_busy"] is False
    assert result["robot_ip"] == "192.168.5.1"


def test_build_status_with_feedback():
    """build_status with live feedback reports connected/enabled/busy."""
    fb = _make_feedback(enable_status=1, running_status=1)
    result = build_status(fb, "ok", 0.1, "", "192.168.5.1")
    assert result["dobot_available"] is True
    assert result["controller_created"] is True
    assert result["is_connected"] is True
    assert result["is_enabled"] is True
    assert result["motion_busy"] is True
    assert result["robot_ip"] == "192.168.5.1"


def test_build_status_disabled_idle():
    """build_status reflects enable_status/running_status == 0."""
    fb = _make_feedback(enable_status=0, running_status=0)
    result = build_status(fb, "ok", 0.1, "", "192.168.5.1")
    assert result["is_enabled"] is False
    assert result["motion_busy"] is False
    assert result["is_connected"] is True


def test_build_feedback_all_with_none():
    """build_feedback_all(fb=None) reports disconnected with null pose."""
    result = build_feedback_all(None, "disconnected", 999.0, "", "192.168.5.1")
    assert result["is_connected"] is False
    assert result["is_enabled"] is False
    assert result["motion_busy"] is False
    assert result["pose"] is None
    assert result["robot_mode"] is None
    assert result["force"] is None
    assert result["feedback_health"]["health"] == "disconnected"
    assert result["feedback_health"]["age"] == 999.0
    assert result["safety_state"]["health"] == "disconnected"
    assert result["safety_state"]["is_connected"] is False
    assert result["safety_state"]["emergency_stopped"] is False
    assert result["safety_state"]["error_status"] is False
    assert result["robot_ip"] == "192.168.5.1"


def test_build_feedback_all_emergency_stopped():
    """build_feedback_all with robot_mode==9 flags emergency stop."""
    fb = _make_feedback(robot_mode=9, error_status=0)
    result = build_feedback_all(fb, "ok", 0.5, "", "192.168.5.1")
    assert result["is_connected"] is True
    assert result["is_enabled"] is True
    assert result["motion_busy"] is True
    assert result["software_emergency_active"] is True
    assert result["robot_mode"] == 9
    assert result["safety_state"]["emergency_stopped"] is True
    assert result["safety_state"]["is_enabled"] is True
    assert result["safety_state"]["robot_mode"] == 9
    assert result["safety_state"]["health"] == "ok"
    assert result["safety_state"]["feedback_age"] == 0.5
    assert result["feedback_health"]["health"] == "ok"
    assert result["feedback_health"]["age"] == 0.5
    assert result["pose"] == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    assert result["force"]["fx"] == 1.0
    assert result["force"]["fy"] == 2.0
    assert result["force"]["fz"] == 3.0
    assert result["force"]["mx"] == 4.0
    assert result["force"]["my"] == 5.0
    assert result["force"]["mz"] == 6.0
    assert result["speed_scaling"] == 0.5
    assert result["current_command_id"] == 42
    assert result["robot_ip"] == "192.168.5.1"


def test_build_feedback_all_normal_mode():
    """build_feedback_all with normal robot_mode reports no emergency."""
    fb = _make_feedback(robot_mode=5, error_status=0)
    result = build_feedback_all(fb, "ok", 0.2, "", "10.0.0.1")
    assert result["software_emergency_active"] is False
    assert result["safety_state"]["emergency_stopped"] is False
    assert result["safety_state"]["error_status"] is False
    assert result["error_status"] == 0
    assert result["robot_ip"] == "10.0.0.1"


def test_build_feedback_all_with_error():
    """build_feedback_all surfaces error_status==1 in safety_state."""
    fb = _make_feedback(error_status=1)
    result = build_feedback_all(fb, "stale", 1.5, "", "192.168.5.1")
    assert result["safety_state"]["error_status"] is True
    assert result["error_status"] == 1


def test_build_health_ok():
    """build_health with healthy feedback reports status='ok'."""
    result = build_health(10.5, "ok", 5, 1, "boom")
    assert result["status"] == "ok"
    assert result["uptime_s"] == 10.5
    assert result["feedback_health"] == "ok"
    assert result["request_count"] == 5
    assert result["error_count"] == 1
    assert result["last_error"] == "boom"


def test_build_health_degraded_when_disconnected():
    """build_health with disconnected feedback reports status='degraded'."""
    result = build_health(10.0, "disconnected", 0, 0)
    assert result["status"] == "degraded"
    assert result["feedback_health"] == "disconnected"


def test_build_health_default_last_error():
    """build_health omits last_error -> empty string."""
    result = build_health(1.0, "ok", 0, 0)
    assert result["last_error"] == ""
    assert result["status"] == "ok"


def test_build_production_status_missing_file(tmp_path):
    """Missing health file -> runtime_state='offline'."""
    health_path = str(tmp_path / "nonexistent_runtime_health.json")
    result = build_production_status(health_path)
    assert result["runtime_state"] == "offline"
    assert result["health_age_s"] is None


def test_build_production_status_corrupt_json(tmp_path):
    """Corrupt JSON -> runtime_state='unknown'."""
    health_path = tmp_path / "runtime_health.json"
    health_path.write_text("{broken json!!!", encoding="utf-8")
    result = build_production_status(str(health_path))
    assert result["runtime_state"] == "unknown"
    assert result["health_age_s"] is None


def test_build_production_status_invalid_timestamp(tmp_path):
    """Non-numeric timestamp -> runtime_state='unknown'."""
    health_path = tmp_path / "runtime_health.json"
    payload = {"timestamp": "not-a-number", "runtime": {"state": "running"}}
    health_path.write_text(json.dumps(payload), encoding="utf-8")
    result = build_production_status(str(health_path))
    assert result["runtime_state"] == "unknown"
    assert result["health_age_s"] is None


def test_build_production_status_stale_file(tmp_path):
    """Stale timestamp (age > threshold) -> runtime_state='offline'."""
    health_path = tmp_path / "runtime_health.json"
    payload = {"timestamp": time.time() - 100}
    health_path.write_text(json.dumps(payload), encoding="utf-8")
    result = build_production_status(str(health_path), stale_threshold_s=3.0)
    assert result["runtime_state"] == "offline"
    assert result["health_age_s"] is not None
    assert result["health_age_s"] >= 100


def test_build_production_status_fresh_file(tmp_path):
    """Fresh health file -> fields extracted from payload."""
    health_path = tmp_path / "runtime_health.json"
    payload = {
        "timestamp": time.time(),
        "runtime": {"state": "running", "maintenance": False},
        "robot": {"connected": True, "enabled": True},
        "modbus": {"is_running": True},
        "production": {"state": "producing"},
        "flow": {"module_name": "grasp", "module_index": 3, "failure_latched": False},
    }
    health_path.write_text(json.dumps(payload), encoding="utf-8")
    result = build_production_status(str(health_path), stale_threshold_s=3.0)
    assert result["runtime_state"] == "running"
    assert result["maintenance"] is False
    assert result["robot_connected"] is True
    assert result["robot_enabled"] is True
    assert result["modbus_running"] is True
    assert result["production_state"] == "producing"
    assert result["current_flow"] == "grasp"
    assert result["module_index"] == 3
    assert result["failure_latched"] is False
    assert result["health_age_s"] is not None
    assert result["health_age_s"] < 3.0


# ============================ SubTask 8.2: token middleware tests ============================

def _make_token_handler(token="", auth_header=""):
    """Build a MagicMock handler with configured token and Authorization header."""
    handler = MagicMock()
    handler.server.app.config.get.return_value = token
    handler.headers.get.return_value = auth_header
    return handler


def test_check_token_empty_config_skips_auth():
    """Empty configured token -> auth disabled (returns True)."""
    handler = _make_token_handler(token="", auth_header="")
    assert APIHandler._check_token(handler) is True


def test_check_token_valid_bearer():
    """Correct Bearer token -> returns True."""
    handler = _make_token_handler(token="secret123", auth_header="Bearer secret123")
    assert APIHandler._check_token(handler) is True


def test_check_token_wrong_bearer():
    """Wrong Bearer token -> returns False."""
    handler = _make_token_handler(token="secret123", auth_header="Bearer wrong")
    assert APIHandler._check_token(handler) is False


def test_check_token_missing_header():
    """Missing Authorization header -> returns False."""
    handler = _make_token_handler(token="secret123", auth_header="")
    assert APIHandler._check_token(handler) is False


def test_check_token_wrong_prefix():
    """Header without 'Bearer ' prefix -> returns False."""
    handler = _make_token_handler(token="secret123", auth_header="secret123")
    assert APIHandler._check_token(handler) is False


def test_health_endpoint_exempt_from_auth():
    """/api/v1/health is served before the token check (no auth required).

    do_GET routing order (confirmed in app.py):
      1. legacy redirects
      2. /api/v1/health  -> served, returns
      3. _check_token()  -> only enforced for routes below
    Setting a non-empty token with no Authorization header still yields a
    successful health response, proving the exemption.
    """
    handler = MagicMock()
    handler.path = "/api/v1/health"
    handler.server.app.config.get.return_value = "secret123"  # token required
    handler.headers.get.return_value = ""  # no Authorization header
    handler.server.app.get_stats.return_value = (10.0, 5, 1, "last err")
    handler.server.app.feedback_worker.get_snapshot.return_value = (
        None, "ok", 0.1, "",
    )
    with patch(
        "dobot_move.remote_api.app.build_health", return_value={"status": "ok"}
    ) as mock_build:
        APIHandler.do_GET(handler)
    # health builder invoked with stats from the server app
    mock_build.assert_called_once_with(10.0, "ok", 5, 1, "last err")
    # response sent successfully, no 401 error
    handler._send_ok.assert_called_once_with({"status": "ok"})
    handler._send_error.assert_not_called()
    handler.server.app.record_request.assert_called_once_with(ok=True)


# ============================ SubTask 8.3: 301 redirect tests ============================

def test_send_redirect_no_query():
    """_send_redirect issues 301 with Location header (no query string)."""
    handler = MagicMock()
    handler.path = "/api/status"
    APIHandler._send_redirect(handler, "/api/v1/status")
    handler.send_response.assert_called_once_with(301)
    handler.send_header.assert_any_call("Location", "/api/v1/status")
    handler.send_header.assert_any_call("Access-Control-Allow-Origin", "*")
    handler.end_headers.assert_called_once()


def test_send_redirect_preserves_query():
    """_send_redirect preserves query string in Location header."""
    handler = MagicMock()
    handler.path = "/api/status?foo=bar&x=1"
    APIHandler._send_redirect(handler, "/api/v1/status")
    handler.send_response.assert_called_once_with(301)
    handler.send_header.assert_any_call("Location", "/api/v1/status?foo=bar&x=1")
    handler.end_headers.assert_called_once()


def test_do_get_status_legacy_redirect():
    """do_GET('/api/status') -> 301 redirect to '/api/v1/status'."""
    handler = MagicMock()
    handler.path = "/api/status"
    APIHandler.do_GET(handler)
    handler._send_redirect.assert_called_once_with("/api/v1/status")
    handler.server.app.record_request.assert_called_once_with(ok=True)


def test_do_get_feedback_all_legacy_redirect():
    """do_GET('/api/feedback/all') -> 301 redirect to '/api/v1/feedback/all'."""
    handler = MagicMock()
    handler.path = "/api/feedback/all"
    APIHandler.do_GET(handler)
    handler._send_redirect.assert_called_once_with("/api/v1/feedback/all")
    handler.server.app.record_request.assert_called_once_with(ok=True)


def test_do_get_modbus_registers_legacy_redirect():
    """do_GET('/api/modbus/registers') -> 301 redirect to '/api/v1/modbus/registers'."""
    handler = MagicMock()
    handler.path = "/api/modbus/registers"
    APIHandler.do_GET(handler)
    handler._send_redirect.assert_called_once_with("/api/v1/modbus/registers")
    handler.server.app.record_request.assert_called_once_with(ok=True)


# ============================ SubTask 8.4: config default merge tests ============================

def test_default_remote_api_config_values():
    """DEFAULT_REMOTE_API_CONFIG exposes documented defaults."""
    assert DEFAULT_REMOTE_API_CONFIG["host"] == "0.0.0.0"
    assert DEFAULT_REMOTE_API_CONFIG["port"] == 8000
    assert DEFAULT_REMOTE_API_CONFIG["token"] == ""
    assert DEFAULT_REMOTE_API_CONFIG["feedback_port"] == 30004
    assert DEFAULT_REMOTE_API_CONFIG["feedback_reconnect_interval_s"] == 2.0
    assert DEFAULT_REMOTE_API_CONFIG["feedback_stale_ok_s"] == 0.3
    assert DEFAULT_REMOTE_API_CONFIG["feedback_stale_fail_s"] == 2.0
    assert DEFAULT_REMOTE_API_CONFIG["modbus_client_timeout_s"] == 3.0
    assert DEFAULT_REMOTE_API_CONFIG["modbus_host"] == "127.0.0.1"
    assert DEFAULT_REMOTE_API_CONFIG["allowed_ips"] == []


def test_get_remote_api_config_no_key_returns_defaults(monkeypatch):
    """Absent 'remote_api' key -> all defaults returned."""
    monkeypatch.setattr(config_manager, "load_config", lambda: {})
    config = config_manager.get_remote_api_config()
    for key, value in DEFAULT_REMOTE_API_CONFIG.items():
        assert config[key] == value, f"default mismatch for {key}"


def test_get_remote_api_config_partial_merge(monkeypatch):
    """Partial 'remote_api' overlay merges with defaults (port overridden)."""
    monkeypatch.setattr(
        config_manager, "load_config", lambda: {"remote_api": {"port": 9000}}
    )
    config = config_manager.get_remote_api_config()
    assert config["port"] == 9000  # overridden
    assert config["host"] == "0.0.0.0"  # default kept
    assert config["token"] == ""  # default kept
    assert config["feedback_port"] == 30004  # default kept
    assert config["modbus_host"] == "127.0.0.1"  # default kept
    assert config["allowed_ips"] == []  # default kept


def test_remote_api_config_delegates_to_config_manager(monkeypatch):
    """remote_api.config.get_remote_api_config delegates to config_manager."""
    monkeypatch.setattr(
        config_manager, "load_config", lambda: {"remote_api": {"port": 9999}}
    )
    config = get_remote_api_config()
    assert config["port"] == 9999
    # defaults still present for untouched keys
    assert config["host"] == "0.0.0.0"
