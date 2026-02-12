"""
Smart Irrigation Main Controller
================================
Main orchestration module for the Raspberry Pi irrigation system.

This module coordinates:
    - Reading sensor data
    - Fetching weather/plant data
    - Making irrigation decisions
    - Executing irrigation commands
    - Sending telemetry to the dashboard server
"""

import os
import time
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any

# Core modules
from water.decision_engine import (
    IrrigationDecisionEngine,
    ZoneConfig,
    SensorReading,
    TankStatus,
    DecisionResult,
)

# Hardware interfaces
from sensors.sensor_providers import (
    SensorDataProvider,
    MockSensorProvider,
)
from water.valve_controller import (
    ValveController,
    MockValveController,
)
from sensors.tank_sensor import get_tank_level

# New communication modules
from config.config_manager import ConfigManager
from config.provisioning import DeviceProvisioner
from images.image_sender import ImageSender

# Telemetry — sends data to dashboard server
from api.telemetry import TelemetrySender

# API modules (optional)
try:
    from api.weather_api import WeatherAPI, create_api as create_weather_api

    WEATHER_API_AVAILABLE = True
except ImportError:
    WEATHER_API_AVAILABLE = False

try:
    from api.plant_api import PlantAPI

    PLANT_API_AVAILABLE = True
except ImportError:
    PLANT_API_AVAILABLE = False

from config.default_config import DEFAULT_CONFIG


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """Load configuration from file or use defaults."""
    config = {**DEFAULT_CONFIG}
    if config_path and Path(config_path).exists():
        import json

        with open(config_path) as f:
            user_config = json.load(f)
        config.update(user_config)
    return config


