# Smart Irrigation System

A modular, scalable smart irrigation system designed for precision agriculture. Built for Raspberry Pi with Arduino sensor integration, weather forecasting, and plant-specific care optimization.

## Project Structure

```
smart-irrigation/
├── README.md
├── requirements.txt
├── .gitignore
│
├── raspberry_pi/
│   ├── main_controller.py      # Main orchestration
│   ├── decision_engine.py      # Irrigation decision logic
│   ├── sensor_providers.py     # Arduino & mock sensor interfaces
│   ├── valve_controller.py     # GPIO valve control
│   ├── tank_sensor.py          # Water tank level sensor
│   ├── weather_api.py          # OpenWeatherMap integration
│   ├── plant_api.py            # Perenual plant database
│   ├── demo_mode.py            # Demo/testing mode
│   └── .env.example            # Environment variables template
│
└── arduino/
    └── sensor_reader.ino       # Arduino sensor sketch
```

## Module Overview

| Module | Purpose |
|--------|---------|
| `main_controller.py` | Entry point, orchestrates all components |
| `decision_engine.py` | Rule-based irrigation decisions with priority queue |
| `sensor_providers.py` | Abstract interface + Arduino/Mock implementations |
| `valve_controller.py` | GPIO valve control + Mock for testing |
| `tank_sensor.py` | Simple tank level reading |
| `weather_api.py` | OpenWeatherMap with caching & ET₀ calculations |
| `plant_api.py` | Perenual plant database integration |
| `demo_mode.py` | Full simulation for demos & testing |

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure API Keys

```bash
cd raspberry_pi
cp .env.example .env
# Edit .env with your API keys
```

### 3. Run

```bash
cd raspberry_pi

# Demo mode (no hardware needed)
python main_controller.py --demo

# Demo with specific scenario
python main_controller.py --demo --scenario critical

# Mock sensors (testing on Pi)
python main_controller.py --mock

# Production (with real hardware)
python main_controller.py
```

## Demo Mode

Demo mode is perfect for:
- Classroom demonstrations
- Dashboard development
- Testing without hardware

### Scenarios

| Scenario | Description |
|----------|-------------|
| `normal` | Typical operation, some zones need water |
| `critical` | One zone critically dry |
| `rain` | Rain forecast, delays irrigation |
| `healthy` | All zones well-watered |
| `low_tank` | Tank running low |
| `mixed` | Mix of conditions |

```bash
# Run demo with specific scenario
python main_controller.py --demo --scenario critical --zones 4

# Single cycle (outputs JSON)
python main_controller.py --demo --once
```

## Hardware Setup

### Raspberry Pi

- Model: 3B+ or newer
- GPIO pins for valve relay modules
- Serial connection to Arduino

### Arduino

- Uno or Nano
- DHT20 sensor (temperature/humidity)
- Capacitive soil moisture sensors (one per zone)
- Optional: HC-SR04 ultrasonic for tank level

Upload `arduino/sensor_reader.ino` to your Arduino.

## Configuration

Create `config.json` for custom settings:

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
      "valve_pin": 17,
      "moisture_threshold_low": 35.0,
      "moisture_threshold_target": 65.0
    }
  ]
}
```

## API Keys

- **OpenWeatherMap**: https://openweathermap.org/api (free tier available)
- **Perenual**: https://perenual.com/docs/api (free tier available)

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      main_controller.py                          │
│                        (Orchestration)                           │
└─────────────────────────┬───────────────────────────────────────┘
                          │
        ┌─────────────────┼─────────────────┐
        │                 │                 │
        ▼                 ▼                 ▼
┌───────────────┐ ┌───────────────┐ ┌───────────────┐
│sensor_providers│ │valve_controller│ │ decision_engine│
│               │ │               │ │               │
│ Arduino/Mock  │ │  GPIO/Mock    │ │ Priority Queue│
│ Soil Sensors  │ │  Relay Valves │ │ Water Alloc   │
└───────┬───────┘ └───────────────┘ └───────┬───────┘
        │                                   │
        │         ┌─────────────────────────┘
        │         │
        ▼         ▼
┌───────────────┐ ┌───────────────┐
│  tank_sensor  │ │  weather_api  │
│               │ │  plant_api    │
│ Water Level   │ │ External Data │
└───────────────┘ └───────────────┘
```

## License

MIT License
