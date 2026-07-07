"""Compatibility shell for the pre-IPC GUI connection coordinator."""


class StartupConnectionMixin:
    """Prevent legacy GUI classes from acquiring Runtime-owned hardware."""

    def _initialize_startup_connections(self):
        if hasattr(self, "_refresh_action_states"):
            self._refresh_action_states()

    def _restart_startup_connection_check(self):
        if hasattr(self, "_poll_status"):
            self._poll_status()

    def _request_device_connection(self, device_name, manual=False):
        del manual
        if hasattr(self, "_show_runtime_ipc_required"):
            return self._show_runtime_ipc_required(f"连接 {device_name}")
        return False

    def _request_missing_devices_background(self, missing_devices):
        del missing_devices
        return False

    def _shutdown_startup_connections(self):
        return None
