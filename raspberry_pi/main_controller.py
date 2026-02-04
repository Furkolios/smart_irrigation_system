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
from decision_engine import (
    IrrigationDecisionEngine,
    ZoneConfig,
    SensorReading,
    TankStatus,
    DecisionResult
)

# Hardware interfaces
from sensor_providers import SensorDataProvider, ArduinoSensorProvider, MockSensorProvider
from valve_controller import ValveController, MockValveController, create_valve_controller
from tank_sensor import get_tank_level

# API modules (optional)
try:
    from weather_api import WeatherAPI, create_api as create_weather_api
    WEATHER_API_AVAILABLE = True
except ImportError:
    WEATHER_API_AVAILABLE = False

try:
    from plant_api import PlantAPI
    PLANT_API_AVAILABLE = True
except ImportError:
    PLANT_API_AVAILABLE = False


# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_CONFIG = {
    "location": {
        "city": "Paris",
        "elevation_m": 35
    },
    "tank": {
        "capacity_liters": 50.0
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
            "valve_pin": 17
        }
    ],
    "timing": {
        "check_interval_seconds": 600,  # 10 minutes
    },
    "logging": {
        "level": "INFO",
        "file": "irrigation.log"
    }
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
    """
    
    def __init__(
        self,
        config: Dict[str, Any],
        sensor_provider: Optional[SensorDataProvider] = None,
        valve_controller: Optional[ValveController] = None,
        weather_api: Optional[Any] = None,
        plant_api: Optional[Any] = None
    ):
        """
        Initialize the controller.
        
        Args:
            config: Configuration dictionary
            sensor_provider: Sensor data provider (uses mock if None)
            valve_controller: Valve controller (uses mock if None)
            weather_api: WeatherAPI instance (optional)
            plant_api: PlantAPI instance (optional)
        """
        self.config = config
        self._setup_logging()
        
        self.logger = logging.getLogger('controller')
        self.logger.info("Initializing Irrigation Controller")
        
        # Parse zones
        self.zones = self._parse_zones()
        self.zone_pins = {
            z['zone_id']: z['valve_pin'] 
            for z in config.get('zones', []) 
            if 'valve_pin' in z
        }
        
        # Setup components
        self.sensor_provider = sensor_provider or MockSensorProvider(
            zone_ids=[z.zone_id for z in self.zones]
        )
        self.valve_controller = valve_controller or MockValveController(self.zone_pins)
        
        # APIs
        self.weather_api = weather_api
        self.plant_api = plant_api
        
        # Decision engine
        self.decision_engine = IrrigationDecisionEngine(zones=self.zones)
        
        # Load plant data if API available
        if self.plant_api:
            self._load_plant_data()
        
        # State
        self._running = False
        self._last_decision: Optional[DecisionResult] = None
        
        self.logger.info("Controller initialized successfully")
    
    def _setup_logging(self):
        """Configure logging."""
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
    
    def _parse_zones(self) -> list:
        """Parse zone configurations."""
        zones = []
        for z in self.config.get('zones', []):
            zones.append(ZoneConfig(
                zone_id=z['zone_id'],
                name=z.get('name', z['zone_id']),
                plant_id=z.get('plant_id'),
                area_m2=z.get('area_m2', 1.0),
                valve_flow_rate_lpm=z.get('valve_flow_rate_lpm', 2.0),
                moisture_threshold_low=z.get('moisture_threshold_low', 30.0),
                moisture_threshold_target=z.get('moisture_threshold_target', 60.0),
                priority_weight=z.get('priority_weight', 1.0)
            ))
        self.logger.info(f"Configured {len(zones)} zones")
        return zones
    
    def _load_plant_data(self):
        """Load plant data from API for all zones."""
        for zone_config in self.config.get('zones', []):
            plant_id = zone_config.get('plant_id')
            if plant_id and self.plant_api:
                try:
                    data = self.plant_api.get_irrigation_data(plant_id)
                    if data:
                        self.decision_engine.set_plant_data(zone_config['zone_id'], data)
                        self.logger.info(f"Loaded plant data for {zone_config['zone_id']}")
                except Exception as e:
                    self.logger.error(f"Failed to load plant data: {e}")
    
    def _get_weather_data(self) -> Dict[str, Any]:
        """Get weather data from API or return defaults."""
        if self.weather_api:
            try:
                location = self.config.get('location', {})
                data = self.weather_api.get_irrigation_data(
                    city=location.get('city', 'Paris'),
                    max_days=3,
                    elevation=location.get('elevation_m', 0)
                )
                if data:
                    return data
            except Exception as e:
                self.logger.error(f"Weather API error: {e}")
        
        # Return defaults
        today = datetime.now().strftime('%Y-%m-%d')
        return {
            today: {
                'rain': {'total_mm': 0, 'will_rain': False, 'by_period': {}},
                'temperature': {'day_min': 15, 'day_max': 25, 'by_period': {}},
                'et': {'et_mm': 3.0},
                'water_balance_mm': -3.0
            }
        }
    
    def _get_sensor_data(self) -> Dict[str, SensorReading]:
        """Get sensor readings from provider."""
        raw = self.sensor_provider.get_sensor_readings()
        return {
            zone_id: SensorReading(
                zone_id=zone_id,
                soil_moisture_percent=data.get('soil_moisture_percent', 50.0),
                temperature_c=data.get('temperature_c', 20.0),
                humidity_percent=data.get('humidity_percent', 50.0)
            )
            for zone_id, data in raw.items()
        }
    
    def _get_tank_status(self) -> TankStatus:
        """Get tank status."""
        level = get_tank_level()
        capacity = self.config.get('tank', {}).get('capacity_liters', 50.0)
        return TankStatus(current_level_liters=level, capacity_liters=capacity)
    
    def _execute_irrigation(self, decision: DecisionResult):
        """Execute irrigation commands."""
        if not decision.should_irrigate or not decision.commands:
            return
        
        self.logger.info(f"Executing {len(decision.commands)} irrigation commands")
        
        for cmd in decision.commands:
            try:
                self.logger.info(f"Irrigating {cmd.zone_name}: {cmd.water_amount_liters:.1f}L")
                
                self.valve_controller.open_valve(cmd.zone_id)
                time.sleep(cmd.duration_seconds)
                self.valve_controller.close_valve(cmd.zone_id)
                
                # Update mock sensor if using it
                if isinstance(self.sensor_provider, MockSensorProvider):
                    zone = next((z for z in self.zones if z.zone_id == cmd.zone_id), None)
                    area = zone.area_m2 if zone else 1.0
                    self.sensor_provider.simulate_irrigation(cmd.zone_id, cmd.water_amount_liters, area)
                
                self.logger.info(f"Completed: {cmd.zone_name}")
                
            except Exception as e:
                self.logger.error(f"Irrigation error for {cmd.zone_id}: {e}")
                self.valve_controller.close_valve(cmd.zone_id)
        
        self.logger.info("Irrigation cycle complete")
    
    # =========================================================================
    # PUBLIC METHODS
    # =========================================================================
    
    def run_once(self, force: bool = False) -> DecisionResult:
        """Run a single decision cycle."""
        self.logger.info("Running decision cycle")
        
        # Gather data
        sensor_data = self._get_sensor_data()
        weather_data = self._get_weather_data()
        tank_status = self._get_tank_status()
        
        # Log state
        self.logger.info(f"Tank: {tank_status.level_percent:.1f}%")
        for zone_id, reading in sensor_data.items():
            self.logger.info(f"{zone_id}: moisture={reading.soil_moisture_percent:.1f}%")
        
        # Make decision
        decision = self.decision_engine.make_decisions(
            sensor_data=sensor_data,
            weather_data=weather_data,
            tank_status=tank_status,
            force=force
        )
        
        self._last_decision = decision
        
        # Execute
        if decision.should_irrigate:
            self._execute_irrigation(decision)
        else:
            self.logger.info(f"No irrigation: {decision.delay_reason or 'Not needed'}")
        
        return decision
    
    def run(self, max_iterations: Optional[int] = None):
        """Run the main control loop."""
        self._running = True
        interval = self.config.get('timing', {}).get('check_interval_seconds', 600)
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
            'timestamp': datetime.now().isoformat(),
            'running': self._running,
            'tank': {
                'level_liters': tank.current_level_liters,
                'level_percent': tank.level_percent,
                'is_low': tank.is_low
            },
            'zones': {
                zone_id: {
                    'moisture_percent': r.soil_moisture_percent,
                    'temperature_c': r.temperature_c,
                    'humidity_percent': r.humidity_percent
                }
                for zone_id, r in sensor_data.items()
            },
            'last_decision': self._last_decision.to_dict() if self._last_decision else None
        }


# =============================================================================
# CLI & MAIN
# =============================================================================

def run_demo_mode(args):
    """Run in demo mode using the demo module."""
    from demo_mode import DemoMode
    
    print("\n" + "=" * 60)
    print("SMART IRRIGATION - DEMO MODE")
    print(f"Scenario: {args.scenario.upper()}")
    print("=" * 60)
    
    demo = DemoMode(
        scenario=args.scenario,
        num_zones=args.zones
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
                for zone in state['zones']:
                    status = "⚠️" if zone['moisture_percent'] < 35 else "✓"
                    print(f"  {zone['name']}: {zone['moisture_percent']:.0f}% {status}")
                
                if result.should_irrigate:
                    print(f"→ Irrigated {len(result.commands)} zones ({result.total_water_liters:.1f}L)")
                
                demo.simulate_time_passage(hours=4)
                time.sleep(2)
                
        except KeyboardInterrupt:
            print("\nDemo stopped")
    
    print("\n✓ Demo complete")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Smart Irrigation Controller')
    parser.add_argument('--config', type=str, help='Path to config file')
    parser.add_argument('--once', action='store_true', help='Run once and exit')
    parser.add_argument('--force', action='store_true', help='Force irrigation')
    parser.add_argument('--status', action='store_true', help='Print status')
    parser.add_argument('--mock', action='store_true', help='Use mock sensors')
    parser.add_argument('--demo', action='store_true', help='Run demo mode')
    parser.add_argument('--scenario', type=str, default='normal',
                       choices=['normal', 'critical', 'rain', 'healthy', 'low_tank', 'mixed'],
                       help='Demo scenario')
    parser.add_argument('--zones', type=int, default=3, help='Number of zones')
    args = parser.parse_args()
    
    # Demo mode
    if args.demo:
        run_demo_mode(args)
        return
    
    # Load config
    config = load_config(args.config)
    
    # Setup APIs
    weather_api = None
    plant_api = None
    
    if WEATHER_API_AVAILABLE:
        try:
            weather_api = create_weather_api(silent=True)
            print("✓ Weather API initialized")
        except Exception as e:
            print(f"⚠ Weather API unavailable: {e}")
    
    if PLANT_API_AVAILABLE:
        try:
            plant_api = PlantAPI()
            print("✓ Plant API initialized")
        except Exception as e:
            print(f"⚠ Plant API unavailable: {e}")
    
    # Create controller
    zone_ids = [z['zone_id'] for z in config.get('zones', [])]
    
    controller = IrrigationController(
        config=config,
        sensor_provider=MockSensorProvider(zone_ids) if args.mock else None,
        valve_controller=None,
        weather_api=weather_api,
        plant_api=plant_api
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
