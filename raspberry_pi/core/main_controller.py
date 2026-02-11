"""
Smart Irrigation Main Controller
================================
Main orchestration module for the Raspberry Pi irrigation system.

This script is the entry point that ties together:
    - Sensor data (from sensor_providers module)
    - Tank level (from tank_sensor module)
    - Weather data (from weather_api module)
    - Plant data (from plant_api module)
    - Decision making (from decision_engine module)
    - Valve control (from valve_controller module)
    - Telemetry (from telemetry module) Ã¢â‚¬â€ sends data to dashboard server

Usage:
    # Production mode (real hardware)
    python main_controller.py

    # Mock sensors (testing on Pi without Arduino)
    python main_controller.py --mock

    # Demo mode (full simulation, no hardware needed)
    python main_controller.py --demo
    python main_controller.py --demo --scenario critical

    # Single cycle
    python main_controller.py --once --mock

    # Specify dashboard server IP
    python main_controller.py --mock --server-ip 192.168.1.50

    # Test hardware components
    python main_controller.py --test sensors --mock
    python main_controller.py --test valves --mock
    python main_controller.py --test both
"""

import os
import json
import time
import logging
import argparse
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
    ArduinoSensorProvider,
    MultiArduinoSensorProvider,
    MockSensorProvider,
)
from water.valve_controller import (
    ValveController,
    MockValveController,
    create_valve_controller,
    GPIO_AVAILABLE,
)
from sensors.tank_sensor import get_tank_level

# New communication modules
from config.config_manager import ConfigManager
from config.provisioning import DeviceProvisioner
from images.image_sender import ImageSender

# Telemetry â€” sends data to dashboard server
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


# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_CONFIG = {
    "location": {"city": "Paris", "elevation_m": 35},
    "tank": {"capacity_liters": 50.0},
    "arduinos": {
        "/dev/ttyACM0": "zone_1",
        "/dev/ttyACM1": "zone_2",
    },
    "zones": [
        {
            "zone_id": "zone_1",
            "name": "Zone 1",
            "plant_id": None,
            "area_m2": 1.0,
            "valve_flow_rate_lpm": 2.0,
            "moisture_threshold_low": 30.0,
            "moisture_threshold_target": 60.0,
            "priority_weight": 1.0,
            "valve_pin": 17,
        },
        {
            "zone_id": "zone_2",
            "name": "Zone 2",
            "plant_id": None,
            "area_m2": 1.0,
            "valve_flow_rate_lpm": 2.0,
            "moisture_threshold_low": 30.0,
            "moisture_threshold_target": 60.0,
            "priority_weight": 1.0,
            "valve_pin": 18,
        },
    ],
    "server": {
        "ip": None,  # Dashboard server IP (None = read from .env)
        "port": 8000,
        "enabled": True,  # Set False to disable telemetry
    },
    "timing": {
        "check_interval_seconds": 600,  # 10 minutes
    },
    "logging": {"level": "INFO", "file": "irrigation.log"},
}


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """Load configuration from file or use defaults."""
    if config_path and Path(config_path).exists():
        with open(config_path) as f:
            user_config = json.load(f)
        config = {**DEFAULT_CONFIG}
        config.update(user_config)
        return config
    return DEFAULT_CONFIG.copy()


# =============================================================================
# MAIN CONTROLLER
# =============================================================================


