import json
import random
from typing import Dict


class MockSerial:
    """Mocks the behavior of serial.Serial for Arduino communication."""

    def __init__(self, port, baudrate, timeout):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.is_open = True
        self.in_waiting = 0
        self._next_data = None

    def reset_input_buffer(self):
        pass

    def readline(self):
        if self._next_data:
            data = self._next_data
            self._next_data = None
            self.in_waiting = 0
            return (json.dumps(data) + "\n").encode("utf-8")
        return b""

    def write(self, data):
        pass

    def close(self):
        self.is_open = False

    def set_next_data(self, data: Dict):
        self._next_data = data
        self.in_waiting = 1


def get_sample_sensor_data(zone_id="zone_1"):
    """Returns a realistic sensor data dictionary for testing."""
    return {zone_id: {"moisture": 45.0, "lux": 15000}, "temp": 22.5, "humidity": 60.0}
