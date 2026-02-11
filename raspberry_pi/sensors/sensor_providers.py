"""
Sensor Data Providers
=====================
Provides sensor data to the irrigation controller.

This module contains:
- SensorDataProvider: Abstract interface
- ArduinoSensorProvider: Single Arduino hardware interface
- MultiArduinoSensorProvider: Multiple Arduinos (one per zone)
- MockSensorProvider: For testing without hardware

Usage:
    from sensor_providers import MultiArduinoSensorProvider, MockSensorProvider

    # For production with 2 Arduinos (one per zone)
    provider = MultiArduinoSensorProvider(
        port_zone_map={"/dev/ttyACM0": "zone_1", "/dev/ttyACM1": "zone_2"}
    )

    # For production with single Arduino (multiple zones)
    provider = ArduinoSensorProvider(port="/dev/ttyACM0")

    # For testing
    provider = MockSensorProvider(zone_ids=["zone_1", "zone_2"])
"""

import json
import logging
import time
import random
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, List, Optional

try:
    import serial
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False


# =============================================================================
# ABSTRACT INTERFACE
# =============================================================================

class SensorDataProvider(ABC):
    """
    Abstract interface for sensor data providers.

    All sensor providers must implement get_sensor_readings().
    """

    @abstractmethod
    def get_sensor_readings(self) -> Dict[str, Dict[str, float]]:
        """
        Get current sensor readings for all zones.

        Returns:
            Dict mapping zone_id to readings:
            {
                "zone_1": {
                    "soil_moisture_percent": 45.0,
                    "temperature_c": 22.0,
                    "humidity_percent": 60.0,
                    "luminosity_lux": 12000.0
                },
                ...
            }
        """
        pass


# =============================================================================
# SINGLE ARDUINO SENSOR PROVIDER
# =============================================================================

class ArduinoSensorProvider(SensorDataProvider):
    """
    Reads sensor data from a single Arduino over serial connection.

    The Arduino should send JSON lines in this format:
        {"zone_1":{"moisture":45.0,"lux":12000},"temp":22.5,"humidity":60.0}

    This class converts that to the format expected by the decision engine.
    """

    def __init__(
        self,
        port: str = "/dev/ttyACM0",
        baud_rate: int = 9600,
        timeout: float = 5.0
    ):
        if not SERIAL_AVAILABLE:
            raise ImportError(
                "pyserial is required for Arduino communication. "
                "Install with: pip install pyserial"
            )

        self.port = port
        self.baud_rate = baud_rate
        self.timeout = timeout

        self._serial: Optional[serial.Serial] = None
        self._last_readings: Dict[str, Dict[str, float]] = {}
        self._logger = logging.getLogger(f'arduino[{port}]')

        self._connect()

    def _connect(self) -> bool:
        try:
            self._serial = serial.Serial(
                port=self.port,
                baudrate=self.baud_rate,
                timeout=self.timeout
            )
            self._serial.reset_input_buffer()
            self._logger.info(f"Connected to Arduino on {self.port}")
            time.sleep(2)
            return True
        except serial.SerialException as e:
            self._logger.error(f"Failed to connect to Arduino on {self.port}: {e}")
            self._serial = None
            return False

    def _read_latest(self) -> Optional[Dict]:
        if not self._serial or not self._serial.is_open:
            if not self._connect():
                return None
        try:
            latest_data = None
            while self._serial.in_waiting > 0:
                line = self._serial.readline().decode("utf-8").strip()
                if line:
                    try:
                        data = json.loads(line)
                        latest_data = data
                    except json.JSONDecodeError:
                        pass
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
        data = self._read_latest()
        if data:
            temp = data.get("temp", 20.0)
            humidity = data.get("humidity", 50.0)
            self._last_readings = {}
            for key, value in data.items():
                if key.startswith("zone_") and isinstance(value, dict):
                    reading = {
                        "soil_moisture_percent": value.get("moisture", 50.0),
                        "temperature_c": temp,
                        "humidity_percent": humidity,
                    }
                    # Include luminosity if present
                    if "lux" in value:
                        reading["luminosity_lux"] = value["lux"]
                    self._last_readings[key] = reading
            if self._last_readings:
                self._logger.debug(
                    f"Sensor readings: {len(self._last_readings)} zones, "
                    f"temp={temp:.1f}C, humidity={humidity:.1f}%"
                )
        return self._last_readings.copy() if self._last_readings else {}

    def close(self):
        if self._serial and self._serial.is_open:
            self._serial.close()
            self._logger.info(f"Arduino connection closed ({self.port})")


# =============================================================================
# MULTI-ARDUINO SENSOR PROVIDER (One Arduino Per Zone)
# =============================================================================

