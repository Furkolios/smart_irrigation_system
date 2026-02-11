"""
Water Distribution Decision Engine
==================================
Core decision-making module for the smart irrigation system.

Architecture:
    1. Calculate water need scores for each zone
    2. Build priority queue (most urgent zones first)
    3. Allocate water respecting tank constraints
    4. Check timing/weather constraints before execution

Designed to run on Raspberry Pi, consuming data from:
    - Arduino sensors (soil moisture, temperature, humidity)
    - Weather API (rain forecast, ET₀)
    - Plant API (species-specific water requirements)

Usage:
    from decision_engine import IrrigationDecisionEngine
    
    engine = IrrigationDecisionEngine(zones_config)
    decisions = engine.make_decisions(sensor_data, weather_data, plant_data)
"""

import logging
from datetime import datetime, time
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any
from enum import Enum
import heapq


# =============================================================================
# CONFIGURATION & DATA CLASSES
# =============================================================================

class WateringLevel(Enum):
    """Watering requirement levels from Perenual API."""
    NONE = "None"
    MINIMUM = "Minimum"
    AVERAGE = "Average"
    FREQUENT = "Frequent"
    
    @classmethod
    def from_string(cls, value: str) -> 'WateringLevel':
        """Parse watering level from API response."""
        if value is None:
            return cls.AVERAGE
        normalized = value.strip().capitalize()
        for level in cls:
            if level.value == normalized:
                return level
        return cls.AVERAGE


@dataclass
class ZoneConfig:
    """Configuration for a single irrigation zone."""
    zone_id: str
    name: str
    plant_id: Optional[int] = None  # Perenual plant ID
    area_m2: float = 1.0  # Zone area in square meters
    valve_flow_rate_lpm: float = 2.0  # Liters per minute
    
    # Thresholds (can be overridden by plant data or adaptive learning)
    moisture_threshold_low: float = 30.0  # Below this = urgent
    moisture_threshold_target: float = 60.0  # Ideal moisture level
    
    # Priority weight (higher = more important, e.g., for valuable crops)
    priority_weight: float = 1.0


@dataclass
class SensorReading:
    """Sensor data from Arduino for a single zone."""
    zone_id: str
    soil_moisture_percent: float  # 0-100
    temperature_c: float
    humidity_percent: float
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class TankStatus:
    """Water tank status."""
    current_level_liters: float
    capacity_liters: float
    
    @property
    def level_percent(self) -> float:
        if self.capacity_liters <= 0:
            return 0.0
        return (self.current_level_liters / self.capacity_liters) * 100
    
    @property
    def is_low(self) -> bool:
        return self.level_percent < 20
    
    @property
    def is_critical(self) -> bool:
        return self.level_percent < 10


@dataclass
class IrrigationCommand:
    """Output command for a single zone."""
    zone_id: str
    zone_name: str
    water_amount_liters: float
    duration_seconds: float
    priority_score: float
    reason: str
    
    def __lt__(self, other):
        """For priority queue comparison (higher score = higher priority)."""
        return self.priority_score > other.priority_score


