import json
import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path

from dobot_move.alarm_history import AlarmHistory
from dobot_move.runtime_resilience import (
    RestartWindow,
    RuntimeState,
    RuntimeStateStore,
    SingleInstanceLock,
    flow_timeout_seconds,
    module_timeout_seconds,
)
from runtime_watchdog import RuntimeWatchdog


@contextmanager
def _workspace_temp_dir():
    path = Path.cwd() / f"_runtime_resilience_test_{uuid.uuid4().hex}"
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def test_unclean_runtime_boot_requires_recovery():
    with _workspace_temp_dir() as tmp_path:
        path = tmp_path / "runtime_state.json"
        first = RuntimeStateStore(path)

        assert first.begin_boot() is False
        first.transition(RuntimeState.RUNNING, flow_id="flow-1")

        second = RuntimeStateStore(path)
        assert second.begin_boot() is True
        assert second.snapshot()["state"] == RuntimeState.RECOVERY_REQUIRED.value


def test_clean_runtime_shutdown_does_not_require_recovery():
    with _workspace_temp_dir() as tmp_path:
        path = tmp_path / "runtime_state.json"
        first = RuntimeStateStore(path)
        first.begin_boot()
        first.mark_clean_shutdown()

        second = RuntimeStateStore(path)
        assert second.begin_boot() is False


def test_corrupt_runtime_state_is_preserved_and_requires_recovery():
    with _workspace_temp_dir() as tmp_path:
        path = tmp_path / "runtime_state.json"
        path.write_text("{broken", encoding="utf-8")

        store = RuntimeStateStore(path)

        assert store.begin_boot() is True
        assert list(tmp_path.glob("runtime_state.json.corrupt.*"))


def test_single_instance_lock_rejects_second_owner():
    with _workspace_temp_dir() as tmp_path:
        path = tmp_path / "runtime.lock"
        first = SingleInstanceLock(path)
        second = SingleInstanceLock(path)
        try:
            assert first.acquire()
            assert not second.acquire()
        finally:
            first.release()
            second.release()


def test_restart_window_locks_after_limit():
    with _workspace_temp_dir() as tmp_path:
        window = RestartWindow(tmp_path / "restarts.json", window_s=600, max_restarts=3)

        assert window.allow_and_record(now=100)
        assert window.allow_and_record(now=101)
        assert window.allow_and_record(now=102)
        assert not window.allow_and_record(now=103)
        assert window.allow_and_record(now=1000)


def test_dynamic_timeout_budget_accounts_for_delay_and_path():
    delay = {"type": "delay", "params": {"duration_s": 20}}
    path = {"type": "relative_path", "params": {"segments": [{}, {}, {}]}}

    assert module_timeout_seconds(delay) == 25
    assert module_timeout_seconds(path) == 90
    assert flow_timeout_seconds([delay, path]) > 115


def test_corrupt_alarm_history_is_preserved():
    with _workspace_temp_dir() as temp_dir:
        path = temp_dir / "alarms.json"
        path.write_text("[broken", encoding="utf-8")
        history = AlarmHistory(path=str(path))

        assert history.list_records() == []
        assert list(temp_dir.glob("alarms.json.corrupt.*"))


def _write_health(path: Path, timestamp: float, running: bool, pid: int = 123):
    path.write_text(
        json.dumps(
            {
                "timestamp": timestamp,
                "runtime": {
                    "state": RuntimeState.RUNNING.value if running else RuntimeState.READY.value
                },
                "flow": {"running": running},
                "process": {"pid": pid},
            }
        ),
        encoding="utf-8",
    )


def test_watchdog_stale_active_flow_stops_then_restarts():
    with _workspace_temp_dir() as tmp_path:
        health_path = tmp_path / "health.json"
        _write_health(health_path, timestamp=10, running=True)
        calls = []
        watchdog = RuntimeWatchdog(
            health_path,
            stale_after_s=15,
            state_dir=tmp_path,
            stop_robot=lambda: calls.append("stop"),
            terminate_process=lambda pid: calls.append(("terminate", pid)),
            restart_task=lambda: calls.append("restart"),
        )

        assert watchdog.check_once(now=30) == "restarted"
        assert calls == ["stop", ("terminate", 123), "restart"]


def test_watchdog_stale_idle_runtime_restarts_without_robot_stop():
    with _workspace_temp_dir() as tmp_path:
        health_path = tmp_path / "health.json"
        _write_health(health_path, timestamp=10, running=False)
        calls = []
        watchdog = RuntimeWatchdog(
            health_path,
            stale_after_s=15,
            state_dir=tmp_path,
            stop_robot=lambda: calls.append("stop"),
            terminate_process=lambda pid: calls.append(("terminate", pid)),
            restart_task=lambda: calls.append("restart"),
        )

        assert watchdog.check_once(now=30) == "restarted"
        assert calls == [("terminate", 123), "restart"]


def test_watchdog_restart_storm_creates_lockout():
    with _workspace_temp_dir() as tmp_path:
        health_path = tmp_path / "health.json"
        _write_health(health_path, timestamp=0, running=False, pid=0)
        watchdog = RuntimeWatchdog(
            health_path,
            stale_after_s=1,
            restart_limit=1,
            state_dir=tmp_path,
            terminate_process=lambda pid: None,
            restart_task=lambda: None,
        )

        assert watchdog.check_once(now=10) == "restarted"
        assert watchdog.check_once(now=11) == "locked_out"
        assert (tmp_path / "runtime_watchdog_lockout.json").exists()
