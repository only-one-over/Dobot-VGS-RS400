import json
import logging
import os
import threading
from datetime import datetime

logger = logging.getLogger(__name__)


class AlarmHistory:
    def __init__(self, path=None, max_records=1000):
        if path is None:
            from ..config.config_manager import ALARM_HISTORY_FILE
            path = ALARM_HISTORY_FILE
        self.path = path
        self.max_records = max_records
        self._lock = threading.Lock()

    def list_records(self):
        with self._lock:
            return self._read_unlocked()

    def add(self, source, code="", level="报警", description="", solution="", raw=""):
        record = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": str(source),
            "code": str(code),
            "level": str(level),
            "description": str(description),
            "solution": str(solution),
            "raw": str(raw),
        }
        with self._lock:
            records = self._read_unlocked()
            records.append(record)
            if len(records) > self.max_records:
                records = records[-self.max_records:]
            self._write_unlocked(records)
        return record

    def clear(self):
        with self._lock:
            self._write_unlocked([])

    def _read_unlocked(self):
        if not os.path.exists(self.path):
            return []
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception as e:
            corrupt_path = (
                self.path
                + ".corrupt."
                + datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            )
            try:
                os.replace(self.path, corrupt_path)
                logger.error(
                    "报警历史损坏，已保留到 %s: %s",
                    corrupt_path,
                    e,
                )
            except OSError:
                logger.exception("报警历史损坏且无法保留: %s", self.path)
            return []

    def _write_unlocked(self, records):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp_path = self.path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, self.path)
