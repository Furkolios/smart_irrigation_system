import time
import logging
import signal
from datetime import datetime
from typing import Optional

from ..config.config_manager import ConfigManager
from ..config.models import SystemMode
from .state_manager import StateManager, SystemState
from .hardware import HardwareManager
from ..water.decision_engine import (
    IrrigationDecisionEngine,
    ZoneConfig,
    SensorReading,
    TankStatus,
)


from .telemetry import TelemetryManager


class SystemOrchestrator:
    """
    Main system orchestrator.
    Coordinated Config, State, Hardware, and Logic.
    """

    def __init__(
        self,
        config_path: str = "config/system_config.yaml",
        override_mode: Optional[str] = None,
    ):
        # 1. Init Config
        self.config_manager = ConfigManager(config_path)
        if override_mode:
            # Override mode in memory only (or update config?)
            # Ideally we update the model in memory
            self.config_manager.config.system_mode = SystemMode(override_mode)

        self.config = self.config_manager.config

        # 2. Init State
        self.state_manager = StateManager()
        self.logger = logging.getLogger("orchestrator")

        # 3. Init Hardware
        self.hardware = HardwareManager(self.config)

        # 4. Init Logic
        self.decision_engine = self._init_decision_engine()

        # 5. Init Telemetry
        self.telemetry = TelemetryManager(self.config.server)

        self._running = False
        self._stop_signal = False

        # Setup signal handlers
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    def _init_decision_engine(self) -> IrrigationDecisionEngine:
        """Initialize decision engine from config."""
        zones = []
        for v_config in self.config.hardware.valves:
            # Map ValveConfig to ZoneConfig
            # Note: ValveConfig is hardware centric (pin), ZoneConfig is logic centric (plant type, area)
            # In a real system, these might be separate configs merged.
            # For now, we assume ValveConfig contains enough info or defaults.
            zones.append(
                ZoneConfig(
                    zone_id=v_config.zone_id,
                    name=v_config.name,
                    valve_flow_rate_lpm=v_config.flow_rate_lpm,
                    # Defaults for now as they aren't in ValveConfig
                    moisture_threshold_low=self.config.irrigation.default_moisture_threshold,
                    moisture_threshold_target=self.config.irrigation.default_moisture_threshold
                    + 30.0,
                )
            )

        return IrrigationDecisionEngine(zones)

    def _handle_signal(self, signum, frame):
        self.logger.info("Shutdown signal received")
        self._stop_signal = True

    def start(self):
        """Main entry point."""
        self.logger.info(f"System starting in {self.config.system_mode} mode")
        self.state_manager.transition_to(SystemState.BOOTING)

        try:
            # Startup checks could go here
            if self.config.system_mode == SystemMode.TEST:
                self._run_test_mode()
                return

            self.state_manager.transition_to(SystemState.RUNNING)
            self._run_loop()

        except Exception as e:
            self.logger.exception(f"Unhandled system error: {e}")
            self.state_manager.report_error(str(e), critical=True)
        finally:
            self.shutdown()

    def _run_loop(self):
        """Main execution loop."""
        self._running = True
        interval = self.config.irrigation.loop_interval_seconds

        while self._running and not self._stop_signal:
            loop_start = time.time()

            try:
                self._run_cycle()

            except Exception as e:
                self.logger.error(f"Error in run cycle: {e}")
                self.state_manager.report_error(str(e))
                # Don't crash main loop

            # Sleep remainder of interval
            elapsed = time.time() - loop_start
            sleep_time = max(1.0, interval - elapsed)

            # Interactive sleep to catch signals faster
            check_interval = 0.5
            while sleep_time > 0 and not self._stop_signal:
                time.sleep(min(sleep_time, check_interval))
                sleep_time -= check_interval

    def _run_cycle(self):
        """Single logic cycle."""
        self.logger.debug("Starting cycle...")

        # 1. Read Sensors
        raw_sensor_data = self.hardware.get_sensor_data()

        # 2. Convert to Decision Engine Inteface
        sensor_readings = {}
        for zone_id, data in raw_sensor_data.items():
            sensor_readings[zone_id] = SensorReading(
                zone_id=zone_id,
                soil_moisture_percent=data.get("soil_moisture_percent", 0.0),
                temperature_c=data.get("temperature_c", 20.0),
                humidity_percent=data.get("humidity_percent", 50.0),
                luminosity_lux=data.get("luminosity_lux", 0.0),
                timestamp=datetime.now(),
            )

        # 3. Get External Data (Weather, Tank)
        # TODO: Implement Weather API client
        weather_data = {}

        # TODO: Implement Tank Level Service
        # For now, default buffer
        tank_status = TankStatus(current_level_liters=50.0, capacity_liters=50.0)

        # 4. Make Decision
        result = self.decision_engine.make_decisions(
            sensor_data=sensor_readings,
            weather_data=weather_data,
            tank_status=tank_status,
        )

        # 5. Execute Commands
        if result.should_irrigate:
            self.logger.info("Executing irrigation commands")
            for cmd in result.commands:
                # Open valve
                if self.hardware.valve_controller.open_valve(cmd.zone_id):
                    # Blocking wait for simplicy (could be async in future)
                    time.sleep(cmd.duration_seconds)
                    self.hardware.valve_controller.close_valve(cmd.zone_id)
                else:
                    self.logger.error(f"Failed to open valve for {cmd.zone_id}")

        # 6. Telemetry
        self.telemetry.send_heartbeat()

        # Prepare telemetry payload
        telemetry_data = {
            "sensors": raw_sensor_data,
            "tank": {
                "level_liters": tank_status.current_level_liters,
                "capacity": tank_status.capacity_liters,
            },
            "decision": result.to_dict() if result else None,
        }
        self.telemetry.send_telemetry(telemetry_data)

    def _run_test_mode(self):
        """Run system diagnostics."""
        self.logger.info("Running TEST mode diagnostics...")
        print("\n" + "=" * 40)
        print("   SMART IRRIGATION SYSTEM TEST")
        print("=" * 40)

        print(f"\nMode: {self.config.system_mode}")

        # 1. Arduino Detection
        print("\n--- SENSORS (ARDUINO) ---")
        if self.hardware.arduino_manager:
            print("Starting Arduino Manager...")
            self.hardware.arduino_manager.start()

            # Wait a few seconds for discovery and first data packets
            discovery_timeout = 8  # Increased timeout
            start_time = time.time()
            found_any_data = False
            last_port_count = -1

            print(f"Scanning for Arduinos (Timeout: {discovery_timeout}s)...")

            while time.time() - start_time < discovery_timeout:
                port_count = self.hardware.arduino_manager.get_connected_count()
                if port_count != last_port_count:
                    print(f"  Ports Connected: {port_count}")
                    last_port_count = port_count

                readings = self.hardware.arduino_manager.get_readings()
                if readings:
                    if not found_any_data:
                        print("  Valid data received!")
                        found_any_data = True

                    # Print current status
                    for dev_id, data in readings.items():
                        print(f"\n    Device Detected: {dev_id}")
                        # Print some key sensor values if present
                        for key, value in data.items():
                            if key.startswith("zone_") and isinstance(value, dict):
                                moisture = value.get("moisture")
                                lux = value.get("lux")
                                print(f"      {key}: moisture={moisture}%, lux={lux}")
                            elif key in ("temp", "humidity"):
                                print(f"      {key}: {value}")

                time.sleep(1)

            if not found_any_data:
                if last_port_count > 0:
                    print(
                        f"  FAILURE: {last_port_count} port(s) connected, but no valid JSON data received."
                    )
                    print("  Check Arduino code and baud rate (9600).")
                else:
                    print("  No Arduinos detected on serial ports.")
        else:
            print("  Arduino Manager not available.")

        # 2. Camera Diagnostics
        print("\n--- VISION ---")
        status = self.hardware.get_status()
        print(f"Cameras Configured: {len(self.config.hardware.cameras)}")
        if self.hardware.camera_manager:
            for role in status["cameras"]:
                print(f"  Testing {role}...")
                path = self.hardware.capture_image(role)
                if path:
                    print(f"    SUCCESS: Captured to {path}")
                else:
                    print(f"    FAILED: Could not capture from {role}")
        else:
            print("  Camera Manager not initialized.")

        # 3. Valve Diagnostics
        print("\n--- ACTUATORS (VALVES) ---")
        print(f"Valves Configured: {len(self.config.hardware.valves)}")
        is_mock = self.hardware.valve_controller.is_mock
        print(f"Controller Type: {'MOCK (Simulation)' if is_mock else 'REAL (GPIO)'}")
        if not is_mock:
            print(
                "Note: Physical valve presence cannot be electrically detected via GPIO alone; "
                "this test validates GPIO pin initialization and sends open/close commands."
            )

        for v in self.config.hardware.valves:
            print(f"  Testing {v.zone_id} ({v.name}) on Pin {v.pin}...")
            if is_mock:
                self.hardware.valve_controller.open_valve(v.zone_id)
                time.sleep(0.5)
                self.hardware.valve_controller.close_valve(v.zone_id)
                print("    OK (Simulated)")
            else:
                pin_ok = self.hardware.valve_controller.check_pin_availability(v.zone_id)
                if not pin_ok:
                    print("    FAILED (GPIO pin init failed / unavailable)")
                    continue

                opened = self.hardware.valve_controller.open_valve(v.zone_id)
                time.sleep(0.5)
                closed = self.hardware.valve_controller.close_valve(v.zone_id)

                if opened and closed:
                    print("    OK (GPIO initialized, open/close commands sent)")
                else:
                    print("    FAILED (Could not toggle valve via GPIO)")

        print("\n" + "=" * 40)
        print("      DIAGNOSTICS COMPLETE")
        print("=" * 40 + "\n")

    def shutdown(self):
        """Clean shutdown."""
        self.state_manager.transition_to(SystemState.SHUTDOWN)
        self.hardware.cleanup()
        self.logger.info("System shutdown complete")


if __name__ == "__main__":
    # Simple test
    logging.basicConfig(level=logging.INFO)
    sys_orch = SystemOrchestrator(override_mode="test")
    sys_orch.start()