class MultiArduinoSensorProvider(SensorDataProvider):
    """
    Reads sensor data from multiple Arduinos, each handling one zone.

    Each Arduino sends JSON like:
        {"zone_1":{"moisture":45.0,"lux":12000},"temp":22.5,"humidity":60.0}

    This provider merges readings from all Arduinos into a single dict.

    Args:
        port_zone_map: Dict mapping serial port to the zone_id that Arduino handles.
                       e.g. {"/dev/ttyACM0": "zone_1", "/dev/ttyACM1": "zone_2"}
        baud_rate: Serial baud rate (must match all Arduinos).
        timeout: Serial read timeout per Arduino.
    """

    def __init__(
        self,
        port_zone_map: Dict[str, str],
        baud_rate: int = 9600,
        timeout: float = 5.0
    ):
        if not SERIAL_AVAILABLE:
            raise ImportError(
                "pyserial is required for Arduino communication. "
                "Install with: pip install pyserial"
            )

        self.port_zone_map = port_zone_map
        self._logger = logging.getLogger('multi_arduino')

        # Create one ArduinoSensorProvider per port
        self._providers: Dict[str, ArduinoSensorProvider] = {}
        for port, zone_id in port_zone_map.items():
            try:
                provider = ArduinoSensorProvider(
                    port=port, baud_rate=baud_rate, timeout=timeout
                )
                self._providers[zone_id] = provider
                self._logger.info(f"Arduino for {zone_id} connected on {port}")
            except Exception as e:
                self._logger.error(f"Failed to connect Arduino for {zone_id} on {port}: {e}")

        self._logger.info(
            f"Multi-Arduino provider initialized: "
            f"{len(self._providers)}/{len(port_zone_map)} connected"
        )

    def get_sensor_readings(self) -> Dict[str, Dict[str, float]]:
        """
        Read from all connected Arduinos and merge results.

        Returns:
            Dict mapping zone_id to sensor readings from all Arduinos.
        """
        merged = {}

        for zone_id, provider in self._providers.items():
            try:
                readings = provider.get_sensor_readings()
                # Each single-zone Arduino returns {"zone_X": {...}}
                # We take whatever zone data it provides
                if readings:
                    merged.update(readings)
                else:
                    self._logger.warning(f"No data from Arduino for {zone_id}")
            except Exception as e:
                self._logger.error(f"Error reading Arduino for {zone_id}: {e}")

        return merged

    def close(self):
        """Close all Arduino connections."""
        for zone_id, provider in self._providers.items():
            provider.close()
        self._logger.info("All Arduino connections closed")


# =============================================================================
# MOCK SENSOR PROVIDER (For Testing)
# =============================================================================

class MockSensorProvider(SensorDataProvider):
    """
    Mock sensor provider for testing without Arduino hardware.

    Simulates realistic sensor behavior:
    - Moisture decays over time (evaporation)
    - Temperature/humidity have slight variations
    - Luminosity varies by simulated time of day
    - Irrigation increases moisture
    """

    def __init__(
        self,
        zone_ids: list,
        initial_moisture: float = 40.0,
        decay_rate_per_hour: float = 2.0
    ):
        self.zone_ids = zone_ids
        self.decay_rate = decay_rate_per_hour
        self._moisture_levels = {z: initial_moisture for z in zone_ids}
        self._last_update = datetime.now()
        self._logger = logging.getLogger('mock_sensors')
        self._logger.info(f"Mock sensor provider initialized for {len(zone_ids)} zones")

    def get_sensor_readings(self) -> Dict[str, Dict[str, float]]:
        now = datetime.now()
        hours_elapsed = (now - self._last_update).total_seconds() / 3600

        # Simulate luminosity based on time of day
        hour = now.hour
        if 6 <= hour < 8:
            base_lux = random.uniform(5000, 15000)
        elif 8 <= hour < 17:
            base_lux = random.uniform(20000, 60000)
        elif 17 <= hour < 20:
            base_lux = random.uniform(2000, 10000)
        else:
            base_lux = random.uniform(0, 50)

        readings = {}
        for zone_id in self.zone_ids:
            current_moisture = self._moisture_levels[zone_id]
            new_moisture = max(10, current_moisture - (hours_elapsed * self.decay_rate))
            self._moisture_levels[zone_id] = new_moisture
            readings[zone_id] = {
                'soil_moisture_percent': new_moisture + random.uniform(-1, 1),
                'temperature_c': 22.0 + random.uniform(-2, 5),
                'humidity_percent': 55.0 + random.uniform(-5, 10),
                'luminosity_lux': round(base_lux + random.uniform(-1000, 1000), 1),
            }
        self._last_update = now
        return readings

    def simulate_irrigation(self, zone_id: str, liters: float, area_m2: float = 1.0):
        if zone_id in self._moisture_levels:
            moisture_increase = (liters / area_m2) * 2
            self._moisture_levels[zone_id] = min(
                90, self._moisture_levels[zone_id] + moisture_increase
            )
            self._logger.debug(f"Zone {zone_id} irrigated: +{moisture_increase:.1f}% moisture")

    def set_moisture(self, zone_id: str, moisture: float):
        if zone_id in self._moisture_levels:
            self._moisture_levels[zone_id] = max(0, min(100, moisture))


# =============================================================================
# TESTING
# =============================================================================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    print("Sensor Providers Test")
    print("=" * 50)

    print("\n--- Mock Sensor Provider (with luminosity) ---")
    mock = MockSensorProvider(
        zone_ids=["zone_1", "zone_2"],
        initial_moisture=45.0
    )

    readings = mock.get_sensor_readings()
    for zone_id, data in readings.items():
        print(
            f"  {zone_id}: "
            f"moisture={data['soil_moisture_percent']:.1f}% | "
            f"temp={data['temperature_c']:.1f}C | "
            f"humidity={data['humidity_percent']:.1f}% | "
            f"lux={data['luminosity_lux']:.0f}"
        )

    print("\n--- After Irrigation (zone_1: 10L) ---")
    mock.simulate_irrigation("zone_1", 10.0)
    readings = mock.get_sensor_readings()
    for zone_id, data in readings.items():
        print(f"  {zone_id}: {data['soil_moisture_percent']:.1f}% moisture")

    print("\n✓ Mock provider working correctly")

    print("\n--- Multi-Arduino Provider ---")
    print("  (Skipped - requires hardware)")
    print("  Usage: MultiArduinoSensorProvider({")
    print('    "/dev/ttyACM0": "zone_1",')
    print('    "/dev/ttyACM1": "zone_2"')
    print("  })")
