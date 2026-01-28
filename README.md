# Smart Irrigation System

A modular, scalable smart irrigation system designed for precision agriculture. Built for Raspberry Pi with Arduino sensor integration, weather forecasting, and plant-specific care optimization.

## Overview

This system automates irrigation decisions by combining:
- **Real-time sensor data** (soil moisture, temperature, humidity) from Arduino
- **Weather forecasts** (rain prediction, evapotranspiration) from OpenWeatherMap API
- **Plant-specific requirements** (watering needs, drought tolerance) from Perenual API
- **Rule-based decision engine** with priority queue allocation

The architecture supports scaling from a single demonstration unit to multi-site agricultural deployments.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         RASPBERRY PI                                     │
│                                                                          │
│   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐                │
│   │   Arduino    │   │  WeatherAPI  │   │   PlantAPI   │                │
│   │   Sensors    │   │              │   │              │                │
│   │              │   │  - Rain      │   │  - Watering  │                │
│   │  - Moisture  │   │  - Temp      │   │  - Drought   │                │
│   │  - Temp      │   │  - ET₀       │   │    tolerance │                │
│   │  - Humidity  │   │              │   │              │                │
│   └──────┬───────┘   └──────┬───────┘   └──────┬───────┘                │
│          │                  │                  │                         │
│          └──────────────────┼──────────────────┘                         │
│                             ▼                                            │
│                  ┌─────────────────────┐                                 │
│                  │   Decision Engine   │                                 │
│                  │                     │                                 │
│                  │  - Calculate needs  │                                 │
│                  │  - Priority queue   │                                 │
│                  │  - Allocate water   │                                 │
│                  └──────────┬──────────┘                                 │
│                             │                                            │
│                             ▼                                            │
│                  ┌─────────────────────┐                                 │
│                  │   Valve Control     │                                 │
│                  │   (GPIO → valves)   │                                 │
│                  └─────────────────────┘                                 │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

## Project Structure

```
smart-irrigation/
├── README.md                 # This file
├── .env                      # API keys (create this - see Setup)
├── .gitignore                # Git ignore patterns
│
├── weather_api.py            # OpenWeatherMap integration
├── plant_api.py              # Perenual plant database integration
├── decision_engine.py        # Core decision-making logic
├── main_controller.py        # Main orchestration loop
│
├── arduino_interface.py      # Arduino serial communication (TODO)
└── config.json               # System configuration (optional)
```

## Requirements

### Hardware
- Raspberry Pi (3B+ or newer recommended)
- Arduino (Uno/Nano) with sensors
- Soil moisture sensors (capacitive recommended)
- Temperature/humidity sensor (DHT22 or similar)
- Water level sensor for tank
- Solenoid valves for irrigation zones
- Relay module for valve control

### Software
- Python 3.9+
- Required packages:
  ```
  requests
  python-dotenv
  ```

### API Keys
- **OpenWeatherMap API**: Free tier available at https://openweathermap.org/api
- **Perenual API**: Free tier available at https://perenual.com/docs/api

## Setup

### 1. Clone and Install Dependencies

```bash
# Clone the repository
git clone https://github.com/yourusername/smart-irrigation.git
cd smart-irrigation

# Install Python dependencies
pip install requests python-dotenv
```

### 2. Configure API Keys

Create a `.env` file in the project root:

```env
OPENWEATHER_API_KEY=your_openweathermap_api_key_here
PERENUAL_API_KEY=your_perenual_api_key_here
```

> **Security Note**: Never commit `.env` to version control. Add it to `.gitignore`.

### 3. Configure Your System

Create a `config.json` file (optional - defaults are provided):

```json
{
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
      "name": "Tomato Bed",
      "plant_id": 285,
      "area_m2": 2.0,
      "valve_flow_rate_lpm": 2.0,
      "moisture_threshold_low": 35.0,
      "moisture_threshold_target": 65.0,
      "priority_weight": 1.2,
      "valve_pin": 17
    },
    {
      "zone_id": "zone_2",
      "name": "Herb Garden",
      "plant_id": 794,
      "area_m2": 1.0,
      "moisture_threshold_low": 25.0,
      "moisture_threshold_target": 50.0,
      "priority_weight": 0.8,
      "valve_pin": 18
    }
  ],
  "timing": {
    "check_interval_seconds": 300,
    "weather_refresh_minutes": 60,
    "plant_refresh_hours": 24
  }
}
```

