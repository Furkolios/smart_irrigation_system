# Smart Irrigation System

A modular smart irrigation system designed to run on a Raspberry Pi. It reads zone sensor data (Arduino or simulated), decides when/how much to irrigate, drives GPIO valves, and can integrate with a backend “dashboard” server for provisioning + telemetry + logs + images.

## Project Structure

```
smart_irrigation_system/
├── README.md
├── requirements.txt
├── .gitignore
│
├── raspberry_pi/
│   ├── main.py                 # Entry point (CLI) → SystemOrchestrator
│   ├── core/
│   │   ├── system.py            # Main orchestrator loop (modes: main/demo/test)
│   │   ├── hardware.py          # Hardware abstraction (Arduino/Cameras/Valves)
│   │   ├── telemetry.py         # Store-and-forward telemetry transport
│   │   ├── arduino_manager.py   # Auto-detect + read Arduino JSON protocol
│   │   ├── camera_manager.py    # Camera capture by role (tank/plant/etc.)
│   │   ├── state_manager.py     # Runtime state + error reporting
│   │   ├── demo_mode.py         # Standalone scenario simulator (classroom/UI demos)
│   │   └── main_controller.py   # Legacy controller (weather/plant/tank modules)
│   ├── config/
│   │   ├── system_config.yaml   # Main device configuration (YAML)
│   │   ├── models.py            # Pydantic config models + enums
│   │   ├── config_manager.py    # YAML load/validate/save
│   │   └── provisioning.py      # Device provisioning client
│   ├── water/
│   │   ├── decision_engine.py   # Irrigation decision engine (priority queue)
│   │   └── valve_controller.py  # GPIO + Mock valve controllers
│   ├── sensors/
│   │   ├── sensor_providers.py  # Mock + serial Arduino providers (utility)
│   │   └── tank_sensor.py       # Camera-based tank level (legacy/optional)
│   ├── api/
│   │   ├── telemetry.py         # Direct telemetry sender (legacy/tools)
│   │   ├── weather_api.py       # Weather client (optional; not wired in orchestrator yet)
│   │   └── plant_api.py         # Plant client (optional; used by legacy controller)
│   ├── images/
│   │   └── image_sender.py      # Direct image uploader (legacy/tools)
│   └── tools/
│       └── hardware_diag.py     # Hardware test utility (sensors/valves)
│
└── arduino/
    └── sensor_reader/
        └── sensor_reader.ino   # Arduino sensor sketch
```

## Module Overview

| Module | Purpose |
|--------|---------|
| `raspberry_pi/main.py` | Device entry point + CLI (`--config`, `--mode`, `--verbose`) |
| `raspberry_pi/core/system.py` | Main loop: read sensors → decide → actuate → (optional) send telemetry/images |
| `raspberry_pi/core/hardware.py` | Central HAL: Arduino + cameras + valves; mock behavior in `demo` mode |
| `raspberry_pi/water/decision_engine.py` | Rule-based irrigation decisions + priority queue allocation |
| `raspberry_pi/core/telemetry.py` | Background worker w/ queue + backlog (`data/telemetry_backlog.jsonl`) |
| `raspberry_pi/config/system_config.yaml` | Main config (hardware, server, intervals, irrigation defaults) |
| `raspberry_pi/config/provisioning.py` | Bootstraps device with server (gets `device_id` + `sensor_map`) |
| `raspberry_pi/core/demo_mode.py` | Standalone scenario simulator (JSON state output for demos) |

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure the device (`system_config.yaml`)

```bash
# Edit this file to match your GPIO pins, zones, and server URL:
#   raspberry_pi/config/system_config.yaml
```

### 3. Run

```bash
# Main mode (real hardware if available)
python raspberry_pi/main.py

# Demo mode (uses mock sensors + mock valves)
python raspberry_pi/main.py --mode demo

# Test mode (runs diagnostics and exits)
python raspberry_pi/main.py --mode test

# Verbose logs (DEBUG)
python raspberry_pi/main.py --verbose
```

## Telemetry

When enabled, the Raspberry Pi can integrate with a backend server using a provisioning + “external device” API contract.

### Provisioning (first boot)

If `server.enabled: true` and `server.base_url` is set, the orchestrator will provision automatically when `server.device_id` / `server.sensor_map` are missing.

- **Provisioning endpoint**: `POST /api/v1/devices/provision`
- **What’s sent**: a stable `hardwareId` (MAC) + declared capabilities (sensors by `localName`, cameras by role)
- **What’s stored locally** (into `server.*` in YAML):
  - `device_id`
  - `sensor_map` (maps local names like `zone_1` to server UUIDs)
  - optional polling intervals (`telemetryIntervalSec`, `heartbeatIntervalSec`)

