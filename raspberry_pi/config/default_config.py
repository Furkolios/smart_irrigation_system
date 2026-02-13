"""
Default configuration for the smart irrigation system.
"""

DEFAULT_CONFIG = {
    "location": {"city": "Paris", "elevation_m": 35},
    "tank": {"capacity_liters": 50.0},
    "arduinos": {
        "/dev/ttyACM0": "zone_1",
        "/dev/ttyACM1": "zone_2",
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
            "valve_pin": 17,
        },
        {
            "zone_id": "zone_2",
            "name": "Zone 2",
            "plant_id": None,
            "area_m2": 1.0,
            "valve_flow_rate_lpm": 2.0,
            "moisture_threshold_low": 30.0,
            "moisture_threshold_target": 60.0,
            "priority_weight": 1.0,
            "valve_pin": 18,
        },
    ],
    "server": {
        "ip": None,  # Dashboard server IP (None = read from .env)
        "port": 8000,
        "enabled": True,  # Set False to disable telemetry
    },
    "timing": {
        "check_interval_seconds": 600,  # 10 minutes
    },
    "logging": {"level": "INFO", "file": "irrigation.log"},
}
