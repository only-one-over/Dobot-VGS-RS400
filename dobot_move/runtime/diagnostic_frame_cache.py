"""In-process single-frame cache for the diagnostic camera stream."""

from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger(__name__)


class DiagnosticFrameCache:
    """Thread-safe single-frame cache holding the latest diagnostic JPEG.

    Producers call :meth:`update` to publish a new frame; consumers call
    :meth:`get_latest` with the last sequence number they saw to fetch a frame
    only when a newer one is available. This replaces the 750 ms polling
    snapshot pattern and is the foundation for the streaming diagnostic view.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seq = 0
        self._jpeg_bytes = b""
        self._metadata: dict = {}
        self._timestamp = 0.0

    def update(self, seq: int, jpeg_bytes: bytes, metadata: dict) -> None:
        """Overwrite the cached frame with a newer one under lock."""
        with self._lock:
            self._seq = seq
            self._jpeg_bytes = jpeg_bytes
            self._metadata = metadata
            self._timestamp = time.time()

    def get_latest(self, last_seq_seen: int) -> dict | None:
        """Return the latest frame dict, or ``None`` if no new frame exists."""
        with self._lock:
            if self._seq == last_seq_seen:
                return None
            return {
                "seq": self._seq,
                "jpeg_bytes": self._jpeg_bytes,
                "metadata": self._metadata,
                "timestamp": self._timestamp,
            }

    def clear(self) -> None:
        """Reset all cached fields to their initial empty state."""
        with self._lock:
            self._seq = 0
            self._jpeg_bytes = b""
            self._metadata = {}
            self._timestamp = 0.0
