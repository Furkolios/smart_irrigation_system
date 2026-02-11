import logging
from typing import Optional, Dict

from ..config.models import SystemConfig
from .arduino_manager import ArduinoManager
from .camera_manager import CameraManager
from ..water.valve_controller import ValveController, MockValveController


class HardwareManager:
    """
    Central Hardware Abstraction Layer (HAL).
    Orchestrates all hardware components:
    - Arduinos (Sensors)
    - Cameras (Vision)
    - Valves (Actuators)
    """

    def __init__(self, config: SystemConfig):
        self._config = config
        self.logger = logging.getLogger("hardware_manager")

        # Sub-managers
        self.arduino_manager: Optional[ArduinoManager] = None
        self.camera_manager: Optional[CameraManager] = None
        self.valve_controller: Optional[ValveController] = None

        self._initialize()

    def _initialize(self):
        self.logger.info("Initializing Hardware Layer...")
        hw_config = self._config.hardware

        # 1. Valves
        # Convert List[ValveConfig] to Dict[zone_id, pin] for legacy controller
        valve_map = {v.zone_id: v.pin for v in hw_config.valves}

        # Check system mode for mocking
        use_mock = self._config.system_mode in ["demo", "test"]

        if use_mock:
            self.logger.info("Using MOCK Valve Controller")
            self.valve_controller = MockValveController(valve_map)
        else:
            self.valve_controller = ValveController(valve_map)

        # 2. Sensors (Arduino or Mock)
        if use_mock:
            self.logger.info("Using MOCK Sensor Provider")
            from ..sensors.sensor_providers import MockSensorProvider

            self.sensor_provider = MockSensorProvider(
                zone_ids=[v.zone_id for v in hw_config.valves]
            )
        else:
            self.sensor_provider = ArduinoManager(hw_config.global_arduino_config)
            if hasattr(self.sensor_provider, "start"):
                self.sensor_provider.start()

        # 3. Cameras
        self.camera_manager = CameraManager(hw_config.cameras)
        if hasattr(self.camera_manager, "initialize"):
            self.camera_manager.initialize()

        self.logger.info("Hardware initialization complete.")

    def get_sensor_data(self) -> Dict[str, dict]:
        """
        Get aggregated sensor data.
        Returns: { "zone_1": { "soil_moisture_percent": 45.0, ... }, ... }
        """
        # If using ArduinoManager, we need to massage the data
        if isinstance(self.sensor_provider, ArduinoManager):
            raw_readings = self.sensor_provider.get_readings()
            aggregated_zones = {}
            for device_id, data in raw_readings.items():
                for key, value in data.items():
                    if key.startswith("zone_") and isinstance(value, dict):
                        zone_data = value.copy()
                        if "temp" in data and "temperature_c" not in zone_data:
                            zone_data["temperature_c"] = data["temp"]
                        if "humidity" in data and "humidity_percent" not in zone_data:
                            zone_data["humidity_percent"] = data["humidity"]
                        aggregated_zones[key] = zone_data
            return aggregated_zones

        # If using MockSensorProvider, it returns { "zone_1": {...}, ... } directly
        elif hasattr(self.sensor_provider, "get_sensor_readings"):
            return self.sensor_provider.get_sensor_readings()

        return {}

    def capture_image(self, role: str) -> Optional[str]:
        if self.camera_manager:
            return self.camera_manager.capture_image(role)
        return None

    def get_status(self) -> dict:
        """Get global hardware status."""

        sensor_status = {}
        if isinstance(self.sensor_provider, ArduinoManager):
            sensor_status = {
                "type": "arduino",
                "connected": self.sensor_provider.get_connected_count(),
                "devices": list(self.sensor_provider.get_readings().keys()),
            }
        else:
            sensor_status = {
                "type": "mock",
                "zones": list(self.sensor_provider.get_sensor_readings().keys()),
            }

        return {
            "sensors": sensor_status,
            "cameras": self.camera_manager.get_status() if self.camera_manager else {},
            "valves": {
                "open": list(self.valve_controller.get_open_valves())
                if self.valve_controller
                else []
            },
        }

    def cleanup(self):
        self.logger.info("Shutting down Hardware Layer...")
        if hasattr(self.sensor_provider, "stop"):
            self.sensor_provider.stop()
        if self.camera_manager:
            self.camera_manager.release()
        if self.valve_controller:
            self.valve_controller.cleanup()
