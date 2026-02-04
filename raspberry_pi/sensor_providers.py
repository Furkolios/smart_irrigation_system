"""
Sensor Data Providers
=====================
Provides sensor data to the irrigation controller.

This module contains:
- SensorDataProvider: Abstract interface
- ArduinoSensorProvider: Real hardware interface
- MockSensorProvider: For testing without hardware

Usage:
    from sensor_providers import ArduinoSensorProvider, MockSensorProvider
    
    # For production
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
from typing import Dict, Optional

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
                    "humidity_percent": 60.0
                },
                ...
            }
        """
        pass


# =============================================================================
# ARDUINO SENSOR PROVIDER (Real Hardware)
# =============================================================================

class ArduinoSensorProvider(SensorDataProvider):
    """
    Reads sensor data from Arduino over serial connection.
    
    The Arduino should send JSON lines in this format:
        {"zone_1":{"moisture":45.0},"zone_2":{"moisture":52.0},"temp":22.5,"humidity":60.0}
    
    This class converts that to the format expected by the decision engine.
    """
    
    def __init__(
        self,
        port: str = "/dev/ttyACM0",
        baud_rate: int = 9600,
        timeout: float = 5.0
    ):
        """
        Initialize Arduino connection.
        
        Args:
            port: Serial port (e.g., "/dev/ttyACM0" on Linux, "COM3" on Windows)
            baud_rate: Serial baud rate (must match Arduino sketch)
            timeout: Serial read timeout in seconds
        """
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
        self._logger = logging.getLogger('arduino')
        
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
            Dict mapping zone_id to readings
        """
        data = self._read_latest()
        
        if data:
            # Extract shared temp/humidity
            temp = data.get("temp", 20.0)
            humidity = data.get("humidity", 50.0)
            
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
    
    def close(self):
        """Close serial connection."""
        if self._serial and self._serial.is_open:
            self._serial.close()
            self._logger.info("Arduino connection closed")


# =============================================================================
# MOCK SENSOR PROVIDER (For Testing)
# =============================================================================

class MockSensorProvider(SensorDataProvider):
    """
    Mock sensor provider for testing without Arduino hardware.
    
    Simulates realistic sensor behavior:
    - Moisture decays over time (evaporation)
    - Temperature/humidity have slight variations
    - Irrigation increases moisture
    """
    
    def __init__(
        self,
        zone_ids: list,
        initial_moisture: float = 40.0,
        decay_rate_per_hour: float = 2.0
    ):
        """
        Initialize mock sensors.
        
        Args:
            zone_ids: List of zone IDs to simulate (e.g., ["zone_1", "zone_2"])
            initial_moisture: Starting moisture percentage for all zones
            decay_rate_per_hour: How fast moisture decreases (% per hour)
        """
        self.zone_ids = zone_ids
        self.decay_rate = decay_rate_per_hour
        
        self._moisture_levels = {z: initial_moisture for z in zone_ids}
        self._last_update = datetime.now()
        self._logger = logging.getLogger('mock_sensors')
        
        self._logger.info(f"Mock sensor provider initialized for {len(zone_ids)} zones")
    
    def get_sensor_readings(self) -> Dict[str, Dict[str, float]]:
        """Get simulated sensor readings."""
        now = datetime.now()
        hours_elapsed = (now - self._last_update).total_seconds() / 3600
        
        readings = {}
        for zone_id in self.zone_ids:
            # Apply moisture decay
            current_moisture = self._moisture_levels[zone_id]
            new_moisture = max(10, current_moisture - (hours_elapsed * self.decay_rate))
            self._moisture_levels[zone_id] = new_moisture
            
            # Add slight random variation
            readings[zone_id] = {
                'soil_moisture_percent': new_moisture + random.uniform(-1, 1),
                'temperature_c': 22.0 + random.uniform(-2, 5),
                'humidity_percent': 55.0 + random.uniform(-5, 10)
            }
        
        self._last_update = now
        return readings
    
    def simulate_irrigation(self, zone_id: str, liters: float, area_m2: float = 1.0):
        """
        Simulate watering a zone.
        
        Args:
            zone_id: Zone to water
            liters: Amount of water applied
            area_m2: Zone area (for calculating moisture increase)
        """
        if zone_id in self._moisture_levels:
            # Rough: 5L per m² increases moisture by ~10%
            moisture_increase = (liters / area_m2) * 2
            self._moisture_levels[zone_id] = min(
                90, 
                self._moisture_levels[zone_id] + moisture_increase
            )
            self._logger.debug(
                f"Zone {zone_id} irrigated: +{moisture_increase:.1f}% moisture"
            )
    
    def set_moisture(self, zone_id: str, moisture: float):
        """Manually set zone moisture (for testing scenarios)."""
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
    
    # Test mock provider
    print("\n--- Mock Sensor Provider ---")
    mock = MockSensorProvider(
        zone_ids=["zone_1", "zone_2", "zone_3"],
        initial_moisture=45.0
    )
    
    readings = mock.get_sensor_readings()
    for zone_id, data in readings.items():
        print(f"  {zone_id}: {data['soil_moisture_percent']:.1f}% moisture")
    
    # Simulate irrigation
    print("\n--- After Irrigation (zone_1: 10L) ---")
    mock.simulate_irrigation("zone_1", 10.0)
    readings = mock.get_sensor_readings()
    for zone_id, data in readings.items():
        print(f"  {zone_id}: {data['soil_moisture_percent']:.1f}% moisture")
    
    print("\n✓ Mock provider working correctly")
