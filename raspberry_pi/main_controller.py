"""
Smart Irrigation Main Controller
================================
Main control loop for the Raspberry Pi irrigation system.

This script orchestrates:
    - Sensor data collection (from Arduino via interface module)
    - Weather data fetching (from WeatherAPI)
    - Plant data fetching (from PlantAPI)
    - Decision making (via IrrigationDecisionEngine)
    - Irrigation execution (via valve control)
    - Logging and optional server reporting

Designed to run continuously on Raspberry Pi.

Usage:
    python main_controller.py
    
    Or with custom config:
    python main_controller.py --config my_config.json
"""

import os
import json
import time
import logging
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass

# Import our modules
from decision_engine import (
    IrrigationDecisionEngine,
    ZoneConfig,
    SensorReading,
    TankStatus,
    DecisionResult
)

# These would be your existing API modules
from weather_api import WeatherAPI
from plant_api import PlantAPI

# This would be written by your friend
# from arduino_interface import ArduinoInterface


# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_CONFIG = {
    "location": {
        "city": "Paris",
        "elevation_m": 35
    },
    "tank": {
        "capacity_liters": 100.0
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
            "valve_pin": 17  # GPIO pin for valve control
        }
    ],
    "timing": {
        "check_interval_seconds": 300,  # 5 minutes
        "weather_refresh_minutes": 60,
        "plant_refresh_hours": 24
    },
    "decision_params": {
        # Override any decision engine params here
    },
    "logging": {
        "level": "INFO",
        "file": "irrigation.log"
    },
    "server": {
        "enabled": False,
        "url": "http://localhost:5000/api",
        "report_interval_seconds": 60
    }
}


# =============================================================================
# DATA PROVIDERS (ABSTRACT INTERFACES)
# =============================================================================

class SensorDataProvider:
    """
    Abstract interface for sensor data.
    
    Your friend will implement the actual Arduino interface.
    This can also be used for testing with mock data.
    """
    
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
        raise NotImplementedError
    
    def get_tank_level(self) -> float:
        """
        Get current tank water level in liters.
        """
        raise NotImplementedError


class MockSensorProvider(SensorDataProvider):
    """
    Mock sensor provider for testing without Arduino.
    """
    
    def __init__(self, zones: list, initial_moisture: float = 20.0):
        self.zones = zones
        self._moisture_levels = {z['zone_id']: initial_moisture for z in zones}
        self._tank_level = 80.0
        self._last_update = datetime.now()
    
    def get_sensor_readings(self) -> Dict[str, Dict[str, float]]:
        # Simulate moisture decay over time
        now = datetime.now()
        hours_elapsed = (now - self._last_update).total_seconds() / 3600
        
        readings = {}
        for zone_id, moisture in self._moisture_levels.items():
            # Decay moisture by ~2% per hour (simulating evaporation)
            new_moisture = max(10, moisture - (hours_elapsed * 2))
            self._moisture_levels[zone_id] = new_moisture
            
            readings[zone_id] = {
                'soil_moisture_percent': new_moisture,
                'temperature_c': 22.0 + (hash(zone_id) % 5),  # Slight variation
                'humidity_percent': 55.0
            }
        
        self._last_update = now
        return readings
    
    def get_tank_level(self) -> float:
        return self._tank_level
    
    def simulate_irrigation(self, zone_id: str, liters: float):
        """Simulate watering a zone."""
        if zone_id in self._moisture_levels:
            # Increase moisture (rough: 10L ≈ 20% moisture increase for 1m² zone)
            self._moisture_levels[zone_id] = min(90, self._moisture_levels[zone_id] + liters * 2)
            self._tank_level = max(0, self._tank_level - liters)


class ArduinoSensorProvider(SensorDataProvider):
    """
    Real sensor provider using Arduino serial interface.
    
    This is a placeholder - your friend will implement the actual
    serial communication with the Arduino.
    """
    
    def __init__(self, port: str = "/dev/ttyUSB0", baud_rate: int = 9600):
        self.port = port
        self.baud_rate = baud_rate
        # self.serial = serial.Serial(port, baud_rate)
        self._logger = logging.getLogger('arduino')
        self._logger.info(f"Arduino interface initialized on {port}")
    
    def get_sensor_readings(self) -> Dict[str, Dict[str, float]]:
        """
        Read sensor data from Arduino.
        
        Expected Arduino message format (JSON):
        {"zone_1": {"moisture": 45, "temp": 22, "humidity": 60}, ...}
        """
        # Placeholder - your friend implements this
        # line = self.serial.readline().decode('utf-8')
        # data = json.loads(line)
        
        # For now, raise to indicate not implemented
        raise NotImplementedError(
            "Arduino interface not yet implemented. "
            "Use MockSensorProvider for testing."
        )
    
    def get_tank_level(self) -> float:
        """Read tank level from Arduino."""
        raise NotImplementedError


