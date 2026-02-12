"""
Demo Mode Module
================
Provides demonstration functionality for the smart irrigation system.

Demo mode allows the system to run without:
- Physical sensors (Arduino)
- Real API calls (Weather/Plant APIs)
- Time-of-day constraints
- Actual valve hardware

This is designed for:
- Classroom demonstrations
- Dashboard development and testing
- System integration testing

Usage:
    from demo_mode import DemoMode

    # Quick start with defaults
    demo = DemoMode()
    result = demo.run_cycle()
    state = demo.get_state()

    # With custom scenario
    demo = DemoMode(scenario="critical", num_zones=4)

    # With telemetry (sends data to dashboard server)
    from telemetry import TelemetrySender
    sender = TelemetrySender(server_ip="192.168.1.50")
    demo = DemoMode(scenario="critical", telemetry_sender=sender)

    # For API/Dashboard integration
    demo_data = demo.get_state()
"""

import random
import logging
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional, Dict, List, Any
from enum import Enum

# Import core modules
from water.decision_engine import (
    IrrigationDecisionEngine,
    ZoneConfig,
    SensorReading,
    TankStatus,
    DecisionResult,
)

# Import telemetry (optional — demo still works without it)
try:
    from api.telemetry import TelemetrySender

    TELEMETRY_AVAILABLE = True
except ImportError:
    TELEMETRY_AVAILABLE = False


# =============================================================================
# SCENARIOS
# =============================================================================


class DemoScenario(Enum):
    """Predefined demo scenarios."""

    NORMAL = "normal"  # Normal operation
    CRITICAL = "critical"  # One zone critically dry
    RAIN_COMING = "rain"  # Rain forecast
    ALL_HEALTHY = "healthy"  # All zones well-watered
    LOW_TANK = "low_tank"  # Tank running low
    MIXED = "mixed"  # Mix of conditions


# =============================================================================
# MOCK DATA GENERATORS
# =============================================================================


def generate_mock_weather(rain_chance: float = 0.2) -> Dict[str, Any]:
    """
    Generate mock weather data matching WeatherAPI format.

    Args:
        rain_chance: Probability of rain (0-1)

    Returns:
        Weather data dict
    """
    today = datetime.now().strftime("%Y-%m-%d")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    will_rain = random.random() < rain_chance
    rain_mm = random.uniform(5, 15) if will_rain else 0
    temp_base = random.uniform(18, 26)

    def make_day(date_str, rain_mm, will_rain, temp):
        return {
            "rain": {
                "total_mm": round(rain_mm, 1),
                "will_rain": will_rain,
                "by_period": {},
            },
            "temperature": {
                "day_min": round(temp - 5, 1),
                "day_max": round(temp + 5, 1),
                "by_period": {},
            },
            "et": {
                "et_mm": round(random.uniform(2, 4.5), 2),
                "temp_avg": round(temp, 1),
                "humidity_avg": round(random.uniform(45, 70), 1),
            },
            "water_balance_mm": round(rain_mm - random.uniform(2, 4), 2),
        }

    return {
        today: make_day(today, rain_mm, will_rain, temp_base),
        tomorrow: make_day(
            tomorrow, random.uniform(0, 5), random.random() < 0.3, temp_base + 1
        ),
    }


def generate_mock_plant(index: int) -> Dict[str, Any]:
    """Generate mock plant data matching PlantAPI format."""
    plants = [
        {"common_name": "Tomato", "watering": "Frequent", "drought_tolerant": False},
        {"common_name": "Basil", "watering": "Average", "drought_tolerant": False},
        {"common_name": "Rosemary", "watering": "Minimum", "drought_tolerant": True},
        {"common_name": "Lettuce", "watering": "Frequent", "drought_tolerant": False},
        {"common_name": "Pepper", "watering": "Average", "drought_tolerant": False},
        {"common_name": "Lavender", "watering": "Minimum", "drought_tolerant": True},
    ]
    return plants[index % len(plants)]


# =============================================================================
# DEMO MODE CLASS
# =============================================================================


@dataclass
class ZoneState:
    """Current state of a demo zone."""

    zone_id: str
    name: str
    moisture_percent: float
    temperature_c: float
    humidity_percent: float
    luminosity_lux: float = 0.0
    water_received_liters: float = 0.0