@dataclass 
class DecisionResult:
    """Complete decision output from the engine."""
    timestamp: datetime
    should_irrigate: bool
    delay_reason: Optional[str]
    commands: List[IrrigationCommand]
    total_water_liters: float
    tank_after_liters: float
    weather_summary: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/API."""
        return {
            'timestamp': self.timestamp.isoformat(),
            'should_irrigate': self.should_irrigate,
            'delay_reason': self.delay_reason,
            'commands': [
                {
                    'zone_id': cmd.zone_id,
                    'zone_name': cmd.zone_name,
                    'water_liters': round(cmd.water_amount_liters, 2),
                    'duration_seconds': round(cmd.duration_seconds, 1),
                    'priority_score': round(cmd.priority_score, 2),
                    'reason': cmd.reason
                }
                for cmd in self.commands
            ],
            'total_water_liters': round(self.total_water_liters, 2),
            'tank_after_liters': round(self.tank_after_liters, 2),
            'weather_summary': self.weather_summary
        }


# =============================================================================
# DECISION ENGINE
# =============================================================================

class IrrigationDecisionEngine:
    """
    Rule-based irrigation decision engine with priority queue allocation.
    
    The engine follows this logic:
    1. Check global constraints (time of day, recent rain, frost risk)
    2. Calculate water need score for each zone
    3. Build priority queue sorted by urgency
    4. Allocate water to zones respecting tank constraints
    5. Return irrigation commands
    """
    
    # Default parameters (can be overridden in constructor)
    DEFAULT_PARAMS = {
        # Water need calculation weights
        'moisture_deficit_weight': 1.0,
        'plant_factor_weight': 1.0,
        'weather_factor_weight': 0.8,
        'et_factor_weight': 0.5,
        
        # Tank management
        'tank_reserve_percent': 10.0,  # Keep this much in reserve
        'emergency_reserve_percent': 5.0,  # Absolute minimum
        
        # Timing constraints
        'preferred_hours_start': 6,  # 6 AM
        'preferred_hours_end': 9,    # 9 AM
        'allowed_hours_start': 5,    # 5 AM (earliest allowed)
        'allowed_hours_end': 20,     # 8 PM (latest allowed)
        'avoid_midday_start': 11,    # 11 AM
        'avoid_midday_end': 15,      # 3 PM
        
        # Weather thresholds
        'rain_threshold_mm': 5.0,  # Skip if this much rain expected
        'recent_rain_threshold_mm': 10.0,  # Skip if this much fell recently
        'frost_threshold_c': 2.0,  # Delay if temp below this
        
        # Urgency thresholds
        'urgency_threshold_critical': 80.0,  # Water immediately regardless of time
        'urgency_threshold_high': 50.0,
        'urgency_threshold_low': 10.0,  # Skip if below this
        
        # Water calculation
        'base_water_per_m2_liters': 5.0,  # Base watering amount
        'max_single_irrigation_liters': 50.0,  # Max per zone per cycle
    }
    
    # Watering level multipliers (from Perenual data)
    WATERING_MULTIPLIERS = {
        WateringLevel.NONE: 0.0,
        WateringLevel.MINIMUM: 0.5,
        WateringLevel.AVERAGE: 1.0,
        WateringLevel.FREQUENT: 1.5,
    }
    
    def __init__(
        self,
        zones: List[ZoneConfig],
        params: Optional[Dict[str, float]] = None,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize the decision engine.
        
        Args:
            zones: List of zone configurations
            params: Override default parameters
            logger: Logger instance
        """
        self.zones = {z.zone_id: z for z in zones}
        self.params = {**self.DEFAULT_PARAMS, **(params or {})}
        self.logger = logger or logging.getLogger('decision_engine')
        
        # Cache for plant data (populated via set_plant_data)
        self._plant_cache: Dict[str, Dict] = {}
    
    def set_plant_data(self, zone_id: str, plant_data: Dict[str, Any]) -> None:
        """
        Cache plant data for a zone (from Perenual API).
        
        Args:
            zone_id: Zone identifier
            plant_data: Data from PlantAPI.get_irrigation_data()
        """
        self._plant_cache[zone_id] = plant_data
        
        # Update zone thresholds based on plant data if available
        if zone_id in self.zones and plant_data:
            zone = self.zones[zone_id]
            
            # Adjust thresholds based on drought tolerance
            if plant_data.get('drought_tolerant'):
                zone.moisture_threshold_low = max(20.0, zone.moisture_threshold_low - 10)
                zone.moisture_threshold_target = max(40.0, zone.moisture_threshold_target - 10)
    
    # =========================================================================
    # MAIN DECISION METHOD
    # =========================================================================
    
    def make_decisions(
        self,
        sensor_data: Dict[str, SensorReading],
        weather_data: Dict[str, Any],
        tank_status: TankStatus,
        force: bool = False
    ) -> DecisionResult:
        """
        Make irrigation decisions based on current conditions.
        
        Args:
            sensor_data: Dict mapping zone_id to SensorReading
            weather_data: Weather forecast from WeatherAPI.get_irrigation_data()
            tank_status: Current tank water level
            force: If True, bypass timing constraints
        
        Returns:
            DecisionResult with irrigation commands
        """
        now = datetime.now()
        self.logger.info(f"Making irrigation decisions at {now}")
        
        # Extract today's weather
        today_str = now.strftime('%Y-%m-%d')
        today_weather = weather_data.get(today_str, {})
        
        weather_summary = {
            'date': today_str,
            'rain_mm': today_weather.get('rain', {}).get('total_mm', 0),
            'will_rain': today_weather.get('rain', {}).get('will_rain', False),
            'et_mm': today_weather.get('et', {}).get('et_mm', 0),
            'water_balance_mm': today_weather.get('water_balance_mm', 0),
            'temp_min': today_weather.get('temperature', {}).get('day_min'),
            'temp_max': today_weather.get('temperature', {}).get('day_max'),
        }
        
        # Check global constraints
        if not force:
            can_irrigate, delay_reason = self._check_global_constraints(
                now, today_weather, sensor_data
            )
            if not can_irrigate:
                self.logger.info(f"Irrigation delayed: {delay_reason}")
                return DecisionResult(
                    timestamp=now,
                    should_irrigate=False,
                    delay_reason=delay_reason,
                    commands=[],
                    total_water_liters=0,
                    tank_after_liters=tank_status.current_level_liters,
                    weather_summary=weather_summary
                )
        
        # Calculate need scores and build priority queue
        priority_queue = self._build_priority_queue(sensor_data, today_weather)
        
        # Allocate water respecting tank constraints
        commands = self._allocate_water(priority_queue, tank_status)
        
        # Calculate totals
        total_water = sum(cmd.water_amount_liters for cmd in commands)
        tank_after = tank_status.current_level_liters - total_water
        
        result = DecisionResult(
            timestamp=now,
            should_irrigate=len(commands) > 0,
            delay_reason=None,
            commands=commands,
            total_water_liters=total_water,
            tank_after_liters=tank_after,
            weather_summary=weather_summary
        )
        
        self.logger.info(
            f"Decision complete: {len(commands)} zones, "
            f"{total_water:.1f}L total, tank will be at {tank_after:.1f}L"
        )
        
        return result
    
    # =========================================================================
    # CONSTRAINT CHECKING
    # =========================================================================
    
    def _check_global_constraints(
        self,
        now: datetime,
        weather: Dict[str, Any],
        sensor_data: Dict[str, SensorReading]
    ) -> tuple[bool, Optional[str]]:
        """
        Check if irrigation should proceed or be delayed.
        
        Returns:
            (can_irrigate, delay_reason) tuple
        """
        hour = now.hour
        
        # Check for critical urgency (overrides time constraints)
        has_critical = any(
            self._calculate_urgency_score(reading, weather) >= 
            self.params['urgency_threshold_critical']
            for reading in sensor_data.values()
        )
        
        if has_critical:
            self.logger.warning("Critical urgency detected - overriding constraints")
            # Still check weather safety
        else:
            # Time of day check
            if hour < self.params['allowed_hours_start']:
                return False, f"Too early ({hour}:00) - waiting until {self.params['allowed_hours_start']}:00"
            
            if hour >= self.params['allowed_hours_end']:
                return False, f"Too late ({hour}:00) - waiting until tomorrow"
            
            if self.params['avoid_midday_start'] <= hour < self.params['avoid_midday_end']:
                return False, f"Avoiding midday evaporation ({hour}:00) - waiting until {self.params['avoid_midday_end']}:00"
        
        # Rain check
        rain_data = weather.get('rain', {})
        expected_rain = rain_data.get('total_mm', 0)
        will_rain = rain_data.get('will_rain', False)
        
        if will_rain and expected_rain >= self.params['rain_threshold_mm']:
            return False, f"Rain expected ({expected_rain:.1f}mm) - delaying irrigation"
        
        # Frost check
        temp_data = weather.get('temperature', {})
        temp_min = temp_data.get('day_min')
        
        if temp_min is not None and temp_min < self.params['frost_threshold_c']:
            return False, f"Frost risk (min temp {temp_min}°C) - delaying irrigation"
        
        return True, None
    
    # =========================================================================
    # NEED CALCULATION
    # =========================================================================
    
    def _calculate_urgency_score(
        self,
        reading: SensorReading,
        weather: Dict[str, Any]
    ) -> float:
        """
        Calculate water urgency score for a zone (0-100 scale).
        
        Higher score = more urgent need for water.
        """
        zone = self.zones.get(reading.zone_id)
        if not zone:
            return 0.0
        
        # Base: moisture deficit
        current = reading.soil_moisture_percent
        target = zone.moisture_threshold_target
        low = zone.moisture_threshold_low
        
        if current >= target:
            moisture_deficit = 0.0
        elif current <= low:
            # Scale from 50-100 based on how far below threshold
            deficit_ratio = (low - current) / low
            moisture_deficit = 50.0 + (50.0 * deficit_ratio)
        else:
            # Scale from 0-50 based on distance from target
            deficit_ratio = (target - current) / (target - low)
            moisture_deficit = 50.0 * deficit_ratio
        
        # Plant factor (from Perenual data)
        plant_data = self._plant_cache.get(reading.zone_id, {})
        watering_level = WateringLevel.from_string(plant_data.get('watering'))
        plant_multiplier = self.WATERING_MULTIPLIERS.get(watering_level, 1.0)
        
        # Weather factor (reduce if rain coming)
        rain_data = weather.get('rain', {})
        rain_chance = 1.0 if rain_data.get('will_rain') else 0.0
        expected_rain = rain_data.get('total_mm', 0)
        weather_factor = max(0.2, 1.0 - (rain_chance * 0.5) - (expected_rain / 20.0))
        
        # ET factor (higher ET = more need)
        et_mm = weather.get('et', {}).get('et_mm', 3.0)  # Default ~3mm/day
        et_factor = et_mm / 5.0  # Normalize around typical value
        
        # Combine factors
        score = moisture_deficit * self.params['moisture_deficit_weight']
        score *= (plant_multiplier * self.params['plant_factor_weight'])
        score *= (weather_factor * self.params['weather_factor_weight'])
        score *= (1.0 + (et_factor - 1.0) * self.params['et_factor_weight'])
        
        # Apply zone priority weight
        score *= zone.priority_weight
        
        return min(100.0, max(0.0, score))
    
    def _calculate_water_amount(
        self,
        zone: ZoneConfig,
        urgency_score: float,
        weather: Dict[str, Any]
    ) -> float:
        """
        Calculate how much water a zone needs (in liters).
        """
        if urgency_score < self.params['urgency_threshold_low']:
            return 0.0
        
        # Base amount from zone area
        base_amount = zone.area_m2 * self.params['base_water_per_m2_liters']
        
        # Scale by urgency (50% at threshold, 100% at max urgency)
        urgency_ratio = urgency_score / 100.0
        scaled_amount = base_amount * (0.5 + 0.5 * urgency_ratio)
        
        # Adjust for plant type
        plant_data = self._plant_cache.get(zone.zone_id, {})
        watering_level = WateringLevel.from_string(plant_data.get('watering'))
        plant_multiplier = self.WATERING_MULTIPLIERS.get(watering_level, 1.0)
        scaled_amount *= plant_multiplier
        
        # Reduce if significant rain expected
        rain_mm = weather.get('rain', {}).get('total_mm', 0)
        if rain_mm > 2:
            # Reduce by estimated rain contribution (rough: 1mm rain ≈ 1L/m²)
            rain_contribution = min(rain_mm * zone.area_m2, scaled_amount * 0.5)
            scaled_amount -= rain_contribution
        
        # Cap at maximum
        return min(scaled_amount, self.params['max_single_irrigation_liters'])
    
    def _build_priority_queue(
        self,
        sensor_data: Dict[str, SensorReading],
        weather: Dict[str, Any]
    ) -> List[tuple[float, str, float, str]]:
        """
        Build priority queue of zones sorted by urgency.
        
        Returns:
            List of (neg_score, zone_id, water_amount, reason) tuples
            (negative score because heapq is min-heap)
        """
        queue = []
        
        for zone_id, reading in sensor_data.items():
            zone = self.zones.get(zone_id)
            if not zone:
                self.logger.warning(f"Unknown zone: {zone_id}")
                continue
            
            # Calculate urgency
            urgency = self._calculate_urgency_score(reading, weather)
            
            # Skip if below threshold
            if urgency < self.params['urgency_threshold_low']:
                self.logger.debug(f"Zone {zone_id}: urgency {urgency:.1f} below threshold, skipping")
                continue
            
            # Calculate water amount
            water_amount = self._calculate_water_amount(zone, urgency, weather)
            
            if water_amount <= 0:
                continue
            
            # Build explanation
            reason = self._build_reason(zone, reading, urgency, weather)
            
            # Add to queue (negative score for max-heap behavior)
            heapq.heappush(queue, (-urgency, zone_id, water_amount, reason))
            
            self.logger.debug(
                f"Zone {zone_id}: urgency={urgency:.1f}, water={water_amount:.1f}L"
            )
        
        return queue
    
    def _build_reason(
        self,
        zone: ZoneConfig,
        reading: SensorReading,
        urgency: float,
        weather: Dict[str, Any]
    ) -> str:
        """Build human-readable explanation for irrigation decision."""
        parts = []
        
        # Moisture status
        if reading.soil_moisture_percent < zone.moisture_threshold_low:
            parts.append(f"moisture critical ({reading.soil_moisture_percent:.0f}%)")
        elif reading.soil_moisture_percent < zone.moisture_threshold_target:
            parts.append(f"moisture below target ({reading.soil_moisture_percent:.0f}%)")
        
        # Plant type
        plant_data = self._plant_cache.get(zone.zone_id, {})
        if plant_data.get('common_name'):
            watering = plant_data.get('watering', 'average')
            parts.append(f"{plant_data['common_name']} ({watering} water needs)")
        
        # Weather influence
        rain_mm = weather.get('rain', {}).get('total_mm', 0)
        if rain_mm > 0:
            parts.append(f"rain forecast: {rain_mm:.1f}mm")
        
        et_mm = weather.get('et', {}).get('et_mm', 0)
        if et_mm > 4:
            parts.append(f"high evaporation: {et_mm:.1f}mm")
        
        return "; ".join(parts) if parts else "routine irrigation"
    
    # =========================================================================
    # WATER ALLOCATION
    # =========================================================================
    
    def _allocate_water(
        self,
        priority_queue: List[tuple[float, str, float, str]],
        tank_status: TankStatus
    ) -> List[IrrigationCommand]:
        """
        Allocate water to zones from priority queue respecting tank constraints.
        """
        commands = []
        
        # Calculate available water (keep reserve)
        reserve_liters = tank_status.capacity_liters * (self.params['tank_reserve_percent'] / 100)
        emergency_reserve = tank_status.capacity_liters * (self.params['emergency_reserve_percent'] / 100)
        
        available = tank_status.current_level_liters - reserve_liters
        
        if available <= 0:
            self.logger.warning(
                f"Tank at reserve level ({tank_status.level_percent:.1f}%), "
                "only emergency irrigation allowed"
            )
            available = tank_status.current_level_liters - emergency_reserve
        
        remaining = available
        
        while priority_queue and remaining > 0:
            neg_score, zone_id, water_requested, reason = heapq.heappop(priority_queue)
            urgency = -neg_score
            zone = self.zones[zone_id]
            
            # Determine how much to actually give
            water_to_give = min(water_requested, remaining)
            
            if water_to_give < 0.5:  # Don't bother with tiny amounts
                continue
            
            # Calculate duration
            duration_seconds = (water_to_give / zone.valve_flow_rate_lpm) * 60
            
            commands.append(IrrigationCommand(
                zone_id=zone_id,
                zone_name=zone.name,
                water_amount_liters=water_to_give,
                duration_seconds=duration_seconds,
                priority_score=urgency,
                reason=reason
            ))
            
            remaining -= water_to_give
            
            self.logger.info(
                f"Allocated {water_to_give:.1f}L to {zone.name} "
                f"(urgency: {urgency:.1f}, duration: {duration_seconds:.0f}s)"
            )
        
        # Sort commands by priority for execution order
        commands.sort(key=lambda c: c.priority_score, reverse=True)
        
        return commands


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def create_engine_from_config(config: Dict[str, Any]) -> IrrigationDecisionEngine:
    """
    Create decision engine from a configuration dictionary.
    
    Expected config format:
    {
        "zones": [
            {
                "zone_id": "zone_1",
                "name": "Tomato Bed",
                "plant_id": 285,
                "area_m2": 2.0,
                "valve_flow_rate_lpm": 2.0,
                "moisture_threshold_low": 35,
                "moisture_threshold_target": 65,
                "priority_weight": 1.0
            },
            ...
        ],
        "params": {
            "tank_reserve_percent": 15,
            ...
        }
    }
    """
    zones = [ZoneConfig(**z) for z in config.get('zones', [])]
    params = config.get('params', {})
    
    return IrrigationDecisionEngine(zones=zones, params=params)