class IrrigationController:
    """
    Main controller that orchestrates the irrigation system.
    """

    def __init__(
        self,
        config: Dict[str, Any],
        sensor_provider: Optional[SensorDataProvider] = None,
        valve_controller: Optional[ValveController] = None,
        weather_api: Optional[Any] = None,
        plant_api: Optional[Any] = None,
        telemetry_sender: Optional[TelemetrySender] = None,
        mock_tank_level: Optional[float] = None,
    ):
        """
        Initialize the controller.
        """
        self.config = config
        self._setup_logging()

        self.logger = logging.getLogger("controller")
        self.logger.info("Initializing Irrigation Controller")

        # Parse zones
        self.zones = self._parse_zones()
        self.zone_pins = {
            z["zone_id"]: z["valve_pin"]
            for z in config.get("zones", [])
            if "valve_pin" in z
        }

        # Setup components
        self.sensor_provider = sensor_provider or MockSensorProvider(
            zone_ids=[z.zone_id for z in self.zones]
        )
        self.valve_controller = valve_controller or MockValveController(self.zone_pins)

        # Tank: use mock level if provided, otherwise real sensor
        self._mock_tank_level = mock_tank_level
        if mock_tank_level is not None:
            self.logger.info(f"Using mock tank level: {mock_tank_level:.1f}L")

        # Configuration management
        self.internal_config = ConfigManager()

        # APIs
        self.weather_api = weather_api
        self.plant_api = plant_api

        # Telemetry
        self.telemetry = None
        self.image_sender = None

        # Initialize communication (Provisioning flow)
        self._initialize_communication(telemetry_sender)

        # Decision engine
        self.decision_engine = IrrigationDecisionEngine(zones=self.zones)

        # Load plant data if API available
        if self.plant_api:
            self._load_plant_data()

        # State
        self._running = False
        self._last_decision: Optional[DecisionResult] = None
        self._last_weather: Dict[str, Any] = {}

        self.logger.info("Controller initialized successfully")

    def _initialize_communication(self, provided_sender: Optional[TelemetrySender]):
        """Handles bootstrapping and initialization of telemetry/image senders."""
        server_config = self.config.get("server", {})
        if not server_config.get("enabled", True):
            self.logger.info("Communication disabled in config")
            return

        server_ip = server_config.get("ip") or os.getenv(
            "DASHBOARD_SERVER_IP", "127.0.0.1"
        )
        server_port = server_config.get("port", 8000)

        # 1. Provisioning Check
        if not self.internal_config.is_provisioned():
            self.logger.info("Device not provisioned. Starting bootstrapping flow...")
            provisioner = DeviceProvisioner(server_ip, server_port)

            # Map current capabilities
            capabilities = {
                "sensors": [
                    item
                    for z in self.zones
                    for item in [
                        {"localName": z.zone_id, "type": "humidity"},
                        {"localName": f"{z.zone_id}_lux", "type": "luminosity"},
                    ]
                ],
                "cameras": ["main_view"],
            }

            provision_data = provisioner.provision(capabilities)
            if provision_data:
                self.internal_config.update_from_provisioning(provision_data)
            else:
                self.logger.warning("Provisioning failed.")

        # 2. Setup Senders if provisioned
        if self.internal_config.is_provisioned():
            device_id = self.internal_config.device_id
            sensor_map = self.internal_config.sensor_map

            self.telemetry = provided_sender or TelemetrySender(
                device_id=device_id,
                sensor_map=sensor_map,
                server_ip=server_ip,
                server_port=server_port,
            )
            self.image_sender = ImageSender(
                device_id=device_id, server_ip=server_ip, server_port=server_port
            )
            self.logger.info(f"Communication initialized (DeviceID: {device_id})")
        else:
            self.logger.warning("Device ID missing. Telemetry/Image upload disabled.")

    def _setup_logging(self):
        """Configure logging."""
        log_config = self.config.get("logging", {})
        level = getattr(logging, log_config.get("level", "INFO"))
        log_file = log_config.get("file")

        logging.basicConfig(
            level=level,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[logging.StreamHandler(), logging.FileHandler(log_file)]
            if log_file
            else [logging.StreamHandler()],
        )

    def _parse_zones(self) -> list:
        """Parse zone configurations."""
        zones = []
        for z in self.config.get("zones", []):
            zones.append(
                ZoneConfig(
                    zone_id=z["zone_id"],
                    name=z.get("name", z["zone_id"]),
                    plant_id=z.get("plant_id"),
                    area_m2=z.get("area_m2", 1.0),
                    valve_flow_rate_lpm=z.get("valve_flow_rate_lpm", 2.0),
                    moisture_threshold_low=z.get("moisture_threshold_low", 30.0),
                    moisture_threshold_target=z.get("moisture_threshold_target", 60.0),
                    priority_weight=z.get("priority_weight", 1.0),
                )
            )
        return zones

    def _load_plant_data(self):
        """Load plant data from API for all zones."""
        for zone_config in self.config.get("zones", []):
            plant_id = zone_config.get("plant_id")
            if plant_id and self.plant_api:
                try:
                    data = self.plant_api.get_irrigation_data(plant_id)
                    if data:
                        self.decision_engine.set_plant_data(
                            zone_config["zone_id"], data
                        )
                except Exception as e:
                    self.logger.error(f"Failed to load plant data: {e}")

    def _get_weather_data(self) -> Dict[str, Any]:
        """Get weather data from API or return defaults."""
        if self.weather_api:
            try:
                location = self.config.get("location", {})
                data = self.weather_api.get_irrigation_data(
                    city=location.get("city", "Paris"),
                    max_days=3,
                    elevation=location.get("elevation_m", 0),
                )
                if data:
                    return data
            except Exception as e:
                self.logger.error(f"Weather API error: {e}")

        # Return defaults
        today = datetime.now().strftime("%Y-%m-%d")
        return {
            today: {
                "rain": {"total_mm": 0, "will_rain": False, "by_period": {}},
                "temperature": {"day_min": 15, "day_max": 25, "by_period": {}},
                "et": {"et_mm": 3.0},
                "water_balance_mm": -3.0,
            }
        }

    def _get_sensor_data(self) -> Dict[str, SensorReading]:
        """Get sensor readings from provider."""
        raw = self.sensor_provider.get_sensor_readings()
        return {
            zone_id: SensorReading(
                zone_id=zone_id,
                soil_moisture_percent=data.get("soil_moisture_percent", 50.0),
                temperature_c=data.get("temperature_c", 20.0),
                humidity_percent=data.get("humidity_percent", 50.0),
                luminosity_lux=data.get("luminosity_lux", 0.0),
            )
            for zone_id, data in raw.items()
        }

    def _get_raw_sensor_data(self) -> Dict[str, Dict[str, float]]:
        """Get raw sensor readings dict (for telemetry)."""
        return self.sensor_provider.get_sensor_readings()

    def _get_tank_status(self) -> TankStatus:
        """Get tank status."""
        capacity = self.config.get("tank", {}).get("capacity_liters", 50.0)
        level = (
            self._mock_tank_level
            if self._mock_tank_level is not None
            else get_tank_level()
        )
        return TankStatus(current_level_liters=level, capacity_liters=capacity)

    def _update_mock_tank(self, water_used: float):
        """Decrease mock tank level after irrigation."""
        if self._mock_tank_level is not None:
            self._mock_tank_level = max(0.0, self._mock_tank_level - water_used)

    def _execute_irrigation(self, decision: DecisionResult):
        """Execute irrigation commands."""
        if not decision.should_irrigate or not decision.commands:
            return

        self.logger.info(f"Executing {len(decision.commands)} irrigation commands")
        for cmd in decision.commands:
            try:
                self.logger.info(
                    f"Irrigating {cmd.zone_name}: {cmd.water_amount_liters:.1f}L"
                )
                self.valve_controller.open_valve(cmd.zone_id)
                time.sleep(cmd.duration_seconds)
                self.valve_controller.close_valve(cmd.zone_id)

                # Update mock sensor if using it
                from sensors.sensor_providers import MockSensorProvider

                if isinstance(self.sensor_provider, MockSensorProvider):
                    zone = next(
                        (z for z in self.zones if z.zone_id == cmd.zone_id), None
                    )
                    area = zone.area_m2 if zone else 1.0
                    self.sensor_provider.simulate_irrigation(
                        cmd.zone_id, cmd.water_amount_liters, area
                    )

            except Exception as e:
                self.logger.error(f"Irrigation error for {cmd.zone_id}: {e}")
                self.valve_controller.close_valve(cmd.zone_id)

        self._update_mock_tank(decision.total_water_liters)

    def _send_telemetry(self, raw_sensors, tank_status, weather_data, decision):
        """Send telemetry data to the dashboard server."""
        if self.telemetry is None:
            return
        try:
            self.telemetry.send_telemetry(
                sensor_data=raw_sensors, print_to_console=True
            )
            if decision.should_irrigate:
                self.telemetry.send_log(
                    "info",
                    f"Started irrigation cycle: {decision.total_water_liters:.1f}L",
                )
        except Exception as e:
            self.logger.warning(f"Telemetry send failed: {e}")

    def _send_heartbeat(self):
        """Send a heartbeat to the server."""
        if self.telemetry:
            self.telemetry.send_heartbeat()

    def _capture_and_send_tank_image(self):
        """Captures a tank image and sends it to the server."""
        if self.image_sender is None:
            return
        from sensors.tank_sensor import CAMERA_AVAILABLE

        if not CAMERA_AVAILABLE:
            return
        try:
            import cv2
            from sensors.tank_sensor import _picam2, _initialize_camera

            _initialize_camera()
            frame_rgb = _picam2.capture_array()
            frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
            temp_path = "tank_capture.jpg"
            cv2.imwrite(temp_path, frame_bgr)
            self.image_sender.upload_image(temp_path, image_type="tank")
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception as e:
            self.logger.error(f"Failed to capture/send tank image: {e}")

    def run_once(self, force: bool = False) -> DecisionResult:
        """Run a single decision cycle."""
        self.logger.info("Running decision cycle")
        raw_sensors = self._get_raw_sensor_data()
        if not raw_sensors:
            self.logger.warning("No sensor data received. Skipping cycle.")
            tank_status = self._get_tank_status()
            return DecisionResult(
                timestamp=datetime.now(),
                should_irrigate=False,
                delay_reason="No sensor data available",
                commands=[],
                total_water_liters=0,
                tank_after_liters=tank_status.current_level_liters,
                weather_summary={"date": datetime.now().strftime("%Y-%m-%d")},
            )

        sensor_data = {
            zone_id: SensorReading(
                zone_id=zone_id,
                soil_moisture_percent=data.get("soil_moisture_percent", 50.0),
                temperature_c=data.get("temperature_c", 20.0),
                humidity_percent=data.get("humidity_percent", 50.0),
                luminosity_lux=data.get("luminosity_lux", 0.0),
            )
            for zone_id, data in raw_sensors.items()
        }
        weather_data = self._get_weather_data()
        tank_status = self._get_tank_status()
        self._last_weather = weather_data

        decision = self.decision_engine.make_decisions(
            sensor_data=sensor_data,
            weather_data=weather_data,
            tank_status=tank_status,
            force=force,
        )
        self._last_decision = decision

        if decision.should_irrigate:
            self._execute_irrigation(decision)

        if self.telemetry:
            self._send_telemetry(raw_sensors, tank_status, weather_data, decision)
        else:
            self._send_heartbeat()

        self._capture_and_send_tank_image()
        return decision

    def run(self, max_iterations: Optional[int] = None):
        """Run the main control loop."""
        self._running = True
        interval = self.config.get("timing", {}).get("check_interval_seconds", 600)
        iteration = 0
        try:
            while self._running:
                if max_iterations and iteration >= max_iterations:
                    break
                try:
                    self.run_once()
                except Exception as e:
                    self.logger.error(f"Cycle error: {e}")
                    self.valve_controller.close_all()
                iteration += 1
                if self._running:
                    time.sleep(interval)
        except KeyboardInterrupt:
            self.logger.info("Interrupted by user")
        finally:
            self.stop()

    def stop(self):
        """Stop the controller."""
        self._running = False
        self.valve_controller.cleanup()

    def get_status(self) -> Dict[str, Any]:
        """Get current system status."""
        sensor_data = self._get_sensor_data()
        tank = self._get_tank_status()
        return {
            "timestamp": datetime.now().isoformat(),
            "running": self._running,
            "tank": {
                "level_liters": tank.current_level_liters,
                "level_percent": tank.level_percent,
                "is_low": tank.is_low,
            },
            "zones": {
                zone_id: {
                    "moisture_percent": r.soil_moisture_percent,
                    "temperature_c": r.temperature_c,
                    "humidity_percent": r.humidity_percent,
                    "luminosity_lux": r.luminosity_lux,
                }
                for zone_id, r in sensor_data.items()
            },
            "last_decision": self._last_decision.to_dict()
            if self._last_decision
            else None,
            "telemetry_enabled": self.telemetry is not None,
        }
