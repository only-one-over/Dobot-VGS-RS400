import warnings
import logging

logger = logging.getLogger(__name__)

warnings.filterwarnings("ignore", message=".*socket.CMSG_SPACE.*")
warnings.filterwarnings("ignore", message=".*uptime.*")
logging.getLogger("can").setLevel(logging.ERROR)

import can


def temp_convert(val):
    return round((val - 2731) / 10.0, 1)


class BatteryMonitor:
    def __init__(self, channel="can0", interface="socketcan"):
        self._channel = channel
        self._interface = interface
        self._bitrate = 500000
        self._bus = None
        self._voltage = 0.0
        self._current = 0.0
        self._soc = 0
        self._temp_max = 0.0
        self._temp_min = 0.0
        self._status = "正常"

    @property
    def is_connected(self):
        return self._bus is not None

    def connect(self):
        try:
            self._bus = can.interface.Bus(
                channel=self._channel,
                bustype=self._interface,
                bitrate=self._bitrate,
            )
        except Exception:
            try:
                self._bus = can.interface.Bus(
                    channel="PCAN_USBBUS1",
                    bustype="pcan",
                    bitrate=self._bitrate,
                )
            except Exception:
                self._bus = None

    def disconnect(self):
        if self._bus is not None:
            try:
                self._bus.shutdown()
            except Exception:
                pass
            self._bus = None

    def read_data(self):
        if self._bus is None:
            return
        try:
            msg = self._bus.recv(timeout=0.2)
            if msg is None:
                return
            can_id = msg.arbitration_id
            data = msg.data
            if can_id == 0x200:
                self._voltage = (data[0] << 8 | data[1]) * 0.01
                self._current = (data[2] << 8 | data[3]) * 0.01
            elif can_id == 0x201:
                self._soc = data[6] << 8 | data[7]
            elif can_id == 0x202:
                flag = data[0] << 8 | data[1]
                self._temp_max = temp_convert(data[4] << 8 | data[5])
                self._temp_min = temp_convert(data[6] << 8 | data[7])
                if flag == 0:
                    self._status = "正常"
                else:
                    self._status = "保护触发"
        except Exception:
            pass

    def get_data(self):
        return {
            "voltage": self._voltage,
            "current": self._current,
            "soc": self._soc,
            "temp_max": self._temp_max,
            "temp_min": self._temp_min,
            "status": self._status,
        }
