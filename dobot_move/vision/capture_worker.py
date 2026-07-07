#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""纯 Python 帧采集 worker，无 Qt 依赖。

本模块提供 :class:`CaptureWorker`（基于 :class:`threading.Thread`），
持续调用 ``vision.capture_numpy_packet(seq)`` 将最新 :class:`FramePacket`
缓存到最新帧缓冲区。供 :mod:`dobot_move.flow.flow_executor`（无 Qt 运行时）
和 :mod:`dobot_move.ui.camera_test_worker`（Qt GUI 适配器）复用。

刻意不导入任何 Qt 模块（``QThread`` / ``QImage`` / ``pyqtSignal`` /
``qt_compat``），以确保 headless Runtime 可在无 Qt 环境下执行相机步骤。
"""

import logging
import threading
import time
from typing import Optional

from .vision_system import FramePacket

logger = logging.getLogger(__name__)


class CaptureWorker(threading.Thread):
    """后台线程：持续采集帧到最新帧缓冲区。

    纯 Python 实现，不依赖 Qt。通过 ``vision.capture_numpy_packet(seq)``
    获取 :class:`FramePacket`，并在内部加锁更新最新帧。
    """

    def __init__(self, vision):
        super().__init__(daemon=True)
        self.vision = vision
        self.running = True
        self._lock = threading.Lock()
        self._latest_packet: Optional[FramePacket] = None
        self._seq = 0
        self._capture_ms = 0.0
        self._dropped = 0

    def run(self):
        while self.running:
            try:
                capture_start = time.perf_counter()
                packet = self.vision.capture_numpy_packet(self._seq)
                if packet is not None:
                    with self._lock:
                        if self._latest_packet is not None:
                            self._dropped += 1
                        self._latest_packet = packet
                        self._seq += 1
                    self._capture_ms = (time.perf_counter() - capture_start) * 1000.0
            except Exception:
                pass

    def get_latest(self):
        """返回 ``(FramePacket | None, capture_ms)``。"""
        with self._lock:
            if self._latest_packet is None:
                return None, 0.0
            return self._latest_packet, self._capture_ms

    def stop(self):
        self.running = False


# 向后兼容别名：旧代码可能使用 ``CaptureThread`` 名称。
CaptureThread = CaptureWorker
