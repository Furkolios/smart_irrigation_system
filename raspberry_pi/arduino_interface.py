"""
Arduino Serial Interface
=========================
Reads sensor data from Arduino over serial and provides it to the main controller.

This module implements the SensorDataProvider interface expected by main_controller.py.
Supports multiple zones from a single Arduino.

Usage:
    from arduino_interface import ArduinoSensorProvider

    provider = ArduinoSensorProvider(port="/dev/ttyACM0")
    readings = provider.get_sensor_readings()
    tank_level = provider.get_tank_level()
"""

import json
import logging
import serial
import time
from typing import Dict, List, Optional


class ArduinoSensorProvider:
    """
    Reads sensor data from Arduino and provides it in the format expected by main_controller.

    The Arduino sends JSON lines like:
        {"zone_1":{"moisture":45.0},"zone_2":{"moisture":52.0},"temp":22.5,"humidity":60.0,"tank_cm":15.0}

    This class converts that to the format expected by the decision engine:
        {
            "zone_1": {"soil_moisture_percent": 45.0, "temperature_c": 22.5, "humidity_percent": 60.0},
            "zone_2": {"soil_moisture_percent": 52.0, "temperature_c": 22.5, "humidity_percent": 60.0}
        }
    """

    def __init__(
        self,
        port: str = "/dev/ttyACM0",
        baud_rate: int = 9600,
        tank_height_cm: float = 50.0,
        tank_capacity_liters: float = 100.0,
        timeout: float = 5.0
    ):
        """
        Initialize Arduino connection.

        Args:
            port: Serial port (e.g., "/dev/ttyACM0" on Linux, "COM3" on Windows)
            baud_rate: Serial baud rate (must match Arduino)
            tank_height_cm: Height of tank in cm (for level calculation)
            tank_capacity_liters: Tank capacity in liters
            timeout: Serial read timeout in seconds
        """
        self.port = port
        self.baud_rate = baud_rate
        self.tank_height_cm = tank_height_cm
        self.tank_capacity_liters = tank_capacity_liters
        self.timeout = timeout

        self._serial: Optional[serial.Serial] = None
        self._last_readings: Dict[str, Dict[str, float]] = {}
        self._last_tank_cm: float = -1
        self._logger = logging.getLogger("arduino")

        self._connect()

    def _connect(self) -> bool:
        """Establish serial connection to Arduino."""
        try:
            self._serial = serial.Serial(
                port=self.port,
                baudrate=self.baud_rate,
                timeout=self.timeout
            )
            # Clear any buffered data
            self._serial.reset_input_buffer()
            self._logger.info(f"Connected to Arduino on {self.port}")

            # Wait for Arduino to reset after connection
            time.sleep(2)
            return True

        except serial.SerialException as e:
            self._logger.error(f"Failed to connect to Arduino: {e}")
            self._serial = None
            return False

    def _read_latest(self) -> Optional[Dict]:
        """
        Read the latest complete JSON line from Arduino.

        Returns the most recent valid reading, discarding older buffered data.
        """
        if not self._serial or not self._serial.is_open:
            if not self._connect():
                return None

        try:
            # Read all available lines, keep only the last valid one
            latest_data = None

            while self._serial.in_waiting > 0:
                line = self._serial.readline().decode("utf-8").strip()
                if line:
                    try:
                        data = json.loads(line)
                        latest_data = data
                    except json.JSONDecodeError:
                        pass

            # If no data in buffer, wait for one reading
            if latest_data is None:
                line = self._serial.readline().decode("utf-8").strip()
                if line:
                    try:
                        latest_data = json.loads(line)
                    except json.JSONDecodeError:
                        self._logger.warning(f"Invalid JSON from Arduino: {line}")

            return latest_data

        except serial.SerialException as e:
            self._logger.error(f"Serial read error: {e}")
            self._serial = None
            return None

    def get_sensor_readings(self) -> Dict[str, Dict[str, float]]:
        """
        Get current sensor readings for all zones.

        Returns:
            Dict mapping zone_id to readings:
            {
                "zone_1": {
                    "soil_moisture_percent": 45.0,
                    "temperature_c": 22.5,
                    "humidity_percent": 60.0
                },
                "zone_2": {
                    "soil_moisture_percent": 52.0,
                    "temperature_c": 22.5,
                    "humidity_percent": 60.0
                }
            }
        """
        data = self._read_latest()

        if data:
            # Extract shared temp/humidity
            temp = data.get("temp", 20.0)
            humidity = data.get("humidity", 50.0)

            # Store tank reading if present
            if "tank_cm" in data:
                self._last_tank_cm = data["tank_cm"]

            # Build readings for each zone
            self._last_readings = {}
            for key, value in data.items():
                # Zone data comes as {"zone_1": {"moisture": X}, ...}
                if key.startswith("zone_") and isinstance(value, dict):
                    self._last_readings[key] = {
                        "soil_moisture_percent": value.get("moisture", 50.0),
                        "temperature_c": temp,
                        "humidity_percent": humidity
                    }

            if self._last_readings:
                self._logger.debug(
                    f"Sensor readings: {len(self._last_readings)} zones, "
                    f"temp={temp:.1f}C, humidity={humidity:.1f}%"
                )

        return self._last_readings.copy() if self._last_readings else {}

    def get_tank_level(self) -> float:
        """
        Get current tank water level in liters.

        Converts distance measurement (cm from top) to water volume.
        If no tank sensor, returns a default value.
        """
        # Try to get fresh reading if we don't have tank data
        if self._last_tank_cm < 0:
            self._read_latest()

        # If still no tank sensor data, return default
        if self._last_tank_cm < 0:
            self._logger.debug("No tank sensor - returning default level")
            return self.tank_capacity_liters * 0.8  # Default 80% full

        # Convert distance from top to water level
        water_height_cm = self.tank_height_cm - self._last_tank_cm
        water_height_cm = max(0, min(water_height_cm, self.tank_height_cm))

        # Convert to liters (assuming cylindrical/rectangular tank)
        level_ratio = water_height_cm / self.tank_height_cm
        level_liters = level_ratio * self.tank_capacity_liters

        self._logger.debug(f"Tank level: {level_liters:.1f}L ({level_ratio*100:.0f}%)")

        return level_liters

    def close(self):
        """Close serial connection."""
        if self._serial and self._serial.is_open:
            self._serial.close()
            self._logger.info("Arduino connection closed")


# For testing without hardware
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    print("Arduino Interface Test (Multi-Zone)")
    print("=" * 50)

    provider = ArduinoSensorProvider(
        port="/dev/ttyACM0"  # Adjust for your system
    )

    print("\nReading sensor data (Ctrl+C to stop)...\n")

    try:
        while True:
            readings = provider.get_sensor_readings()
            tank = provider.get_tank_level()

            if readings:
                print(f"Tank: {tank:.1f}L")
                for zone_id, data in sorted(readings.items()):
                    print(
                        f"  [{zone_id}] "
                        f"Moisture: {data['soil_moisture_percent']:5.1f}% | "
                        f"Temp: {data['temperature_c']:5.1f}C | "
                        f"Humidity: {data['humidity_percent']:5.1f}%"
                    )
                print()
            else:
                print("No data received")

            time.sleep(2)

    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        provider.close()