### 4. Run the System

```bash
# Run with mock sensors (for testing)
python main_controller.py --mock

# Run once and see the decision
python main_controller.py --once --mock

# Run with real sensors
python main_controller.py --config config.json

# Force irrigation (bypass time/weather constraints)
python main_controller.py --once --force --mock
```

---

## Module Documentation

### weather_api.py

Fetches weather data from OpenWeatherMap API with caching and evapotranspiration (ET₀) calculations.

#### Classes

**`WeatherAPI`**
```python
from weather_api import WeatherAPI

api = WeatherAPI(api_key="your_key")

# Get complete irrigation data
data = api.get_irrigation_data("Paris", max_days=3, elevation=35)
```

**`CacheManager`**
- Automatic file-based caching (default: 30 minutes)
- Reduces API calls and handles offline scenarios

#### Key Methods

| Method | Description | Returns |
|--------|-------------|---------|
| `get_irrigation_data(city, max_days, elevation)` | Complete weather data for irrigation | Dict with rain, temp, ET per day |
| `get_rain_predictions(city, max_days)` | Rain forecast by time period | Dict with mm and probability |
| `get_temperature_predictions(city, max_days)` | Temperature forecast | Dict with min/max per period |
| `get_et_predictions(city, max_days, elevation)` | Evapotranspiration calculation | Dict with ET₀ in mm/day |
| `calculate_et(temp_c, humidity, wind_speed, ...)` | Simplified Penman ET₀ | Float (mm/day) |

#### Output Format

```python
{
    "2025-01-28": {
        "rain": {
            "total_mm": 5.2,
            "will_rain": True,
            "by_period": {"morning": {...}, "afternoon": {...}}
        },
        "temperature": {
            "day_min": 8.0,
            "day_max": 15.0,
            "by_period": {...}
        },
        "et": {
            "et_mm": 2.45,
            "temp_avg": 12.0,
            "humidity_avg": 65.0
        },
        "water_balance_mm": 2.75  # rain - ET (positive = surplus)
    }
}
```

---

### plant_api.py

Fetches plant care data from the Perenual API for species-specific irrigation.

#### Classes

**`PlantAPI`**
```python
from plant_api import PlantAPI

api = PlantAPI()  # Uses PERENUAL_API_KEY from .env

# Search for plants (for UI dropdown)
options = api.search_plants_simple("tomato", max_results=10)
# Returns: [{"id": 285, "name": "Tomato", "scientific_name": "Solanum lycopersicum"}, ...]

# Get irrigation-specific data
data = api.get_irrigation_data(plant_id=285)
```

#### Key Methods

| Method | Description | Returns |
|--------|-------------|---------|
| `search_plants(query, **filters)` | Full search with filters | Dict with pagination |
| `search_plants_simple(query, max_results)` | Simplified search for dropdowns | List of {id, name, scientific_name} |
| `get_plant_details(plant_id)` | Complete plant information | Full plant data dict |
| `get_irrigation_data(plant_id)` | Irrigation-relevant fields only | Filtered plant data |
| `get_pest_diseases(query)` | Pest and disease information | Dict with pest data |

#### Irrigation Data Output

```python
{
    "id": 285,
    "common_name": "Tomato",
    "scientific_name": ["Solanum lycopersicum"],
    "watering": "Frequent",           # None, Minimum, Average, Frequent
    "watering_general_benchmark": {
        "value": "3-4",
        "unit": "days"
    },
    "drought_tolerant": False,
    "hardiness": {"min": "10", "max": "11"},
    "sunlight": ["full sun"],
    "soil": ["loamy", "sandy"],
    "growth_rate": "High",
    "care_level": "Medium",
    "indoor": False
}
```

#### Search Filters

```python
# Filter by watering needs, sunlight, cycle, etc.
results = api.search_plants(
    "herbs",
    watering="minimum",      # frequent, average, minimum, none
    sunlight="full_sun",     # full_shade, part_shade, sun-part_shade, full_sun
    drought_tolerant=True,
    indoor=False
)
```

---

### decision_engine.py

The core decision-making module that determines when and how much to water each zone.

#### Architecture