class IrrigationController:
    """
    Main controller that orchestrates the irrigation system.

    This class coordinates:
    - Reading sensor data
    - Fetching weather/plant data
    - Making irrigation decisions
    - Executing irrigation commands
    - Sending telemetry to the dashboard server
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

        Args:
            config: Configuration dictionary
            sensor_provider: Sensor data provider (uses mock if None)
            valve_controller: Valve controller (uses mock if None)
            weather_api: WeatherAPI instance (optional)
            plant_api: PlantAPI instance (optional)
            telemetry_sender: TelemetrySender instance (auto-created if None and enabled)
            mock_tank_level: Fixed tank level in liters for mock/testing mode.
                             If set, bypasses the real camera-based tank sensor.
                             Decreases as water is used and can be refilled.
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

        # Telemetry Ã¢â‚¬â€ sends data to dashboard
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
        """
        Handles the bootstrapping and initialization of telemetry/image senders.
        Fulfills Section 2.1 of the Technical Manual.
        """
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
                self.logger.warning(
                    "Provisioning failed. Will retry next time. Proceeding with limited functionality."
                )

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
            self.logger.info(
                f"Ã¢Å“â€œ Communication initialized (DeviceID: {device_id})"
            )
        else:
            self.logger.warning(
                "Ã¢Å¡Â  Device ID missing. Telemetry and Image upload will be disabled."
            )

    def _setup_logging(self):
        """Configure logging."""
        log_config = self.config.get("logging", {})
        level = getattr(logging, log_config.get("level", "INFO"))
        log_file = log_config.get("file")

        handlers = [logging.StreamHandler()]
        if log_file:
            handlers.append(logging.FileHandler(log_file))

        logging.basicConfig(
            level=level,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=handlers,
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
        self.logger.info(f"Configured {len(zones)} zones")
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
                        self.logger.info(
                            f"Loaded plant data for {zone_config['zone_id']}"
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
            )
            for zone_id, data in raw.items()
        }

    def _get_raw_sensor_data(self) -> Dict[str, Dict[str, float]]:
        """Get raw sensor readings dict (for telemetry)."""
        return self.sensor_provider.get_sensor_readings()

    def _get_tank_status(self) -> TankStatus:
        """
        Get tank status.

        Uses mock tank level if set (for --mock mode),
        otherwise reads from the real camera-based tank sensor.
        """
        capacity = self.config.get("tank", {}).get("capacity_liters", 50.0)

        if self._mock_tank_level is not None:
            level = self._mock_tank_level
        else:
            level = get_tank_level()

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
                if isinstance(self.sensor_provider, MockSensorProvider):
                    zone = next(
                        (z for z in self.zones if z.zone_id == cmd.zone_id), None
                    )
                    area = zone.area_m2 if zone else 1.0
                    self.sensor_provider.simulate_irrigation(
                        cmd.zone_id, cmd.water_amount_liters, area
                    )

                self.logger.info(f"Completed: {cmd.zone_name}")

            except Exception as e:
                self.logger.error(f"Irrigation error for {cmd.zone_id}: {e}")
                self.valve_controller.close_valve(cmd.zone_id)

        # Update mock tank level
        self._update_mock_tank(decision.total_water_liters)

        self.logger.info("Irrigation cycle complete")

    def _send_telemetry(
        self,
        raw_sensors: Dict[str, Dict[str, float]],
        tank_status: TankStatus,
        weather_data: Dict[str, Any],
        decision: DecisionResult,
    ):
        """Send telemetry data to the dashboard server."""
        if self.telemetry is None:
            return

        try:
            self.telemetry.send_telemetry(
                sensor_data=raw_sensors, print_to_console=True
            )

            # Optionally send a log about the decision if it was significant
            if decision.should_irrigate:
                self.telemetry.send_log(
                    "info",
                    f"Started irrigation cycle: {decision.total_water_liters:.1f}L total",
                )

        except Exception as e:
            self.logger.warning(f"Telemetry send failed: {e}")

    def _send_heartbeat(self):
        """Send a heartbeat to the server if telemetry wasn't sent."""
        if self.telemetry is None:
            return
        self.telemetry.send_heartbeat()

    def _capture_and_send_tank_image(self):
        """Captures a tank image and sends it to the server."""
        if self.image_sender is None:
            return

        # We can't easily 'steal' the frame from tank_sensor.py without changes,
        # but we can try to use its logic if we import its internal components
        # or just capture a new one if CAMERA_AVAILABLE.
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

            # Cleanup temp file
            if os.path.exists(temp_path):
                os.remove(temp_path)

        except Exception as e:
            self.logger.error(f"Failed to capture/send tank image: {e}")

    # =========================================================================
    # PUBLIC METHODS
    # =========================================================================

    def run_once(self, force: bool = False) -> DecisionResult:
        """Run a single decision cycle."""
        self.logger.info("Running decision cycle")

        # Gather data
        raw_sensors = self._get_raw_sensor_data()

        # Warn if no sensor data received (Arduino disconnected, etc.)
        if not raw_sensors:
            self.logger.warning(
                "No sensor data received Ã¢â‚¬â€ Arduino may be disconnected. "
                "Skipping this cycle."
            )
            now = datetime.now()
            weather_data = self._get_weather_data()
            tank_status = self._get_tank_status()
            return DecisionResult(
                timestamp=now,
                should_irrigate=False,
                delay_reason="No sensor data available",
                commands=[],
                total_water_liters=0,
                tank_after_liters=tank_status.current_level_liters,
                weather_summary={"date": now.strftime("%Y-%m-%d")},
            )

        sensor_data = {
            zone_id: SensorReading(
                zone_id=zone_id,
                soil_moisture_percent=data.get("soil_moisture_percent", 50.0),
                temperature_c=data.get("temperature_c", 20.0),
                humidity_percent=data.get("humidity_percent", 50.0),
            )
            for zone_id, data in raw_sensors.items()
        }
        weather_data = self._get_weather_data()
        tank_status = self._get_tank_status()

        # Store weather for telemetry
        self._last_weather = weather_data

        # Log state
        self.logger.info(f"Tank: {tank_status.level_percent:.1f}%")
        for zone_id, reading in sensor_data.items():
            self.logger.info(
                f"{zone_id}: moisture={reading.soil_moisture_percent:.1f}%"
            )

        # Make decision
        decision = self.decision_engine.make_decisions(
            sensor_data=sensor_data,
            weather_data=weather_data,
            tank_status=tank_status,
            force=force,
        )

        self._last_decision = decision

        # Execute irrigation
        if decision.should_irrigate:
            self._execute_irrigation(decision)
        else:
            self.logger.info(f"No irrigation: {decision.delay_reason or 'Not needed'}")

        # Send telemetry to dashboard server
        if self.telemetry:
            self._send_telemetry(raw_sensors, tank_status, weather_data, decision)
        else:
            # If telemetry not available/sent, at least send a heartbeat if possible
            self._send_heartbeat()

        # Capture and send tank image
        self._capture_and_send_tank_image()

        return decision

    def run(self, max_iterations: Optional[int] = None):
        """Run the main control loop."""
        self._running = True
        interval = self.config.get("timing", {}).get("check_interval_seconds", 600)
        iteration = 0

        self.logger.info(f"Starting control loop (interval: {interval}s)")

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
        self.logger.info("Stopping controller")
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
                }
                for zone_id, r in sensor_data.items()
            },
            "last_decision": self._last_decision.to_dict()
            if self._last_decision
            else None,
            "telemetry_enabled": self.telemetry is not None,
        }