### Configuration

Telemetry is controlled via `raspberry_pi/config/system_config.yaml`:

- `server.enabled`
- `server.base_url` (example: `http://192.168.1.50:8000`)
- intervals: `telemetry_interval_seconds`, `heartbeat_interval_seconds`, `health_interval_seconds`, `image_interval_seconds`

### Payload Format

The orchestrator sends telemetry as a list of “readings” using server-provisioned sensor UUIDs:

```json
{
  "sentAt": "2026-02-13T10:15:30Z",
  "readings": [
    {
      "sensorId": "uuid-from-server",
      "type": "humidity",
      "value": 45.5,
      "unit": "%",
      "readingAt": "2026-02-13T10:15:30Z"
    }
  ]
}
```

### Endpoints used (device → server)

- `POST /api/v1/external-devices/{device_id}/telemetry`
- `POST /api/v1/external-devices/{device_id}/logs`
- `POST /api/v1/external-devices/{device_id}/images` (multipart/form-data)
- `GET  /api/v1/external-devices/{device_id}/status` (heartbeat)

### Reliability behavior

- Telemetry is sent from a background worker with a queue and a local backlog file at `data/telemetry_backlog.jsonl`.
- Transient failures are retried later; most non-rate-limited 4xx rejections are logged and dropped (to avoid infinite retry loops).

## Demo Mode

The orchestrator supports a device-level demo mode that runs without hardware by using mock sensors and mock valves.

```bash
python raspberry_pi/main.py --mode demo
```

There is also a standalone scenario simulator at `raspberry_pi/core/demo_mode.py` (with scenarios like `critical`, `rain`, `low_tank`) that can be used for dashboard/UI demos independent of the main orchestrator.

## Test / Diagnostics Mode

`--mode test` runs startup diagnostics and exits:

- Arduino detection + “valid JSON received” check
- Camera capture test per configured role
- Valve controller init + open/close toggling (real GPIO when available)

## Hardware Setup

### Raspberry Pi

- Model: 3B+ or newer
- GPIO pins for valve relay modules
- Serial connection to Arduino (USB)
- Optional cameras (USB or Pi camera depending on your setup) configured by **role** (e.g. `tank`, `plant`)

### Arduino

- Uno or Nano
- DHT20 sensor (temperature/humidity)
- Capacitive soil moisture sensors (one per zone)

Upload `arduino/sensor_reader/sensor_reader.ino` to your Arduino.

## Configuration

The orchestrator uses a YAML config file at `raspberry_pi/config/system_config.yaml`.

Key sections:

- `hardware.valves`: zone IDs, names, GPIO pins, and flow rate
- `hardware.cameras`: list of cameras with `role` and `resolution`
- `server`: backend integration (`enabled`, `base_url`, intervals; `device_id` + `sensor_map` are filled by provisioning)
- `irrigation`: loop interval and default thresholds

## API Keys

The current orchestrator loop does not yet wire in the weather/plant API clients, but the repo includes optional modules:

- `raspberry_pi/api/weather_api.py` (OpenWeatherMap parsing)
- `raspberry_pi/api/plant_api.py` (Perenual plant database)

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        raspberry_pi/main.py                       │
│                   (CLI → SystemOrchestrator)                      │
└───────────────┬───────────────────────────┬──────────────────────┘
                │                           │
        ┌───────▼────────┐          ┌──────▼─────────┐
        │ HardwareManager │          │ TelemetryManager│
        │ - Arduino/mock  │          │ - queue+backlog │
        │ - cameras       │          │ - POST/GET API  │
        │ - valves GPIO   │          └──────┬─────────┘
        └───────┬────────┘                 │
                │                          │
        ┌───────▼──────────────┐          │
        │ IrrigationDecisionEngine│         │
        │ (priority queue + rules)│         │
        └────────────────────────┘          │
                                            │
                                 ┌──────────▼──────────┐
                                 │ Backend server       │
                                 │ /devices/provision   │
                                 │ /external-devices/*  │
                                 └──────────────────────┘
```

## CLI Reference

```
python raspberry_pi/main.py [OPTIONS]

Options:
  --config FILE       Path to YAML config (default: raspberry_pi/config/system_config.yaml)
  --mode MODE         System mode override: main | demo | test
  --verbose           Enable DEBUG logging
```

## License

MIT License
