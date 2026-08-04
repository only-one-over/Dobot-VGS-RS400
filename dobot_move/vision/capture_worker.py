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
import queue
import threading
import time
from typing import Optional

from .vision_system import FramePacket

logger = logging.getLogger(__name__)


class CaptureWorker(threading.Thread):
    """后台线程：持续采集帧到最新帧缓冲区。

    纯 Python 实现，不依赖 Qt。通过 ``vision.capture_numpy_packet(seq)``
    获取 :class:`FramePacket`，并在内部加锁更新最新帧。

    可选 ``frame_queue``：若传入，每采集到一帧便把 ``(packet, capture_ms)``
    推入该队列（满了丢最旧），用于流水线化（采集/推理解耦）。不传入时行为
    与历史版本完全一致（仅更新最新帧缓冲区）。
    """

    def __init__(self, vision, frame_queue=None):
        super().__init__(daemon=True)
        self.vision = vision
        self.running = True
        self._lock = threading.Lock()
        self._latest_packet: Optional[FramePacket] = None
        self._seq = 0
        self._capture_ms = 0.0
        self._dropped = 0
        # 流水线帧输出队列（可选）。maxsize 由调用方决定（通常为 2）。
        self._frame_queue = frame_queue

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
                    capture_ms = (time.perf_counter() - capture_start) * 1000.0
                    self._capture_ms = capture_ms
                    # 若配置了帧队列，把新帧推入（满了丢最旧，保证队列里始终是最新帧）
                    if self._frame_queue is not None:
                        try:
                            self._frame_queue.put_nowait((packet, capture_ms))
                        except queue.Full:
                            try:
                                self._frame_queue.get_nowait()
                            except queue.Empty:
                                pass
                            try:
                                self._frame_queue.put_nowait((packet, capture_ms))
                            except queue.Full:
                                pass
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
