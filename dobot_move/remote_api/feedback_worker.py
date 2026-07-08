"""30004 feedback background worker for remote_api."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

from ..robot.dobot_api import DobotApiFeedBack

logger = logging.getLogger(__name__)


class FeedbackWorker:
    """Background thread that maintains a 30004 feedback connection and caches the latest frame.

    Dobot CR supports multiple concurrent 30004 clients, so this connection
    coexists with the Runtime's own 30004 connection without interference.
    """

    def __init__(
        self,
        robot_ip: str,
        feedback_port: int = 30004,
        reconnect_interval_s: float = 2.0,
        stale_ok_s: float = 0.3,
        stale_fail_s: float = 2.0,
    ) -> None:
        self._robot_ip = robot_ip
        self._feedback_port = feedback_port
        self._reconnect_interval_s = reconnect_interval_s
        self._stale_ok_s = stale_ok_s
        self._stale_fail_s = stale_fail_s

        self._lock = threading.Lock()
        self._latest_feedback: Any = None
        self._recv_time: float = 0.0
        self._error: str = ""

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start the background feedback thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="remote-api-feedback-30004",
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Signal the background thread to stop and wait briefly."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def get_snapshot(self) -> tuple[Any, str, float, str]:
        """Return (feedback_array, health, age_s, error).

        health is one of "ok" / "stale" / "disconnected".
        """
        with self._lock:
            fb = self._latest_feedback
            recv_time = self._recv_time
            error = self._error

        if fb is None or recv_time <= 0:
            return None, "disconnected", 999.0, error

        age = time.monotonic() - recv_time
        if age <= self._stale_ok_s:
            health = "ok"
        elif age <= self._stale_fail_s:
            health = "stale"
        else:
            health = "disconnected"
        return fb, health, age, error

    def _run(self) -> None:
        """Background loop: connect, read, reconnect on failure."""
        while not self._stop_event.is_set():
            try:
                logger.info(
                    "正在连接 30004 反馈端口 %s:%d ...",
                    self._robot_ip, self._feedback_port,
                )
                fb = DobotApiFeedBack(self._robot_ip, self._feedback_port)
                try:
                    while not self._stop_event.is_set():
                        data = fb.feedBackData()
                        if data is not None and len(data) > 0:
                            with self._lock:
                                self._latest_feedback = data
                                self._recv_time = time.monotonic()
                                self._error = ""
                finally:
                    if hasattr(fb, "close"):
                        try:
                            fb.close()
                        except Exception:
                            pass
            except Exception as e:
                with self._lock:
                    self._error = str(e)
                logger.warning(
                    "30004 反馈连接异常: %s，%.0fs 后重连",
                    e, self._reconnect_interval_s,
                )
                # Wait for reconnect interval or stop signal
                self._stop_event.wait(self._reconnect_interval_s)
