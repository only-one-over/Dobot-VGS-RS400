import logging
import minimalmodbus
import time
import serial

logger = logging.getLogger(__name__)


class GripperController:
    REG_STOP = 16
    REG_RESTART = 17
    REG_SET_VEL = 20
    REG_SET_POS = 32
    REG_CUR_POS = 33

    def __init__(self, serial_port="COM6"):
        self._serial_port = serial_port
        self._baudrate = 9600
        self._slave_id = 1
        self._parity = minimalmodbus.serial.PARITY_EVEN
        self._bytesize = 8
        self._stopbits = 1
        self._instrument = None
        self._connect()

    def _check_port_availability(self):
        try:
            ser = serial.Serial(self._serial_port)
            ser.close()
            return True
        except serial.SerialException:
            return False

    def _connect(self):
        max_retries = 3
        retry_count = 0
        while retry_count < max_retries:
            if self._check_port_availability():
                try:
                    self._instrument = minimalmodbus.Instrument(self._serial_port, self._slave_id)
                    self._instrument.serial.baudrate = self._baudrate
                    self._instrument.serial.bytesize = self._bytesize
                    self._instrument.serial.parity = self._parity
                    self._instrument.serial.stopbits = self._stopbits
                    self._instrument.serial.timeout = 0.5
                    self._instrument.mode = minimalmodbus.MODE_RTU
                    self._instrument.clear_buffers_before_each_transaction = True
                    return
                except Exception:
                    retry_count += 1
                    time.sleep(1)
            else:
                self._instrument = None
                return
        self._instrument = None

    @property
    def is_connected(self):
        return self._instrument is not None

    def open(self):
        if not self.is_connected:
            return False
        try:
            self._instrument.write_register(self.REG_RESTART, 1, 0, functioncode=6)
            time.sleep(0.1)
            self._instrument.write_register(self.REG_SET_VEL, 3000, 0, functioncode=6)
            time.sleep(0.1)
            self._instrument.write_register(self.REG_SET_POS, 2000, 0, functioncode=6)
            return True
        except Exception:
            return False

    def close(self):
        if not self.is_connected:
            return False
        try:
            self._instrument.write_register(self.REG_SET_POS, 0, 0, functioncode=6)
            return True
        except Exception:
            return False

    def read_position(self):
        if not self.is_connected:
            return None
        try:
            pos = self._instrument.read_register(self.REG_CUR_POS, 0, functioncode=3, signed=True)
            return pos
        except Exception:
            return None