# =============================================================================
# CLI & MAIN
# =============================================================================


def run_demo_mode(args):
    """Run in demo mode using the demo module."""
    from core.demo_mode import DemoMode

    print("\n" + "=" * 60)
    print("SMART IRRIGATION - DEMO MODE")
    print(f"Scenario: {args.scenario.upper()}")
    print("=" * 60)

    # Setup telemetry for demo mode if server IP provided
    telemetry = None
    if args.server_ip:
        telemetry = TelemetrySender(server_ip=args.server_ip)
        print(f"Ã¢Å“â€œ Telemetry enabled Ã¢â€ â€™ {telemetry.url}")

    demo = DemoMode(
        scenario=args.scenario, num_zones=args.zones, telemetry_sender=telemetry
    )

    if args.once:
        result = demo.run_cycle()
        state = demo.get_state()
        print(json.dumps(state, indent=2))
    else:
        print("\nRunning demo cycles (Ctrl+C to stop)...")
        try:
            for i in range(10):
                print(f"\n--- Cycle {i + 1} ---")
                result = demo.run_cycle()
                state = demo.get_state()

                print(f"Tank: {state['tank']['level_percent']:.0f}%")
                for zone in state["zones"]:
                    status = (
                        "Ã¢Å¡Â Ã¯Â¸Â" if zone["moisture_percent"] < 35 else "Ã¢Å“â€œ"
                    )
                    print(f"  {zone['name']}: {zone['moisture_percent']:.0f}% {status}")

                if result.should_irrigate:
                    print(
                        f"Ã¢â€ â€™ Irrigated {len(result.commands)} zones ({result.total_water_liters:.1f}L)"
                    )

                demo.simulate_time_passage(hours=4)
                time.sleep(2)

        except KeyboardInterrupt:
            print("\nDemo stopped")

    print("\nÃ¢Å“â€œ Demo complete")