```
Inputs                    Processing                     Output
─────────────────────────────────────────────────────────────────
Soil moisture ─┐
Temperature   ─┤          ┌─────────────────┐
Humidity      ─┼─────────►│ Calculate Need  │
               │          │ Score (0-100)   │
Weather data ──┤          └────────┬────────┘
  - Rain      ─┤                   │
  - ET₀       ─┤                   ▼
               │          ┌─────────────────┐
Plant data   ──┤          │ Priority Queue  │──────► Irrigation
  - Watering  ─┤          │ (most urgent    │        Commands
  - Drought   ─┘          │  zones first)   │        [zone, liters,
               │          └────────┬────────┘         duration, reason]
Tank level   ──┘                   │
                                   ▼
                          ┌─────────────────┐
                          │ Constraint      │
                          │ Checking        │
                          │ - Time of day   │
                          │ - Rain forecast │
                          │ - Frost risk    │
                          │ - Tank reserve  │
                          └─────────────────┘
```

#### Classes

**`IrrigationDecisionEngine`**
```python
from decision_engine import IrrigationDecisionEngine, ZoneConfig, SensorReading, TankStatus

# Define zones
zones = [
    ZoneConfig(
        zone_id="zone_1",
        name="Tomato Bed",
        plant_id=285,
        area_m2=2.0,
        moisture_threshold_low=35.0,
        moisture_threshold_target=65.0,
        priority_weight=1.2
    )
]

# Create engine
engine = IrrigationDecisionEngine(zones)

# Add plant data (from PlantAPI)
engine.set_plant_data("zone_1", plant_api.get_irrigation_data(285))

# Make decision
result = engine.make_decisions(
    sensor_data={"zone_1": SensorReading(...)},
    weather_data=weather_api.get_irrigation_data("Paris"),
    tank_status=TankStatus(current_level_liters=80, capacity_liters=100)
)
```

#### Decision Logic

1. **Urgency Score Calculation** (per zone):
   - Base: moisture deficit from target (0-100 scale)
   - Multiplied by: plant watering needs (0.5x for drought-tolerant, 1.5x for frequent)
   - Multiplied by: weather factor (reduced if rain coming)
   - Multiplied by: ET factor (increased on high-evaporation days)
   - Multiplied by: zone priority weight

2. **Global Constraints** (checked before irrigation):
   - Time of day: Prefers 6-9 AM, avoids 11 AM - 3 PM (evaporation)
   - Rain forecast: Skips if >5mm expected
   - Frost risk: Delays if temp <2°C forecast
   - Critical override: Urgency >80 bypasses time constraints

3. **Water Allocation**:
   - Zones sorted by urgency (priority queue)
   - Water allocated until tank reaches reserve (10%)
   - Each zone gets proportional water based on area and urgency

#### Output Format

```python
DecisionResult(
    timestamp=datetime,
    should_irrigate=True,
    delay_reason=None,  # or "Rain expected (8.0mm)"
    commands=[
        IrrigationCommand(
            zone_id="zone_1",
            zone_name="Tomato Bed",
            water_amount_liters=15.0,
            duration_seconds=450,
            priority_score=85.2,
            reason="moisture critical (22%); Tomato (Frequent water needs)"
        )
    ],
    total_water_liters=15.0,
    tank_after_liters=65.0,
    weather_summary={...}
)
```

#### Quick Usage Function

```python
from decision_engine import quick_decision

result = quick_decision(
    zones=[{"zone_id": "z1", "name": "Test", "area_m2": 1.0}],
    sensor_readings=[{"zone_id": "z1", "soil_moisture_percent": 25.0}],
    weather_data=weather_api.get_irrigation_data("Paris"),
    tank_level_liters=80.0,
    tank_capacity_liters=100.0
)
```

---

### main_controller.py

The orchestration layer that runs on the Raspberry Pi and ties everything together.

#### Features

- Continuous monitoring loop (configurable interval)
- Automatic caching of weather/plant data
- Mock providers for testing without hardware
- CLI interface for different run modes
- Graceful shutdown with valve safety

#### Usage

```bash
# Test mode (mock sensors and valves)
python main_controller.py --mock

# Single decision cycle
python main_controller.py --once --mock

# Force irrigation (bypass constraints)
python main_controller.py --once --force --mock

# Check current status
python main_controller.py --status --mock

# Production with config file
python main_controller.py --config config.json
```

#### Classes

