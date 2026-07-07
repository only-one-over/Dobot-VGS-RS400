"""Non-blocking GUI device connection tasks."""

from __future__ import annotations

import threading

from ..ui.qt_compat import QObject, pyqtSignal


class ConnectionSignals(QObject):
    finished = pyqtSignal(str, int, bool, object, str)


class DaemonConnectionTask:
    """Run one blocking connector in a daemon thread and report via Qt signal."""

    def __init__(self, device_name, generation, connector):
        self.device_name = device_name
        self.generation = int(generation)
        self.connector = connector
        self.signals = ConnectionSignals()
        self._thread = threading.Thread(
            target=self._run,
            name=f"Gui{device_name}Connect",
            daemon=True,
        )

    @property
    def is_alive(self):
        return self._thread.is_alive()

    def start(self):
        self._thread.start()

    def _run(self):
        payload = None
        error = ""
        try:
            payload = self.connector()
            success = payload is not None and payload is not False
        except Exception as exc:
            success = False
            error = str(exc)
        self.signals.finished.emit(
            self.device_name,
            self.generation,
            success,
            payload,
            error,
        )