def run_tests(args):
    """
    Test individual hardware components (sensors and/or valves).

    Sensor tests also send telemetry if the device is provisioned.

    Usage:
        python main_controller.py --test sensors --mock
        python main_controller.py --test valves --mock
        python main_controller.py --test both --mock
    """
    config = load_config(args.config)
    zone_configs = config.get("zones", [])

    print("\n" + "=" * 60)
    print("SMART IRRIGATION - TEST MODE")
    print(f"Testing: {args.test.upper()}")
    print("=" * 60)

    # Build telemetry sender for sensor tests (reuses provisioning data)
    telemetry = None
    if args.test in ("sensors", "both") and not args.no_telemetry:
        telemetry = _build_telemetry(config, args.server_ip)

    if args.test in ("sensors", "both"):
        _test_sensors(zone_configs, use_mock=args.mock, telemetry=telemetry)

    if args.test in ("valves", "both"):
        _test_valves(zone_configs, use_mock=args.mock)

    print("\n" + "=" * 60)
    print("Tests complete")
    print("=" * 60)


def _build_telemetry(
    config: Dict[str, Any], cli_server_ip: Optional[str] = None
) -> Optional[TelemetrySender]:
    """
    Create a TelemetrySender from provisioning data if available.

    Returns None (with a message) if the device hasn't been provisioned yet.
    """
    internal_config = ConfigManager()
    if not internal_config.is_provisioned():
        print("[Telemetry] Device not provisioned - telemetry disabled")
        print(
            "[Telemetry] Run the system normally first to provision, or use --no-telemetry"
        )
        return None

    server_config = config.get("server", {})
    server_ip = (
        cli_server_ip
        or server_config.get("ip")
        or os.getenv("DASHBOARD_SERVER_IP", "127.0.0.1")
    )
    server_port = server_config.get("port", 8000)

    try:
        sender = TelemetrySender(
            device_id=internal_config.device_id,
            sensor_map=internal_config.sensor_map,
            server_ip=server_ip,
            server_port=server_port,
        )
        print(f"[Telemetry] Enabled -> {sender.telemetry_url}")
        return sender
    except Exception as e:
        print(f"[Telemetry] Setup failed: {e}")
        return None


def _test_sensors(
    zone_configs: list,
    use_mock: bool = False,
    telemetry: Optional[TelemetrySender] = None,
):
    """Read and display sensor data for all zones, optionally sending telemetry."""
    zone_ids = [z["zone_id"] for z in zone_configs]

    if use_mock:
        provider = MockSensorProvider(zone_ids)
        print("\n[Sensors] Using MOCK provider")
    else:
        try:
            provider = ArduinoSensorProvider()
            print("\n[Sensors] Using REAL Arduino connection")
        except Exception as e:
            print(f"\n[Sensors] Cannot connect to Arduino: {e}")
            print("[Sensors] Tip: use --mock to test without hardware")
            return

    print(f"[Sensors] Reading {len(zone_ids)} zone(s)...\n")

    try:
        for i in range(3):
            readings = provider.get_sensor_readings()

            if not readings:
                print(f"  Reading {i + 1}: No data received")
            else:
                print(f"  Reading {i + 1}:")
                for zone_id, data in sorted(readings.items()):
                    name = next(
                        (
                            z.get("name", zone_id)
                            for z in zone_configs
                            if z["zone_id"] == zone_id
                        ),
                        zone_id,
                    )
                    print(
                        f"    {name}: "
                        f"moisture={data['soil_moisture_percent']:.1f}% | "
                        f"temp={data['temperature_c']:.1f}C | "
                        f"humidity={data['humidity_percent']:.1f}%"
                    )

                if telemetry:
                    ok = telemetry.send_telemetry(readings, print_to_console=False)
                    tag = "sent" if ok else "FAILED"
                    print(f"    [Telemetry] {tag}")

            time.sleep(2)

    except KeyboardInterrupt:
        print("\n  Sensor test interrupted")
    finally:
        if hasattr(provider, "close"):
            provider.close()

    print("\n[Sensors] Done")