def quick_decision(
    zones: List[Dict],
    sensor_readings: List[Dict],
    weather_data: Dict,
    tank_level_liters: float,
    tank_capacity_liters: float,
    plant_data: Optional[Dict[str, Dict]] = None
) -> Dict:
    """
    Quick decision function for simple usage.
    
    Args:
        zones: List of zone config dicts
        sensor_readings: List of sensor reading dicts
        weather_data: Weather forecast from WeatherAPI
        tank_level_liters: Current tank level
        tank_capacity_liters: Tank capacity
        plant_data: Optional dict mapping zone_id to plant data
    
    Returns:
        Decision result as dictionary
    """
    # Create engine
    zone_configs = [ZoneConfig(**z) for z in zones]
    engine = IrrigationDecisionEngine(zones=zone_configs)
    
    # Add plant data if provided
    if plant_data:
        for zone_id, data in plant_data.items():
            engine.set_plant_data(zone_id, data)
    
    # Convert sensor readings
    sensor_data = {
        r['zone_id']: SensorReading(
            zone_id=r['zone_id'],
            soil_moisture_percent=r['soil_moisture_percent'],
            temperature_c=r.get('temperature_c', 20.0),
            humidity_percent=r.get('humidity_percent', 50.0)
        )
        for r in sensor_readings
    }
    
    # Create tank status
    tank = TankStatus(
        current_level_liters=tank_level_liters,
        capacity_liters=tank_capacity_liters
    )
    
    # Make decision
    result = engine.make_decisions(sensor_data, weather_data, tank)
    
    return result.to_dict()