**`IrrigationController`**
```python
from main_controller import IrrigationController, load_config

config = load_config("config.json")
controller = IrrigationController(
    config=config,
    weather_api=weather_api,
    plant_api=plant_api
)

# Run single cycle
result = controller.run_once()

# Run continuous loop
controller.run()

# Get status
status = controller.get_status()
```

**`SensorDataProvider`** (Abstract Interface)

Your Arduino interface should implement this:

```python
class ArduinoSensorProvider(SensorDataProvider):
    def get_sensor_readings(self) -> Dict[str, Dict[str, float]]:
        """
        Returns:
            {
                "zone_1": {
                    "soil_moisture_percent": 45.0,
                    "temperature_c": 22.0,
                    "humidity_percent": 60.0
                },
                ...
            }
        """
        # Read from Arduino serial
        pass
    
    def get_tank_level(self) -> float:
        """Returns tank level in liters."""
        pass
```

---

## Configuration Reference

### Zone Configuration

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `zone_id` | string | required | Unique identifier |
| `name` | string | zone_id | Human-readable name |
| `plant_id` | int | null | Perenual plant ID |
| `area_m2` | float | 1.0 | Zone area in square meters |
| `valve_flow_rate_lpm` | float | 2.0 | Valve flow rate (liters/minute) |
| `moisture_threshold_low` | float | 30.0 | Critical moisture level (%) |
| `moisture_threshold_target` | float | 60.0 | Target moisture level (%) |
| `priority_weight` | float | 1.0 | Zone importance multiplier |
| `valve_pin` | int | null | GPIO pin for valve relay |

### Decision Engine Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `tank_reserve_percent` | 10.0 | Minimum tank level to maintain |
| `preferred_hours_start` | 6 | Preferred irrigation start hour |
| `preferred_hours_end` | 9 | Preferred irrigation end hour |
| `avoid_midday_start` | 11 | Avoid irrigation after this hour |
| `avoid_midday_end` | 15 | Avoid irrigation until this hour |
| `rain_threshold_mm` | 5.0 | Skip if this much rain expected |
| `frost_threshold_c` | 2.0 | Delay if temp below this |
| `urgency_threshold_critical` | 80.0 | Override time constraints above this |
| `base_water_per_m2_liters` | 5.0 | Base watering amount per m² |

---

## Development

### Running Tests

```bash
# Test weather API
python weather_api.py

# Test plant API
python plant_api.py

# Test decision engine
python decision_engine.py

# Test full system with mocks
python main_controller.py --once --mock
```

### Adding a New Zone

1. Add physical hardware (sensor, valve)
2. Update `config.json` with new zone entry
3. (Optional) Look up plant ID on Perenual and add to config
4. Restart the controller

### Implementing Arduino Interface

Create `arduino_interface.py`:

```python
import serial
import json

class ArduinoInterface:
    def __init__(self, port="/dev/ttyUSB0", baud_rate=9600):
        self.serial = serial.Serial(port, baud_rate, timeout=1)
    
    def get_sensor_readings(self):
        self.serial.write(b"READ\n")
        line = self.serial.readline().decode('utf-8')
        return json.loads(line)
    
    def get_tank_level(self):
        self.serial.write(b"TANK\n")
        line = self.serial.readline().decode('utf-8')
        return float(line)
```

Expected Arduino JSON format:
```json
{"zone_1": {"moisture": 45, "temp": 22, "humidity": 60}}
```

---

## Future Enhancements

- [ ] Web dashboard for remote monitoring
- [ ] Multi-site support with central server
- [ ] Adaptive threshold learning from plant response
- [ ] Camera integration for plant health monitoring
- [ ] MQTT/WebSocket for real-time updates
- [ ] Historical data logging and analysis
- [ ] Simulink integration for simulation

---

## Troubleshooting

### API Key Issues
```
ValueError: API key not found
```
→ Check your `.env` file exists and contains valid keys

### No Irrigation Happening
```
Irrigation delayed: Avoiding midday evaporation
```
→ Normal behavior. Use `--force` to override, or wait for preferred hours (6-9 AM)

### Mock Mode Not Working
```
ArduinoInterface not implemented
```
→ Use `--mock` flag to enable mock sensors

### Weather Data Stale
```
Using stale weather cache
```
→ API might be unreachable. System continues with cached data.

---

## License

MIT License - See LICENSE file for details.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

---

## Acknowledgments

- OpenWeatherMap for weather data API
- Perenual for plant database API
- Penman-Monteith equation for ET₀ calculations
