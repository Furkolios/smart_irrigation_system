# Smart Irrigation System: Execution & Configuration

This guide explains how to run the system and configure it for different environments.

## 1. Execution Modes

The system supports three operation modes, controlled via the `--mode` argument or the `system_mode` configuration.

| Mode | Description | Used For |
| :--- | :--- | :--- |
| **MAIN** | Normal operation. Monitors sensors, controls valves, and sends telemetry. | Production deployment |
| **DEMO** | Simulation mode with faster cycles. Does not require real hardware. | Testing logic & UI |
| **TEST** | Hardware diagnostic mode. Checks connectivity of all configured devices. | Maintenance & setup |

### Loop Intervals
- **Main/Test**: Defined by `irrigation.loop_interval_seconds` (default: 60s)
- **Demo**: Fixed at 5 seconds for rapid feedback.

## 2. Running the Controller

Run the main controller from the `raspberry_pi` directory.

### Command Line Arguments
| Argument | Description | Default |
| :--- | :--- | :--- |
| `mode` | Overrides configuration mode | Config file value |
| `config` | Path to YAML config file | `config/system_config.yaml` |
| `verbose` | Enables DEBUG logging | False |

### Examples
```bash
# Default (uses system_config.yaml and configured mode)
python3 main.py

# Force specific mode
python3 main.py --mode demo

# Use custom config file
python3 main.py --config ./config/my_config.yaml

# Enable debug logging
python3 main.py --verbose
```

## 3. Configuration Reference

The system is configured via a YAML file. Below are the available settings based on the current system model.

### Top Level
| Parameter | Description |
| :--- | :--- |
| `system_mode` | Default operation mode (`main`, `demo`, `test`) |
| `location` | Location data (`city`, `elevation_m`) for potential weather adjustments |

### Hardware (`hardware`)
Defines the physical connections.
- **max_arduinos**: Max serial connections to attempt.
- **max_cameras**: Max cameras to auto-detect.
- **valves**: List of valve configurations.
  - `zone_id`: Unique identifier (e.g., "zone_1").
  - `pin`: GPIO pin number (BCM).
  - `name`: Human-readable name.
  - `flow_rate_lpm`: Flow rate in Liters/Minute.
- **cameras**: List of camera configurations.
  - `role`: "tank" or "plant".
  - `resolution`: [width, height].
  - `device_path`: Optional override (e.g., `/dev/video0`).

### Server (`server`)
Upstream API connection settings.
- **enabled**: Toggle server communication (true/false).
- **base_url**: API endpoint (e.g., `http://192.168.1.100:8000`).
- **telemetry_interval_seconds**: Frequency of sensor data uploads.
- **image_interval_seconds**: Frequency of image uploads.
- **heartbeat_interval_seconds**: Frequency of status pings.

### Irrigation (`irrigation`)
autonomous control logic.
- **loop_interval_seconds**: Main control loop frequency.
- **default_moisture_threshold**: Soil moisture % to trigger watering.
- **default_water_amount_liters**: Water volume to dispense per event.

### Logging (`logging`)
- **level**: `INFO`, `DEBUG`, `WARNING`, `ERROR`.
- **file_path**: Path to the log file.
- **max_size_mb**: Max size before rotation.
- **backup_count**: Number of backup files to keep.
