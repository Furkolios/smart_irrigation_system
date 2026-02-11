import json
import logging
import time
import glob
from typing import Dict
from threading import Thread
from datetime import datetime

# Try importing serial, but don't fail if not present (handled gracefully)
try:
    import serial

    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False

from ..config.models import ArduinoConfig


class ArduinoManager:
    """
    Manages connection and data retrieval from Arduino devices.
    Supports auto-detection and structured JSON protocol.
    """

    def __init__(self, config: ArduinoConfig):
        self.config = config
        self.logger = logging.getLogger("arduino_manager")
        self._devices: Dict[str, serial.Serial] = {}  # device_path -> Serial
        self._device_ids: Dict[
            str, str
        ] = {}  # device_path -> device_id (from handshake/data)
        self._last_readings: Dict[str, dict] = {}  # device_id -> reading dict
        self._running = False
        self._monitor_thread = None

        if not SERIAL_AVAILABLE:
            self.logger.warning(
                "pyserial not available. Arduino functionality disabled."
            )

    def start(self):
        """Start the background monitoring/reading thread."""
        if not SERIAL_AVAILABLE:
            return

        self._running = True
        self._monitor_thread = Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()
        self.logger.info("Arduino Manager started")

    def stop(self):
        """Stop the background thread and close connections."""
        self._running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=2.0)

        for port in list(self._devices.keys()):
            self._close_device(port)

    def _monitor_loop(self):
        """Main loop: Detect devices -> Read Data -> Handle Disconnects."""
        last_scan_time = 0
        scan_interval = 5.0  # Scan for new devices every 5 seconds

        while self._running:
            now = time.time()

            # 1. Scan for devices periodically
            if now - last_scan_time > scan_interval:
                self._scan_devices()
                last_scan_time = now

            # 2. Read from connected devices
            self._read_all_devices()

            # small sleep to prevent CPU hogging
            time.sleep(0.1)

    def _scan_devices(self):
        """Scan /dev/tty* for new compatible devices."""
        # Common patterns for Arduino on Linux/Mac
        patterns = ["/dev/ttyACM*", "/dev/ttyUSB*", "/dev/cu.usbmodem*"]
        found_ports = []
        for p in patterns:
            found_ports.extend(glob.glob(p))

        # Filter out already connected
        new_ports = [p for p in found_ports if p not in self._devices]

        for port in new_ports:
            try:
                self.logger.info(f"Attempting connection to {port}")
                ser = serial.Serial(
                    port, self.config.baud_rate, timeout=self.config.timeout
                )
                # Allow reset time
                time.sleep(2.0)

                # Check cleanliness (flush junk)
                ser.reset_input_buffer()

                self._devices[port] = ser
                self.logger.info(f"Connected to {port}")

            except serial.SerialException as e:
                self.logger.warning(f"Could not connect to {port}: {e}")
            except Exception as e:
                self.logger.error(f"Error connecting to {port}: {e}")

    def _close_device(self, port: str):
        if port in self._devices:
            try:
                self._devices[port].close()
            except Exception:
                pass
            del self._devices[port]
            # Also remove ID mapping if exists
            id_to_remove = None
            for device_id, p in self._device_ids.items():
                if p == port:
                    id_to_remove = device_id
                    break
            if id_to_remove:
                del self._device_ids[id_to_remove]

            self.logger.info(f"Disconnected {port}")

    def _read_all_devices(self):
        """Read lines from all connected serial ports."""
        for port in list(self._devices.keys()):
            ser = self._devices[port]
            try:
                if ser.in_waiting:
                    line = ser.readline().decode("utf-8", errors="ignore").strip()
                    if line:
                        self._process_data(port, line)
            except OSError:
                self.logger.error(f"Device at {port} disconnected unexpectedly.")
                self._close_device(port)
            except Exception as e:
                self.logger.error(f"Read error on {port}: {e}")

    def _process_data(self, port: str, raw_line: str):
        """Parse JSON data from device."""
        try:
            data = json.loads(raw_line)

            # Validation: Check required fields
            # Required: device_id, timestamp
            if "device_id" not in data:
                # self.logger.debug(f"Ignored data without device_id: {raw_line}")
                return

            device_id = data["device_id"]

            # Map port to device_id if not already done
            if device_id not in self._device_ids or self._device_ids[device_id] != port:
                self._device_ids[device_id] = port
                self.logger.info(f"Registered device {device_id} on {port}")

            # Store validated reading with system timestamp reception time as well
            data["_received_at"] = datetime.now()
            self._last_readings[device_id] = data

        except json.JSONDecodeError:
            # self.logger.debug(f"Invalid JSON: {raw_line}")
            pass

    def get_readings(self) -> Dict[str, dict]:
        """Return the latest readings from all connected devices."""
        return self._last_readings.copy()

    def get_connected_count(self) -> int:
        return len(self._devices)
