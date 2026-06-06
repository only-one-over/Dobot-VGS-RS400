import json
import os
import threading
from datetime import datetime


class AlarmHistory:
    def __init__(self, path=None, max_records=1000):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.path = path or os.path.join(base_dir, "alarm_history.json")
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
        except Exception:
            return []

    def _write_unlocked(self, records):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp_path = self.path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, self.path)
