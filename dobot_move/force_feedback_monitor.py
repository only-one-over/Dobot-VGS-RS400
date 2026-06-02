import logging
import threading
import time
import re

logger = logging.getLogger(__name__)


class ForceFeedbackMonitor:
    def __init__(self, dashboard, force_thresholds=None, monitor_freq=10):
        self.dashboard = dashboard
        self.force_thresholds = force_thresholds or {
            'fx': 2.0, 'fy': 2.0, 'fz': 2.0,
            'frx': 0.5, 'fry': 0.5, 'frz': 0.5
        }
        self.monitor_freq = monitor_freq
        self._current_force = {'fx': 0.0, 'fy': 0.0, 'fz': 0.0, 'frx': 0.0, 'fry': 0.0, 'frz': 0.0}
        self._lock = threading.Lock()
        self._stop_flag = threading.Event()
        self._thread = None

    def start(self):
        self._stop_flag.clear()
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_flag.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def _monitor_loop(self):
        keys = ['fx', 'fy', 'fz', 'frx', 'fry', 'frz']
        while not self._stop_flag.is_set():
            try:
                result = self.dashboard.GetForce()
                match = re.search(r'\{([^}]+)\}', result)
                if match:
                    values = match.group(1).split(',')
                    values = [v.strip() for v in values]
                    force = {}
                    for i, key in enumerate(keys):
                        if i < len(values):
                            force[key] = float(values[i])
                    with self._lock:
                        self._current_force.update(force)
            except Exception:
                pass
            time.sleep(1.0 / self.monitor_freq)

    def get_current_force(self):
        with self._lock:
            return dict(self._current_force)

    def get_force_deviation(self, target_force):
        current = self.get_current_force()
        deviation = {}
        for key in ['fx', 'fy', 'fz', 'frx', 'fry', 'frz']:
            diff = current.get(key, 0.0) - target_force.get(key, 0.0)
            threshold = self.force_thresholds.get(key, 0.0)
            if abs(diff) > threshold:
                deviation[key] = diff
            else:
                deviation[key] = 0.0
        return deviation

    def get_correction(self, target_force, gain=0.5):
        deviation = self.get_force_deviation(target_force)
        correction = {}
        for key in ['fx', 'fy', 'fz', 'frx', 'fry', 'frz']:
            raw = -gain * deviation[key]
            if key in ('fx', 'fy', 'fz'):
                raw = max(-200.0, min(200.0, raw))
            else:
                raw = max(-12.0, min(12.0, raw))
            correction[key] = raw
        return correction

    def is_running(self):
        return self._thread is not None and self._thread.is_alive()