# =============================================================================
# EXAMPLE USAGE
# =============================================================================

if __name__ == "__main__":
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Example zone configuration
    zones = [
        ZoneConfig(
            zone_id="zone_1",
            name="Tomato Bed",
            plant_id=285,
            area_m2=2.0,
            moisture_threshold_low=35.0,
            moisture_threshold_target=65.0,
            priority_weight=1.2  # Tomatoes are valuable
        ),
        ZoneConfig(
            zone_id="zone_2", 
            name="Herb Garden",
            plant_id=None,
            area_m2=1.0,
            moisture_threshold_low=25.0,
            moisture_threshold_target=50.0,
            priority_weight=0.8
        ),
        ZoneConfig(
            zone_id="zone_3",
            name="Lettuce Row",
            plant_id=1234,
            area_m2=1.5,
            moisture_threshold_low=40.0,
            moisture_threshold_target=70.0,
            priority_weight=1.0
        ),
    ]
    
    # Create engine
    engine = IrrigationDecisionEngine(zones)
    
    # Set plant data (normally from PlantAPI)
    engine.set_plant_data("zone_1", {
        'common_name': 'Tomato',
        'watering': 'Frequent',
        'drought_tolerant': False
    })
    engine.set_plant_data("zone_2", {
        'common_name': 'Mixed Herbs',
        'watering': 'Minimum',
        'drought_tolerant': True
    })
    engine.set_plant_data("zone_3", {
        'common_name': 'Lettuce',
        'watering': 'Average',
        'drought_tolerant': False
    })
    
    # Simulate sensor readings
    sensor_data = {
        "zone_1": SensorReading(
            zone_id="zone_1",
            soil_moisture_percent=28.0,  # Below threshold!
            temperature_c=24.0,
            humidity_percent=55.0
        ),
        "zone_2": SensorReading(
            zone_id="zone_2",
            soil_moisture_percent=45.0,  # OK
            temperature_c=24.0,
            humidity_percent=55.0
        ),
        "zone_3": SensorReading(
            zone_id="zone_3",
            soil_moisture_percent=38.0,  # Slightly below target
            temperature_c=24.0,
            humidity_percent=55.0
        ),
    }
    
    # Simulate weather data (format from WeatherAPI.get_irrigation_data)
    today = datetime.now().strftime('%Y-%m-%d')
    weather_data = {
        today: {
            'rain': {
                'total_mm': 2.0,
                'will_rain': True,
                'by_period': {}
            },
            'temperature': {
                'day_min': 15.0,
                'day_max': 28.0,
                'by_period': {}
            },
            'et': {
                'et_mm': 4.5,
                'temp_avg': 22.0,
                'humidity_avg': 55.0
            },
            'water_balance_mm': -2.5
        }
    }
    
    # Simulate tank status
    tank = TankStatus(
        current_level_liters=80.0,
        capacity_liters=100.0
    )
    
    # Make decision
    print("\n" + "="*60)
    print("IRRIGATION DECISION ENGINE - TEST RUN")
    print("="*60)
    
    result = engine.make_decisions(sensor_data, weather_data, tank)
    
    print(f"\nTimestamp: {result.timestamp}")
    print(f"Should irrigate: {result.should_irrigate}")
    
    if result.delay_reason:
        print(f"Delay reason: {result.delay_reason}")
    
    print(f"\nWeather Summary:")
    for key, value in result.weather_summary.items():
        print(f"  {key}: {value}")
    
    if result.commands:
        print(f"\nIrrigation Commands ({len(result.commands)} zones):")
        print("-" * 50)
        for cmd in result.commands:
            print(f"  Zone: {cmd.zone_name} ({cmd.zone_id})")
            print(f"    Water: {cmd.water_amount_liters:.1f} L")
            print(f"    Duration: {cmd.duration_seconds:.0f} seconds")
            print(f"    Priority: {cmd.priority_score:.1f}")
            print(f"    Reason: {cmd.reason}")
            print()
    
    print(f"Total water: {result.total_water_liters:.1f} L")
    print(f"Tank after: {result.tank_after_liters:.1f} L ({result.tank_after_liters/tank.capacity_liters*100:.1f}%)")
    print("="*60)
    
    # Also demonstrate the quick function
    print("\n\nQUICK FUNCTION DEMO:")
    print("-"*40)
    
    quick_result = quick_decision(
        zones=[
            {"zone_id": "z1", "name": "Test Zone", "area_m2": 1.0}
        ],
        sensor_readings=[
            {"zone_id": "z1", "soil_moisture_percent": 20.0}
        ],
        weather_data=weather_data,
        tank_level_liters=50.0,
        tank_capacity_liters=100.0
    )
    
    print(f"Should irrigate: {quick_result['should_irrigate']}")
    print(f"Commands: {len(quick_result['commands'])}")