# =============================================================================
# VALVE CONTROLLER
# =============================================================================

class ValveController:
    """
    Controls irrigation valves via GPIO.
    
    This is a placeholder - implement with RPi.GPIO or gpiozero.
    """
    
    def __init__(self, zone_pins: Dict[str, int]):
        """
        Initialize valve controller.
        
        Args:
            zone_pins: Dict mapping zone_id to GPIO pin number
        """
        self.zone_pins = zone_pins
        self._logger = logging.getLogger('valves')
        
        # Initialize GPIO (commented out - uncomment on Pi)
        # import RPi.GPIO as GPIO
        # GPIO.setmode(GPIO.BCM)
        # for pin in zone_pins.values():
        #     GPIO.setup(pin, GPIO.OUT)
        #     GPIO.output(pin, GPIO.LOW)
        
        self._logger.info(f"Valve controller initialized for {len(zone_pins)} zones")
    
    def open_valve(self, zone_id: str) -> bool:
        """Open valve for a zone."""
        if zone_id not in self.zone_pins:
            self._logger.error(f"Unknown zone: {zone_id}")
            return False
        
        pin = self.zone_pins[zone_id]
        self._logger.info(f"Opening valve for {zone_id} (GPIO {pin})")
        
        # GPIO.output(pin, GPIO.HIGH)
        return True
    
    def close_valve(self, zone_id: str) -> bool:
        """Close valve for a zone."""
        if zone_id not in self.zone_pins:
            return False
        
        pin = self.zone_pins[zone_id]
        self._logger.info(f"Closing valve for {zone_id} (GPIO {pin})")
        
        # GPIO.output(pin, GPIO.LOW)
        return True
    
    def close_all(self):
        """Emergency close all valves."""
        self._logger.warning("Closing ALL valves")
        for zone_id in self.zone_pins:
            self.close_valve(zone_id)
    
    def cleanup(self):
        """Clean up GPIO on shutdown."""
        self.close_all()
        # GPIO.cleanup()


class MockValveController(ValveController):
    """Mock valve controller for testing."""
    
    def __init__(self, zone_pins: Dict[str, int]):
        self.zone_pins = zone_pins
        self._logger = logging.getLogger('valves')
        self._open_valves = set()
    
    def open_valve(self, zone_id: str) -> bool:
        self._open_valves.add(zone_id)
        self._logger.info(f"[MOCK] Opened valve: {zone_id}")
        return True
    
    def close_valve(self, zone_id: str) -> bool:
        self._open_valves.discard(zone_id)
        self._logger.info(f"[MOCK] Closed valve: {zone_id}")
        return True


# =============================================================================
# MAIN CONTROLLER
# =============================================================================

