from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PROJECT_ROOT / "scripts"


def _read(name):
    return (SCRIPTS / name).read_text(encoding="utf-8")


def test_install_script_is_transactional_and_keeps_legacy_tasks():
    text = _read("install_windows_services.ps1")

    assert "Backup-AndDisableLegacyTasks" in text
    assert "Disable-ScheduledTask" in _read("windows_service_common.ps1")
    assert "Unregister-ScheduledTask" not in text
    assert "Stop-And-UninstallServiceWrapper" in text
    assert "Restore-LegacyTasks" in text
    assert "WasRunning" in _read("windows_service_common.ps1")


def test_install_script_uses_secure_credential_and_scrubs_xml():
    text = _read("install_windows_services.ps1")

    assert "PSCredential" in text
    assert "SecureStringToBSTR" in text
    assert "ZeroFreeBSTR" in text
    assert "generate_config" in text
    assert "runtime_ipc.token" in text


def test_uninstall_order_is_watchdog_then_runtime():
    text = _read("uninstall_windows_services.ps1")

    watchdog_index = text.index("DobotRuntimeWatchdog.exe")
    runtime_index = text.index("DobotRuntimeService.exe")
    assert watchdog_index < runtime_index