class DemoMode:
    """
    Demo mode for the smart irrigation system.

    Provides mock sensor data, weather data, and bypasses all constraints
    to allow testing and demonstration without hardware.

    Optionally sends telemetry to the dashboard server after each cycle.
    """

    # Zone names for demos
    ZONE_NAMES = [
        "Tomato Bed",
        "Herb Garden",
        "Lettuce Row",
        "Pepper Plants",
        "Squash Patch",
        "Berry Bushes",
    ]

    def __init__(
        self,
        scenario: str = "normal",
        num_zones: int = 3,
        tank_capacity: float = 100.0,
        telemetry_sender: Optional[Any] = None,
    ):
        """
        Initialize demo mode.

        Args:
            scenario: One of "normal", "critical", "rain", "healthy", "low_tank", "mixed"
            num_zones: Number of zones to simulate (1-6)
            tank_capacity: Tank capacity in liters
            telemetry_sender: Optional TelemetrySender instance for dashboard integration
        """
        self.scenario = self._parse_scenario(scenario)
        self.num_zones = min(6, max(1, num_zones))
        self.tank_capacity = tank_capacity
        self.telemetry = telemetry_sender

        self._logger = logging.getLogger("demo_mode")

        # Initialize state
        self._init_demo()

        self._logger.info(f"Demo initialized: scenario={scenario}, zones={num_zones}")
        if self.telemetry:
            self._logger.info(f"Telemetry enabled → {self.telemetry.url}")

    def _parse_scenario(self, scenario: str) -> DemoScenario:
        """Parse scenario string to enum."""
        mapping = {
            "normal": DemoScenario.NORMAL,
            "critical": DemoScenario.CRITICAL,
            "rain": DemoScenario.RAIN_COMING,
            "healthy": DemoScenario.ALL_HEALTHY,
            "low_tank": DemoScenario.LOW_TANK,
            "mixed": DemoScenario.MIXED,
        }
        return mapping.get(scenario.lower(), DemoScenario.NORMAL)

    def _init_demo(self):
        """Initialize all demo components."""
        # Create zones
        self.zones: List[ZoneConfig] = []
        self.zone_states: Dict[str, ZoneState] = {}

        for i in range(self.num_zones):
            zone_id = f"zone_{i + 1}"
            name = self.ZONE_NAMES[i]

            zone = ZoneConfig(
                zone_id=zone_id,
                name=name,
                plant_id=1000 + i,
                area_m2=random.uniform(1.0, 2.5),
                valve_flow_rate_lpm=2.0,
                moisture_threshold_low=30.0,
                moisture_threshold_target=60.0,
                priority_weight=1.0,
            )
            self.zones.append(zone)

            self.zone_states[zone_id] = ZoneState(
                zone_id=zone_id,
                name=name,
                moisture_percent=self._get_initial_moisture(i),
                temperature_c=20.0 + random.uniform(0, 6),
                humidity_percent=50.0 + random.uniform(-10, 15),
                luminosity_lux=random.uniform(200, 1000),
            )

        # Tank level (fully simulated, no hardware needed)
        self.tank_level = self._get_initial_tank_level()

        # Create decision engine with constraints bypassed
        demo_params = {
            "preferred_hours_start": 0,
            "preferred_hours_end": 24,
            "allowed_hours_start": 0,
            "allowed_hours_end": 24,
            "avoid_midday_start": 25,
            "avoid_midday_end": 0,
            "rain_threshold_mm": 999,
            "frost_threshold_c": -50,
        }

        self.engine = IrrigationDecisionEngine(zones=self.zones, params=demo_params)

        # Add plant data to engine
        for i, zone in enumerate(self.zones):
            plant_data = generate_mock_plant(i)
            self.engine.set_plant_data(zone.zone_id, plant_data)

        # Generate weather
        rain_chance = 0.8 if self.scenario == DemoScenario.RAIN_COMING else 0.2
        self.weather_data = generate_mock_weather(rain_chance)

        # Tracking
        self.cycle_count = 0
        self.total_water_used = 0.0
        self.last_result: Optional[DecisionResult] = None

    def _get_initial_moisture(self, zone_index: int) -> float:
        """Get initial moisture based on scenario."""
        if self.scenario == DemoScenario.CRITICAL:
            return random.uniform(15, 25) if zone_index == 0 else random.uniform(35, 60)
        elif self.scenario == DemoScenario.ALL_HEALTHY:
            return random.uniform(55, 75)
        elif self.scenario == DemoScenario.MIXED:
            return random.choice(
                [random.uniform(20, 30), random.uniform(40, 55), random.uniform(60, 75)]
            )
        elif self.scenario == DemoScenario.LOW_TANK:
            return random.uniform(25, 45)
        else:
            return random.uniform(30, 55)

    def _get_initial_tank_level(self) -> float:
        """Get initial tank level based on scenario."""
        if self.scenario == DemoScenario.LOW_TANK:
            return self.tank_capacity * 0.15
        else:
            return self.tank_capacity * random.uniform(0.6, 0.9)

    # =========================================================================
    # MAIN OPERATIONS
    # =========================================================================

    def run_cycle(self) -> DecisionResult:
        """
        Run a single demo irrigation cycle.

        Returns:
            DecisionResult from the engine
        """
        self.cycle_count += 1
        self._logger.info(f"Demo cycle #{self.cycle_count}")

        # Build sensor readings
        sensor_data = {}
        for zone_id, state in self.zone_states.items():
            sensor_data[zone_id] = SensorReading(
                zone_id=zone_id,
                soil_moisture_percent=state.moisture_percent + random.uniform(-1, 1),
                temperature_c=state.temperature_c + random.uniform(-0.5, 0.5),
                humidity_percent=state.humidity_percent + random.uniform(-2, 2),
                luminosity_lux=state.luminosity_lux + random.uniform(-20, 20),
            )

        # Tank status (fully simulated)
        tank_status = TankStatus(
            current_level_liters=self.tank_level, capacity_liters=self.tank_capacity
        )

        # Make decision
        result = self.engine.make_decisions(
            sensor_data=sensor_data,
            weather_data=self.weather_data,
            tank_status=tank_status,
            force=True,  # Always force in demo mode
        )

        # Apply irrigation effects
        if result.should_irrigate:
            self._apply_irrigation(result)

        self.last_result = result

        # Send telemetry to dashboard server
        self._send_telemetry(sensor_data, tank_status, result)

        return result

    def _apply_irrigation(self, result: DecisionResult):
        """Apply irrigation effects to zone states."""
        for cmd in result.commands:
            if cmd.zone_id in self.zone_states:
                state = self.zone_states[cmd.zone_id]
                zone = next(z for z in self.zones if z.zone_id == cmd.zone_id)

                # Increase moisture
                moisture_increase = (cmd.water_amount_liters / zone.area_m2) * 2
                state.moisture_percent = min(
                    90, state.moisture_percent + moisture_increase
                )
                state.water_received_liters += cmd.water_amount_liters

        # Update tank
        self.tank_level = max(0, self.tank_level - result.total_water_liters)
        self.total_water_used += result.total_water_liters

    def _send_telemetry(
        self,
        sensor_data: Dict[str, SensorReading],
        tank_status: TankStatus,
        result: DecisionResult,
    ):
        """Send telemetry after a cycle if sender is available."""
        if self.telemetry is None:
            return

        try:
            # Convert SensorReading objects to raw dicts for telemetry
            raw_sensors = {
                zone_id: {
                    "soil_moisture_percent": reading.soil_moisture_percent,
                    "temperature_c": reading.temperature_c,
                    "humidity_percent": reading.humidity_percent,
                    "luminosity_lux": reading.luminosity_lux,
                }
                for zone_id, reading in sensor_data.items()
            }

            self.telemetry.send(
                sensor_data=raw_sensors,
                tank_level_liters=tank_status.current_level_liters,
                tank_capacity_liters=tank_status.capacity_liters,
                weather_data=self.weather_data,
                decision_result=result.to_dict(),
                print_to_console=True,
            )
        except Exception as e:
            self._logger.warning(f"Telemetry send failed: {e}")

    def simulate_time_passage(self, hours: float = 4):
        """
        Simulate time passing (moisture decreases).

        Args:
            hours: Hours to simulate
        """
        for state in self.zone_states.values():
            loss = random.uniform(0.5, 1.5) * hours
            state.moisture_percent = max(10, state.moisture_percent - loss)

        self._logger.info(f"Simulated {hours} hours passing")

    def refill_tank(self, amount: Optional[float] = None) -> float:
        """
        Refill the tank.

        Args:
            amount: Liters to add (None = full refill)

        Returns:
            New tank level
        """
        if amount is None:
            self.tank_level = self.tank_capacity
        else:
            self.tank_level = min(self.tank_capacity, self.tank_level + amount)

        return self.tank_level

    def set_zone_moisture(self, zone_id: str, moisture: float):
        """Manually set zone moisture for testing."""
        if zone_id in self.zone_states:
            self.zone_states[zone_id].moisture_percent = max(0, min(100, moisture))

    # =========================================================================
    # STATE OUTPUT
    # =========================================================================

    def get_state(self) -> Dict[str, Any]:
        """
        Get complete demo state for dashboard/API.

        Returns:
            Dictionary with all state information
        """
        today = datetime.now().strftime("%Y-%m-%d")
        today_weather = self.weather_data.get(today, {})

        return {
            "demo_info": {
                "is_demo": True,
                "scenario": self.scenario.value,
                "cycle_count": self.cycle_count,
                "total_water_used_liters": round(self.total_water_used, 2),
                "telemetry_enabled": self.telemetry is not None,
            },
            "tank": {
                "level_liters": round(self.tank_level, 1),
                "capacity_liters": self.tank_capacity,
                "level_percent": round((self.tank_level / self.tank_capacity) * 100, 1),
            },
            "zones": [
                {
                    "zone_id": state.zone_id,
                    "name": state.name,
                    "moisture_percent": round(state.moisture_percent, 1),
                    "temperature_c": round(state.temperature_c, 1),
                    "humidity_percent": round(state.humidity_percent, 1),
                    "luminosity_lux": round(state.luminosity_lux, 1),
                    "water_received_liters": round(state.water_received_liters, 2),
                }
                for state in self.zone_states.values()
            ],
            "weather": {
                "rain_mm": today_weather.get("rain", {}).get("total_mm", 0),
                "will_rain": today_weather.get("rain", {}).get("will_rain", False),
                "temp_min": today_weather.get("temperature", {}).get("day_min"),
                "temp_max": today_weather.get("temperature", {}).get("day_max"),
                "is_mock": True,
            },
            "last_decision": self.last_result.to_dict() if self.last_result else None,
            "timestamp": datetime.now().isoformat(),
        }


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def create_demo(
    scenario: str = "normal", num_zones: int = 3, server_ip: Optional[str] = None
) -> DemoMode:
    """
    Quick demo creation.

    Args:
        scenario: Demo scenario name
        num_zones: Number of zones
        server_ip: Dashboard server IP (None = no telemetry)
    """
    telemetry = None
    if server_ip and TELEMETRY_AVAILABLE:
        telemetry = TelemetrySender(server_ip=server_ip)

    return DemoMode(scenario=scenario, num_zones=num_zones, telemetry_sender=telemetry)