class IrrigationController:
    """
    Main controller class that orchestrates the entire system.
    """
    
    def __init__(
        self,
        config: Dict[str, Any],
        sensor_provider: Optional[SensorDataProvider] = None,
        valve_controller: Optional[ValveController] = None,
        weather_api=None,  # Type: WeatherAPI
        plant_api=None,    # Type: PlantAPI
    ):
        """
        Initialize the irrigation controller.
        
        Args:
            config: Configuration dictionary
            sensor_provider: Sensor data provider (uses mock if None)
            valve_controller: Valve controller (uses mock if None)
            weather_api: WeatherAPI instance (optional - can work without)
            plant_api: PlantAPI instance (optional - can work without)
        """
        self.config = config
        self._setup_logging()
        
        self.logger = logging.getLogger('controller')
        self.logger.info("Initializing Irrigation Controller")
        
        # Setup components
        self._setup_zones()
        self._setup_sensor_provider(sensor_provider)
        self._setup_valve_controller(valve_controller)
        self._setup_decision_engine()
        
        # API clients (optional)
        self.weather_api = weather_api
        self.plant_api = plant_api
        
        # State
        self._weather_cache = {}
        self._weather_cache_time = None
        self._plant_cache = {}
        self._plant_cache_time = {}
        self._running = False
        self._last_decision: Optional[DecisionResult] = None
        
        self.logger.info("Controller initialized successfully")
    
    def _setup_logging(self):
        """Configure logging based on config."""
        log_config = self.config.get('logging', {})
        level = getattr(logging, log_config.get('level', 'INFO'))
        log_file = log_config.get('file')
        
        handlers = [logging.StreamHandler()]
        if log_file:
            handlers.append(logging.FileHandler(log_file))
        
        logging.basicConfig(
            level=level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=handlers
        )
    
    def _setup_zones(self):
        """Parse zone configurations."""
        self.zones = []
        self.zone_pins = {}
        
        for zone_data in self.config.get('zones', []):
            self.zones.append(ZoneConfig(
                zone_id=zone_data['zone_id'],
                name=zone_data.get('name', zone_data['zone_id']),
                plant_id=zone_data.get('plant_id'),
                area_m2=zone_data.get('area_m2', 1.0),
                valve_flow_rate_lpm=zone_data.get('valve_flow_rate_lpm', 2.0),
                moisture_threshold_low=zone_data.get('moisture_threshold_low', 30.0),
                moisture_threshold_target=zone_data.get('moisture_threshold_target', 60.0),
                priority_weight=zone_data.get('priority_weight', 1.0)
            ))
            
            if 'valve_pin' in zone_data:
                self.zone_pins[zone_data['zone_id']] = zone_data['valve_pin']
        
        self.logger.info(f"Configured {len(self.zones)} zones")
    
    def _setup_sensor_provider(self, provider: Optional[SensorDataProvider]):
        """Setup sensor data provider."""
        if provider:
            self.sensor_provider = provider
        else:
            self.logger.warning("No sensor provider - using mock data")
            self.sensor_provider = MockSensorProvider(
                self.config.get('zones', [])
            )
    
    def _setup_valve_controller(self, controller: Optional[ValveController]):
        """Setup valve controller."""
        if controller:
            self.valve_controller = controller
        else:
            self.logger.warning("No valve controller - using mock")
            self.valve_controller = MockValveController(self.zone_pins)
    
    def _setup_decision_engine(self):
        """Initialize the decision engine."""
        params = self.config.get('decision_params', {})
        self.decision_engine = IrrigationDecisionEngine(
            zones=self.zones,
            params=params
        )
    
    # =========================================================================
    # DATA FETCHING
    # =========================================================================
    
    def _get_weather_data(self) -> Dict[str, Any]:
        """
        Get weather data, using cache if fresh.
        """
        refresh_minutes = self.config.get('timing', {}).get('weather_refresh_minutes', 60)
        
        # Check cache
        if (self._weather_cache_time and 
            datetime.now() - self._weather_cache_time < timedelta(minutes=refresh_minutes)):
            self.logger.debug("Using cached weather data")
            return self._weather_cache
        
        # Fetch fresh data
        if self.weather_api:
            try:
                location = self.config.get('location', {})
                city = location.get('city', 'Paris')
                elevation = location.get('elevation_m', 0)
                
                self.logger.info(f"Fetching weather data for {city}")
                data = self.weather_api.get_irrigation_data(
                    city=city,
                    max_days=3,
                    elevation=elevation
                )
                
                if data:
                    self._weather_cache = data
                    self._weather_cache_time = datetime.now()
                    return data
                    
            except Exception as e:
                self.logger.error(f"Weather API error: {e}")
        
        # Return cached data even if stale, or empty dict
        if self._weather_cache:
            self.logger.warning("Using stale weather cache")
            return self._weather_cache
        
        self.logger.warning("No weather data available - using defaults")
        return self._get_default_weather()
    
    def _get_default_weather(self) -> Dict[str, Any]:
        """Return default weather data when API unavailable."""
        today = datetime.now().strftime('%Y-%m-%d')
        return {
            today: {
                'rain': {'total_mm': 0, 'will_rain': False, 'by_period': {}},
                'temperature': {'day_min': 15, 'day_max': 25, 'by_period': {}},
                'et': {'et_mm': 3.0},
                'water_balance_mm': -3.0
            }
        }
    
    def _get_plant_data(self, zone_id: str, plant_id: int) -> Optional[Dict]:
        """
        Get plant data for a zone, using cache if fresh.
        """
        refresh_hours = self.config.get('timing', {}).get('plant_refresh_hours', 24)
        
        # Check cache
        cache_time = self._plant_cache_time.get(zone_id)
        if (cache_time and 
            datetime.now() - cache_time < timedelta(hours=refresh_hours) and
            zone_id in self._plant_cache):
            return self._plant_cache[zone_id]
        
        # Fetch fresh data
        if self.plant_api and plant_id:
            try:
                self.logger.info(f"Fetching plant data for zone {zone_id} (plant ID: {plant_id})")
                data = self.plant_api.get_irrigation_data(plant_id)
                
                if data:
                    self._plant_cache[zone_id] = data
                    self._plant_cache_time[zone_id] = datetime.now()
                    
                    # Update decision engine
                    self.decision_engine.set_plant_data(zone_id, data)
                    return data
                    
            except Exception as e:
                self.logger.error(f"Plant API error for {zone_id}: {e}")
        
        return self._plant_cache.get(zone_id)
    
    def _refresh_plant_data(self):
        """Refresh plant data for all zones with plant IDs."""
        for zone_config in self.config.get('zones', []):
            plant_id = zone_config.get('plant_id')
            if plant_id:
                self._get_plant_data(zone_config['zone_id'], plant_id)
    
    def _get_sensor_data(self) -> Dict[str, SensorReading]:
        """Get current sensor readings converted to SensorReading objects."""
        raw_readings = self.sensor_provider.get_sensor_readings()
        
        return {
            zone_id: SensorReading(
                zone_id=zone_id,
                soil_moisture_percent=data.get('soil_moisture_percent', 50.0),
                temperature_c=data.get('temperature_c', 20.0),
                humidity_percent=data.get('humidity_percent', 50.0)
            )
            for zone_id, data in raw_readings.items()
        }
    
    def _get_tank_status(self) -> TankStatus:
        """Get current tank status."""
        level = self.sensor_provider.get_tank_level()
        capacity = self.config.get('tank', {}).get('capacity_liters', 100.0)
        
        return TankStatus(
            current_level_liters=level,
            capacity_liters=capacity
        )
    
    # =========================================================================
    # IRRIGATION EXECUTION
    # =========================================================================
    
    def _execute_irrigation(self, decision: DecisionResult):
        """
        Execute irrigation commands from a decision.
        """
        if not decision.should_irrigate or not decision.commands:
            return
        
        self.logger.info(f"Executing irrigation: {len(decision.commands)} commands")
        
        for cmd in decision.commands:
            try:
                self.logger.info(
                    f"Irrigating {cmd.zone_name}: {cmd.water_amount_liters:.1f}L "
                    f"for {cmd.duration_seconds:.0f}s"
                )
                
                # Open valve
                self.valve_controller.open_valve(cmd.zone_id)
                
                # Wait for irrigation duration
                time.sleep(cmd.duration_seconds)
                
                # Close valve
                self.valve_controller.close_valve(cmd.zone_id)
                
                # Update mock sensor if using it
                if isinstance(self.sensor_provider, MockSensorProvider):
                    self.sensor_provider.simulate_irrigation(
                        cmd.zone_id, 
                        cmd.water_amount_liters
                    )
                
                self.logger.info(f"Completed irrigation for {cmd.zone_name}")
                
            except Exception as e:
                self.logger.error(f"Irrigation error for {cmd.zone_id}: {e}")
                self.valve_controller.close_valve(cmd.zone_id)
        
        self.logger.info("Irrigation cycle complete")
    
    # =========================================================================
    # MAIN CONTROL LOOP
    # =========================================================================
    
    def run_once(self, force: bool = False) -> DecisionResult:
        """
        Run a single decision cycle.
        
        Args:
            force: Bypass timing constraints
        
        Returns:
            The decision result
        """
        self.logger.info("Running decision cycle")
        
        # Gather data
        sensor_data = self._get_sensor_data()
        weather_data = self._get_weather_data()
        tank_status = self._get_tank_status()
        
        # Log current state
        self.logger.info(f"Tank level: {tank_status.level_percent:.1f}%")
        for zone_id, reading in sensor_data.items():
            self.logger.info(
                f"Zone {zone_id}: moisture={reading.soil_moisture_percent:.1f}%, "
                f"temp={reading.temperature_c:.1f}°C"
            )
        
        # Make decision
        decision = self.decision_engine.make_decisions(
            sensor_data=sensor_data,
            weather_data=weather_data,
            tank_status=tank_status,
            force=force
        )
        
        self._last_decision = decision
        
        # Execute if needed
        if decision.should_irrigate:
            self._execute_irrigation(decision)
        else:
            reason = decision.delay_reason or "No irrigation needed"
            self.logger.info(f"No irrigation: {reason}")
        
        return decision
    
    def run(self, max_iterations: Optional[int] = None):
        """
        Run the main control loop.
        
        Args:
            max_iterations: Stop after this many cycles (None = run forever)
        """
        self._running = True
        check_interval = self.config.get('timing', {}).get('check_interval_seconds', 300)
        iteration = 0
        
        self.logger.info(f"Starting control loop (interval: {check_interval}s)")
        
        # Initial plant data fetch
        self._refresh_plant_data()
        
        try:
            while self._running:
                if max_iterations and iteration >= max_iterations:
                    self.logger.info(f"Reached max iterations ({max_iterations})")
                    break
                
                try:
                    self.run_once()
                except Exception as e:
                    self.logger.error(f"Error in control cycle: {e}")
                    # Safety: close all valves on error
                    self.valve_controller.close_all()
                
                iteration += 1
                
                if self._running:
                    self.logger.debug(f"Sleeping for {check_interval}s")
                    time.sleep(check_interval)
                    
        except KeyboardInterrupt:
            self.logger.info("Received interrupt signal")
        finally:
            self.stop()
    
    def stop(self):
        """Stop the control loop and clean up."""
        self.logger.info("Stopping controller")
        self._running = False
        self.valve_controller.cleanup()
    
    # =========================================================================
    # STATUS & REPORTING
    # =========================================================================
    
    def get_status(self) -> Dict[str, Any]:
        """Get current system status."""
        sensor_data = self._get_sensor_data()
        tank = self._get_tank_status()
        
        return {
            'timestamp': datetime.now().isoformat(),
            'running': self._running,
            'tank': {
                'level_liters': tank.current_level_liters,
                'level_percent': tank.level_percent,
                'is_low': tank.is_low
            },
            'zones': {
                zone_id: {
                    'moisture_percent': reading.soil_moisture_percent,
                    'temperature_c': reading.temperature_c,
                    'humidity_percent': reading.humidity_percent
                }
                for zone_id, reading in sensor_data.items()
            },
            'last_decision': self._last_decision.to_dict() if self._last_decision else None
        }


