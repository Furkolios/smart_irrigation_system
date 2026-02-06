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
│   ├── tank_sensor.py          # Water tank level sensor (camera)
│   ├── weather_api.py          # OpenWeatherMap integration
│   ├── plant_api.py            # Perenual plant database
│   ├── telemetry.py            # Dashboard telemetry (HTTP POST)
│   ├── demo_mode.py            # Demo/testing mode
│   └── .env.example            # Environment variables template
│
└── arduino/
    └── sensor_reader/
        └── sensor_reader.ino   # Arduino sensor sketch
```

## Module Overview

| Module | Purpose |
|--------|---------|
| `main_controller.py` | Entry point, orchestrates all components |
| `decision_engine.py` | Rule-based irrigation decisions with priority queue |
| `sensor_providers.py` | Abstract interface + Arduino/Mock implementations |
| `valve_controller.py` | GPIO valve control + Mock for testing |
| `tank_sensor.py` | Camera-based tank level reading (red floater detection) |
| `weather_api.py` | OpenWeatherMap with caching & ET₀ calculations |
| `plant_api.py` | Perenual plant database integration |
| `telemetry.py` | Sends system data to dashboard server via HTTP POST |
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

# Mock sensors (testing on Pi without Arduino)
python main_controller.py --mock --once

# Production (with real hardware)
python main_controller.py
```

## Telemetry

The system sends data to a dashboard server after each decision cycle via HTTP POST.

**Endpoint:** `http://<server_ip>:8000/api/v1/telemetry`

### Configuration

Set the dashboard server IP in one of three ways (in priority order):

1. **CLI argument:** `--server-ip 192.168.1.50`
2. **Config file:** `"server": {"ip": "192.168.1.50"}`
3. **Environment variable:** `DASHBOARD_SERVER_IP=192.168.1.50` in `.env`

### Payload Format

```json
{
  "timestamp": "2025-01-21T08:30:00",
  "zones": [
    {"zone_id": "zone_1", "soil_moisture_percent": 32.5, "temperature_c": 23.0, "humidity_percent": 58.0}
  ],
  "tank": {"level_liters": 35.0, "capacity_liters": 50.0, "level_percent": 70.0},
  "weather": {"rain_mm": 2.0, "will_rain": true, "temp_min": 14.0, "temp_max": 26.0, "et_mm": 3.5},
  "last_decision": {"should_irrigate": true, "commands": [...], "total_water_liters": 6.9}
}
```

### Disable Telemetry

```bash
python main_controller.py --mock --no-telemetry
```

## Demo Mode

Demo mode is perfect for classroom demonstrations, dashboard development, and testing without hardware.

### Scenarios

| Scenario | Description |
|----------|-------------|
| `normal` | Typical operation, some zones need water |
| `critical` | One zone critically dry |
| `rain` | Rain forecast, reduces urgency |
| `healthy` | All zones well-watered |
| `low_tank` | Tank running low |
| `mixed` | Mix of conditions |

```bash
# Run demo with specific scenario
python main_controller.py --demo --scenario critical --zones 4

# Single cycle (outputs JSON)
python main_controller.py --demo --once

# Demo with telemetry to dashboard
python main_controller.py --demo --server-ip 192.168.1.50
```

## Hardware Setup

### Raspberry Pi

- Model: 3B+ or newer
- GPIO pins for valve relay modules
- Serial connection to Arduino
- Pi Camera for tank level detection (optional)

### Arduino

- Uno or Nano
- DHT20 sensor (temperature/humidity)
- Capacitive soil moisture sensors (one per zone)

Upload `arduino/sensor_reader/sensor_reader.ino` to your Arduino.

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
  "server": {
    "ip": "192.168.1.50",
    "port": 8000,
    "enabled": true
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
└───────────┬───────────────┬───────────────┬─────────────────────┘
            │               │               │
    ┌───────▼───────┐ ┌────▼────────┐ ┌────▼────────┐
    │sensor_providers│ │valve_control│ │decision_eng.│
    │ Arduino/Mock  │ │ GPIO/Mock   │ │Priority Queue│
    └───────┬───────┘ └─────────────┘ └──────┬──────┘
            │                                │
    ┌───────▼───────┐ ┌─────────────┐ ┌──────▼──────┐
    │  tank_sensor  │ │ weather_api │ │  plant_api  │
    │ Camera/Mock   │ │ OpenWeather │ │  Perenual   │
    └───────────────┘ └─────────────┘ └─────────────┘
                              │
                      ┌───────▼───────┐
                      │  telemetry.py │
                      │  HTTP POST →  │
                      │  Dashboard    │
                      └───────────────┘
```

## CLI Reference

```
python main_controller.py [OPTIONS]

Options:
  --config FILE       Path to config.json
  --once              Run single cycle and exit
  --force             Force irrigation (bypass time/weather constraints)
  --status            Print current system status as JSON
  --mock              Use mock sensors and tank level
  --demo              Run demo mode (full simulation)
  --scenario NAME     Demo scenario (normal/critical/rain/healthy/low_tank/mixed)
  --zones N           Number of demo zones (1-6)
  --server-ip IP      Dashboard server IP address
  --no-telemetry      Disable telemetry sending
```

## License

MIT License