def run_demo_mode(args):
    """Run in demo mode using the demo module."""
    import json
    import time

    print("\n" + "=" * 60)
    print("SMART IRRIGATION - DEMO MODE")
    print(f"Scenario: {args.scenario.upper()}")
    print("=" * 60)

    # Setup telemetry for demo mode if server IP provided
    telemetry = None
    if getattr(args, "server_ip", None):
        telemetry = TelemetrySender(server_ip=args.server_ip)
        print(f"✓ Telemetry enabled -> {telemetry.telemetry_url}")

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
                    status = "⚠️ " if zone["moisture_percent"] < 35 else "✓"
                    print(f"  {zone['name']}: {zone['moisture_percent']:.0f}% {status}")

                if result.should_irrigate:
                    print(
                        f"-> Irrigated {len(result.commands)} zones ({result.total_water_liters:.1f}L)"
                    )

                demo.simulate_time_passage(hours=4)
                time.sleep(2)

        except KeyboardInterrupt:
            print("\nDemo stopped")

    print("\n✓ Demo complete")


def quick_demo_cycle(
    scenario: str = "normal", server_ip: Optional[str] = None
) -> Dict[str, Any]:
    """Run a single demo cycle and return state."""
    demo = create_demo(scenario, server_ip=server_ip)
    demo.run_cycle()
    return demo.get_state()


# =============================================================================
# STANDALONE TESTING
# =============================================================================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    print("\n" + "=" * 60)
    print("DEMO MODE - Testing All Scenarios")
    print("=" * 60)

    for scenario in ["normal", "critical", "rain", "healthy", "low_tank", "mixed"]:
        print(f"\n--- Scenario: {scenario.upper()} ---")

        demo = create_demo(scenario=scenario, num_zones=3)
        result = demo.run_cycle()
        state = demo.get_state()

        # Display results
        print(f"Tank: {state['tank']['level_percent']:.0f}%")
        print("Zones:", end=" ")
        for zone in state["zones"]:
            status = "⚠️" if zone["moisture_percent"] < 35 else "✓"
            print(
                f"{zone['name'].split()[0]}:{zone['moisture_percent']:.0f}%{status}",
                end=" ",
            )
        print()

        print(f"Decision: ", end="")
        if result.should_irrigate:
            print(
                f"Irrigate {len(result.commands)} zone(s), {result.total_water_liters:.1f}L total"
            )
        else:
            print(f"Skip - {result.delay_reason or 'All healthy'}")

    print("\n" + "=" * 60)
    print("✓ Demo mode working correctly")
    print("=" * 60)
