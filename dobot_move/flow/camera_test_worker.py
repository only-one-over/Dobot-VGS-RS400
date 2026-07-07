#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GUI-only camera test workers.

This module intentionally keeps Qt dependencies (``QThread``, ``QImage``,
``pyqtSignal``) because the live preview image is rendered through Qt's
image pipeline. It must only be imported from GUI code paths; the headless
runtime and ``flow_executor`` should never import this module directly.
"""

import logging
import threading
import time
from typing import Optional

import numpy as np

from ..ui.qt_compat import QImage, QThread, pyqtSignal
from ..vision.vision_system import FramePacket

try:
    import cv2
except ImportError:
    cv2 = None

logger = logging.getLogger(__name__)


class CaptureThread(threading.Thread):
    """Background thread that continuously captures frames into a latest-frame buffer."""

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
        with self._lock:
            if self._latest_packet is None:
                return None, 0.0
            return self._latest_packet, self._capture_ms

    def stop(self):
        self.running = False


class CameraTestWorker(QThread):
    result_ready = pyqtSignal(dict)

    def __init__(self, vision, cam_type, controller):
        super().__init__()
        self.vision = vision
        self.cam_type = cam_type
        self.controller = controller
        self.running = True
        perf_config = getattr(self.vision, "performance_config", {})
        detection_fps = max(1.0, float(perf_config.get("camera_test_detection_fps", 10)))
        display_fps = max(1.0, float(perf_config.get("camera_test_display_fps", 10)))
        self.detection_interval = 1.0 / detection_fps
        self.display_interval = 1.0 / display_fps
        self.frame_interval = min(self.detection_interval, self.display_interval)
        self.performance_log_interval_frames = max(1, int(perf_config.get("performance_log_interval_frames", 30)))
        self.last_target = None
        self.last_object_position = None
        self._perf_count = 0
        self._perf_totals = {}
        self._last_perf_log = 0.0
        self._capture_thread = None
        self._frame_count = 0
        self._last_processed_seq = -1
        self._detect_every_n_frames = max(1, int(round(self.detection_interval / max(0.001, self.frame_interval))))
        self._snapshot_lock = threading.Lock()
        self._last_detection_snapshot = None
        self._flow_mode_lock = threading.Lock()
        self._flow_active = False
        self._flow_detection_enabled = False

    def _record_performance(self, timings):
        self._perf_count += 1
        for key, value in timings.items():
            self._perf_totals[key] = self._perf_totals.get(key, 0.0) + value

        now = time.perf_counter()
        if self._perf_count % self.performance_log_interval_frames != 0 or now - self._last_perf_log < 3.0:
            return

        count = max(1, self._perf_count)
        parts = [
            f"{key}={total / count:.1f}ms" if key not in ('fps', 'dropped') else f"{key}={total / count:.1f}"
            for key, total in sorted(self._perf_totals.items())
        ]
        logger.info("performance[camera_test_worker] frames=%s %s", self._perf_count, " ".join(parts))
        self._perf_count = 0
        self._perf_totals = {}
        self._last_perf_log = now

    def run(self):
        self.vision.reset_tracking()
        self._capture_thread = CaptureThread(self.vision)
        self._capture_thread.start()

        while self.running:
            try:
                packet, capture_ms = self._capture_thread.get_latest()
                if packet is None or packet.seq == self._last_processed_seq:
                    self.msleep(5)
                    continue

                self._last_processed_seq = packet.seq
                self._frame_count += 1
                loop_start = time.perf_counter()

                with self._flow_mode_lock:
                    flow_active = self._flow_active
                    flow_detection_enabled = self._flow_detection_enabled

                detection_allowed = (not flow_active) or flow_detection_enabled

                # Detection (frame count based)
                should_detect = detection_allowed and (self._frame_count % self._detect_every_n_frames) == 0
                should_display = True  # display every processed frame

                detection_start = time.perf_counter()
                if should_detect:
                    target = self.vision.run_detection_tracked(packet.color_image)
                    self.last_target = target
                    # Use numpy depth_image directly (calculate_object_position now accepts numpy)
                    self.last_object_position = self.vision.calculate_object_position_smoothed(
                        packet.depth_image, packet.color_image, target
                    )
                    confidence = 0.0
                    if self.last_object_position:
                        confidence = float(self.last_object_position.get('confidence', 0.0) or 0.0)
                    elif target:
                        confidence = float(target.get('score', target.get('confidence', 0.0)) or 0.0)
                    with self._snapshot_lock:
                        self._last_detection_snapshot = {
                            'seq': packet.seq,
                            'timestamp': packet.timestamp,
                            'target': target,
                            'object_position': self.last_object_position,
                            'confidence': confidence,
                            'capture_ms': capture_ms,
                        }
                else:
                    target = self.last_target if detection_allowed else None
                detection_done = time.perf_counter()

                object_position = self.last_object_position if detection_allowed else None

                # Draw
                draw_start = time.perf_counter()
                q_img = None
                if should_display:
                    display_image = packet.color_image.copy()
                    if target and not target.get('predicted', False):
                        bbox = target.get('bbox')
                        if bbox:
                            x1, y1, x2, y2 = bbox
                            cv2.rectangle(display_image, (x1, y1), (x2, y2), (0, 255, 0), 2)
                        mask = target.get('mask')
                        if mask is not None and np.any(mask > 0):
                            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                            cv2.drawContours(display_image, contours, -1, (0, 255, 0), 2)

                    rgb_image = cv2.cvtColor(display_image, cv2.COLOR_BGR2RGB)
                    h, w, ch = rgb_image.shape
                    bytes_per_line = ch * w
                    q_img = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format.Format_RGB888).copy()
                draw_done = time.perf_counter()

                # Build result
                result = {
                    'status': 'ok',
                    'object_position': object_position,
                    'cam_type': self.cam_type,
                }
                if q_img is not None:
                    result['q_image'] = q_img

                if object_position:
                    cam_coords = object_position.get('camera_coords', [])
                    result['cam_coords'] = cam_coords
                    result['confidence'] = object_position.get('confidence', 0.0)
                    result['source'] = object_position.get('source', 'unknown')

                    if self.controller.is_connected and len(cam_coords) >= 3:
                        end_coords = self.vision.convert_to_end_coords(cam_coords)
                        result['end_coords'] = end_coords
                        current_pose = self.controller.get_current_pose_fast()
                        if current_pose:
                            base_coords = self.vision.convert_to_base_coords(end_coords, current_pose)
                            result['base_coords'] = base_coords

                self.result_ready.emit(result)
                emit_done = time.perf_counter()

                # Performance logging
                dropped = self._capture_thread._dropped
                timings = {
                    "capture_thread": capture_ms,
                    "detection_loop": (detection_done - detection_start) * 1000.0 if should_detect else 0.0,
                    "draw_emit": (emit_done - draw_start) * 1000.0,
                    "total": (emit_done - loop_start) * 1000.0,
                    "fps": 1000.0 / max(0.1, (emit_done - loop_start) * 1000.0),
                    "dropped": float(dropped),
                }
                self._record_performance(timings)

            except Exception as e:
                self.result_ready.emit({'status': 'error', 'error_msg': str(e)[:100]})

        self._capture_thread.stop()
        self._capture_thread.join(timeout=3.0)

    def stop(self):
        self.running = False
        if self._capture_thread:
            self._capture_thread.stop()
            self._capture_thread.join(timeout=3.0)

    def set_flow_active(self, active):
        with self._flow_mode_lock:
            self._flow_active = bool(active)
            self._flow_detection_enabled = False
        if active:
            self.last_target = None
            self.last_object_position = None
            with self._snapshot_lock:
                self._last_detection_snapshot = None

    def set_flow_detection_enabled(self, enabled):
        with self._flow_mode_lock:
            self._flow_detection_enabled = bool(enabled) and self._flow_active
        if enabled:
            self.last_target = None
            self.last_object_position = None
            with self._snapshot_lock:
                self._last_detection_snapshot = None

    def get_flow_detection_snapshot(self):
        with self._snapshot_lock:
            if self._last_detection_snapshot is None:
                return None
            return dict(self._last_detection_snapshot)