def _test_valves(zone_configs: list, use_mock: bool = False, duration: float = 3.0):
    """Open each valve briefly to verify operation."""
    zone_pins = {z["zone_id"]: z["valve_pin"] for z in zone_configs if "valve_pin" in z}

    if not zone_pins:
        print("\n[Valves] No valve pins configured - skipping")
        return

    try:
        controller = create_valve_controller(zone_pins, use_mock=use_mock)
    except Exception as e:
        print(f"\n[Valves] Cannot initialize valve controller: {e}")
        print("[Valves] Tip: use --mock to test without hardware")
        return

    label = "MOCK" if use_mock or not GPIO_AVAILABLE else "REAL GPIO"
    print(f"\n[Valves] Using {label} controller")
    print(f"[Valves] Testing {len(zone_pins)} valve(s), {duration:.0f}s each...\n")

    try:
        for zone_id, pin in zone_pins.items():
            name = next(
                (
                    z.get("name", zone_id)
                    for z in zone_configs
                    if z["zone_id"] == zone_id
                ),
                zone_id,
            )
            print(f"  {name} (GPIO {pin}): opening...", end="", flush=True)
            controller.open_valve(zone_id)
            time.sleep(duration)
            controller.close_valve(zone_id)
            print(" closed")

    except KeyboardInterrupt:
        print("\n  Valve test interrupted - closing all valves")
    finally:
        controller.cleanup()

    print("\n[Valves] Done")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Smart Irrigation Controller")
    parser.add_argument("--config", type=str, help="Path to config file")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--force", action="store_true", help="Force irrigation")
    parser.add_argument("--status", action="store_true", help="Print status")
    parser.add_argument("--mock", action="store_true", help="Use mock sensors")
    parser.add_argument("--demo", action="store_true", help="Run demo mode")
    parser.add_argument(
        "--test",
        type=str,
        default=None,
        choices=["sensors", "valves", "both"],
        help="Test hardware components (sensors/valves/both)",
    )
    parser.add_argument(
        "--scenario",
        type=str,
        default="normal",
        choices=["normal", "critical", "rain", "healthy", "low_tank", "mixed"],
        help="Demo scenario",
    )
    parser.add_argument("--zones", type=int, default=3, help="Number of zones")
    parser.add_argument(
        "--server-ip",
        type=str,
        default=None,
        help="Dashboard server IP (overrides .env)",
    )
    parser.add_argument(
        "--no-telemetry", action="store_true", help="Disable telemetry sending"
    )
    args = parser.parse_args()

    # Demo mode
    if args.demo:
        run_demo_mode(args)
        return

    # Test mode
    if args.test:
        run_tests(args)
        return

    # Load config
    config = load_config(args.config)

    # Override server config from CLI args
    if args.server_ip:
        config.setdefault("server", {})["ip"] = args.server_ip
    if args.no_telemetry:
        config.setdefault("server", {})["enabled"] = False

    # Setup APIs
    weather_api = None
    plant_api = None

    if WEATHER_API_AVAILABLE:
        try:
            weather_api = create_weather_api(silent=True)
            print("Ã¢Å“â€œ Weather API initialized")
        except Exception as e:
            print(f"Ã¢Å¡Â  Weather API unavailable: {e}")

    if PLANT_API_AVAILABLE:
        try:
            plant_api = PlantAPI()
            print("Ã¢Å“â€œ Plant API initialized")
        except Exception as e:
            print(f"Ã¢Å¡Â  Plant API unavailable: {e}")

    # Create controller
    zone_ids = [z["zone_id"] for z in config.get("zones", [])]

    # In --mock mode, use a mock tank level (80% of capacity)
    # since the real camera-based tank sensor won't be available
    mock_tank = None
    sensor_provider = None

    if args.mock:
        capacity = config.get("tank", {}).get("capacity_liters", 50.0)
        mock_tank = capacity * 0.8
        sensor_provider = MockSensorProvider(zone_ids)
    else:
        # Use multi-Arduino provider (one Arduino per zone)
        arduino_map = config.get("arduinos", {})
        if arduino_map:
            try:
                sensor_provider = MultiArduinoSensorProvider(port_zone_map=arduino_map)
                print(f"\u2713 Multi-Arduino provider: {len(arduino_map)} Arduino(s)")
            except Exception as e:
                print(f"\u26a0 Multi-Arduino setup failed: {e}")
                print("  Falling back to mock sensors")
                sensor_provider = MockSensorProvider(zone_ids)
                capacity = config.get("tank", {}).get("capacity_liters", 50.0)
                mock_tank = capacity * 0.8

    controller = IrrigationController(
        config=config,
        sensor_provider=sensor_provider,
        valve_controller=None,
        weather_api=weather_api,
        plant_api=plant_api,
        mock_tank_level=mock_tank,
    )

    # Execute
    if args.status:
        print(json.dumps(controller.get_status(), indent=2))
    elif args.once:
        result = controller.run_once(force=args.force)
        print(json.dumps(result.to_dict(), indent=2))
    else:
        controller.run()


if __name__ == "__main__":
    main()