# =============================================================================
# CLI & MAIN
# =============================================================================

def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """Load configuration from file or use defaults."""
    if config_path and Path(config_path).exists():
        with open(config_path) as f:
            user_config = json.load(f)
        # Merge with defaults
        config = {**DEFAULT_CONFIG}
        config.update(user_config)
        return config
    
    return DEFAULT_CONFIG.copy()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Smart Irrigation Controller')
    parser.add_argument('--config', type=str, help='Path to config file')
    parser.add_argument('--once', action='store_true', help='Run once and exit')
    parser.add_argument('--force', action='store_true', help='Force irrigation (bypass constraints)')
    parser.add_argument('--status', action='store_true', help='Print status and exit')
    parser.add_argument('--mock', action='store_true', help='Use mock sensors/valves')
    args = parser.parse_args()
    
    # Load config
    config = load_config(args.config)
    
    # Setup API clients (if available)
    weather_api = None
    plant_api = None
    
    try:
        from weather_api import WeatherAPI, create_api
        weather_api = create_api(silent=True)
        print("✓ Weather API initialized")
    except Exception as e:
        print(f"⚠ Weather API not available: {e}")
    
    try:
        from plant_api import PlantAPI
        plant_api = PlantAPI()
        print("✓ Plant API initialized")
    except Exception as e:
        print(f"⚠ Plant API not available: {e}")
    
    # Create controller
    controller = IrrigationController(
        config=config,
        sensor_provider=MockSensorProvider(config.get('zones', [])) if args.mock else None,
        valve_controller=None,  # Will use mock
        weather_api=weather_api,
        plant_api=plant_api
    )
    
    if args.status:
        status = controller.get_status()
        print(json.dumps(status, indent=2))
        return
    
    if args.once:
        result = controller.run_once(force=args.force)
        print(json.dumps(result.to_dict(), indent=2))
        return
    
    # Run main loop
    controller.run()


if __name__ == "__main__":
    main()
